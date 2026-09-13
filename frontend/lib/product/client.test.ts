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
});
