import { z } from 'zod';

export type Json = null | boolean | number | string | Json[] | { [key: string]: Json };
export type MathNode = { label?: string; definitions?: string[]; facts?: string[]; goals?: Record<string, Json>[]; children?: MathNode[]; uncertainties?: Record<string, Json>[] };
export type MathCandidate = { original_text?: string; root: MathNode; match_status: string; family_id: string | null; match_reason: string };
export type SourceVersion = { id: string; source_hash: string; images: { source_id: string; filename: string; sha256: string }[] };
export type Diagnostic = { path?: string; message?: string; code?: string; action?: string };
export type Validation = { contract_valid: boolean; reports?: { ir?: { issues?: Diagnostic[] }; match?: { issues?: unknown[] } } };
export type Candidate = { id: string; candidate_json: MathCandidate; kind: string; created_at: string; source_version_id: string; validation_json: Validation; parent_candidate_json?: MathCandidate | null; source_version?: SourceVersion; origin_run_id: string | null; diagnostics?: Diagnostic[] };
export type Run = { id: string; mode: string; status: string; created_at: string; build_id: string; error_code: string | null; result_json: { status?: string; source_status?: string; source_reviewed?: boolean; diagnostics?: Diagnostic[]; parsed?: Validation; continuation?: { reason: string; blocked: boolean }; events?: Json[] } | null; calls?: { number: number; stage: string; status: string; request_artifact_id: string; response_artifact_id: string | null; details: { elapsed_seconds?: number; usage?: { prompt_tokens?: number; completion_tokens?: number } } | null }[] };
export type Understanding = { problem_id: string; source_version: SourceVersion | null; candidate: Candidate | null; latest_run: Run | null; parse_status: string; source_status: string; source_reviewed: boolean; review_stale_reason?: 'configuration_changed' | 'candidate_or_source_changed' | 'run_not_completed' | null; match_status: string | null; diagnostics: Diagnostic[]; primary_source_id: string; current_revision_id: string | null; current_page_build_id: string | null; formal_page: { id: string; build_id: string; revision_id: string } | null };

export class UnderstandingError extends Error {
  constructor(public status: number, message: string, public diagnostics: Diagnostic[] = []) { super(message); }
}
export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/product/v1${path}`, { cache: 'no-store', ...init });
  const data = await response.json();
  if (!response.ok) throw new UnderstandingError(response.status, response.status === 409 ? '版本已变化，请刷新后检查差异，再提交修订。' : data.error?.message ?? '请求未完成', data.error?.details ?? []);
  return data;
}
export const PendingActionSchema = z.object({ key: z.string(), path: z.string(), body: z.unknown() });
export type PendingAction = z.infer<typeof PendingActionSchema>;
export const actionKey = (id: string) => `product.understanding.action.${id}`;
export async function sendAction<T>(action: PendingAction, storage: Pick<Storage, 'setItem' | 'removeItem'>, id: string): Promise<T> {
  storage.setItem(actionKey(id), JSON.stringify(action));
  try {
    const result = await request<T>(action.path, { method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': action.key }, body: JSON.stringify(action.body) });
    storage.removeItem(actionKey(id));
    return result;
  } catch (error) {
    // Transport / server failures may have committed. Retain the same body and key.
    if (error instanceof UnderstandingError && [400, 403, 404, 409, 422].includes(error.status)) storage.removeItem(actionKey(id));
    throw error;
  }
}
const escapePointer = (s: string) => s.replaceAll('~', '~0').replaceAll('/', '~1');
export function changes(a: unknown, b: unknown, path = ''): { path: string; before: unknown; after: unknown }[] {
  if (JSON.stringify(a) === JSON.stringify(b)) return [];
  if (a && b && typeof a === 'object' && typeof b === 'object' && Array.isArray(a) === Array.isArray(b)) {
    const left = a as Record<string, unknown>, right = b as Record<string, unknown>;
    return [...new Set([...Object.keys(left), ...Object.keys(right)])].flatMap(k => changes(left[k], right[k], `${path}/${escapePointer(k)}`));
  }
  return [{ path: path || '/', before: a, after: b }];
}
// The editor formats before locating an issue, so duplicate values in sibling questions are unambiguous.
export function formatted(value: unknown) {
  const lines: string[] = [], locations: Record<string, number> = {};
  function visit(v: unknown, path: string, depth: number, prefix = '', suffix = '') {
    locations[path || '/'] = lines.length;
    const indent = '  '.repeat(depth);
    if (v && typeof v === 'object' && Object.keys(v).length) {
      const array = Array.isArray(v), entries = Object.entries(v);
      lines.push(indent + prefix + (array ? '[' : '{'));
      entries.forEach(([k, item], i) => visit(item, `${path}/${escapePointer(k)}`, depth + 1, array ? '' : JSON.stringify(k) + ': ', i < entries.length - 1 ? ',' : ''));
      lines.push(indent + (array ? ']' : '}') + suffix);
    } else lines.push(indent + prefix + JSON.stringify(v) + suffix);
  }
  visit(value, '', 0);
  return { text: lines.join('\n'), locations };
}
export const stateLabel = (value: string) => ({ queued: '排队中', running: '处理中', completed: '处理结束', failed: '技术失败', cancelled: '已取消', superseded: '已被新版本替代', valid: '解析通过', invalid: '解析未通过', unavailable: '尚无候选', confirmed: '原图复核通过', uncertain: '原图待确认', not_reviewed: '尚未复核', stale: '复核已失效', needs_confirmation: '待补充／待确认', reviewed_candidate: '原图复核通过', validated_candidate: '仅代码校验通过', invalid_candidate: '代码校验未通过', code_gap: '解析能力待完善', 'workflow.budget_exhausted': '自动处理次数已用完', 'workflow.no_progress': '修复未取得进展', 'workflow.oscillation': '修复反复变动', matched: '已匹配题型', unmatched: '未匹配题型' }[value] ?? value);
export function understandingNotice(data: Pick<Understanding, 'source_status' | 'source_reviewed' | 'review_stale_reason' | 'latest_run'>): string | null {
  if (data.source_status === 'stale') {
    if (data.review_stale_reason === 'configuration_changed') return '提取或复核的代码、模板或配置已更新，历史复核结论已失效。请复核当前版本（会调用模型）。';
    if (data.review_stale_reason === 'candidate_or_source_changed') return '题意或原图版本已变化，历史复核结论不适用于当前版本。请重新复核。';
    return '历史复核结论已失效，请复核当前版本。';
  }
  if (data.source_reviewed || data.latest_run?.status !== 'completed') return null;
  switch (data.latest_run.result_json?.status) {
    case 'needs_confirmation': return '本次处理已结束，题目仍待补充或确认。请查看下方诊断和原图。';
    case 'code_gap': return '题意候选已保存，部分数学表达尚无法校验，当前版本尚未确认。请查看下方诊断。';
    case 'validated_candidate': return '代码校验已完成；当前版本尚未完成原图复核。';
    default: return '自动处理已结束，当前题意尚未确认。请查看下方诊断和处理记录。';
  }
}
export const artifactUrl = (run: Run, id: string) => `/api/product/v1/builds/${run.build_id}/artifacts/${id}`;
