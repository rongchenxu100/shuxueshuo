import { z } from 'zod';

export const BuildSchema = z.object({
  id: z.string(), problem_id: z.string(), status: z.string(), error_code: z.string().nullable(),
  requested_revision_id: z.string().nullable(), resolved_revision_id: z.string().nullable(),
  page_id: z.string().nullable(), page_current: z.boolean(), last_seq: z.number(),
  reviews: z.array(z.object({ id: z.string(), decision: z.string(), comment: z.string().nullable(), created_at: z.string() })),
  stages: z.array(z.object({ id: z.string(), stage_key: z.string(), title: z.string(), ordinal: z.number(), status: z.string(), summary: z.string().nullable() })),
  attempts: z.array(z.object({
    id: z.string(), build_stage_id: z.string(), attempt_no: z.number(), kind: z.string(), status: z.string(),
    started_at: z.string().nullable(), finished_at: z.string().nullable(),
  })).default([]),
  artifacts: z.array(z.object({ id: z.string(), name: z.string(), stage_key: z.string(), role: z.string(), content_type: z.string(), size_bytes: z.number() })),
});
export type ProductBuild = z.infer<typeof BuildSchema>;
export const terminal = (state: string) => ['succeeded', 'failed', 'interrupted', 'cancelled'].includes(state);
export const label = (state: string) => ({ queued: '排队中', pending: '等待中', running: '进行中', succeeded: '已完成',
  failed: '失败', interrupted: '已中断', cancelled: '已取消', unbuilt: '尚未生成', blocked: '受阻' }[state] ?? state);

export function formatDuration(ms: number) {
  const seconds = Math.max(0, Math.floor(ms / 1000));
  if (seconds < 60) return `${seconds} 秒`;
  const minutes = Math.floor(seconds / 60);
  const rem = seconds % 60;
  if (minutes < 60) return rem ? `${minutes} 分 ${rem} 秒` : `${minutes} 分`;
  const hours = Math.floor(minutes / 60);
  const min = minutes % 60;
  return min ? `${hours} 小时 ${min} 分` : `${hours} 小时`;
}

/** Latest attempt for a stage; used for live and final elapsed time. */
export function stageElapsedMs(build: ProductBuild, stageId: string, now = Date.now()) {
  const attempt = [...build.attempts].filter(a => a.build_stage_id === stageId).sort((a, b) => b.attempt_no - a.attempt_no)[0];
  if (!attempt?.started_at) return null;
  const start = Date.parse(attempt.started_at);
  if (Number.isNaN(start)) return null;
  const end = attempt.finished_at ? Date.parse(attempt.finished_at) : now;
  if (Number.isNaN(end)) return null;
  return Math.max(0, end - start);
}

export const failureMessage = (code: string) => ({
  'extraction.problem_source_uncertain': '原图题面仍待确认，本次生成已停止。请在高级审查中查看无法辨认或来源不明的区域，并确认图片是否完整、清晰。',
  'extraction.rebuild_required': '题意识别策略已更新，本次任务使用旧配置。请重新预览并提交新构建。',
  'execution.incompatible_environment': '本次任务所属的运行版本已更新，请重新预览并提交新构建。',
  'extraction.blocked': '题意识别未通过校验，本次生成已停止。请在高级审查中查看缺失或冲突的内容。',
  'observation.provider_failed': '图片识别未完成，请检查图片是否完整、清晰。',
  'solver.failed': '本次求解未通过验证，没有生成解析网页。',
  'model.budget_exhausted': '本次生成的模型尝试次数已用完。可以预览后重新提交生成。',
  'job.budget_exhausted': '任务多次中断，已停止自动恢复。可以预览后重新提交生成。',
  'build.environment_changed': '运行条件发生变化，请重新预览生成范围。',
  'build.timeout': '本次生成超过时限，已停止。',
  'page.compile_failed': '解析网页编译未通过，请查看阶段校验材料。',
}[code] ?? '本次生成未完成，请查看阶段校验材料后预览重建范围。');

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/product/v1${path}`, { cache: 'no-store', ...init });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error?.message ?? data.detail ?? '请求未完成');
  return data as T;
}

export const post = <T>(path: string, body: unknown, key = crypto.randomUUID()) => api<T>(path, {
  method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': key }, body: JSON.stringify(body),
});

export function websocketUrl() {
  // Local: connect to product API on loopback. Production: same host as the page
  // (Nginx proxies /api/product/ including WebSocket).
  let origin = process.env.NEXT_PUBLIC_PRODUCT_WS_ORIGIN ?? 'ws://127.0.0.1:8000';
  if (typeof window !== 'undefined') {
    const host = window.location.hostname;
    if (!['127.0.0.1', 'localhost', '[::1]'].includes(host)) {
      origin = `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}`;
    }
  }
  const url = new URL('/api/product/v1/ws', origin);
  if (!['ws:', 'wss:'].includes(url.protocol)) throw new Error('WebSocket 协议无效');
  const loopback = ['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname);
  const sameSite = typeof window !== 'undefined' && url.hostname === window.location.hostname;
  if (!loopback && !sameSite) throw new Error('WebSocket 地址必须是本机服务或当前站点');
  return url.toString();
}
