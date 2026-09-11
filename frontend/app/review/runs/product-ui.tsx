'use client';

import Link from 'next/link';
import { useCallback, useEffect, useRef, useState } from 'react';
import { api, post, BuildSchema, type ProductBuild, label, terminal, websocketUrl, failureMessage } from '@/lib/product/client';
import { ArtifactPreview } from './artifact-preview';

type Problem = { id: string; title: string | null; latest_build_id: string | null; current_revision_id: string | null; current_page_build_id: string | null; primary_source_id: string };
type Upload = { status: 'created' | 'reused' | 'ambiguous'; source_id?: string; candidate_ids?: string[];
  item?: { id: string; problem_id: string; source_id: string }; problem?: Problem };
type Pending = { key: string; batch_id?: string; result?: Upload };
const pendingKey = 'product.pending-upload.v1';
const button = 'rounded-lg border border-slate-300 px-4 py-2 text-sm hover:bg-slate-100 disabled:opacity-50';

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
    <header><h1 className="text-2xl font-semibold">题目解析 · Review</h1><p className="mt-2 text-sm text-slate-500">上传完整单题图片，生成解析网页并审查结果。</p></header>
    <section className="rounded-xl border border-dashed border-slate-300 bg-white p-6">
      <label className="block font-medium">拍照或选择题目图片<input disabled={busy} type="file" accept="image/png,image/jpeg,image/webp" className="mt-3 block text-sm" onChange={e => { const file = e.target.files?.[0]; if (file) void upload(file); e.target.value = ''; }} /></label>
      <p className="mt-3 text-sm text-slate-500">PNG、JPEG、WebP，20 MiB 以内。新题会开始生成；相同图片会引用已有题目。</p>
      {busy && <p role="status" className="mt-3">正在接收并登记图片…</p>}
    </section>
    {error && <p role="alert" className="rounded-lg bg-red-50 p-3 text-red-800">{error}</p>}
    {result?.status === 'ambiguous' && <section className="space-y-3 rounded-xl border p-5"><p>发现多个已关联题目，请选择本次引用的题目：</p>{result.candidate_ids?.map(id => <button className={button} key={id} onClick={() => void resolve(id)}>{id}</button>)}</section>}
    {result?.status === 'reused' && <section className="space-y-3 rounded-xl border p-5"><p>已引用已有题目，没有重复生成。</p>
      {result.problem?.latest_build_id ? <Link className={button} href={`/review/runs/${result.problem.latest_build_id}`}>查看已有解析或任务</Link> :
        <button className={button} onClick={() => void generate(result, pending.current?.key ?? crypto.randomUUID()).catch(e => setError(e.message))}>生成解析</button>}
      <button className={`${button} ml-3`} onClick={() => { pending.current = null; localStorage.removeItem(pendingKey); setResult(null); }}>继续上传</button></section>}
    <section><h2 className="mb-3 text-lg font-medium">已有题目</h2><div className="space-y-2">{problems.map(p => <article key={p.id} className="flex items-center justify-between rounded-xl border bg-white p-4">
      <span>{p.title ?? `题目 ${p.id.slice(0, 8)}`}</span>{p.latest_build_id ? <Link className={button} href={`/review/runs/${p.latest_build_id}`}>查看任务</Link> : <span className="text-sm text-slate-500">尚未生成</span>}
    </article>)}{!problems.length && <p className="text-slate-500">还没有题目，上传第一张图片开始。</p>}</div></section>
  </main>;
}

type Preview = { fingerprint: string; requested_stage: string | null; reuse_stages: string[]; rerun_stages: string[]; model_stages: string[]; available: boolean; reasons: { stage: string; code: string }[] };

export function ProductDetail({ runId }: { runId: string }) {
  const [build, setBuild] = useState<ProductBuild | null>(null);
  const [error, setError] = useState('');
  const [connected, setConnected] = useState(false);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [domain, setDomain] = useState('');
  const [baseId, setBaseId] = useState<string | null>(null);
  const [revisionResult, setRevisionResult] = useState('');
  const [artifact, setArtifact] = useState<{ id: string; name: string } | null>(null);
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
  async function action(task: () => Promise<unknown>) { setError(''); try { await task(); await refresh(); } catch (e) { setError(e instanceof Error ? e.message : '操作失败'); } }
  async function edit() {
    if (!build) return;
    const problem = await api<Problem>(`/problems/${build.problem_id}`);
    if (!problem.current_revision_id) throw new Error('尚无通过校验的题意');
    const revision = await api<{ domain_json: unknown }>(`/problems/${build.problem_id}/revisions/${problem.current_revision_id}`);
    setBaseId(problem.current_revision_id); setDomain(JSON.stringify(revision.domain_json, null, 2));
  }
  if (!build) return <main className="p-8"><p>{error || '正在读取任务…'}</p><Link href="/review/runs">返回题目列表</Link></main>;
  return <main className="mx-auto max-w-6xl space-y-5 p-8 text-slate-800">
    <Link className="text-sm text-blue-700" href="/review/runs">← 题目列表</Link>
    <header className="flex items-center justify-between"><div><h1 className="text-2xl font-semibold">题目解析</h1><p className="mt-1 text-sm text-slate-500">{runId.slice(0, 8)} · {label(build.status)} · {connected ? '实时更新' : '正在恢复连接'}</p></div>
      {!terminal(build.status) && <button className={button} onClick={() => void action(() => post(`/builds/${runId}/cancel`, {}))}>取消生成</button>}</header>
    {error && <p role="alert" className="rounded-lg bg-red-50 p-3 text-red-800">{error}</p>}
    {build.error_code && <p className="rounded-lg bg-amber-50 p-3">{failureMessage(build.error_code)}</p>}
    <ol className="grid gap-3 sm:grid-cols-3">{build.stages.map(s => <li key={s.stage_key} className="rounded-xl border bg-white p-4"><div className="flex justify-between"><strong>{s.ordinal}. {s.title}</strong><span className="text-sm">{label(s.status)}</span></div><p className="mt-2 text-sm text-slate-500">{s.summary}</p>
      {terminal(build.status) && <button className="mt-2 text-sm text-blue-700" onClick={() => void action(async () => setPreview(await post(`/builds/${runId}/rebuild-preview`, { requested_stage: s.stage_key })))}>从此阶段重建…</button>}</li>)}</ol>
    {preview && <section className="space-y-3 rounded-xl border bg-white p-5"><h2 className="font-medium">重建影响预览</h2><p>复用：{preview.reuse_stages.join('、') || '无'}</p><p>重新执行：{preview.rerun_stages.join('、') || '无'}</p><p>模型调用阶段：{preview.model_stages.join('、') || '无'}</p>
      <button className={button} disabled={!preview.available} onClick={() => void action(async () => { const created = await post<{ build_id: string }>(`/builds/${runId}/rebuild`, { requested_stage: preview.requested_stage, fingerprint: preview.fingerprint }); window.location.assign(`/review/runs/${created.build_id}`); })}>确认重建</button></section>}
    {build.page_id && <section className="space-y-3 rounded-xl border bg-white p-5"><div className="flex justify-between"><h2 className="font-medium">{build.page_current ? '当前有效解析' : '历史版本预览'}</h2><a className="text-sm text-blue-700" href={`/api/product/v1/pages/${build.page_id}/index.html`} target="_blank" rel="noreferrer">新窗口打开</a></div>
      <iframe title="解析网页" sandbox="allow-scripts" className="h-[75vh] w-full rounded-lg border" src={`/api/product/v1/pages/${build.page_id}/index.html`} />
      <div className="flex gap-3"><button className={button} onClick={() => void action(async () => { await post(`/pages/${build.page_id}/reviews`, { decision: 'approved' }); setDecision('本版本已通过审查'); })}>通过本版本</button>
        <button className={button} onClick={() => void action(async () => { await post(`/pages/${build.page_id}/reviews`, { decision: 'rejected' }); setDecision('本版本已标记需修改'); })}>需修改</button><span>{decision || ({ approved: '本版本已通过审查', rejected: '本版本需修改', revoked: '本版本审查已撤销' }[build.reviews.at(-1)?.decision ?? ''] ?? '尚未审查')}</span></div></section>}
    <details className="rounded-xl border bg-white p-5"><summary className="cursor-pointer font-medium">高级审查：题意修订与执行材料</summary>
      {build.error_code && <p className="mt-3 text-xs text-slate-500">诊断代码：{build.error_code}</p>}
      <button className={`${button} my-4`} onClick={() => void action(edit)}>读取当前题意</button>
      {domain && <div className="space-y-3"><textarea aria-label="题意 JSON" className="h-80 w-full rounded border p-3 font-mono text-xs" value={domain} onChange={e => setDomain(e.target.value)} />
        <button className={button} onClick={() => void action(async () => setRevisionResult(JSON.stringify(await post(`/problems/${build.problem_id}/revision-preview`, { base_revision_id: baseId, domain: JSON.parse(domain) }), null, 2)))}>校验并预览差异</button>
        <button className={`${button} ml-3`} onClick={() => void action(async () => { const saved = await post<{ id: string }>(`/problems/${build.problem_id}/revisions`, { base_revision_id: baseId, domain: JSON.parse(domain) }); setBaseId(saved.id); setRevisionResult('题意已保存；解析需单独预览并重建。'); })}>保存题意</button><pre className="max-h-64 overflow-auto whitespace-pre-wrap text-xs">{revisionResult}</pre></div>}
      <ul className="mt-4 max-h-80 overflow-auto text-sm">{build.artifacts.map((a, i) => <li className="border-b py-2" key={`${a.id}-${i}`}><button className="text-left text-blue-700" onClick={() => setArtifact({ id: a.id, name: `${a.stage_key} · ${a.name}` })}>{a.stage_key} · {a.name} · {a.role}</button></li>)}</ul>
      {artifact && <ArtifactPreview key={`${runId}-${artifact.id}`} url={`/api/product/v1/builds/${runId}/artifacts/${artifact.id}`} name={artifact.name} />}
    </details>
  </main>;
}
