import { describe, expect, it } from 'vitest';
import { failureMessage } from './client';

describe('extraction failure explanations', () => {
  it('identifies a source image that still needs confirmation', () => {
    expect(failureMessage('extraction.problem_source_uncertain')).toContain('原图题面仍待确认');
    expect(failureMessage('extraction.problem_source_uncertain')).not.toBe(failureMessage('extraction.blocked'));
  });

  it('explains how to replace a build with an outdated extraction policy', () => {
    expect(failureMessage('extraction.rebuild_required')).toContain('提交新构建');
    expect(failureMessage('execution.incompatible_environment')).toContain('提交新构建');
  });

  it('explains unsupported family admission without calling it a system failure', () => {
    expect(failureMessage('admission.family_unmatched')).toContain('暂不支持该题型');
    expect(failureMessage('admission.adapter_missing')).toContain('暂不支持该题型');
  });
});
