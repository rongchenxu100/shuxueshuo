import { z } from 'zod';
import { api, post, type ProductBuild } from './client';

export const ProblemSchema = z.object({
  id: z.string().uuid(), title: z.string().nullable(), latest_build_id: z.string().uuid().nullable(),
  current_page_build_id: z.string().uuid().nullable(), updated_at: z.string(),
  statement_text: z.string().nullable().optional(), source_filename: z.string().nullable().optional(),
  latest_build_status: z.string().nullable().optional(),
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
export const processing = (problem: WorkspaceProblem) => ['queued', 'running'].includes(problem.latest_build_status ?? '');
export function problemTitle(problem: WorkspaceProblem) {
  return problem.statement_text?.replace(/\s+/g, ' ').trim() || problem.title || problem.source_filename || '新上传的题目';
}
export function unreadResult(problem: WorkspaceProblem, read: ReadResults) {
  return problem.latest_build_status === 'succeeded' && !!problem.current_page_build_id &&
    read[problem.id] !== problem.current_page_build_id;
}
export function markResultRead(problem: WorkspaceProblem, read: ReadResults): ReadResults {
  return unreadResult(problem, read) ? { ...read, [problem.id]: problem.current_page_build_id! } : read;
}

export async function fileFingerprint(file: File) {
  const digest = await crypto.subtle.digest('SHA-256', await file.arrayBuffer());
  return Array.from(new Uint8Array(digest), b => b.toString(16).padStart(2, '0')).join('');
}

// Persist each accepted boundary before continuing. Network retries retain the same keys.
export async function continueUpload(pending: PendingUpload, file: File | null, save: (value: PendingUpload) => void) {
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
  let buildId: string | null = null;
  if (upload.status === 'created') {
    const build = z.object({ build_id: z.string().uuid() }).parse(await post(`/problems/${upload.item.problem_id}/builds`, {
      source_id: upload.item.source_id, batch_item_id: upload.item.id,
    }, `${state.key}-build`));
    buildId = build.build_id;
  }
  const problem = ProblemSchema.parse(await api(`/problems/${upload.item.problem_id}`));
  return { kind: 'accepted' as const, problem: { ...problem, latest_build_id: buildId ?? problem.latest_build_id }, reused: upload.status === 'reused' };
}

export function previewPage(build: ProductBuild | null) {
  return build?.status === 'succeeded' && build.page_current ? build.page_id : null;
}

export function stageLabel(stage: ProductBuild['stages'][number]) {
  return ({ source: '接收题目图片', observation: '识别文字与公式', extraction: '理解题目', projection: '准备求解',
    solver: '求解与验证', evidence: '整理解题依据', lesson: '生成步骤讲解', visual: '绘制交互图形', page: '生成解析网页' }[stage.stage_key] ?? stage.title);
}
