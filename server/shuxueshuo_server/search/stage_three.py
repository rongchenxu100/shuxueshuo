"""Local search adapter over the existing stage-three runner and authoritative store.

Each stage-two attempt owns one immutable run directory. Reads never create or
resume work. Opening an outdated lesson or explicitly retrying creates a new
attempt; explicit resume checks the selected run's frozen implementation.
"""

import fcntl
import json
import logging
import re
import tempfile
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError

from shuxueshuo_server.graph_lesson.stage_three import runner
from shuxueshuo_server.graph_lesson.stage_three.budget import BudgetConflict
from shuxueshuo_server.graph_lesson.stage_three.checkpoint import identity_from_seed
from shuxueshuo_server.graph_lesson.stage_three.events import EventStore
from shuxueshuo_server.graph_lesson.stage_three.preview import open_store
from shuxueshuo_server.graph_lesson.stage_three.runner import fingerprint
from shuxueshuo_server.graph_lesson.stage_three.storage import (
    RunNotFound,
    RunUnavailable,
    read_run,
)
from shuxueshuo_server.graph_lesson.stage_three.teaching_version import (
    teaching_revision,
)
from shuxueshuo_server.problem_understanding.workflow_ledger import save

from .lesson import RESULT, attempts

RUN_ID = re.compile(r"^[0-9a-f]{32}$")
RETRY_INTENT = ".lesson-retry.json"
_LOG = logging.getLogger(__name__)


class LessonBusy(RuntimeError):
    pass


class LessonConflict(ValueError):
    pass


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def acquire_problem(directory):
    """Reserve a local problem before queueing mutations, across router processes."""
    stream = (Path(directory) / ".lesson.lock").open("a+b")
    try:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        stream.close()
        raise LessonBusy("lesson.running") from exc
    try:
        # An abandoned process may leave intent behind, but a new lease never
        # inherits it (especially when this operation is a resume, not a retry).
        (Path(directory) / RETRY_INTENT).unlink(missing_ok=True)
    except BaseException:
        stream.close()
        raise
    return stream


def release_problem(stream):
    try:
        Path(stream.name).with_name(RETRY_INTENT).unlink(missing_ok=True)
    finally:
        fcntl.flock(stream, fcntl.LOCK_UN)
        stream.close()


def reserve_retry(directory):
    """Publish the next attempt while its problem lease is held, before queueing."""
    directory = Path(directory)
    name = f"stage-two-{len(attempts(directory)) + 1}"
    save(directory / RETRY_INTENT, {"attempt": name})


def pending_retry(directory):
    """Cross-router readers must not attach the preceding stream to a new retry."""
    directory = Path(directory)
    try:
        name = read(directory / RETRY_INTENT)["attempt"]
    except FileNotFoundError:
        return None
    if not _locked(directory / ".lesson.lock"):
        return None
    attempt = directory / name
    if (attempt / RESULT).is_file():
        return None
    return attempt


def _locked(path):
    try:
        stream = path.open("rb")
    except FileNotFoundError:
        return False
    with stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(stream, fcntl.LOCK_UN)
        return False


@contextmanager
def _run_lock(stage_two_directory):
    stream = (Path(stage_two_directory) / ".stage-three.lock").open("a+b")
    try:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise LessonBusy("lesson.running") from exc
        yield
    finally:
        stream.close()


def latest_attempt(directory):
    values = attempts(directory)
    return values[-1] if values else None


def run_stage_three(stage_two_directory, *, hooks=None):
    """Start exactly once from already saved stage two; existing runs are never rerun."""
    stage_two_directory = Path(stage_two_directory)
    with _run_lock(stage_two_directory):
        output = stage_two_directory / "stage-three"
        if output.exists():
            if (output / "stage-three-result.json").is_file():
                return read(output / "stage-three-result.json")
            raise LessonConflict("lesson.resume_required")
        try:
            revision = teaching_revision()
            result = runner.run_sample(stage_two_directory / RESULT, output, hooks=hooks)
            if result['status'] == 'completed':
                save(output / 'teaching-version.json', {'revision': revision})
            return result
        except Exception as exc:
            save(stage_two_directory / "stage-three-error.json", {"type": type(exc).__name__, "message": str(exc)})
            raise


def needs_teaching_update(attempt):
    """Historical run URLs remain immutable; only the current lesson is upgraded."""
    output = Path(attempt) / 'stage-three'
    final = output / 'stage-three-result.json'
    if not final.is_file() or read(final).get('status') != 'completed':
        return False
    stamp = output / 'teaching-version.json'
    return not stamp.is_file() or read(stamp).get('revision') != teaching_revision()


def refresh_teaching(directory, source, *, hooks=None):
    """Replay saved recognition into a NEW version, without OCR or model calls.

    The caller owns the problem/lifecycle leases and publishes retry intent.
    Existing run IDs, steps and practice history are never rewritten.
    """
    from shuxueshuo_server.graph_lesson.stage_two.runner import record_run, replay_run
    assert_current_attempt(directory, source)
    target = Path(directory) / f'stage-two-{len(attempts(directory)) + 1}'
    with tempfile.TemporaryDirectory(prefix='lesson-teaching-update-') as scratch:
        recording = record_run(source, Path(scratch) / 'recording')
        replayed = replay_run(recording, target, refresh_features=True)
    if replayed['status'] != 'completed' or not replayed['replay_comparison']['ok']:
        raise LessonConflict('lesson.recognition_replay_changed')
    return run_stage_three(target, hooks=hooks)


def find_run(directory, run_id):
    if RUN_ID.fullmatch(run_id) is None:
        raise FileNotFoundError("lesson.run_not_found")
    for attempt in attempts(directory):
        output = attempt / "stage-three"
        path = output / "run.json"
        if path.is_file() and read(path).get("run_id") == run_id:
            return output
    raise FileNotFoundError("lesson.run_not_found")


def stream_descriptor(search_id, output, *, strict=False):
    """Use stored identity; old streams remain readable after a code update."""
    output = Path(output)
    try:
        if not (output / "run.json").is_file():
            return None
        seed = read(output / "run.json")
        if not isinstance(seed, dict) or any(not isinstance(seed.get(key), str) or not seed[key]
                                            for key in ("run_id", "lesson_version")):
            raise ValueError("checkpoint.invalid_identity")
        identity = read_run(seed["run_id"])["identity"]
        if not isinstance(seed, dict) or not isinstance(identity, dict):
            raise TypeError("checkpoint.invalid_identity")
        expected = identity_from_seed(seed) if 'stage_one' in seed or 'stage_two' in seed else seed
        if any(identity.get(key) != expected[key] for key in expected
               if key in {'run_id', 'lesson_version', 'input_sha256'}):
            raise ValueError("checkpoint.identity_mismatch")
    except RunUnavailable:
        if strict:
            raise
        return None
    except RunNotFound:
        if strict:
            raise
        return None
    except SQLAlchemyError:
        if strict:
            raise
        _LOG.warning("Could not read stage-three stream identity in %s; stream temporarily unavailable", output,
                     exc_info=True)
        return None
    except FileNotFoundError:
        return None
    except (OSError, ValueError, KeyError, TypeError):
        _LOG.warning("Could not read stage-three stream identity in %s; stream temporarily unavailable", output,
                     exc_info=True)
        return None
    base = f"/api/search/problems/{search_id}/lesson/{seed['run_id']}"
    return {"run_id": seed["run_id"], "lesson_version": seed["lesson_version"], "stream_id": seed["run_id"],
            "snapshot_url": base + "/snapshot", "events_url": base + "/events", "websocket_url": base + "/ws"}


def presentation(directory, search_id, *, running=False, attempt=None):
    # A status response pins its stage-two material and stream to one attempt.
    # A concurrent explicit retry may advance latest while that response renders.
    attempt = attempt if attempt is not None else latest_attempt(directory)
    if attempt is None:
        return {"execution_status": "not_started", "stream": None}
    running = running or _locked(Path(directory) / ".lesson.lock") or _locked(attempt / ".stage-three.lock")
    output = attempt / "stage-three"
    stream = stream_descriptor(search_id, output)
    # A completed file can precede the worker's finally/lease release. Keep
    # polling until that operation can actually accept the student's retry.
    if running:
        status = "running" if output.exists() else "starting"
    elif output.exists() and (stream is None or not resumable_files(output)):
        return {"execution_status": "unavailable", "stream": None}
    elif (output / "stage-three-result.json").is_file():
        status = read(output / "stage-three-result.json")["status"]
        if has_pending_interactions(output):
            # Mathematics stays completed in its result and route records. The
            # stopped interaction work still needs the existing resume action.
            status = "interrupted"
    elif (attempt / "stage-three-error.json").is_file():
        status = "error"
    else:
        status = "interrupted" if output.exists() else "not_started"
    return {"execution_status": status, "stream": stream}


def has_pending_interactions(output):
    """Read committed interaction state without creating or migrating storage."""
    output = Path(output)
    try:
        if not (output / "run.json").is_file():
            return False
        seed = read(output / "run.json")
        expected = identity_from_seed(seed)
        saved = read_run(seed["run_id"])["identity"]
        if any(saved.get(key) != value for key, value in expected.items()):
            raise ValueError("checkpoint.identity_mismatch")
        return EventStore(output, saved).has_pending_interactions()
    except (FileNotFoundError, RunNotFound, RunUnavailable):
        return False
    except (SQLAlchemyError, OSError, ValueError, KeyError, TypeError):
        _LOG.warning("Could not read pending interaction status in %s; keeping mathematical status", output,
                     exc_info=True)
        return False


def event_page(output, after_seq):
    store = open_store(output)
    events = store.events(after_seq)
    return {"run_id": store.identity["run_id"], "lesson_version": store.identity["lesson_version"],
            "stream_id": store.identity["run_id"], "events": events,
            "last_seq": events[-1]["seq"] if events else after_seq}


def assert_current_attempt(directory, attempt):
    if attempt != latest_attempt(directory):
        raise LessonConflict("lesson.stale_run")


def resumable_files(output):
    output = Path(output)
    return all(path.is_file() for path in (output / 'run.json', output / 'frozen.json', output.parent / RESULT))


def assert_resumable(directory, output):
    assert_current_attempt(directory, output.parent)
    if not resumable_files(output):
        raise LessonConflict("lesson.execution_unavailable")
    try:
        available = stream_descriptor(Path(directory).name, output, strict=True)
    except (RunNotFound, RunUnavailable) as exc:
        raise LessonConflict("lesson.execution_unavailable") from exc
    if available is None:
        raise LessonConflict("lesson.execution_unavailable")
    frozen = read(output / "frozen.json")
    if frozen["implementation"] != fingerprint():
        raise LessonConflict("checkpoint.revisions_changed")


def resume_stage_three(directory, run_id, *, hooks=None):
    output = find_run(directory, run_id)
    with _run_lock(output.parent):
        assert_resumable(directory, output)
        completed = output / "stage-three-result.json"
        if completed.is_file():
            return runner.resume_interactions(output, hooks=hooks)
        try:
            return runner.resume_sample(output, hooks=hooks)
        except BudgetConflict as exc:
            raise LessonBusy(str(exc)) from exc
