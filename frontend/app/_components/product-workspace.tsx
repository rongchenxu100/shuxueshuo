'use client';

import Link from 'next/link';
import { useCallback, useEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react';
import { api, post, BuildSchema, failureMessage, formatDuration, label, stageElapsedMs, terminal, websocketUrl, type ProductBuild } from '@/lib/product/client';
import { continueUpload, fileFingerprint, PendingUploadSchema, pendingUploadKey, ProblemListSchema, ProblemSchema,
  previewPage, stageLabel, problemTitle, problemStatus, processing, unreadResult, markResultRead, ReadResultsSchema, readResultsKey, type ReadResults, type PendingUpload, type WorkspaceProblem } from '@/lib/product/workspace';
import styles from './product-workspace.module.css';

const message = (error: unknown) => error instanceof Error ? error.message : '请求未完成，请稍后重试。';

function formatUpdated(value?: string | null) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

export function ProblemListItem({ problem: p, selected, disabled, unread, onSelect }: {
  problem: WorkspaceProblem; selected: boolean; disabled: boolean; unread: boolean; onSelect: () => void;
}) {
  return <button disabled={disabled} aria-current={selected} title={problemTitle(p)} className={styles.item} onClick={onSelect}>
    <span className="flex items-start gap-2">
      {p.presentation?.title_kind === 'image' &&
        // Original source thumbnail is authenticated by the same product API.
        // eslint-disable-next-line @next/next/no-img-element
        <img src={`/api/product/v1/problems/${p.id}/source-images/${p.presentation.image_source_id}`} alt="原题缩略图" loading="lazy" className="h-10 w-12 shrink-0 rounded border border-zinc-200 object-contain" />}
      <span className="line-clamp-2 min-w-0 flex-1 leading-6">{problemTitle(p)}</span>
      {processing(p) ? <span role="status" aria-label={problemStatus(p)} className={styles.spinner} /> :
        unread && <span role="status" aria-label="有新的处理结果，未读" className={styles.unread} />}
    </span>
    <span className="mt-1 block text-xs text-zinc-500">
      <span className={styles.itemStatus} data-status={p.presentation?.status}>{problemStatus(p)}</span>
      {p.updated_at ? ` · ${formatUpdated(p.updated_at)}` : ''}
    </span>
  </button>;
}

export function ProductWorkspace() {
  const [problems, setProblems] = useState<WorkspaceProblem[]>([]);
  const [more, setMore] = useState(false);
  const [readResults, setReadResults] = useState<ReadResults>({});
  const loadedCount = useRef(50);
  const loadingList = useRef(false);
  const [selected, setSelected] = useState<WorkspaceProblem | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [listError, setListError] = useState('');
  const [notice, setNotice] = useState('');
  const [pending, setPending] = useState<PendingUpload | null>(null);
  const [needsFile, setNeedsFile] = useState(false);
  const [candidates, setCandidates] = useState<{ source_id: string; candidates: string[] } | null>(null);
  const [sidebarWidth, setSidebarWidth] = useState(250);
  const [progressWidth, setProgressWidth] = useState(300);
  const [resizing, setResizing] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const [mobilePane, setMobilePane] = useState<'list' | 'detail'>('list');
  const pendingRef = useRef<PendingUpload | null>(null);
  const inFlight = useRef(false);
  const navigation = useRef(0);

  const loadList = useCallback(async (after?: WorkspaceProblem) => {
    if (loadingList.current) return;
    loadingList.current = true;
    try {
      const fresh: WorkspaceProblem[] = [];
      let cursor = after;
      let hasMore = false;
      do {
        const query = new URLSearchParams({ limit: '50' });
        if (cursor) { query.set('before_time', cursor.updated_at); query.set('before_id', cursor.id); }
        const data = ProblemListSchema.parse(await api(`/problems?${query}`));
        fresh.push(...data.problems); hasMore = data.problems.length === 50;
        cursor = data.problems.at(-1);
      } while (!after && hasMore && fresh.length < loadedCount.current);
      loadedCount.current = after ? loadedCount.current + fresh.length : Math.max(50, fresh.length);
      setProblems(old => after ? Array.from(new Map([...old, ...fresh].map(p => [p.id, p])).values()) : fresh);
      setMore(hasMore); setListError('');
    } catch (e) { setListError(message(e)); }
    finally { loadingList.current = false; }
  }, []);

  useEffect(() => {
    const restoreRead = () => {
      try {
        const parsed = ReadResultsSchema.safeParse(JSON.parse(localStorage.getItem(readResultsKey) ?? '{}'));
        if (parsed.success) setReadResults(parsed.data);
      } catch { /* A restricted browser still supports session-only read indicators. */ }
    };
    const boot = requestAnimationFrame(restoreRead);
    const refresh = () => { restoreRead(); void loadList(); };
    const visible = () => { if (!document.hidden) refresh(); };
    const storage = (event: StorageEvent) => { if (event.key === readResultsKey || event.key === null) restoreRead(); };
    const poll = setInterval(() => void loadList(), 5000);
    window.addEventListener('focus', refresh); window.addEventListener('storage', storage);
    document.addEventListener('visibilitychange', visible);
    return () => { cancelAnimationFrame(boot); clearInterval(poll); window.removeEventListener('focus', refresh); window.removeEventListener('storage', storage); document.removeEventListener('visibilitychange', visible); };
  }, [loadList]);

  function acknowledgeResult(problem: WorkspaceProblem) {
    let stored = readResults;
    try {
      const parsed = ReadResultsSchema.safeParse(JSON.parse(localStorage.getItem(readResultsKey) ?? '{}'));
      if (parsed.success) stored = { ...stored, ...parsed.data };
    } catch { /* Keep the in-memory read state if browser storage is unavailable. */ }
    const next = markResultRead(problem, stored);
    setReadResults(next);
    try { localStorage.setItem(readResultsKey, JSON.stringify(next)); } catch { /* Session-only fallback. */ }
  }

  const showProblem = useCallback((problem: WorkspaceProblem | null) => {
    navigation.current++;
    setSelected(problem); setError('');
    if (problem) setMobilePane('detail');
    const url = new URL(window.location.href);
    if (problem) url.searchParams.set('problem', problem.id); else url.searchParams.delete('problem');
    window.history.replaceState(null, '', url);
  }, []);
  const savePending = useCallback((value: PendingUpload) => {
    // Fail before sending a new request if durable browser metadata cannot be saved.
    localStorage.setItem(pendingUploadKey, JSON.stringify(value));
    pendingRef.current = value; setPending(value);
  }, []);

  const resume = useCallback(async (state: PendingUpload, file: File | null) => {
    if (inFlight.current) return;
    inFlight.current = true; setBusy(true); setError(''); setNeedsFile(false);
    try {
      const result = await continueUpload(state, file, savePending);
      if (result.kind === 'needs_file') { setNeedsFile(true); setMobilePane('detail'); return; }
      if (result.kind === 'ambiguous') { setCandidates(result); setMobilePane('detail'); return; }
      localStorage.removeItem(pendingUploadKey); pendingRef.current = null; setPending(null); setCandidates(null);
      showProblem(result.problem);
      setNotice(result.reused
        ? '已找到相同图片，引用已有题目，没有重复生成。'
        : '图片已接收，正在为你生成解析。');
      await loadList();
    } catch (e) { setError(message(e)); }
    finally { inFlight.current = false; setBusy(false); }
  }, [loadList, savePending, showProblem]);

  useEffect(() => {
    let active = true;
    const turn = navigation.current;
    async function initialize() {
      try {
        const raw = localStorage.getItem(pendingUploadKey);
        if (raw) {
          const parsed = PendingUploadSchema.safeParse(JSON.parse(raw));
          if (!parsed.success) throw new Error('上次上传记录无法读取，请清除该次记录后重新选择图片。');
          if (active) { pendingRef.current = parsed.data; setPending(parsed.data); await resume(parsed.data, null); }
          return;
        }
        const id = new URL(window.location.href).searchParams.get('problem');
        if (id) {
          if (!ProblemSchema.shape.id.safeParse(id).success) throw new Error('题目链接无效。');
          const problem = ProblemSchema.parse(await api(`/problems/${id}`));
          if (active && navigation.current === turn) { setSelected(problem); setMobilePane('detail'); }
        }
      } catch (e) { if (active) setError(message(e)); }
    }
    const boot = requestAnimationFrame(() => { void loadList(); void initialize(); });
    return () => { active = false; cancelAnimationFrame(boot); };
  }, [loadList, resume]);

  async function selectProblem(item: WorkspaceProblem) {
    if (inFlight.current) return;
    const turn = ++navigation.current;
    setNotice(''); setError('');
    try {
      const problem = ProblemSchema.parse(await api(`/problems/${item.id}`));
      if (turn === navigation.current) { acknowledgeResult(problem); showProblem(problem); }
    } catch (e) { if (turn === navigation.current) setError(message(e)); }
  }

  async function upload(file: File) {
    if (inFlight.current) return;
    if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type) || file.size > 20 * 1024 * 1024 || !file.size) {
      setError('请选择 20 MiB 以内的 PNG、JPEG 或 WebP 图片。'); return;
    }
    setError('');
    // Lock file fingerprinting too, so rapid double clicks cannot create two upload intents.
    inFlight.current = true; setBusy(true);
    let state: PendingUpload;
    try {
      state = pendingRef.current ?? { key: crypto.randomUUID(), filename: file.name, sha256: await fileFingerprint(file) };
      savePending(state);
    } catch (e) { setError(message(e)); inFlight.current = false; setBusy(false); return; }
    inFlight.current = false;
    await resume(state, file);
  }

  function clearPending() {
    localStorage.removeItem(pendingUploadKey); pendingRef.current = null;
    setPending(null); setCandidates(null); setNeedsFile(false); setError('');
    setNotice('已结束本地上传恢复；服务器已接收的题目和任务仍保留在题目列表中。');
    void loadList();
  }

  async function resolve(id: string) {
    if (!candidates || !pendingRef.current || inFlight.current) return;
    inFlight.current = true; setBusy(true);
    try {
      const result = await post(`/sources/${candidates.source_id}/resolve`, { problem_id: id }, `${pendingRef.current.key}-resolve`);
      const state = PendingUploadSchema.parse({ ...pendingRef.current, upload: result });
      savePending(state); inFlight.current = false;
      await resume(state, null);
    } catch (e) { setError(message(e)); }
    finally { inFlight.current = false; setBusy(false); }
  }

  const activeProblem = selected ? problems.find(p => p.id === selected.id) ?? selected : null;
  const uploadPanel = <>
    {notice && <p role="status" className="mb-4 rounded-xl bg-teal-50 p-3 text-sm text-teal-800">{notice}</p>}
    {error && <p role="alert" className={`${styles.error} mb-4`}>{error}</p>}
    {(pending || busy) && <div className={`${styles.card} mb-4 space-y-3`}>
      <p className="break-words text-sm">{busy ? '正在接收图片并登记生成任务…' : '有一项上传尚未完成'} {pending?.filename}</p>
      {needsFile && <p className={styles.muted}>该图片尚未确认上传成功，请重新选择同一个文件继续。已经接收的请求不会重复生成。</p>}
      {!busy && !candidates && <button className={styles.button} onClick={() => pending && void resume(pending, null)}>恢复上次请求</button>}
      {!busy && <button className={`${styles.button} ml-2`} onClick={clearPending}>结束本地恢复</button>}
    </div>}
    {candidates && <div className={`${styles.card} mb-4 space-y-3`}><p>这张图片对应多个已有题目，请选择要查看的题目：</p>{candidates.candidates.map(id => <button className={`${styles.button} mr-2`} disabled={busy} key={id} onClick={() => void resolve(id)}>{problems.find(p => p.id === id)?.title || `题目 ${id.slice(0, 8)}`}</button>)}</div>}
  </>;

  return <main className={styles.workspace} data-pane={mobilePane} style={{ '--sidebar-width': collapsed ? '56px' : `${sidebarWidth}px`, '--progress-width': `${progressWidth}px` } as CSSProperties}>
    {resizing && <div className="fixed inset-0 z-50 cursor-col-resize" />}
    <aside className={styles.sidebar} aria-label="题目列表">
      <header className={styles.header}>{!collapsed && <span>数学说 · 工作台</span>}<button aria-label={collapsed ? '展开题目列表' : '收起题目列表'} onClick={() => setCollapsed(v => !v)} className={`${styles.collapse} cursor-pointer text-zinc-500`}>{collapsed ? '›' : '‹'}</button></header>
      {!collapsed && <><div className="p-4"><button disabled={busy} className={`${styles.button} ${styles.primary} w-full`} onClick={() => { showProblem(null); setMobilePane('detail'); setNotice(''); }}>＋ 上传新题目</button></div>
        <div className={styles.scroll} style={{ padding: '0 12px 16px' }}>
          <p className="px-3 py-2 text-xs text-zinc-500">我的题目</p>
          {listError && <p role="alert" className={styles.error}>{listError}<button className="ml-2 underline" onClick={() => void loadList()}>重新加载</button></p>}
          {problems.map(p => <ProblemListItem key={p.id} problem={p} selected={selected?.id === p.id} disabled={busy}
            unread={unreadResult(p, readResults)} onSelect={() => void selectProblem(p)} />)}
          {!problems.length && !listError && <p className="p-3 text-sm text-zinc-500">上传第一张题目图片开始。</p>}
          {more && <button className={styles.button} onClick={() => void loadList(problems.at(-1))}>加载更多</button>}
        </div><footer className="border-t border-zinc-200 p-4 text-xs text-zinc-500">本地工作空间</footer>
        <ResizeHandle label="调整题目列表宽度" value={sidebarWidth} min={190} max={340} onChange={setSidebarWidth} onResizing={setResizing} /></>}
    </aside>
    {activeProblem?.latest_build_id ? <RunWorkspace key={`${activeProblem.id}:${activeProblem.latest_build_id}`} problem={activeProblem} onComplete={loadList}
      notices={uploadPanel} width={progressWidth} onWidth={setProgressWidth} onResizing={setResizing}
      onBack={() => setMobilePane('list')} /> : <>
      <section className={styles.middle} aria-label="上传与生成进度"><header className={styles.header}>
        <button type="button" className={styles.back} onClick={() => setMobilePane('list')}>← 题目列表</button>
        <span className="min-w-0 truncate">{selected ? problemTitle(selected) : '新题目'}</span>
      </header><div className={styles.scroll}>
        {uploadPanel}
        {selected ? <UnbuiltProblem problem={selected} onCreated={showProblem} /> : <UploadForm key={pending?.key ?? 'new'} disabled={busy || !!candidates} onUpload={upload} filename={needsFile ? pending?.filename : undefined} />}
      </div></section>
    </>}
  </main>;
}

function UploadForm({ disabled, onUpload, filename }: { disabled: boolean; onUpload: (file: File) => Promise<void>; filename?: string }) {
  const [file, setFile] = useState<File | null>(null);
  const [imageUrl, setImageUrl] = useState('');
  useEffect(() => {
    if (!file) return;
    const url = URL.createObjectURL(file);
    const task = requestAnimationFrame(() => setImageUrl(url));
    return () => { cancelAnimationFrame(task); URL.revokeObjectURL(url); };
  }, [file]);
  return <div className={`${styles.card} space-y-5`}>
    <div><h1 className="text-xl font-semibold">上传图片，生成解析网页</h1><p className={`${styles.muted} mt-3`}>选择一张包含完整题干和配图的单题截图。生成进度会显示在这里，完成后自动展开解析网页。</p></div>
    <label className="block rounded-2xl border border-dashed border-zinc-300 bg-zinc-50 p-5 text-sm">
      <span>{filename ? `重新选择：${filename}` : '拍照或选择题目图片'}</span>
      <input aria-label="题目图片" className="mt-4 block w-full text-sm file:mr-3 file:rounded-lg file:border-0 file:bg-white file:px-3 file:py-2" disabled={disabled} type="file" accept="image/png,image/jpeg,image/webp" onChange={e => { setImageUrl(''); setFile(e.target.files?.[0] ?? null); }} />
    </label>
    {file && imageUrl && <figure><div className="max-h-72 overflow-auto rounded-xl border border-zinc-200 bg-white">
      {/* Local file preview never goes through the image optimization service. */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={imageUrl} alt="待上传题目" className="mx-auto h-auto max-w-full" /></div><figcaption className="mt-2 break-words text-xs text-zinc-500">{file.name}</figcaption></figure>}
    <button className={`${styles.button} ${styles.primary} w-full`} disabled={disabled || !file} onClick={() => file && void onUpload(file)}>{disabled ? '正在提交…' : '上传并生成'}</button>
    <p className={styles.muted}>PNG、JPEG、WebP · 最大 20 MiB<br />相同图片会引用已有题目，不重复生成。多题图片请先裁剪为单题截图。</p>
  </div>;
}

function UnbuiltProblem({ problem, onCreated }: { problem: WorkspaceProblem; onCreated: (problem: WorkspaceProblem) => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function generate() {
    setBusy(true); setError('');
    try {
      const source = await api<{ primary_source_id: string; latest_build_id: string | null }>(`/problems/${problem.id}`);
      if (source.latest_build_id) { onCreated({ ...problem, latest_build_id: source.latest_build_id }); return; }
      const build = await post<{ build_id: string }>(`/problems/${problem.id}/builds`, { source_id: source.primary_source_id }, `workspace-initial:${problem.id}`);
      onCreated({ ...problem, latest_build_id: build.build_id });
    } catch (e) { setError(message(e)); } finally { setBusy(false); }
  }
  return <div className={`${styles.card} space-y-4`}><p>图片已保存，尚未提交生成。</p>{error && <p role="alert" className={styles.error}>{error}</p>}<button disabled={busy} className={`${styles.button} ${styles.primary}`} onClick={() => void generate()}>{busy ? '正在提交…' : '生成解析'}</button></div>;
}

function RunWorkspace({ problem, onComplete, notices, width, onWidth, onResizing, onBack }: {
  problem: WorkspaceProblem; onComplete: () => Promise<void>; notices: ReactNode; width: number;
  onWidth: (value: number) => void; onResizing: (value: boolean) => void; onBack: () => void;
}) {
  const [build, setBuild] = useState<ProductBuild | null>(null);
  const [error, setError] = useState('');
  const [connected, setConnected] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const live = Boolean(build && !terminal(build.status));
  useEffect(() => {
    if (!live) return;
    const boot = requestAnimationFrame(() => setNow(Date.now()));
    const tick = setInterval(() => setNow(Date.now()), 1000);
    return () => { cancelAnimationFrame(boot); clearInterval(tick); };
  }, [live, build?.id]);
  useEffect(() => {
    let stopped = false, fetching = false, completed = false;
    let watermark = 0;
    let socket: WebSocket | null = null;
    let reconnect: ReturnType<typeof setTimeout> | undefined;
    async function refresh() {
      if (stopped || fetching) return;
      fetching = true;
      try {
        const current = BuildSchema.parse(await api(`/builds/${problem.latest_build_id}`));
        if (stopped) return;
        watermark = Math.max(watermark, current.last_seq);
        setBuild(old => old && old.last_seq > current.last_seq ? old : current);
        setError('');
        if (!completed && terminal(current.status)) { completed = true; void onComplete(); }
      } catch (e) { if (!stopped) setError(message(e)); }
      finally { fetching = false; }
    }
    async function connect() {
      await refresh();
      if (stopped) return;
      try {
        socket = new WebSocket(websocketUrl());
        socket.onopen = () => { if (!stopped) setConnected(true); socket?.send(JSON.stringify({ streams: [{ kind: 'build', id: problem.latest_build_id, after: watermark }] })); };
        socket.onmessage = event => {
          if (stopped) return;
          try {
            const data = JSON.parse(event.data);
            if (data.type === 'event' && data.seq > watermark) { watermark = data.seq; void refresh(); }
            if (data.type === 'resnapshot_required') { watermark = 0; socket?.close(); }
          } catch { socket?.close(); }
        };
        socket.onclose = () => { if (!stopped) { setConnected(false); reconnect = setTimeout(() => void connect(), 2000); } };
        socket.onerror = () => socket?.close();
      } catch { if (!stopped) reconnect = setTimeout(() => void connect(), 2000); }
    }
    void connect();
    // Periodic authoritative refresh also covers lost notifications and page invalidation by Review.
    const poll = setInterval(() => void refresh(), 5000);
    const focus = () => void refresh(); window.addEventListener('focus', focus);
    return () => { stopped = true; clearInterval(poll); clearTimeout(reconnect); socket?.close(); window.removeEventListener('focus', focus); };
  }, [problem.id, problem.latest_build_id, onComplete]);
  const normalized = build?.artifacts.find(a => a.stage_key === 'source' && a.name === '规范化图片');
  return <>
    <PagePreview build={build} />
    <section className={styles.middle} aria-label="生成进度"><header className={styles.header}>
      <button type="button" className={styles.back} onClick={onBack}>← 题目列表</button>
      <span>生成进度</span>
      <span className="shrink-0 text-xs font-normal text-zinc-500">{connected ? '实时更新' : '正在同步'}</span>
    </header>
      <div className={styles.scroll}>{notices}{error && <p role="alert" className={`${styles.error} mb-4`}>{error}</p>}
        <div className={`${styles.card} space-y-4`}>
          <h1 className="text-xl font-semibold">{build ? label(build.status) === '已完成' ? '解析已生成' : label(build.status) : '正在读取生成进度…'}</h1>
          {normalized && <details><summary className="cursor-pointer text-sm text-zinc-500">查看题目图片</summary>
            {/* Authenticated artifact endpoint; bypass image optimization. */}
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img alt="题目图片" className="mt-3 h-auto max-w-full rounded-lg" src={`/api/product/v1/builds/${build!.id}/artifacts/${normalized.id}`} />
          </details>}
          {build?.error_code && <div className={styles.error}><p>{failureMessage(build.error_code)}</p><Link className="mt-2 inline-block underline" href={`/review/runs/${build.id}`}>查看诊断与重试</Link></div>}
          {build?.status === 'succeeded' && !previewPage(build) && <p className={styles.muted}>解析版本已失效，请到审查页面确认并重新生成。</p>}
          {build?.status === 'cancelled' && <p className={styles.muted}>本次生成已取消，题目图片仍已保存。</p>}
          {build && !terminal(build.status) && <p className={styles.muted}>正在处理题目。关闭页面不会中断生成，稍后可以从左侧列表继续查看。</p>}
          <ol aria-label="生成步骤">{build?.stages.map(stage => {
            const elapsed = stageElapsedMs(build, stage.id, now);
            const statusLine = [label(stage.status), elapsed != null ? formatDuration(elapsed) : null].filter(Boolean).join(' · ');
            return <li className={styles.stage} key={stage.id}>
              <span className={styles.dot} data-status={stage.status}>{stage.status === 'succeeded' ? '✓' : stage.ordinal}</span>
              <div className="min-w-0 flex-1"><p className="text-sm font-medium">{stageLabel(stage)}</p><p className="mt-1 text-xs text-zinc-500">{statusLine}</p></div>
            </li>;
          })}</ol>
        </div>
      </div>{previewPage(build) && <ResizeHandle label="调整生成进度栏宽度" value={width} min={240} max={480} onChange={onWidth} onResizing={onResizing} reverse />}
    </section>
  </>;
}

function PagePreview({ build }: { build: ProductBuild | null }) {
  const page = previewPage(build);
  if (!page) return null;
  return <section className={styles.preview} aria-label="解析网页"><header className={styles.header}><span>解析网页</span><a className="text-xs font-normal text-teal-700" href={`/api/product/v1/pages/${page}/index.html`} target="_blank" rel="noreferrer">新窗口打开 ↗</a></header>
    <iframe key={page} className={styles.frame} title="题目解析网页" sandbox="allow-scripts" src={`/api/product/v1/pages/${page}/index.html`} />
  </section>;
}

function ResizeHandle({ label: title, value, min, max, onChange, onResizing, reverse = false }: { reverse?: boolean; label: string; value: number; min: number; max: number; onChange: (value: number) => void; onResizing: (value: boolean) => void }) {
  const start = useRef<{ x: number; value: number } | null>(null);
  const clamp = (n: number) => Math.max(min, Math.min(max, n));
  return <button aria-label={title} className={`${styles.resize} ${reverse ? styles.resizeLeft : ''}`}
    onKeyDown={e => { if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') { e.preventDefault(); onChange(clamp(value + (e.key === 'ArrowRight' ? 20 : -20) * (reverse ? -1 : 1))); } }}
    onPointerDown={e => { if (e.button !== 0) return; start.current = { x: e.clientX, value }; e.currentTarget.setPointerCapture(e.pointerId); onResizing(true); }}
    onPointerMove={e => { if (start.current) onChange(clamp(start.current.value + (e.clientX - start.current.x) * (reverse ? -1 : 1))); }}
    onPointerUp={e => { start.current = null; if (e.currentTarget.hasPointerCapture(e.pointerId)) e.currentTarget.releasePointerCapture(e.pointerId); onResizing(false); }}
    onLostPointerCapture={() => { start.current = null; onResizing(false); }} />;
}
