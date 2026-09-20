'use client';
import Link from 'next/link';
import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { continueUpload, PendingUploadSchema, fileFingerprint, type PendingUpload } from '@/lib/product/workspace';

const key = 'product.understanding.upload.v1';
export function UnderstandingUpload() {
  const [file, setFile] = useState<File | null>(null), [pending, setPending] = useState<PendingUpload | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [choices, setChoices] = useState<string[]>([]);
  const router = useRouter();
  useEffect(() => {
    // Restore a browser-owned durable request after hydration.
    const timer = setTimeout(() => { try { const raw = localStorage.getItem(key); if (raw) setPending(PendingUploadSchema.parse(JSON.parse(raw))); } catch { setError('上传恢复记录无法读取。'); } }, 0);
    return () => clearTimeout(timer);
  }, []);
  function save(value: PendingUpload) { localStorage.setItem(key, JSON.stringify(value)); setPending(value); }
  async function upload() {
    if (busy || (!file && !pending)) return;
    setBusy(true); setError('');
    try {
      const state = pending ?? { key: crypto.randomUUID(), filename: file!.name, sha256: await fileFingerprint(file!) };
      save(state);
      const result = await continueUpload(state, file, save, false);
      if (result.kind === 'needs_file') setError('请重新选择同一张图片，继续上次上传。');
      else if (result.kind === 'ambiguous') setChoices(result.candidates);
      else { localStorage.removeItem(key); router.push(`/understanding/${result.problem.id}`); }
    } catch (e) { setError(e instanceof Error ? e.message : '上传未完成'); }
    finally { setBusy(false); }
  }
  return <main className="mx-auto max-w-2xl space-y-6 p-8">
    <Link href="/" className="text-teal-700">← 工作台</Link><h1 className="text-2xl font-semibold">提取题意</h1>
    <p className="text-zinc-600">上传题图后，查看并启动题意提取。支持保存候选、补图和人工修订。</p>
    {pending && <p role="status">继续上传：{pending.filename}。已接收的请求不会重复创建。</p>}
    <input aria-label="题目图片" type="file" accept="image/png,image/jpeg,image/webp" disabled={busy} onChange={e => setFile(e.target.files?.[0] ?? null)} />
    <p className="text-sm text-zinc-500">PNG、JPEG、WebP，最大 20 MiB。补充图片可在题目详情中上传。</p>
    <button className="rounded-lg bg-teal-700 px-4 py-2 text-white disabled:opacity-40" disabled={busy || (!file && !pending)} onClick={() => void upload()}>{busy ? '上传中…' : pending ? '继续上传' : '上传题图'}</button>
    {error && <p role="alert" className="text-red-700">{error}</p>}
    {choices.map(id => <Link className="block underline" key={id} href={`/understanding/${id}`}>查看已有题目 {id.slice(0, 8)}</Link>)}
  </main>;
}
