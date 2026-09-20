import { afterEach, describe, expect, it, vi } from 'vitest';
import { continueUpload, fileFingerprint, previewPage, stageLabel, problemTitle, problemStatus, problemIntervention, processing, unreadResult, markResultRead, ReadResultsSchema, type PendingUpload } from './workspace';
import type { ProductBuild } from './client';

afterEach(() => vi.unstubAllGlobals());
const problemId = '11111111-1111-4111-8111-111111111111';
const batchId = '22222222-2222-4222-8222-222222222222';
const buildId = '33333333-3333-4333-8333-333333333333';
const sourceId = '44444444-4444-4444-8444-444444444444';
const itemId = '55555555-5555-4555-8555-555555555555';
const problem = { id: problemId, title: null, latest_build_id: buildId, current_page_build_id: null, updated_at: '2026-09-11T00:00:00Z' };
const uploaded = { status: 'created' as const, item: { id: itemId, problem_id: problemId, source_id: sourceId } };
const initial = (): PendingUpload => ({ key: '66666666-6666-4666-8666-666666666666', filename: 'question.png', sha256: 'original' });
const reply = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } });

it('uses source wording, never filenames or UUIDs as the student title', () => {
  expect(problemTitle({ ...problem, statement_text: '已知抛物线\n（1）求顶点' })).toBe('已知抛物线 （1）求顶点');
  expect(problemTitle({ ...problem, source_filename: '数学作业.png' })).toBe('新上传的题目');
  expect(problemTitle(problem)).toBe('新上传的题目');
});

it('uses the latest presentation for titles, outcomes, progress and unread results', () => {
  const value = { ...problem, statement_text: '旧题干', latest_build_status: 'succeeded', current_page_build_id: buildId,
    presentation: { title: '已知函数f(x)=x²+bx+c，g(x)=2x−1。', title_kind: 'source_text' as const, image_source_id: sourceId,
      phase: 'understanding' as const, status: 'unsupported', reason: null, result_id: itemId } };
  expect(problemTitle(value)).toBe(value.presentation.title);
  expect(problemStatus(value)).toBe('暂不支持题型');
  expect(unreadResult(value, { [problemId]: buildId })).toBe(true);
  const read = markResultRead(value, {});
  expect(read[problemId]).toBe(itemId);
  expect(unreadResult(value, read)).toBe(false);
  const running = { ...value, presentation: { ...value.presentation, status: 'running', result_id: null } };
  expect(processing(running)).toBe(true);
  expect(unreadResult(running, {})).toBe(false);
  expect(problemStatus(running)).toBe('正在提取题目');
  expect(problemStatus({ ...value, presentation: { ...value.presentation, status: 'needs_confirmation', reason: 'missing_figure' } }))
    .toBe('题目缺少图片');
  expect(problemStatus({ ...value, presentation: { ...value.presentation, status: 'needs_review', reason: 'stale' } }))
    .toBe('题目需要确认');
  expect(problemStatus({ ...value, presentation: { ...value.presentation, status: 'needs_revision' } }))
    .toBe('题目需要确认');
  expect(problemStatus({ ...value, presentation: { ...value.presentation, phase: 'generation', status: 'ready' } }))
    .toBe('已完成');
  expect(problemStatus({
    ...value,
    latest_build_status: 'running',
    presentation: { ...value.presentation, phase: 'understanding', status: 'ready' },
  })).toBe('正在解答');
  expect(processing({
    ...value,
    latest_build_status: 'running',
    presentation: { ...value.presentation, phase: 'understanding', status: 'ready' },
  })).toBe(true);
  expect(unreadResult({
    ...value,
    latest_build_status: 'running',
    presentation: { ...value.presentation, phase: 'understanding', status: 'ready' },
  }, {})).toBe(false);
  expect(problemStatus({ ...value, latest_build_status: 'failed', presentation: { ...value.presentation, status: 'ready' } }))
    .toBe('解答失败（系统错误）');
  expect(problemStatus({
    ...value,
    latest_build_status: 'failed',
    presentation: { ...value.presentation, status: 'unsupported', reason: 'admission.family_unmatched' },
  })).toBe('暂不支持题型');
  expect(problemIntervention({
    ...value,
    presentation: { ...value.presentation, status: 'unsupported', reason: 'admission.family_unmatched' },
  })).toBe('unsupported');
  expect(problemStatus({ ...value, presentation: { ...value.presentation, phase: 'generation', status: 'running' } }))
    .toBe('正在解答');
  expect(problemStatus({ ...value, presentation: { ...value.presentation, phase: 'understanding', status: 'queued' } }))
    .toBe('正在提取题目');
  expect(problemStatus({ ...value, presentation: { ...value.presentation, phase: 'understanding', status: 'failed' } }))
    .toBe('提取题目失败（系统错误）');
  expect(problemStatus({ ...value, presentation: { ...value.presentation, phase: 'generation', status: 'failed' } }))
    .toBe('解答失败（系统错误）');
  expect(problemIntervention({ ...value, presentation: { ...value.presentation, status: 'needs_confirmation', reason: 'missing_figure' } }))
    .toBe('missing_figure');
  expect(problemIntervention({ ...value, presentation: { ...value.presentation, status: 'needs_revision' } }))
    .toBe('confirmation');
  expect(problemIntervention({ ...value, presentation: { ...value.presentation, status: 'code_gap' } }))
    .toBe('unsupported');
});

it('marks only completed results as read and alerts again for a different generated page', () => {
  const completed = { ...problem, latest_build_status: 'succeeded', current_page_build_id: buildId };
  expect(unreadResult(completed, {})).toBe(true);
  const read = markResultRead(completed, {});
  expect(unreadResult(completed, ReadResultsSchema.parse(JSON.parse(JSON.stringify(read))))).toBe(false);
  expect(unreadResult({ ...completed, current_page_build_id: sourceId }, read)).toBe(true);
  for (const status of ['queued', 'running', 'failed', 'cancelled']) {
    const pending = { ...completed, latest_build_status: status };
    expect(unreadResult(pending, {})).toBe(false);
    expect(markResultRead(pending, {})).toEqual({});
  }
  expect(processing({ ...problem, latest_build_status: 'running' })).toBe(true);
  expect(processing({ ...problem, latest_build_status: 'queued' })).toBe(true);
  expect(processing(completed)).toBe(false);
  expect(unreadResult({ ...completed, current_page_build_id: null }, {})).toBe(false);
});

describe('workspace upload recovery', () => {
  it('recovers an accepted upload after response loss, then submits exactly the original first build', async () => {
    const fetcher = vi.fn(async (url: string) => {
      if (url.includes('/requests/upload/')) return reply({ found: true, response: uploaded });
      if (url.endsWith('/builds')) return reply({ build_id: buildId });
      return reply(problem);
    }); vi.stubGlobal('fetch', fetcher);
    const save = vi.fn();
    const result = await continueUpload({ ...initial(), batch_id: batchId }, null, save);
    expect(result.kind).toBe('accepted');
    expect(fetcher.mock.calls.map(([url]) => url).some(url => url.endsWith('/uploads'))).toBe(false);
    const buildCall = fetcher.mock.calls.find(([url]) => url.endsWith('/builds'))!;
    const options = (buildCall as unknown as [string, RequestInit])[1];
    expect(options.headers).toMatchObject({ 'Idempotency-Key': `${initial().key}-build` });
    expect(JSON.parse(String(options.body))).toMatchObject({ batch_item_id: itemId });
    expect(save).toHaveBeenCalledWith(expect.objectContaining({ upload: uploaded }));
  });

  it('skips rebuild only when a reused image already has a live or successful build', async () => {
    const newBuild = '77777777-7777-4777-8777-777777777777';
    for (const status of ['succeeded', 'queued', 'running'] as const) {
      const fetcher = vi.fn().mockResolvedValue(reply({ ...problem, latest_build_status: status }));
      vi.stubGlobal('fetch', fetcher);
      const result = await continueUpload({ ...initial(), batch_id: batchId, upload: { ...uploaded, status: 'reused' } }, null, vi.fn());
      expect(result).toMatchObject({ kind: 'accepted', reused: true, problem: { latest_build_id: buildId } });
      expect(fetcher).toHaveBeenCalledTimes(1);
      expect(fetcher.mock.calls[0][1]?.method).toBeUndefined();
    }
    for (const status of ['failed', 'interrupted', 'cancelled', null] as const) {
      const fetcher = vi.fn(async (url: string) => {
        if (url.endsWith('/builds')) return reply({ build_id: newBuild });
        return reply({ ...problem, latest_build_id: status === null ? null : buildId, latest_build_status: status });
      });
      vi.stubGlobal('fetch', fetcher);
      const result = await continueUpload({ ...initial(), batch_id: batchId, upload: { ...uploaded, status: 'reused' } }, null, vi.fn());
      expect(result).toMatchObject({ kind: 'accepted', reused: false, problem: { latest_build_id: newBuild } });
      expect(fetcher.mock.calls.some(([url]) => String(url).endsWith('/builds'))).toBe(true);
    }
  });

  it('retains the build request key when the build response is lost', async () => {
    let saved = { ...initial(), batch_id: batchId, upload: uploaded };
    let first = true;
    const keys: unknown[] = [];
    const fetcher = vi.fn(async (url: string, options?: RequestInit) => {
      if (url.endsWith('/builds')) {
        keys.push((options?.headers as Record<string, string>)['Idempotency-Key']);
        if (first) { first = false; throw new Error('connection lost'); }
        return reply({ build_id: buildId });
      }
      return reply(problem);
    }); vi.stubGlobal('fetch', fetcher);
    await expect(continueUpload(saved, null, p => { saved = p as typeof saved; })).rejects.toThrow('connection lost');
    await expect(continueUpload(saved, null, vi.fn())).resolves.toMatchObject({ kind: 'accepted' });
    expect(keys).toEqual([`${initial().key}-build`, `${initial().key}-build`]);
  });

  it('requires the original file only when the upload was not accepted', async () => {
    const fetcher = vi.fn().mockImplementation(() => Promise.resolve(reply({ found: false }))); vi.stubGlobal('fetch', fetcher);
    await expect(continueUpload({ ...initial(), batch_id: batchId }, null, vi.fn())).resolves.toEqual({ kind: 'needs_file' });
    expect(fetcher).toHaveBeenCalledTimes(1);
    const other = new File(['different bytes'], 'question.png', { type: 'image/png' });
    await expect(continueUpload({ ...initial(), batch_id: batchId }, other, vi.fn())).rejects.toThrow('同一张图片');
    expect(fetcher.mock.calls.every(([, options]) => !options?.method)).toBe(true);
  });

  it('uploads one selected file using the original request key and persists the accepted item', async () => {
    const file = new File(['image bytes'], 'question.png', { type: 'image/png' });
    const state = { ...initial(), sha256: await fileFingerprint(file) };
    const fetcher = vi.fn(async (url: string, options?: RequestInit) => {
      if (url.endsWith('/batches')) return reply({ id: batchId });
      if (url.includes('/requests/upload/')) return reply({ found: false });
      if (url.endsWith('/uploads')) {
        expect(options?.body).toBeInstanceOf(FormData);
        expect((options?.body as FormData).get('image')).toBe(file);
        expect(options?.headers).toEqual({ 'Idempotency-Key': `${state.key}-upload` });
        return reply(uploaded);
      }
      if (url.endsWith('/builds')) return reply({ build_id: buildId });
      return reply(problem);
    }); vi.stubGlobal('fetch', fetcher);
    const save = vi.fn();
    await expect(continueUpload(state, file, save)).resolves.toMatchObject({ kind: 'accepted', reused: false });
    expect(save.mock.calls[0][0]).toMatchObject({ batch_id: batchId });
    expect(save.mock.calls.at(-1)![0]).toMatchObject({ upload: uploaded });
  });

  it('does not generate for ambiguous matches or turn backend failure into mock success', async () => {
    const fetcher = vi.fn(); vi.stubGlobal('fetch', fetcher);
    await expect(continueUpload({ ...initial(), batch_id: batchId, upload: { status: 'ambiguous', source_id: sourceId, candidate_ids: [problemId] } }, null, vi.fn())).resolves.toMatchObject({ kind: 'ambiguous' });
    expect(fetcher).not.toHaveBeenCalled();
    fetcher.mockResolvedValue(reply({ error: { message: '服务不可用' } }, 503));
    await expect(continueUpload(initial(), null, vi.fn())).rejects.toThrow('服务不可用');
  });
});

it('shows only the selected successful current page and keeps unknown stage titles from the snapshot', () => {
  const build = { status: 'succeeded', page_current: true, page_id: buildId } as ProductBuild;
  expect(previewPage(build)).toBe(buildId);
  expect(previewPage({ ...build, status: 'failed' })).toBeNull();
  expect(previewPage({ ...build, status: 'failed' }, sourceId)).toBe(sourceId);
  expect(previewPage({ ...build, page_current: false })).toBeNull();
  expect(previewPage({ ...build, status: 'running' }, sourceId)).toBeNull();
  expect(stageLabel({ stage_key: 'new_stage', title: '新流程步骤' } as ProductBuild['stages'][number])).toBe('新流程步骤');
});
