"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import Image from "next/image";
import { useRouter } from "next/navigation";
import { Artifact, ReviewRun, RunSchema, RunsSchema, StartSchema, reviewFetch, statusLabel, terminal } from "@/lib/review/contracts";
import styles from "./review.module.css";

const date = (t: number) => new Date(t * 1000).toLocaleString();
const duration = (start: number | null, end: number | null) => start == null ? "—" : `${Math.round((end ?? Date.now() / 1000) - start)} 秒`;

export function ReviewList() {
  const router = useRouter();
  const [runs, setRuns] = useState<ReviewRun[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState("");
  const [listError, setListError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let active = true;
    const update = () => reviewFetch("/api/review/runs").then((v) => { if (active) { setRuns(RunsSchema.parse(v).runs); setListError(""); } }).catch((e) => { if (active) setListError(String(e.message)); });
    void update(); const timer = setInterval(update, 5000);
    return () => { active = false; clearInterval(timer); };
  }, []);
  async function upload() {
    if (!file) return;
    setBusy(true); setError("");
    try {
      const form = new FormData(); form.set("image", file);
      const result = StartSchema.parse(await reviewFetch("/api/review/runs", { method: "POST", body: form }));
      router.push(result.review_url);
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); setBusy(false); }
  }
  return <main className={styles.shell}>
    <header><p className={styles.eyebrow}>G3-A · LOCAL REVIEW</p><h1>从真实图片到课程页</h1><p>查看每个阶段真正使用的输入、产生的输出和校验依据。</p></header>
    <section className={styles.panel}><h2>开始一次真实生成</h2><p>上传一张包含完整题干与配图的单题截图。自动运行本地 OCR、真实抽取与解题模型；不使用 Mock。</p>
      <input aria-label="单题图片" type="file" accept="image/png,image/jpeg,image/webp" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
      <button disabled={!file || busy} onClick={upload}>{busy ? "上传中…" : "上传并生成"}</button><small>PNG / JPEG / WebP · 最多 20 MiB、2500 万像素 · 会调用已配置的真实模型</small>
    </section>
    {error && <p role="alert" className={styles.error}>{error}</p>}
    {listError && <p role="alert" className={styles.error}>{listError}</p>}
    <section className={styles.panel}><h2>运行记录</h2>{!runs.length && <p>还没有运行记录。需要同时启动 API 和 Review worker。</p>}
      {runs.map((run) => <Link className={styles.runRow} href={`/review/runs/${run.id}`} key={run.id}><span><strong>{run.filename}</strong><small>{date(run.created_at)} · {run.id.slice(0, 8)}</small></span><span data-status={run.status}>{statusLabel(run.status)} →</span></Link>)}
    </section>
  </main>;
}

export function ReviewDetail({ runId }: { runId: string }) {
  const router = useRouter();
  const [run, setRun] = useState<ReviewRun | null>(null);
  const [selected, setSelected] = useState("source");
  const [tab, setTab] = useState("output");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [connected, setConnected] = useState(false);
  useEffect(() => {
    let active = true; let pending = false;
    const refresh = async () => {
      if (pending) return;
      pending = true;
      try { const doc = RunSchema.parse(await reviewFetch(`/api/review/runs/${runId}`)); if (active) { setRun(doc); setError(""); } }
      catch (e) { if (active) setError(e instanceof Error ? e.message : String(e)); }
      finally { pending = false; }
    };
    void refresh();
    const source = new EventSource(`/api/review/runs/${runId}/events`);
    source.onopen = () => setConnected(true);
    source.onerror = () => setConnected(false);
    source.addEventListener("update", refresh);
    source.addEventListener("done", () => { void refresh(); source.close(); setConnected(false); });
    const timer = setInterval(refresh, 5000);
    return () => { active = false; source.close(); clearInterval(timer); };
  }, [runId]);
  async function rerun(fromStage?: string) {
    setBusy(true);
    try { const result = StartSchema.parse(await reviewFetch(`/api/review/runs/${runId}/rerun${fromStage ? `?from_stage=${encodeURIComponent(fromStage)}` : ""}`, { method: "POST" })); router.push(result.review_url); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  }
  const stage = run?.stages.find((s) => s.id === selected);
  const original = run?.artifacts.find((a) => a.stage === "source" && a.role === "input");
  const artifacts = run?.artifacts.filter((a) => a.stage === selected && (tab === "call" ? ["call", "raw"].includes(a.role) : a.role === tab)) ?? [];
  return <main className={styles.shell}>
    <Link href="/review/runs">← 所有运行</Link>
    <header className={styles.detailHeader}>{original && <a href={original.url} target="_blank" rel="noreferrer"><Image unoptimized width={104} height={76} src={original.url} alt="原始上传题图" /></a>}
      <div><p className={styles.eyebrow}>REAL PIPELINE · READ ONLY</p><h1 title={run?.filename}>{run?.filename ?? "载入运行…"}</h1><p>{run && `${statusLabel(run.status)} · ${date(run.created_at)} · 耗时 ${duration(run.started_at, run.finished_at)}`}</p>
        <small>{runId} {run && !terminal(run.status) && (connected ? "· 实时更新" : "· 自动重连 / 轮询恢复")}</small>
        {run?.parent_run_id && <Link href={`/review/runs/${run.parent_run_id}`}>查看上一次运行</Link>}</div>
      <button onClick={() => rerun()} disabled={!run || busy || !terminal(run.status)}>{busy ? "创建中…" : "整题重新运行"}</button>
    </header>
    {error && <p role="alert" className={styles.error}>{error}</p>}
    {run?.error && <p role="alert" className={styles.error}>{run.error}</p>}
    <div className={styles.layout}>
      <nav className={styles.stages} aria-label="生成阶段">{run?.stages.map((s, i) => <button key={s.id} onClick={() => setSelected(s.id)} aria-current={selected === s.id ? "step" : undefined}><span>{i + 1}. {s.title}</span><small data-status={s.status}>{s.reused_from_run_id ? "已复用" : statusLabel(s.status)} · {duration(s.started_at, s.finished_at)}</small></button>)}
        <button onClick={() => setSelected("preview")} aria-current={selected === "preview" ? "step" : undefined}>最终课程页<small>{run?.page_url ? "可预览" : "尚未生成"}</small></button>
      </nav>
      <section className={styles.content}>
        {selected === "preview" ? <><h2>最终课程页</h2>{run?.page_url ? <><a href={run.page_url} target="_blank" rel="noreferrer">新窗口打开课程页 ↗</a><iframe className={styles.preview} src={run.page_url} sandbox="allow-scripts" title="生成的课程页" /></> : <p>完整生成链通过校验后，课程页才会在这里出现。失败不会显示旧页面。</p>}</> : <>
          <h2>{stage?.title}</h2>
          {stage && <div><button onClick={() => rerun(stage.id)} disabled={busy || !run?.rerun_options?.[stage.id]?.available}>{busy ? "创建中…" : "从此阶段重新运行"}</button>
            <small>{run?.rerun_options?.[stage.id]?.reason || "新建运行记录，复用此前成功产物，使用当前代码执行本阶段及后续阶段。"}</small>
            {["source", "observation", "extraction", "projection", "solver", "evidence", "lesson"].includes(stage.id) && <small>后续包含模型调用，会使用当前配置并产生调用费用。</small>}
          </div>}
          <p>{stage?.summary || "等待本阶段执行"}</p>
          {stage && <details className={styles.artifact}><summary>阶段记录与配置依赖</summary><pre>{JSON.stringify(stage, null, 2)}</pre></details>}
          {stage?.diagnostics.map((d, i) => <p className={styles.error} key={i}><strong>{d.code}</strong><br />{d.message}</p>)}
          <div className={styles.tabs}>{[["input", "输入"], ["output", "输出"], ["validation", "校验"], ["call", "调用记录 / 原始返回"]].map(([key, title]) => <button key={key} onClick={() => setTab(key)} aria-pressed={tab === key}>{title}</button>)}</div>
          {!artifacts.length && <p className={styles.empty}>暂无已保存的内容。阶段执行后自动更新，不使用占位模型结果。</p>}
          {artifacts.map((artifact) => <ArtifactCard key={artifact.id} artifact={artifact} />)}
        </>}
      </section>
    </div>
  </main>;
}

function ArtifactCard({ artifact }: { artifact: Artifact }) {
  const [expanded, setExpanded] = useState(false);
  const [text, setText] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [copied, setCopied] = useState(false);
  const isImage = artifact.media_type.startsWith("image/");
  const isArchive = artifact.media_type === "application/zip";
  useEffect(() => {
    if (!expanded || isImage || isArchive) return;
    let active = true;
    fetch(artifact.url).then(async (r) => { if (!r.ok) throw new Error(`无法读取产物 (${r.status})`); return r.text(); }).then((v) => { if (active) setText(v); }).catch((e) => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [expanded, isImage, isArchive, artifact.url]);
  const lines = text?.split("\n");
  const shown = search ? lines?.map((line, i) => ({ line, i })).filter(({ line }) => line.toLowerCase().includes(search.toLowerCase())).map(({ line, i }) => `${i + 1}: ${line}`).join("\n") : text;
  let callData: Record<string, unknown> | null = null;
  if (text && artifact.role === "call") {
    try { callData = JSON.parse(text); } catch { /* raw text remains available */ }
  }
  const callSummary = callData && <p>Provider：{String(callData.provider ?? "未提供")} · 模型：{String(callData.request_model ?? callData.model ?? "未提供")} · 耗时：{callData.duration_seconds == null ? "未提供" : `${Number(callData.duration_seconds).toFixed(2)} 秒`} · usage：{callData.usage == null || Object.keys(Object(callData.usage)).length === 0 ? "未提供" : JSON.stringify(callData.usage)}</p>;
  return <article className={styles.artifact}><button className={styles.artifactTitle} onClick={() => setExpanded(!expanded)} aria-expanded={expanded}>{expanded ? "▾" : "▸"} {artifact.name}<small>{artifact.media_type} · {(artifact.size / 1024).toFixed(1)} KiB</small></button>
    <small>SHA256 {artifact.sha256.slice(0, 16)}… · {artifact.dependencies.length} 项依赖</small>{artifact.reused_from && <small>复用自运行 {artifact.reused_from.run_id.slice(0, 8)} · 内容哈希保持一致</small>}
    {expanded && <><p className={styles.actions}><a href={`${artifact.url}?download=1`}>下载完整产物</a>{!isImage && !isArchive && <button onClick={async () => { try { await navigator.clipboard.writeText(text ?? ""); setCopied(true); } catch { setError("复制失败，请下载产物"); } }} disabled={text == null}>{copied ? "已复制" : "复制"}</button>}</p>
      {isArchive ? <p>包含阶段恢复所需的原始产物，可下载查看。</p> : isImage ? <Image unoptimized width={1200} height={800} className={styles.artifactImage} src={artifact.url} alt={artifact.name} /> : <>{callSummary}<input aria-label={`搜索 ${artifact.name}`} placeholder="搜索内容（显示匹配行）" value={search} onChange={(e) => setSearch(e.target.value)} /><pre>{error || (text == null ? "加载中…" : shown || "没有匹配内容")}</pre></>}
      <details><summary>身份与依赖 manifest</summary><pre>{JSON.stringify(artifact, null, 2)}</pre></details>
    </>}
  </article>;
}
