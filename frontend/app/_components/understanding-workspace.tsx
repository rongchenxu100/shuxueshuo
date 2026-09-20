'use client';
import Link from 'next/link';
import Image from 'next/image';
import { useCallback, useEffect, useRef, useState } from 'react';
import { fileFingerprint } from '@/lib/product/workspace';
import { websocketUrl } from '@/lib/product/client';
import { actionKey, activeUnderstandingBuilds, artifactUrl, cancelUnderstandingBuilds, changes, formatted, PendingActionSchema, request, sendAction, stateLabel, understandingNotice, UnderstandingError, bindingLabel,
  type BindingRun, type Candidate, type Diagnostic, type Json, type MathNode, type PendingAction, type Run, type SourceVersion, type Understanding } from '@/lib/product/understanding';

const button = 'rounded-lg border border-zinc-300 px-3 py-2 text-sm hover:bg-zinc-50 disabled:opacity-40';
const panel = 'rounded-xl border border-zinc-200 bg-white p-5';
const message = (e: unknown) => e instanceof Error ? e.message : '请求未完成';
const dump = (value: unknown) => JSON.stringify(value, null, 2) ?? '（不存在）';
type Supplement = { key: string; filename: string; sha256: string; source_id?: string; base: string | null; sources: string[] };

export function UnderstandingStatusNotice({ data }: { data: Parameters<typeof understandingNotice>[0] }) {
  const text = understandingNotice(data);
  return text ? <p role="status" className="rounded-lg bg-amber-50 p-4 text-sm text-amber-900">{text}</p> : null;
}

export function BindingStatusNotice({ data }: { data: Pick<Understanding, 'binding_status' | 'blocking_reasons'> }) {
  return <div role="status" className="space-y-1 rounded-lg bg-zinc-50 p-3 text-sm">
    <p>{bindingLabel(data.binding_status ?? 'not_checked')}</p>
    {data.blocking_reasons?.map((d, i) => <p key={i} className="text-amber-800">{d.message ?? d.code}</p>)}
  </div>;
}

export function OriginalProblemText({ text }: { text?: string }) {
  return text?.trim()
    ? <p className="mt-3 whitespace-pre-wrap break-words leading-7">{text}</p>
    : <p className="mt-3 text-sm text-zinc-500">此版本尚未保存原题文字，请对照原图。重新提取整题或复核当前版本时可补充转录。</p>;
}

export function CandidateTree({ node, path = '/root', locate }: { node: MathNode; path?: string; locate: (path: string) => void }) {
  return <section className="my-3 border-l-2 border-teal-100 pl-4">
    <h3 className="mb-2 font-semibold">{node.label || '题目'}</h3>
    {(['definitions', 'facts', 'goals', 'uncertainties'] as const).map(field => node[field]?.length ? <div key={field} className="mb-3">
      <p className="mb-1 text-xs text-zinc-500">{{ definitions: '对象与定义', facts: '条件', goals: '所求', uncertainties: '待确认' }[field]}</p>
      {node[field]!.map((value, i) => <button key={i} onClick={() => locate(`${path}/${field}/${i}`)} className="block max-w-full whitespace-pre-wrap break-words rounded px-1 py-1 text-left font-mono text-sm hover:bg-teal-50">{typeof value === 'string' ? value : dump(value)}</button>)}
    </div> : null)}
    {node.children?.map((child, i) => <CandidateTree key={i} node={child} path={`${path}/children/${i}`} locate={locate} />)}
  </section>;
}

export function UnderstandingWorkspace({ problemId }: { problemId: string }) {
  const prefix = `/problems/${problemId}`, supplementKey = `product.understanding.supplement.${problemId}`;
  const [data, setData] = useState<Understanding | null>(null), [history, setHistory] = useState<Candidate[]>([]), [cursor, setCursor] = useState<string | null>(null);
  const [bindingRuns, setBindingRuns] = useState<BindingRun[]>([]), [bindingRun, setBindingRun] = useState<BindingRun | null>(null);
  const [runs, setRuns] = useState<Run[]>([]), [runCursor, setRunCursor] = useState<string | null>(null), [run, setRun] = useState<Run | null>(null);
  const [selected, setSelected] = useState<Candidate | null>(null), [selectedId, setSelectedId] = useState<string | null>(null);
  const [editor, setEditor] = useState(''), [editorBase, setEditorBase] = useState<{ id: string | null; source: string } | null>(null);
  const [dirty, setDirty] = useState(false), [error, setError] = useState(''), [notice, setNotice] = useState(''), [busy, setBusy] = useState(false);
  const [pending, setPending] = useState<PendingAction | null>(null), [supplement, setSupplement] = useState<Supplement | null>(null);
  const [file, setFile] = useState<File | null>(null), [raw, setRaw] = useState<unknown>(null), [extraDiagnostics, setExtraDiagnostics] = useState<Diagnostic[]>([]);
  const editorRef = useRef<HTMLTextAreaElement>(null), inFlight = useRef(false), runChoice = useRef<string | null>(null);
  const dirtyRef = useRef(false), selection = useRef<string | null>(null), loadedEditor = useRef<string | null>(null);
  const load = useCallback(async () => {
    const [fresh, candidates, recent, checks] = await Promise.all([
      request<Understanding>(`${prefix}/understanding`), request<{ candidates: Candidate[]; next_cursor: string | null }>(`${prefix}/candidates`), request<{ runs: Run[]; next_cursor: string | null }>(`${prefix}/extraction-runs`),
      request<{ runs: BindingRun[] }>(`${prefix}/runtime-binding-runs`),
    ]);
    setBindingRuns(checks.runs);
    if (fresh.latest_binding_run) setBindingRun(await request<BindingRun>(`/runtime-binding-runs/${fresh.latest_binding_run.id}`));
    else setBindingRun(null);
    setData(fresh); setHistory(candidates.candidates); setCursor(candidates.next_cursor); setRuns(recent.runs); setRunCursor(recent.next_cursor);
    const id = selection.current ?? fresh.candidate?.id;
    if (id) {
      const value = await request<Candidate>(`${prefix}/candidates/${id}`);
      // An explicit historical selection stays selected while a running extraction advances.
      if (selection.current && selection.current !== id) return;
      setSelected(value); setSelectedId(value.id);
      if (!dirtyRef.current && loadedEditor.current !== value.id) {
        setEditor(formatted(value.candidate_json).text); setEditorBase({ id: value.id, source: value.source_version_id }); loadedEditor.current = value.id;
      }
    } else if (!selection.current) {
      setSelected(null); setSelectedId(null);
      if (!dirtyRef.current) { setEditor(''); setEditorBase(null); loadedEditor.current = null; }
    }
    const runId = runChoice.current ?? fresh.latest_run?.id ?? recent.runs[0]?.id;
    if (runId) setRun(await request<Run>(`/extraction-runs/${runId}`));
    else setRun(null);
  }, [prefix]);
  useEffect(() => {
    const timer = setTimeout(() => {
    try {
      const saved = localStorage.getItem(actionKey(problemId));
      if (saved) setPending(PendingActionSchema.parse(JSON.parse(saved)));
      const upload = localStorage.getItem(supplementKey); if (upload) setSupplement(JSON.parse(upload));
    } catch { setError('本地恢复记录无法读取，请检查浏览器存储。'); }
    void load().catch(e => setError(message(e)));
    }, 0);
    const focus = () => void load().catch(e => setError(message(e)));
    window.addEventListener('focus', focus); return () => { clearTimeout(timer); window.removeEventListener('focus', focus); };
  }, [load, problemId, supplementKey]);
  const activeBuildKey = activeUnderstandingBuilds(data).join(',');
  useEffect(() => {
    if (!activeBuildKey) return;
    const refresh = () => void load().catch(e => setError(message(e)));
    const interval = setInterval(refresh, 2500);
    const socket = new WebSocket(websocketUrl());
    socket.onopen = () => socket.send(JSON.stringify({ streams: activeBuildKey.split(',').map(id => ({ kind: 'build', id, after: 0 })) }));
    socket.onmessage = refresh;
    return () => { clearInterval(interval); socket.close(); };
  }, [activeBuildKey, load]);

  async function cancelActiveBuilds() {
    try { await cancelUnderstandingBuilds(activeBuildKey.split(',')); }
    catch (error) {
      // One cancellation may have succeeded; show the remaining active task.
      await load();
      throw error;
    }
  }

  async function operate(fn: () => Promise<unknown>) {
    if (inFlight.current) return;
    inFlight.current = true; setBusy(true); setError(''); setNotice(''); setExtraDiagnostics([]);
    try { await fn(); await load(); }
    catch (e) { setError(message(e)); if (e instanceof UnderstandingError) setExtraDiagnostics(e.diagnostics); }
    finally {
      const saved = localStorage.getItem(actionKey(problemId)); setPending(saved ? PendingActionSchema.parse(JSON.parse(saved)) : null);
      inFlight.current = false; setBusy(false);
    }
  }
  async function post<T>(path: string, body: unknown): Promise<T> {
    if (localStorage.getItem(actionKey(problemId))) throw new Error('请先恢复上次请求，确认其结果后再提交新操作。');
    const action = { path, body, key: crypto.randomUUID() }; setPending(action);
    return sendAction<T>(action, localStorage, problemId);
  }
  async function ensureSource() {
    if (data!.source_version) return data!.source_version;
    return post<SourceVersion>(`${prefix}/source-versions`, { base_source_version_id: null, source_ids: [data!.primary_source_id] });
  }
  async function start(mode: 'extract' | 'review' | 'validate') {
    const source = await ensureSource(); runChoice.current = null; selection.current = null;
    await post(`${prefix}/extraction-runs`, { source_version_id: source.id, base_candidate_id: data!.candidate?.id ?? null, mode });
    setNotice(mode === 'validate' ? '已提交代码校验，不调用模型。' : '任务已提交，结果将自动更新。');
  }
  async function chooseCandidate(id: string | null) {
    selection.current = id; dirtyRef.current = false; setDirty(false); loadedEditor.current = null;
    setError(''); await load();
  }
  function locate(path: string) {
    try {
      const value = formatted(JSON.parse(editor)), line = value.locations[path] ?? 0;
      setEditor(value.text);
      requestAnimationFrame(() => {
        const start = value.text.split('\n').slice(0, line).reduce((n, l) => n + l.length + 1, 0);
        const input = editorRef.current; input?.focus(); input?.setSelectionRange(start, value.text.indexOf('\n', start) < 0 ? value.text.length : value.text.indexOf('\n', start));
        if (input) input.scrollTop = Math.max(0, line * 22 - 80);
      });
    } catch { setError('JSON 语法不合法，请先修正后定位。'); }
  }
  async function save() {
    const candidate = JSON.parse(editor);
    const source = editorBase?.source ?? (await ensureSource()).id;
    await post(`${prefix}/candidates`, { source_version_id: source, base_candidate_id: editorBase?.id ?? null, candidate });
    dirtyRef.current = false; setDirty(false); selection.current = null; loadedEditor.current = null; runChoice.current = null;
    setNotice('修订已保存并完成代码校验，原图复核需单独发起。');
  }
  async function recoverAction() {
    await sendAction(pending!, localStorage, problemId);
    if (pending!.path.endsWith('/source-versions')) {
      localStorage.removeItem(supplementKey); setSupplement(null); setFile(null);
    }
    selection.current = null; runChoice.current = null; dirtyRef.current = false;
    setDirty(false); loadedEditor.current = null;
  }
  async function addImages() {
    if (!file && !supplement) return;
    let record = supplement;
    if (!record) {
      record = { key: crypto.randomUUID(), filename: file!.name, sha256: await fileFingerprint(file!), base: data!.source_version?.id ?? null, sources: data!.source_version?.images.map(i => i.source_id) ?? [data!.primary_source_id] };
      localStorage.setItem(supplementKey, JSON.stringify(record)); setSupplement(record);
    }
    if (!record.source_id) {
      const found = await request<{ found: boolean; response?: { source_id: string } }>(`/requests/understanding.upload/${record.key}`);
      if (found.found) record.source_id = found.response!.source_id;
      else {
        if (!file || record.filename !== file.name || record.sha256 !== await fileFingerprint(file)) throw new Error('请重新选择上次的补图文件，继续上传。');
        const body = new FormData(); body.set('image', file);
        const response = await request<{ source_id: string }>(`${prefix}/source-images`, { method: 'POST', headers: { 'Idempotency-Key': record.key }, body });
        record.source_id = response.source_id;
      }
      localStorage.setItem(supplementKey, JSON.stringify(record)); setSupplement({ ...record });
    }
    await post(`${prefix}/source-versions`, { base_source_version_id: record.base, source_ids: [...new Set([...record.sources, record.source_id])] });
    localStorage.removeItem(supplementKey); setSupplement(null); setFile(null); selection.current = null; runChoice.current = null;
    dirtyRef.current = false; setDirty(false); loadedEditor.current = null;
    setNotice('新来源已保存。点击“重新提取整题”使用全部图片；旧候选保留在历史中。');
  }
  const candidate = selected, historical = !!candidate && candidate.id !== data?.candidate?.id;
  const shownSource = candidate?.source_version ?? data?.source_version;
  const diagnosis = [...new Map([...extraDiagnostics, ...(historical ? [] : data?.diagnostics ?? []), ...(candidate?.diagnostics ?? [])].map(d => [JSON.stringify(d), d])).values()];
  const disabled = busy || !!pending;
  if (!data) return <main className="p-8"><Link href="/">← 工作台</Link><p role={error ? 'alert' : 'status'} className="my-6">{error || '正在加载题意…'}</p><button className={button} onClick={() => void load().catch(e => setError(message(e)))}>重新加载</button></main>;
  return <main className="mx-auto max-w-[1600px] space-y-5 p-5 md:p-8">
    <header className="flex flex-wrap items-center justify-between gap-3"><div><Link href="/" className="text-sm text-teal-700">← 工作台</Link><h1 className="mt-2 text-2xl font-semibold">题意候选</h1><p className="mt-1 text-sm text-zinc-500">提取、复核与修订记录</p></div><Link href="/understanding" className={button}>上传另一题</Link></header>
    <div className="flex flex-wrap gap-3 rounded-xl bg-teal-50 p-4 text-sm text-teal-900">
      <span>{stateLabel(data.parse_status)}</span><span>· {stateLabel(data.source_reviewed ? 'confirmed' : data.source_status)}</span><span>· {stateLabel(data.match_status ?? 'unavailable')}</span>
      {data.latest_run && <span>· {stateLabel(data.latest_run.status)}</span>}
    </div>
    <UnderstandingStatusNotice data={data} />
    <BindingStatusNotice data={data} />
    <div className="flex flex-wrap gap-2">
      <button className={`${button} bg-teal-700 text-white hover:bg-teal-800`} disabled={disabled} onClick={() => void operate(() => start('extract'))}>{data.source_version ? '重新提取整题' : '提取题意'}</button>
      <button className={button} disabled={disabled || !data.candidate} onClick={() => void operate(() => start('review'))}>复核当前版本（调用模型）</button>
      <button className={button} disabled={disabled || !data.candidate} onClick={() => void operate(() => start('validate'))}>仅代码校验</button>
      <button className={button} disabled={disabled || !data.candidate || !data.source_version || data.binding_status === 'checking'} onClick={() => void operate(() => post(`${prefix}/runtime-binding-runs`, { candidate_id: data.candidate!.id, source_version_id: data.source_version!.id }))}>{data.latest_binding_run ? '重新检查求解条件' : '检查求解条件'}（不调用模型）</button>
      {activeBuildKey && <button className={button} disabled={disabled} onClick={() => void operate(cancelActiveBuilds)}>取消全部处理</button>}
      <button className={button} disabled={busy} onClick={() => void load().catch(e => setError(message(e)))}>刷新</button>
    </div>
    {error && <p role="alert" className="rounded-lg bg-red-50 p-3 text-red-800">{error}</p>}
    {notice && <p role="status" className="rounded-lg bg-teal-50 p-3 text-teal-800">{notice}</p>}
    {pending && <div className={`${panel} space-y-2`}><p>有一项请求尚未确认结果。恢复时使用同一请求，不重复发起。</p><button className={button} disabled={busy} onClick={() => void operate(recoverAction)}>恢复上次请求</button></div>}
    {!!bindingRuns.length && <details className={`${panel} space-y-3`}>
      <summary className="cursor-pointer font-semibold">求解条件检查记录与 JSON 产物</summary>
      <div className="flex flex-wrap gap-2">{bindingRuns.map(item => <button className={button} key={item.id} onClick={() => void request<BindingRun>(`/runtime-binding-runs/${item.id}`).then(setBindingRun).catch(e => setError(message(e)))}>{new Date(item.created_at).toLocaleString()} · {stateLabel(item.status)}</button>)}</div>
      {bindingRun && <><p className="text-xs text-zinc-500">候选版本 {bindingRun.candidate_id}{bindingRun.id !== data.latest_binding_run?.id ? ' · 历史检查' : ''}</p>
        <pre className="max-h-64 overflow-auto whitespace-pre-wrap text-xs">{dump(bindingRun.result_json)}</pre>
        <div className="flex flex-wrap gap-3">{bindingRun.artifacts?.filter(a => a.artifact_type.startsWith('math_runtime:')).map(a => <a className="text-sm text-teal-700 underline" key={a.id} href={`/api/product/v1/builds/${bindingRun.build_id}/artifacts/${a.id}`} target="_blank" rel="noreferrer">{a.artifact_type.replace('math_runtime:', '')}</a>)}</div></>}
    </details>}
    <div className="grid items-start gap-5 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
      <aside className="space-y-5"><section className={panel}><h2 className="mb-3 font-semibold">{historical ? '历史候选对应原图' : '当前原图'}</h2>
        {(shownSource?.images ?? [{ source_id: data.primary_source_id, filename: '原图', sha256: '' }]).map((item, index) => <figure className="mb-4" key={item.source_id}>
          <a href={`/api/product/v1${prefix}/source-images/${item.source_id}`} target="_blank" rel="noreferrer"><Image unoptimized width={1200} height={900} className="max-h-[650px] w-full rounded-lg border object-contain" src={`/api/product/v1${prefix}/source-images/${item.source_id}`} alt={`题图 ${index + 1}：${item.filename}`} /></a>
          <figcaption className="mt-1 text-xs text-zinc-500">{index + 1}. {item.filename}</figcaption>
        </figure>)}
        {shownSource && <p className="break-all text-xs text-zinc-400">来源版本 {shownSource.id}</p>}
      </section>
      <section className={`${panel} space-y-3`}><h2 className="font-semibold">补充题图</h2><p className="text-sm text-zinc-600">补图追加到当前图片列表末尾。保存后再重新提取整题。</p>
        {historical && <p className="text-sm text-amber-800">正在查看历史版本；补图将添加到当前来源。</p>}
        {supplement && <p className="text-sm">待完成：{supplement.filename}</p>}
        <input aria-label="补充题图" type="file" accept="image/png,image/jpeg,image/webp" disabled={disabled} onChange={e => setFile(e.target.files?.[0] ?? null)} />
        <button className={button} disabled={disabled || (!file && !supplement)} onClick={() => void operate(addImages)}>保存补图与新来源</button>
      </section>
      <section className={`${panel} space-y-2`}><h2 className="font-semibold">候选历史</h2><button className={`${button} w-full text-left`} onClick={() => void chooseCandidate(null)}>查看当前来源的候选</button>
        {history.map(item => <button key={item.id} aria-pressed={selectedId === item.id} className={`${button} w-full text-left aria-pressed:border-teal-600 aria-pressed:bg-teal-50`} onClick={() => void chooseCandidate(item.id)}>{item.kind === 'manual' ? '人工修订' : '模型候选'} · {new Date(item.created_at).toLocaleString()}<span className="block text-xs text-zinc-500">{item.id.slice(0, 8)} · {item.id === data.candidate?.id ? '当前采用' : '历史／未采用'}</span></button>)}
        {!history.length && <p className="text-sm text-zinc-500">尚无符合结构要求的候选。原始返回保留在处理记录中。</p>}
        {cursor && <button className={button} onClick={async () => { try { const result = await request<{ candidates: Candidate[]; next_cursor: string | null }>(`${prefix}/candidates?before=${cursor}`); setHistory(h => [...h, ...result.candidates]); setCursor(result.next_cursor); } catch (e) { setError(message(e)); } }}>更多候选</button>}
      </section></aside>
      <div className="min-w-0 space-y-5"><section className={panel}>
        <h2 className="font-semibold">{historical ? '历史原题文字' : '原题文字'}</h2>
        <OriginalProblemText text={candidate?.candidate_json.original_text} />
      </section><section className={panel}>
        <h2 className="font-semibold">{historical ? '历史数学候选' : '数学候选'}</h2>
        {historical && <p className="mt-2 text-sm text-amber-800">历史候选可查看；编辑请先切换到当前版本。</p>}
        {candidate ? <CandidateTree node={candidate.candidate_json.root} locate={locate} /> : <p className="my-5 text-zinc-600">当前来源尚无有效候选。可以重新提取、查看历史或原始返回，也可直接填写 JSON 保存。</p>}
        {candidate && <p className="text-sm text-zinc-500">{candidate.candidate_json.match_reason}</p>}
      </section>
      <section className={`${panel} space-y-3`}><h2 className="font-semibold">校验诊断</h2>
        {!diagnosis.length && <p className="text-sm text-zinc-500">暂无代码或来源诊断。是否已复核请查看顶部独立状态。</p>}
        {diagnosis.map((d, i) => <button className="block w-full rounded bg-amber-50 p-3 text-left text-sm text-amber-900" key={i} onClick={() => locate(d.path ?? '/')}><code className="block break-all">{d.path ?? '/'} · {d.code}</code>{d.message ?? d.action}</button>)}
      </section>
      <section className={`${panel} space-y-3`}><div className="flex flex-wrap items-center justify-between gap-2"><h2 className="font-semibold">JSON 修订 {dirty && <span className="text-sm font-normal text-amber-700">· 未保存</span>}</h2><button className={button} onClick={() => { try { setEditor(formatted(JSON.parse(editor)).text); } catch { setError('JSON 语法不合法'); } }}>格式化</button></div>
        <textarea ref={editorRef} aria-label="题意候选 JSON" spellCheck={false} readOnly={historical || busy} className="min-h-[420px] w-full rounded-lg border bg-zinc-50 p-3 font-mono text-xs leading-[22px]" value={editor} onChange={e => { setEditor(e.target.value); setDirty(true); dirtyRef.current = true; }} />
        <button className={button} disabled={disabled || historical || !editor.trim()} onClick={() => void operate(save)}>保存修订（仅代码校验）</button>
        <details><summary className="cursor-pointer text-sm text-teal-800">与上一候选的差异</summary><Diff before={candidate?.parent_candidate_json ?? null} after={candidate?.candidate_json ?? null} /></details>
        {dirty && <details open><summary className="cursor-pointer text-sm text-teal-800">未保存修改</summary><DraftDiff before={candidate?.candidate_json ?? null} text={editor} /></details>}
      </section></div>
    </div>
    <section className={`${panel} space-y-4`}><h2 className="font-semibold">处理与调用记录</h2>
      <div className="flex flex-wrap gap-2">{runs.map(item => <button key={item.id} className={`${button} ${run?.id === item.id ? 'border-teal-600 bg-teal-50' : ''}`} onClick={() => void operate(async () => { runChoice.current = item.id; setRun(await request<Run>(`/extraction-runs/${item.id}`)); setRaw(null); })}>{item.mode} · {stateLabel(item.status)} · {new Date(item.created_at).toLocaleTimeString()}</button>)}</div>
      {runCursor && <button className={button} onClick={async () => { try { const r = await request<{ runs: Run[]; next_cursor: string | null }>(`${prefix}/extraction-runs?before=${runCursor}`); setRuns(old => [...old, ...r.runs]); setRunCursor(r.next_cursor); } catch (e) { setError(message(e)); } }}>更多记录</button>}
      {run && <>{run.id !== data.latest_run?.id && <p className="text-sm text-amber-800">正在查看历史运行记录；该复核结论不代表当前版本。</p>}<p className="text-sm">任务：{stateLabel(run.status)} · 处理结论：{stateLabel(run.result_json?.status ?? run.error_code ?? '尚未结束')} · 原图复核：{stateLabel(run.result_json?.source_status ?? 'not_reviewed')}</p>
        <div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead><tr className="border-b"><th className="p-2">调用</th><th>状态</th><th>耗时</th><th>输入 / 输出 token</th><th>材料</th></tr></thead><tbody>{run.calls?.map(call => <tr key={call.number} className="border-b"><td className="p-2">{call.number}. {call.stage}</td><td>{call.status}</td><td>{call.details?.elapsed_seconds ?? '—'} 秒</td><td>{call.details?.usage?.prompt_tokens ?? '—'} / {call.details?.usage?.completion_tokens ?? '—'}</td><td><a className="mr-3 underline" href={artifactUrl(run, call.request_artifact_id)} target="_blank" rel="noreferrer">请求</a>{call.response_artifact_id && <button className="underline" onClick={() => void operate(async () => { const response = await fetch(artifactUrl(run, call.response_artifact_id!)); if (!response.ok) throw new Error('原始响应读取失败'); setRaw(await response.json()); })}>原始响应</button>}</td></tr>)}</tbody></table></div>
        <details><summary className="cursor-pointer text-sm text-teal-800">完整校验、修改范围和采用决定</summary><pre className="mt-3 max-h-[500px] overflow-auto whitespace-pre-wrap break-words rounded bg-zinc-50 p-3 text-xs">{dump(run.result_json)}</pre></details>
      </>}
      {raw !== null && <div><h3 className="mb-2 font-semibold">完整原始响应</h3><pre className="max-h-[600px] overflow-auto whitespace-pre-wrap break-words rounded bg-zinc-50 p-4 text-xs">{dump(raw)}</pre></div>}
      {!runs.length && <p className="text-sm text-zinc-500">尚未发起处理任务。</p>}
    </section>
    {data.current_revision_id && <p className="text-sm text-zinc-500">已有完整生成结果使用正式题意版本 {data.formal_page?.revision_id ?? data.current_revision_id}。此处候选独立保存。{data.formal_page && <Link className="ml-2 underline" href={`/review/runs/${data.formal_page.build_id}`}>查看完整生成记录</Link>}</p>}
  </main>;
}

export function Diff({ before, after }: { before: unknown; after: unknown }) {
  const differences = changes(before, after);
  return <div className="mt-2 space-y-2 text-xs">{differences.length ? differences.map(d => <div key={d.path} className="rounded border p-2"><code className="break-all">{d.path}</code><pre className="whitespace-pre-wrap break-words text-red-700">− {dump(d.before)}</pre><pre className="whitespace-pre-wrap break-words text-teal-800">+ {dump(d.after)}</pre></div>) : <p>无差异</p>}</div>;
}
function DraftDiff({ before, text }: { before: unknown; text: string }) {
  let after: Json;
  try { after = JSON.parse(text); } catch { return <p className="text-sm text-amber-800">JSON 语法不合法，暂不能比较。</p>; }
  return <Diff before={before} after={after} />;
}
