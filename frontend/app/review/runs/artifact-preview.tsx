'use client';

import { useEffect, useState } from 'react';

type Content = { url: string; kind: 'image' | 'text' | 'binary'; text?: string; mime: string };

export function ArtifactPreview({ url, name }: { url: string; name: string }) {
  const [content, setContent] = useState<Content | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    let objectUrl: string | undefined;
    async function load() {
      try {
        const response = await fetch(url, { signal: controller.signal });
        if (!response.ok) throw new Error(`材料读取失败（HTTP ${response.status}）`);
        const blob = await response.blob();
        const mime = blob.type.split(';')[0].trim().toLowerCase();
        let kind: Content['kind'] = 'binary';
        let text: string | undefined;
        if (['image/png', 'image/jpeg', 'image/webp', 'image/gif'].includes(mime)) kind = 'image';
        else if (mime.startsWith('text/') || mime === 'application/json' || mime.endsWith('+json')) {
          try {
            text = new TextDecoder('utf-8', { fatal: true }).decode(await blob.arrayBuffer());
            // Some legacy metadata labels binary files as text. Never print their bytes.
            if (/[\u0000-\u0008\u000e-\u001f]/.test(text)) text = undefined;
            if (text !== undefined) {
              kind = 'text';
              if (mime === 'application/json' || mime.endsWith('+json')) {
                try { text = JSON.stringify(JSON.parse(text), null, 2); } catch { /* Preserve malformed JSON for review. */ }
              }
            }
          } catch { /* Offer undecodable files for download. */ }
        }
        if (controller.signal.aborted) return;
        // Download unknown files as opaque bytes, never as an executable document.
        objectUrl = URL.createObjectURL(kind === 'binary' ? new Blob([blob], { type: 'application/octet-stream' }) : blob);
        setContent({ url: objectUrl, kind, text, mime });
      } catch (e) {
        if (!controller.signal.aborted) setError(e instanceof Error ? e.message : '材料读取失败');
      }
    }
    void load();
    return () => { controller.abort(); if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [url]);

  return <section aria-label="材料预览" className="mt-4 rounded bg-slate-50 p-3">
    <h3 className="mb-3 break-words text-sm font-medium">{name}</h3>
    {error ? <p role="alert" className="text-sm text-red-800">{error}</p> : !content ? <p role="status">正在读取材料…</p> : <>
      {content.kind === 'image' && <div className="max-h-[70vh] overflow-auto">
        {/* Authenticated, already-fetched blob; no Next image optimization request is needed. */}
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={content.url} alt={name} className="mx-auto h-auto max-w-full" />
      </div>}
      {content.kind === 'text' && <pre className="max-h-96 overflow-auto whitespace-pre-wrap break-words text-xs">{content.text || '（空文件）'}</pre>}
      {content.kind === 'binary' && <p className="text-sm text-slate-600">此材料为二进制文件，可下载查看。</p>}
      <a href={content.url} download={`${name.replace(/[\\/]/g, '-')}${content.kind === 'image' ? `.${content.mime.split('/')[1]}` : content.mime === 'application/json' ? '.json' : content.kind === 'text' ? '.txt' : '.bin'}`} className="mt-3 inline-block text-sm text-blue-700">下载材料</a>
    </>}
  </section>;
}
