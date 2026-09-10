"""Durable run journal. Artifact IDs never expose caller-controlled paths."""
from __future__ import annotations

from contextlib import contextmanager
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
import re
import sqlite3
import time
from uuid import uuid4

from PIL import Image, ImageOps

VERSION = "review-run/v1"
STAGES = (
    ("source", "来源入库"), ("observation", "OCR 与观察"),
    ("extraction", "题意抽取"), ("projection", "Solver 输入投影"),
    ("solver", "规划与执行"), ("evidence", "教学证据"),
    ("lesson", "学生讲解"), ("visual", "图形生成"), ("page", "页面编译"),
)
TERMINAL = {"succeeded", "failed", "interrupted"}
MAX_BYTES = 20 * 1024 * 1024
MAX_PIXELS = 25_000_000
REPO = Path(__file__).resolve().parents[3]


def data_root() -> Path:
    return Path(os.environ.get("REVIEW_DATA_DIR", REPO / "internal/review-runs")).resolve()


def redact(value, secrets=()):
    if isinstance(value, dict):
        return {str(k): "[REDACTED]" if re.search(
            r"api.?key|authorization|password|secret|access.token|cookie", str(k), re.I
        ) else redact(v, secrets) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v, secrets) for v in value]
    if isinstance(value, str):
        for secret in secrets:
            if secret and len(secret) > 5:
                value = value.replace(secret, "[REDACTED]")
        value = re.sub(r"(?i)bearer\s+[\w.\-]+", "Bearer [REDACTED]", value)
        return re.sub(r"\bsk-[A-Za-z0-9_-]{8,}", "[REDACTED]", value)
    return value


def normalize_image(content: bytes, media_type: str) -> bytes:
    if not content or len(content) > MAX_BYTES:
        raise ValueError("upload.size: 图片须在 20 MiB 以内")
    expected = {"image/png": "PNG", "image/jpeg": "JPEG", "image/webp": "WEBP"}
    if media_type not in expected:
        raise ValueError("upload.format: 只支持 PNG/JPEG/WebP")
    try:
        with Image.open(BytesIO(content)) as im:
            if im.format != expected[media_type] or im.width * im.height > MAX_PIXELS:
                raise ValueError("upload.image: 格式不匹配或超过 2500 万像素")
            if getattr(im, "n_frames", 1) != 1:
                raise ValueError("upload.image: 请上传静态单题截图")
            im.verify()
        with Image.open(BytesIO(content)) as im:
            out = BytesIO()
            ImageOps.exif_transpose(im).convert("RGB").save(out, format="PNG")
            return out.getvalue()
    except (OSError, Image.DecompressionBombError) as exc:
        raise ValueError("upload.image: 无法解码图片") from exc


class ReviewStore:
    def __init__(self, root: Path | None = None, *, secrets=()):
        self.root = (root or data_root()).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.secrets = tuple(secrets)
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, doc TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL, doc TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS event_run ON events(run_id, seq);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.root / "review.sqlite3", timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    @contextmanager
    def edit(self, run_id):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT doc FROM runs WHERE id=?", (run_id,)).fetchone()
            if row is None:
                raise KeyError(run_id)
            doc = json.loads(row["doc"])
            yield doc
            doc["updated_at"] = time.time()
            doc = redact(doc, self.secrets)
            db.execute("UPDATE runs SET doc=? WHERE id=?", (json.dumps(doc), run_id))
            self._event(db, doc)
            if doc["status"] == "succeeded":
                from .versions import publish
                publish(db, doc)

    def _event(self, db, doc):
        payload = {"schema_version": "review-event/v1", "run_id": doc["id"],
                   "status": doc["status"], "updated_at": doc["updated_at"]}
        db.execute("INSERT INTO events(run_id,doc) VALUES(?,?)", (doc["id"], json.dumps(payload)))

    def create(self, content, media_type, filename, *, parent_run_id=None, enqueue=True):
        normalized = normalize_image(content, media_type)
        run_id = uuid4().hex
        now = time.time()
        doc = {"schema_version": VERSION, "id": run_id, "parent_run_id": parent_run_id,
               "filename": Path(filename or "image").name, "status": "initializing",
               "created_at": now, "updated_at": now, "started_at": None, "finished_at": None,
               "page_url": None, "artifacts": [], "stages": [
                   {"schema_version": "review-stage/v1", "id": key, "title": title,
                    "status": "pending", "started_at": None, "finished_at": None,
                    "summary": "", "diagnostics": [], "input_refs": [], "output_refs": [],
                    "validation_refs": [], "call_refs": [], "raw_refs": [], "attempts": [],
                    "configuration_ref": None}
                   for key, title in STAGES]}
        with self.connect() as db:
            db.execute("INSERT INTO runs VALUES(?,?)", (run_id, json.dumps(doc)))
        self.add(run_id, "source", "input", "原始上传图片", content, media_type)
        self.add(run_id, "source", "output", "规范化图片", normalized, "image/png")
        from .versions import Versions
        Versions(self).attach(run_id, parent_run_id, requested=enqueue)
        with self.edit(run_id) as doc:
            doc["status"] = "queued" if enqueue else "initializing"
        return self.get(run_id)

    def get(self, run_id):
        with self.connect() as db:
            row = db.execute("SELECT doc FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        return json.loads(row["doc"])

    def list(self):
        with self.connect() as db:
            rows = db.execute("SELECT doc FROM runs ORDER BY rowid DESC LIMIT 100").fetchall()
        return [json.loads(row["doc"]) for row in rows]

    def events(self, run_id, after=0):
        with self.connect() as db:
            rows = db.execute("SELECT seq,doc FROM events WHERE run_id=? AND seq>? ORDER BY seq LIMIT 100",
                              (run_id, after)).fetchall()
        return [{**json.loads(row["doc"]), "seq": row["seq"]} for row in rows]

    def claim(self):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for row in db.execute("SELECT id,doc FROM runs ORDER BY rowid"):
                doc = json.loads(row["doc"])
                if doc["status"] != "queued":
                    continue
                doc.update(status="running", started_at=time.time(), updated_at=time.time())
                db.execute("UPDATE runs SET doc=? WHERE id=?", (json.dumps(doc), doc["id"]))
                self._event(db, doc)
                return doc["id"]
        return None

    def stage(self, run_id, key, status, summary="", diagnostics=()):
        with self.edit(run_id) as doc:
            if doc["status"] != "running":
                raise ValueError("run is not running")
            stage = next(s for s in doc["stages"] if s["id"] == key)
            if status == "running":
                stage.pop("reused_from_run_id", None)
            stage.update(status=status, summary=summary, diagnostics=list(diagnostics))
            stage["started_at" if status == "running" else "finished_at"] = time.time()

    def finish(self, run_id, *, error=None, interrupted=False):
        from .versions import Versions
        if error is None:
            Versions(self).capture(run_id)
        with self.edit(run_id) as doc:
            if doc["status"] in TERMINAL:
                return
            doc["status"] = "interrupted" if interrupted else "failed" if error else "succeeded"
            doc["finished_at"] = time.time()
            if error:
                doc["error"] = str(error)
                # A failure may occur between stages (e.g. validating subprocess
                # output). Attribute it to the next stage rather than losing it.
                if not any(s["status"] == "running" for s in doc["stages"]):
                    next_stage = next((s for s in doc["stages"] if s["status"] == "pending"), None)
                    if next_stage:
                        next_stage.update(status="running", started_at=time.time())
                for stage in doc["stages"]:
                    if stage["status"] == "running":
                        stage.update(status=doc["status"], finished_at=time.time(),
                                     diagnostics=[{"code": "run.interrupted" if interrupted else "stage.failed",
                                                   "message": str(error)}])
                    elif stage["status"] == "pending":
                        stage["status"] = "blocked"
            else:
                if any(s["status"] != "succeeded" for s in doc["stages"]):
                    raise ValueError("cannot succeed with incomplete stages")
                page = next((a for a in doc["artifacts"] if a.get("page_path") == "lesson.html"), None)
                if page is None:
                    raise ValueError("missing compiled page")
                doc["page_url"] = f"/api/review/runs/{run_id}/page/lesson.html"

    def interrupt_unfinished(self):
        with self.connect() as db:
            docs = [json.loads(row["doc"]) for row in db.execute("SELECT doc FROM runs")]
        for doc in docs:
            if doc["status"] in {"running", "initializing"}:
                self.finish(doc["id"], error="worker 重启；未自动重做模型调用，请重新运行", interrupted=True)

    def add(self, run_id, stage, role, name, content, media_type="application/json", *, dependencies=None, page_path=None):
        attempt = content.get("attempt") if isinstance(content, dict) and role == "call" else None
        if isinstance(content, bytes) and (media_type.startswith("text/") or media_type == "application/json"):
            content = redact(content.decode("utf-8"), self.secrets).encode()
        if not isinstance(content, bytes):
            content = redact(content, self.secrets)
            content = (json.dumps(content, ensure_ascii=False, indent=2, default=str)
                       if media_type == "application/json" else str(content)).encode()
        digest = sha256(content).hexdigest()
        artifact_id = uuid4().hex
        directory = self.root / run_id / "artifacts"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / artifact_id).write_bytes(content)
        with self.edit(run_id) as doc:
            if doc["status"] in TERMINAL:
                raise ValueError("cannot append artifacts to a terminal run")
            existing = {a["id"] for a in doc["artifacts"]}
            # G3-A deliberately uses a conservative prefix DAG: it retains all
            # actual prior evidence, including same-stage retries/repairs. G3-B
            # can narrow these edges for reuse; dropping edges now is unsafe.
            deps = dependencies if dependencies is not None else [a["id"] for a in doc["artifacts"]]
            if not set(deps).issubset(existing):
                raise ValueError("artifact dependencies must belong to this run")
            ref = {"schema_version": "review-artifact/v1", "id": artifact_id, "run_id": run_id,
                   "stage": stage, "role": role, "name": name, "media_type": media_type,
                   "size": len(content), "sha256": digest, "producer": stage, "dependencies": deps,
                   "created_at": time.time(), "page_path": page_path,
                   "url": f"/api/review/runs/{run_id}/artifacts/{artifact_id}"}
            doc["artifacts"].append(ref)
            record = next(s for s in doc["stages"] if s["id"] == stage)
            record.setdefault(f"{role}_refs", []).append(artifact_id)
            if attempt is not None:
                record.setdefault("attempts", []).append({"attempt": attempt, "call_ref": artifact_id})
            if name == "运行配置 / 代码与 Spec 版本":
                keys = [key for key, _ in STAGES]
                for record in doc["stages"]:
                    if keys.index(record["id"]) >= keys.index(stage):
                        record["configuration_ref"] = artifact_id
        return ref

    def read(self, run_id, artifact_id):
        doc = self.get(run_id)
        ref = next((a for a in doc["artifacts"] if a["id"] == artifact_id), None)
        if ref is None:
            raise KeyError(artifact_id)
        content = (self.root / doc["id"] / "artifacts" / ref["id"]).read_bytes()
        if sha256(content).hexdigest() != ref["sha256"]:
            raise ValueError("artifact integrity check failed")
        return ref, content

    def rerun(self, run_id, from_stage=None, *, enqueue=True):
        doc = self.get(run_id)
        ref = next(a for a in doc["artifacts"] if a["stage"] == "source" and a["role"] == "input")
        _, content = self.read(run_id, ref["id"])
        if from_stage is None:
            return self.create(content, ref["media_type"], doc["filename"], parent_run_id=run_id, enqueue=enqueue)
        from .replay import KEYS, ARCHIVE, availability, archive_bytes, archive_source, find
        if from_stage not in KEYS:
            raise ValueError("未知重跑阶段")
        option = availability(self, doc)[from_stage]
        if not option["available"]:
            raise ValueError(option["reason"])
        before = KEYS[:KEYS.index(from_stage)]
        child = self.create(content, ref["media_type"], doc["filename"], parent_run_id=run_id, enqueue=False)
        child_id = child["id"]
        try:
            ids = {}
            reused = {}
            for artifact in doc["artifacts"]:
                if artifact["stage"] not in before:
                    continue
                _, raw = self.read(run_id, artifact["id"])
                existing = next((a for a in child["artifacts"] if a["name"] == artifact["name"] and a["sha256"] == artifact["sha256"]), None)
                copied = existing or self.add(child_id, artifact["stage"], artifact["role"], artifact["name"], raw,
                    artifact["media_type"], dependencies=[ids[d] for d in artifact["dependencies"]], page_path=artifact.get("page_path"))
                ids[artifact["id"]] = copied["id"]
                reused[copied["id"]] = {"run_id": run_id, "artifact_id": artifact["id"], "sha256": artifact["sha256"]}
            for owner in ("observation", "extraction"):
                source = archive_source(self, doc, owner) if owner in before else None
                if source and not find(doc, owner, ARCHIVE):
                    source_run, source_ref = source
                    archive = (self.read(source_run, source_ref["id"])[1] if source_ref else
                               archive_bytes(self.root / source_run / "extraction-artifacts"))
                    self.add(child_id, owner, "output", ARCHIVE, archive, "application/zip")
            with self.edit(child_id) as new:
                new["from_stage"] = from_stage
                for a in new["artifacts"]:
                    if a["id"] in reused:
                        a["reused_from"] = reused[a["id"]]
                for stage in new["stages"]:
                    if stage["id"] in before:
                        stage.update(status="succeeded", summary="复用上一次成功产物", reused_from_run_id=run_id)
                        old = next(s for s in doc["stages"] if s["id"] == stage["id"])
                        if old.get("manifest"):
                            stage["manifest"] = old["manifest"]
                new["status"] = "queued" if enqueue else "initializing"
            return self.get(child_id)
        except Exception as exc:
            self.finish(child_id, error=f"replay.prepare_failed: {exc}")
            raise
