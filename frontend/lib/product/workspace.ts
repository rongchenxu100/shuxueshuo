import { z } from 'zod';
import { api, label, post, type ProductBuild } from './client';

const PresentationSchema = z.object({
  title: z.string(), title_kind: z.enum(['source_text', 'image']), image_source_id: z.string().uuid(),
  phase: z.enum(['understanding', 'generation', 'upload']), status: z.string(), reason: z.string().nullable(), result_id: z.string().uuid().nullable(),
});

export const ProblemSchema = z.object({
  id: z.string().uuid(), title: z.string().nullable(), latest_build_id: z.string().uuid().nullable(),
  current_page_build_id: z.string().uuid().nullable(), updated_at: z.string(),
  statement_text: z.string().nullable().optional(), source_filename: z.string().nullable().optional(),
  latest_build_status: z.string().nullable().optional(),
  presentation: PresentationSchema.optional(),
});
export type WorkspaceProblem = z.infer<typeof ProblemSchema>;
export const ProblemListSchema = z.object({ problems: z.array(ProblemSchema) });
const UploadSchema = z.object({
  status: z.enum(['created', 'reused', 'ambiguous']),
  source_id: z.string().uuid().optional(), candidate_ids: z.array(z.string().uuid()).optional(),
  item: z.object({ id: z.string().uuid(), problem_id: z.string().uuid(), source_id: z.string().uuid() }).optional(),
});
export const PendingUploadSchema = z.object({
  key: z.string().uuid(), filename: z.string(), sha256: z.string(), batch_id: z.string().uuid().optional(),
  upload: UploadSchema.optional(),
});
export type PendingUpload = z.infer<typeof PendingUploadSchema>;
export const pendingUploadKey = 'product.workspace.upload.v1';
export const readResultsKey = 'product.workspace.read-results.v1';
export const ReadResultsSchema = z.record(z.string().uuid(), z.string().uuid());
export type ReadResults = z.infer<typeof ReadResultsSchema>;
export const processing = (problem: WorkspaceProblem) => ['queued', 'running'].includes(problem.presentation?.status ?? problem.latest_build_status ?? '');
export function problemTitle(problem: WorkspaceProblem) {
  return (problem.presentation?.title ?? problem.statement_text)?.replace(/\s+/g, ' ').trim() || problem.title || '新上传的题目';
}
export function problemStatus(problem: WorkspaceProblem) {
  const p = problem.presentation;
  if (!p) return label(problem.latest_build_status ?? 'unbuilt');
  if (p.status === 'ready') return p.phase === 'understanding' ? '题意已提取' : '解析已生成';
  if (p.status === 'unsupported') return '题意已提取 · 暂不支持题型';
  if (p.status === 'needs_confirmation') return p.reason === 'missing_figure' ? '待确认题目 · 缺少配图' : '待确认题目';
  if (p.status === 'needs_review') return p.reason === 'stale' ? '题意已保存 · 需重新复核' : '题意已保存 · 待复核';
  if (p.status === 'needs_revision') return '待修订题意';
  if (p.status === 'code_gap') return '题意已保存 · 解析暂不支持';
  if (p.status === 'not_started') return '已上传 · 待提取';
  if (p.status === 'running') return p.phase === 'understanding' ? '正在处理题意' : '正在生成解析';
  if (p.status === 'failed') return p.phase === 'understanding' ? '题意处理失败' : '生成失败';
  return label(p.status);
}
export function unreadResult(problem: WorkspaceProblem, read: ReadResults) {
  if (problem.presentation) return !!problem.presentation.result_id && read[problem.id] !== problem.presentation.result_id;
  return problem.latest_build_status === 'succeeded' && !!problem.current_page_build_id &&
    read[problem.id] !== problem.current_page_build_id;
}
export function markResultRead(problem: WorkspaceProblem, read: ReadResults): ReadResults {
  return unreadResult(problem, read) ? { ...read, [problem.id]: problem.presentation?.result_id ?? problem.current_page_build_id! } : read;
}

export async function fileFingerprint(file: File) {
  const digest = await crypto.subtle.digest('SHA-256', await file.arrayBuffer());
  return Array.from(new Uint8Array(digest), b => b.toString(16).padStart(2, '0')).join('');
}

// Persist each accepted boundary before continuing. Network retries retain the same keys.
export async function continueUpload(pending: PendingUpload, file: File | null, save: (value: PendingUpload) => void, generate = true) {
  let state = { ...pending };
  const persist = () => save({ ...state });
  if (!state.batch_id) {
    const batch = z.object({ id: z.string().uuid() }).parse(await post('/batches', { name: state.filename }, `${state.key}-batch`));
    state = { ...state, batch_id: batch.id }; persist();
  }
  if (!state.upload) {
    const found = z.object({ found: z.boolean(), response: z.unknown().optional() }).parse(await api(`/requests/upload/${state.key}-upload`));
    if (found.found) state.upload = UploadSchema.parse(found.response);
    else {
      if (!file) return { kind: 'needs_file' as const };
      if (await fileFingerprint(file) !== state.sha256 || file.name !== state.filename) throw new Error('请选择上次提交的同一张图片，或放弃该次上传后重新开始。');
      const body = new FormData(); body.set('image', file);
      state.upload = UploadSchema.parse(await api(`/batches/${state.batch_id}/uploads`, {
        method: 'POST', headers: { 'Idempotency-Key': `${state.key}-upload` }, body,
      }));
    }
    persist();
  }
  const upload = state.upload;
  if (upload.status === 'ambiguous') return { kind: 'ambiguous' as const, source_id: upload.source_id!, candidates: upload.candidate_ids ?? [] };
  if (!upload.item) throw new Error('上传响应缺少题目关联，请稍后恢复该次请求。');
  const problem = ProblemSchema.parse(await api(`/problems/${upload.item.problem_id}`));
  // Same-image reuse must still start a new build when the latest run failed or never ran.
  const latest = problem.latest_build_status;
  const needsBuild = upload.status === 'created' ||
    !problem.latest_build_id ||
    !['succeeded', 'queued', 'running'].includes(latest ?? '');
  let buildId: string | null = null;
  let reusedIdle = false;
  if (needsBuild && generate) {
    const build = z.object({ build_id: z.string().uuid() }).parse(await post(`/problems/${upload.item.problem_id}/builds`, {
      source_id: upload.item.source_id, batch_item_id: upload.item.id,
    }, `${state.key}-build`));
    buildId = build.build_id;
  } else {
    reusedIdle = upload.status === 'reused';
  }
  return {
    kind: 'accepted' as const,
    problem: { ...problem, latest_build_id: buildId ?? problem.latest_build_id },
    reused: reusedIdle,
  };
}

export function previewPage(build: ProductBuild | null) {
  return build?.status === 'succeeded' && build.page_current ? build.page_id : null;
}

export function stageLabel(stage: ProductBuild['stages'][number]) {
  return ({ source: '接收题目图片', observation: '识别文字与公式', extraction: '理解题目', projection: '准备求解',
    solver: '求解与验证', evidence: '整理解题依据', lesson: '生成步骤讲解', visual: '绘制交互图形', page: '生成解析网页' }[stage.stage_key] ?? stage.title);
}
