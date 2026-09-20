'use client';

import Link from 'next/link';
import { useCallback, useEffect, useRef, useState } from 'react';
import { api, post, BuildSchema, type ProductBuild, label, terminal, websocketUrl, failureMessage } from '@/lib/product/client';
import { problemTitle, type WorkspaceProblem } from '@/lib/product/workspace';
import { ArtifactPreview } from './artifact-preview';

type Problem = WorkspaceProblem & { primary_source_id?: string; current_revision_id?: string | null };
type Upload = { status: 'created' | 'reused' | 'ambiguous'; source_id?: string; candidate_ids?: string[];
  item?: { id: string; problem_id: string; source_id: string }; problem?: Problem };
type Pending = { key: string; batch_id?: string; result?: Upload };
const pendingKey = 'product.pending-upload.v1';
const button = 'rounded-lg border border-slate-300 px-4 py-2 text-sm hover:bg-slate-100 disabled:opacity-50';
const primaryButton = 'rounded-lg bg-slate-900 px-4 py-2 text-sm text-white hover:bg-slate-800 disabled:opacity-50';

function formatUpdated(value?: string | null) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function statusTone(status?: string | null) {
  if (status === 'succeeded') return 'bg-emerald-50 text-emerald-800';
  if (status === 'failed' || status === 'interrupted' || status === 'cancelled') return 'bg-amber-50 text-amber-900';
  if (status === 'queued' || status === 'running') return 'bg-sky-50 text-sky-800';
  return 'bg-slate-100 text-slate-600';
}

function problemStatus(problem: Problem) {
  return problem.latest_build_status ? label(problem.latest_build_status) : '尚未生成';
}

function ListUploadForm({ busy, onUpload }: { busy: boolean; onUpload: (file: File) => Promise<void> }) {
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState('');
  useEffect(() => {
    if (!file) { setPreview(''); return; }
    const url = URL.createObjectURL(file);
    const frame = requestAnimationFrame(() => setPreview(url));
    return () => { cancelAnimationFrame(frame); URL.revokeObjectURL(url); };
  }, [file]);
  return (
    <section className="rounded-2xl border border-dashed border-slate-300 bg-white p-6 shadow-sm">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h2 className="text-lg font-medium">上传单题图片</h2>
          <p className="mt-1 text-sm text-slate-500">完整题干与配图的单题截图；多题请先裁成单题。</p>
        </div>
        <p className="text-xs text-slate-500 sm:max-w-[14rem] sm:text-right">PNG / JPEG / WebP · ≤ 20 MiB<br />相同图片引用已有题目</p>
      </div>
      <label className="mt-5 flex cursor-pointer flex-col items-center justify-center rounded-xl border border-slate-200 bg-slate-50 px-4 py-8 text-center transition hover:border-slate-400 hover:bg-slate-100">
        <span className="text-sm font-medium text-slate-800">{file ? '更换图片' : '点击选择或拍照上传'}</span>
        <span className="mt-1 text-xs text-slate-500">{file ? file.name : '选择后可预览，再确认生成'}</span>
        <input
          aria-label="题目图片"
          disabled={busy}
          type="file"
          accept="image/png,image/jpeg,image/webp"
          className="sr-only"
          onChange={e => { setFile(e.target.files?.[0] ?? null); e.target.value = ''; }}
        />
      </label>
      {file && preview && (
        <figure className="mt-4 overflow-hidden rounded-xl border border-slate-200 bg-slate-50">
          {/* Local file preview never goes through the image optimization service. */}
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={preview} alt="待上传题目预览" className="mx-auto max-h-64 w-auto object-contain" />
          <figcaption className="border-t border-slate-200 px-3 py-2 text-xs text-slate-500">{file.name}</figcaption>
        </figure>
      )}
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <button className={primaryButton} disabled={busy || !file} onClick={() => file && void onUpload(file)}>
          {busy ? '正在接收并登记…' : '上传并生成'}
        </button>
        {file && !busy && (
          <button className={button} type="button" onClick={() => setFile(null)}>清除选择</button>
        )}
      </div>
    </section>
  );
}

export function ProductList() {
  const [problems, setProblems] = useState<Problem[]>([]);
  const [result, setResult] = useState<Upload | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const pending = useRef<Pending | null>(null);
  const load = useCallback(() => api<{ problems: Problem[] }>('/problems').then(r => setProblems(r.problems)).catch(e => setError(String(e.message))), []);
  const generate = useCallback(async (upload: Upload, key: string) => {
    if (!upload.item) return;
    const build = await post<{ build_id: string }>(`/problems/${upload.item.problem_id}/builds`,
      { source_id: upload.item.source_id, batch_item_id: upload.item.id }, `${key}-build`);
    localStorage.removeItem(pendingKey);
    window.location.assign(`/review/runs/${build.build_id}`);
  }, []);
  useEffect(() => {
    void load();
    const saved = localStorage.getItem(pendingKey);
    if (!saved) return;
    try {
      const state: Pending = JSON.parse(saved);
      pending.current = state;
      const recover = async () => {
        let upload = state.result;
        if (!upload && state.batch_id) {
          const found = await api<{ found: boolean; response: Upload }>(`/requests/upload/${state.key}-upload`);
          if (found.found) upload = found.response;
        }
        if (upload) {
          setResult(upload);
          if (upload.status === 'created') await generate(upload, state.key);
        }
      };
      void recover().catch(e => setError(e.message));
    } catch { localStorage.removeItem(pendingKey); }
  }, [load, generate]);
  async function upload(file: File) {
    setBusy(true); setError('');
    let state: Pending = pending.current?.result ? { key: crypto.randomUUID() } : { ...(pending.current ?? { key: crypto.randomUUID() }) };
    pending.current = state;
    try {
      localStorage.setItem(pendingKey, JSON.stringify(state));
      if (!state.batch_id) {
        const batch = await post<{ id: string }>('/batches', { name: file.name }, `${state.key}-batch`);
        state = { ...state, batch_id: batch.id };
        pending.current = state;
        localStorage.setItem(pendingKey, JSON.stringify(state));
      }
      const body = new FormData(); body.set('image', file);
      const accepted = await api<Upload>(`/batches/${state.batch_id}/uploads`, { method: 'POST', headers: { 'Idempotency-Key': `${state.key}-upload` }, body });
      state = { ...state, result: accepted };
      pending.current = state;
      localStorage.setItem(pendingKey, JSON.stringify(state));
      setResult(accepted);
      if (accepted.status === 'created') await generate(accepted, state.key);
      else await load();
    } catch (e) { setError(e instanceof Error ? e.message : '上传失败'); }
    finally { setBusy(false); }
  }
  async function resolve(id: string) {
    if (!result?.source_id) return;
    try {
      const resolved = await post<Upload>(`/sources/${result.source_id}/resolve`, { problem_id: id });
      resolved.problem = await api<Problem>(`/problems/${id}`);
      setResult(resolved);
      if (pending.current) { pending.current = { ...pending.current, result: resolved }; localStorage.setItem(pendingKey, JSON.stringify(pending.current)); }
      await load();
    } catch (e) { setError(e instanceof Error ? e.message : '选择未完成'); }
  }
  return <main className="mx-auto max-w-5xl space-y-6 p-8 text-slate-800">
    <header>
      <p className="text-xs font-medium uppercase tracking-[0.14em] text-slate-400">Review</p>
      <h1 className="mt-1 text-2xl font-semibold tracking-tight">题目解析</h1>
      <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-500">上传完整单题图片，生成解析网页并审查结果。列表展示题干摘要、最近生成状态与更新时间。</p>
    </header>
    <ListUploadForm busy={busy} onUpload={upload} />
    {error && <p role="alert" className="rounded-lg bg-red-50 p-3 text-red-800">{error}</p>}
    {result?.status === 'ambiguous' && <section className="space-y-3 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <p className="font-medium">发现多个已关联题目，请选择本次引用的题目：</p>
      <div className="space-y-2">{result.candidate_ids?.map(id => {
        const match = problems.find(item => item.id === id);
        return <button className={`${button} block w-full text-left`} key={id} onClick={() => void resolve(id)}>
          <span className="block font-medium">{match ? problemTitle(match) : `题目 ${id.slice(0, 8)}`}</span>
          <span className="mt-1 block text-xs text-slate-500">{id.slice(0, 8)}{match?.latest_build_status ? ` · ${label(match.latest_build_status)}` : ''}</span>
        </button>;
      })}</div>
    </section>}
    {result?.status === 'reused' && <section className="space-y-3 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <p className="font-medium">已引用已有题目，没有重复生成。</p>
      {result.problem && <p className="text-sm text-slate-600">{problemTitle(result.problem)}
        {result.problem.latest_build_status ? ` · ${label(result.problem.latest_build_status)}` : ''}</p>}
      <div className="flex flex-wrap gap-3">
        {result.problem?.latest_build_id ? <Link className={primaryButton} href={`/review/runs/${result.problem.latest_build_id}`}>查看已有任务</Link> :
          <button className={primaryButton} onClick={() => void generate(result, pending.current?.key ?? crypto.randomUUID()).catch(e => setError(e.message))}>生成解析</button>}
        <button className={button} onClick={() => { pending.current = null; localStorage.removeItem(pendingKey); setResult(null); }}>继续上传</button>
      </div>
    </section>}
    <section>
      <div className="mb-3 flex items-end justify-between gap-3">
        <h2 className="text-lg font-medium">已有题目</h2>
        <span className="text-xs text-slate-500">{problems.length ? `共 ${problems.length} 题` : '暂无题目'}</span>
      </div>
      <div className="space-y-2">
        {problems.map(p => {
          const title = problemTitle(p);
          const status = problemStatus(p);
          return <article key={p.id} className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
              <div className="min-w-0 flex-1">
                <h3 className="line-clamp-2 text-sm font-medium leading-6 text-slate-900" title={p.statement_text || title}>{title}</h3>
                <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                  <span className={`rounded-full px-2 py-0.5 font-medium ${statusTone(p.latest_build_status)}`}>{status}</span>
                  {p.source_filename && <span className="truncate" title={p.source_filename}>{p.source_filename}</span>}
                  {p.updated_at && <span>更新于 {formatUpdated(p.updated_at)}</span>}
                  <span className="font-mono text-slate-400">{p.id.slice(0, 8)}</span>
                </div>
              </div>
              <div className="flex shrink-0 flex-wrap gap-2">
                {p.latest_build_id ? <Link className={primaryButton} href={`/review/runs/${p.latest_build_id}`}>查看任务</Link>
                  : <span className="self-center text-sm text-slate-500">尚未生成</span>}
                {p.current_page_build_id && (
                  <a className={button} href={`/api/product/v1/pages/${p.current_page_build_id}/index.html`} target="_blank" rel="noreferrer">打开解析</a>
                )}
              </div>
            </div>
          </article>;
        })}
        {!problems.length && <p className="rounded-xl border border-dashed border-slate-200 bg-slate-50 px-4 py-8 text-center text-sm text-slate-500">还没有题目。上传第一张图片开始审查。</p>}
      </div>
    </section>
  </main>;
}

type Preview = { fingerprint: string; requested_stage: string | null; reuse_stages: string[]; rerun_stages: string[]; model_stages: string[]; available: boolean; reasons: { stage: string; code: string }[] };
type Artifact = ProductBuild['artifacts'][number];
type StageTab = 'input' | 'output' | 'validation' | 'call';
const stageTabs: { key: StageTab; title: string }[] = [
  { key: 'input', title: '输入' },
  { key: 'output', title: '输出' },
  { key: 'validation', title: '校验' },
  { key: 'call', title: '调用 / 原始返回' },
];

function stageArtifacts(build: ProductBuild, stageKey: string, tab: StageTab) {
  return build.artifacts.filter(a => a.stage_key === stageKey && (tab === 'call' ? ['call', 'raw'].includes(a.role) : a.role === tab));
}

function defaultSelection(build: ProductBuild) {
  const failed = build.stages.find(s => ['failed', 'interrupted', 'cancelled'].includes(s.status));
  if (failed) return failed.stage_key;
  if (build.page_id && build.status === 'succeeded') return 'page';
  return build.stages[0]?.stage_key ?? 'page';
}

export function ProductDetail({ runId }: { runId: string }) {
  const [build, setBuild] = useState<ProductBuild | null>(null);
  const [error, setError] = useState('');
  const [connected, setConnected] = useState(false);
  const [selected, setSelected] = useState('');
  const [tab, setTab] = useState<StageTab>('output');
  const [preview, setPreview] = useState<Preview | null>(null);
  const [domain, setDomain] = useState('');
  const [baseId, setBaseId] = useState<string | null>(null);
  const [revisionResult, setRevisionResult] = useState('');
  const [activeArtifact, setActiveArtifact] = useState<Artifact | null>(null);
  const [decision, setDecision] = useState('');
  const refresh = useCallback(async () => {
    const data = BuildSchema.parse(await api(`/builds/${runId}`));
    setBuild(current => current?.id === data.id && current.last_seq > data.last_seq ? current : data);
    return data;
  }, [runId]);
  useEffect(() => {
    let stop = false; let socket: WebSocket | undefined; let timer: ReturnType<typeof setTimeout> | undefined;
    let watermark: number | null = null;
    async function connect() {
      try {
        const current = await refresh();
        if (stop) return;
        if (watermark === null) watermark = current.last_seq;
        socket = new WebSocket(websocketUrl());
        socket.onopen = () => { setConnected(true); socket?.send(JSON.stringify({ streams: [{ kind: 'build', id: runId, after: watermark }] })); };
        socket.onmessage = e => {
          const message = JSON.parse(e.data);
          if (message.type === 'event' && message.seq > (watermark ?? -1)) { watermark = message.seq; void refresh().catch(e => setError(e.message)); }
          if (message.type === 'resnapshot_required') { watermark = null; socket?.close(); }
        };
        socket.onclose = () => { setConnected(false); if (!stop) timer = setTimeout(() => void connect(), 1500); };
      } catch (e) { if (!stop) { setError(e instanceof Error ? e.message : '连接失败'); timer = setTimeout(() => void connect(), 2000); } }
    }
    void connect();
    return () => { stop = true; clearTimeout(timer); socket?.close(); };
  }, [refresh, runId]);
  useEffect(() => {
    if (!build) return;
    setSelected(current => current || defaultSelection(build));
  }, [build]);
  useEffect(() => {
    setActiveArtifact(null);
    setTab('output');
    setPreview(null);
  }, [selected]);
  async function action(task: () => Promise<unknown>) { setError(''); try { await task(); await refresh(); } catch (e) { setError(e instanceof Error ? e.message : '操作失败'); } }
  async function edit() {
    if (!build) return;
    const problem = await api<Problem>(`/problems/${build.problem_id}`);
    if (!problem.current_revision_id) throw new Error('尚无通过校验的题意');
    const revision = await api<{ domain_json: unknown }>(`/problems/${build.problem_id}/revisions/${problem.current_revision_id}`);
    setBaseId(problem.current_revision_id); setDomain(JSON.stringify(revision.domain_json, null, 2));
  }
  if (!build) return <main className="p-8"><p>{error || '正在读取任务…'}</p><Link href="/review/runs">返回题目列表</Link></main>;
  const stage = build.stages.find(s => s.stage_key === selected);
  const artifacts = stage ? stageArtifacts(build, stage.stage_key, tab) : [];
  const navButton = (key: string, title: string, meta: string, current: boolean) => (
    <button
      key={key}
      type="button"
      aria-current={current ? 'step' : undefined}
      onClick={() => setSelected(key)}
      className={`rounded-xl px-3 py-2.5 text-left transition ${current ? 'bg-slate-900 text-white' : 'bg-slate-100 text-slate-700 hover:bg-slate-200'}`}
    >
      <span className="block text-[13px] font-medium leading-5">{title}</span>
      <small className={`mt-1 block text-[11px] leading-4 ${current ? 'text-slate-300' : 'text-slate-500'}`}>{meta}</small>
    </button>
  );
  return <main className="mx-auto w-full max-w-[1480px] space-y-5 px-4 py-6 text-slate-800 sm:px-6 lg:px-8">
    <Link className="text-sm text-blue-700" href="/review/runs">← 题目列表</Link>
    <header className="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">题目解析</h1>
        <p className="mt-1 text-sm text-slate-500">{runId.slice(0, 8)} · {label(build.status)} · {connected ? '实时更新' : '正在恢复连接'}</p>
        <Link className="mt-3 inline-block text-sm text-teal-700" href={`/understanding/${build.problem_id}`}>提取题意 · 查看候选、补图与修订 →</Link>
      </div>
      {!terminal(build.status) && <button className={button} onClick={() => void action(() => post(`/builds/${runId}/cancel`, {}))}>取消生成</button>}
    </header>
    {error && <p role="alert" className="rounded-lg bg-red-50 p-3 text-red-800">{error}</p>}
    {build.error_code && <p className="rounded-lg bg-amber-50 p-3 text-sm">{failureMessage(build.error_code)}</p>}
    <div className="grid grid-cols-1 gap-5 md:grid-cols-[200px_minmax(0,1fr)] md:items-start xl:grid-cols-[220px_minmax(0,1fr)]">
      <nav className="grid max-h-[70vh] gap-2 overflow-y-auto md:sticky md:top-4 md:max-h-[calc(100vh-2rem)]" aria-label="生成阶段">
        {build.stages.map(s => navButton(
          s.stage_key,
          `${s.ordinal}. ${s.title}`,
          `${label(s.status)} · ${build.artifacts.filter(a => a.stage_key === s.stage_key).length} 项材料`,
          selected === s.stage_key,
        ))}
        {navButton('page', '最终解析页', build.page_id ? (build.page_current ? '当前有效版本' : '历史版本') : '尚未生成', selected === 'page')}
        {navButton('advanced', '高级审查', '题意修订与全量材料', selected === 'advanced')}
      </nav>
      <section className="min-h-[32rem] min-w-0 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5">
        {selected === 'page' ? <>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-lg font-medium">{build.page_current ? '当前有效解析' : '历史版本预览'}</h2>
            {build.page_id && <a className="text-sm text-blue-700" href={`/api/product/v1/pages/${build.page_id}/index.html`} target="_blank" rel="noreferrer">新窗口打开</a>}
          </div>
          {build.page_id ? <>
            <iframe title="解析网页" sandbox="allow-scripts" className="mt-4 h-[min(78vh,900px)] w-full rounded-lg border bg-white" src={`/api/product/v1/pages/${build.page_id}/index.html`} />
            <div className="mt-4 flex flex-wrap items-center gap-3">
              <button className={button} onClick={() => void action(async () => { await post(`/pages/${build.page_id}/reviews`, { decision: 'approved' }); setDecision('本版本已通过审查'); })}>通过本版本</button>
              <button className={button} onClick={() => void action(async () => { await post(`/pages/${build.page_id}/reviews`, { decision: 'rejected' }); setDecision('本版本已标记需修改'); })}>需修改</button>
              <span className="text-sm text-slate-600">{decision || ({ approved: '本版本已通过审查', rejected: '本版本需修改', revoked: '本版本审查已撤销' }[build.reviews.at(-1)?.decision ?? ''] ?? '尚未审查')}</span>
            </div>
          </> : <p className="mt-6 text-sm text-slate-500">完整链路通过校验后，解析页会出现在这里。</p>}
        </> : selected === 'advanced' ? <>
          <h2 className="text-lg font-medium">高级审查</h2>
          <p className="mt-1 text-sm text-slate-500">题意人工修订，以及不按阶段过滤的全量产物列表。</p>
          {build.error_code && <p className="mt-3 text-xs text-slate-500">诊断代码：{build.error_code}</p>}
          <button className={`${button} my-4`} onClick={() => void action(edit)}>读取当前题意</button>
          {domain && <div className="space-y-3"><textarea aria-label="题意 JSON" className="h-80 w-full rounded border p-3 font-mono text-xs" value={domain} onChange={e => setDomain(e.target.value)} />
            <button className={button} onClick={() => void action(async () => setRevisionResult(JSON.stringify(await post(`/problems/${build.problem_id}/revision-preview`, { base_revision_id: baseId, domain: JSON.parse(domain) }), null, 2)))}>校验并预览差异</button>
            <button className={`${button} ml-3`} onClick={() => void action(async () => { const saved = await post<{ id: string }>(`/problems/${build.problem_id}/revisions`, { base_revision_id: baseId, domain: JSON.parse(domain) }); setBaseId(saved.id); setRevisionResult('题意已保存；解析需单独预览并重建。'); })}>保存题意</button>
            <pre className="max-h-64 overflow-auto whitespace-pre-wrap text-xs">{revisionResult}</pre></div>}
          <ul className="mt-4 max-h-80 overflow-auto text-sm">{build.artifacts.map((a, i) => <li className="border-b py-2" key={`${a.id}-${i}`}>
            <button className="text-left text-blue-700" onClick={() => setActiveArtifact(a)}>{a.stage_key} · {a.name} · {a.role}</button>
          </li>)}</ul>
          {activeArtifact && <ArtifactPreview key={`${runId}-${activeArtifact.id}`} url={`/api/product/v1/builds/${runId}/artifacts/${activeArtifact.id}`} name={`${activeArtifact.stage_key} · ${activeArtifact.name}`} />}
        </> : stage ? <>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 className="text-lg font-medium">{stage.ordinal}. {stage.title}</h2>
              <p className="mt-1 text-sm text-slate-500">{label(stage.status)}{stage.summary ? ` · ${stage.summary}` : ''}</p>
            </div>
            {terminal(build.status) && (
              <button className={button} onClick={() => void action(async () => setPreview(await post(`/builds/${runId}/rebuild-preview`, { requested_stage: stage.stage_key })))}>
                从此阶段重建…
              </button>
            )}
          </div>
          {preview && preview.requested_stage === stage.stage_key && (
            <div className="mt-4 space-y-2 rounded-xl border border-slate-200 bg-slate-50 p-4 text-sm">
              <h3 className="font-medium">重建影响预览</h3>
              <p>复用：{preview.reuse_stages.join('、') || '无'}</p>
              <p>重新执行：{preview.rerun_stages.join('、') || '无'}</p>
              <p>模型调用阶段：{preview.model_stages.join('、') || '无'}</p>
              <button className={primaryButton} disabled={!preview.available} onClick={() => void action(async () => {
                const created = await post<{ build_id: string }>(`/builds/${runId}/rebuild`, { requested_stage: preview.requested_stage, fingerprint: preview.fingerprint });
                window.location.assign(`/review/runs/${created.build_id}`);
              })}>确认重建</button>
            </div>
          )}
          <div className="mt-5 flex flex-wrap gap-2 border-b border-slate-200 pb-3" role="tablist" aria-label="阶段材料类型">
            {stageTabs.map(item => {
              const count = stageArtifacts(build, stage.stage_key, item.key).length;
              return <button
                key={item.key}
                type="button"
                role="tab"
                aria-selected={tab === item.key}
                className={`rounded-lg px-3 py-1.5 text-sm ${tab === item.key ? 'bg-slate-900 text-white' : 'bg-slate-100 text-slate-700 hover:bg-slate-200'}`}
                onClick={() => { setTab(item.key); setActiveArtifact(null); }}
              >{item.title}{count ? ` (${count})` : ''}</button>;
            })}
          </div>
          <div className="mt-4 space-y-2">
            {!artifacts.length && <p className="py-10 text-center text-sm text-slate-500">本标签下暂无已保存材料。阶段执行后会按输入 / 输出 / 校验 / 调用归类出现。</p>}
            {artifacts.map(a => (
              <button
                key={a.id}
                type="button"
                onClick={() => setActiveArtifact(a)}
                className={`block w-full rounded-xl border px-4 py-3 text-left transition ${activeArtifact?.id === a.id ? 'border-slate-900 bg-slate-50' : 'border-slate-200 hover:border-slate-400'}`}
              >
                <span className="block text-sm font-medium text-slate-900">{a.name}</span>
                <span className="mt-1 block text-xs text-slate-500">{a.role} · {a.content_type} · {(a.size_bytes / 1024).toFixed(1)} KiB</span>
              </button>
            ))}
          </div>
          {activeArtifact && (
            <ArtifactPreview
              key={`${runId}-${activeArtifact.id}-${tab}`}
              url={`/api/product/v1/builds/${runId}/artifacts/${activeArtifact.id}`}
              name={activeArtifact.name}
            />
          )}
        </> : <p className="text-sm text-slate-500">请选择左侧阶段查看对应材料。</p>}
      </section>
    </div>
  </main>;
}
