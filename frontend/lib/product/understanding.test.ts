import { afterEach, expect, it, vi } from 'vitest';
import { actionKey, changes, formatted, PendingActionSchema, sendAction, UnderstandingError } from './understanding';
import { continueUpload } from './workspace';
afterEach(() => vi.unstubAllGlobals());
const reply = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status });
const problemId = '11111111-1111-4111-8111-111111111111';
const sourceId = '44444444-4444-4444-8444-444444444444';
const key = '66666666-6666-4666-8666-666666666666';

it('uploads into the independent entry without creating a lesson build or an extraction call', async () => {
  const fetcher = vi.fn().mockResolvedValue(reply({ id: problemId, title: null, latest_build_id: null, current_page_build_id: null, updated_at: '' }));
  vi.stubGlobal('fetch', fetcher);
  const result = await continueUpload({ key, filename: 'source.png', sha256: '', upload: { status: 'created', item: { id: key, problem_id: problemId, source_id: sourceId } }, batch_id: key }, null, vi.fn(), false);
  expect(result.kind).toBe('accepted');
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect(fetcher.mock.calls[0][0]).toBe(`/api/product/v1/problems/${problemId}`);
});

it.each(['extraction-runs', 'candidates', 'source-versions'])('restores a lost %s response using the exact persisted body and key', async endpoint => {
  const persisted = new Map<string, string>();
  const storage = { setItem: (k: string, v: string) => persisted.set(k, v), removeItem: (k: string) => persisted.delete(k) };
  const action = { key, path: `/problems/${problemId}/${endpoint}`, body: { base_candidate_id: 'old', source_version_id: 'source', mode: 'review' } };
  const fetcher = vi.fn().mockRejectedValueOnce(new TypeError('lost response')).mockResolvedValue(reply({ id: 'saved' }));
  vi.stubGlobal('fetch', fetcher);
  await expect(sendAction(action, storage, problemId)).rejects.toThrow('lost response');
  const restored = PendingActionSchema.parse(JSON.parse(persisted.get(actionKey(problemId))!));
  await expect(sendAction(restored, storage, problemId)).resolves.toEqual({ id: 'saved' });
  expect(fetcher.mock.calls[0]).toEqual(fetcher.mock.calls[1]);
  expect(persisted.size).toBe(0);
});

it('surfaces version conflicts and schema pointers without retrying stale edits', async () => {
  const storage = { setItem: vi.fn(), removeItem: vi.fn() };
  const fetcher = vi.fn().mockResolvedValueOnce(reply({ error: { details: [{ path: '/root/facts/1', message: 'expected string' }] } }, 422)).mockResolvedValue(reply({}, 409));
  vi.stubGlobal('fetch', fetcher);
  const action = { key, path: '/candidates', body: {} };
  await expect(sendAction(action, storage, problemId)).rejects.toMatchObject({ status: 422, diagnostics: [{ path: '/root/facts/1' }] });
  await expect(sendAction(action, storage, problemId)).rejects.toBeInstanceOf(UnderstandingError);
  expect(storage.removeItem).toHaveBeenCalledTimes(2);
});

it('locates the exact sibling occurrence after formatting without confusing equal strings', () => {
  const value = { root: { facts: ['t>0'], children: [{ facts: ['t>0'] }, { facts: ['t>0'], uncertainties: [] }] } };
  const result = formatted(value);
  expect(JSON.parse(result.text)).toEqual(value);
  expect(result.locations['/root/children/1/facts/0']).toBeGreaterThan(result.locations['/root/children/0/facts/0']);
  expect(result.text.split('\n')[result.locations['/root/children/1/facts/0']].trim()).toBe('"t>0"');
});

it('shows version differences for removals, new goals and changed conditions', () => {
  const result = changes({ root: { facts: ['t>0'], goals: [{ kind: 'find_value', expression: 't' }] } }, { root: { facts: ['t≥0'], goals: [] } });
  expect(result.map(d => d.path)).toEqual(['/root/facts/0', '/root/goals/0']);
  expect(result[0]).toMatchObject({ before: 't>0', after: 't≥0' });
});
