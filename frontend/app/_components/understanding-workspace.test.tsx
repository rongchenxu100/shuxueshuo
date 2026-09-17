import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { expect, it, vi } from 'vitest';
import type { Run } from '@/lib/product/understanding';
import { CandidateTree, Diff, OriginalProblemText, UnderstandingStatusNotice } from './understanding-workspace';

it.each([
  ['needs_confirmation', '题目仍待补充或确认'],
  ['code_gap', '部分数学表达尚无法校验'],
  ['validated_candidate', '当前版本尚未完成原图复核'],
  ['workflow.budget_exhausted', '当前题意尚未确认'],
])('does not present a finished %s task as a confirmed problem', (status, expected) => {
  const run: Run = { id: 'run', mode: 'extract', status: 'completed', created_at: '', build_id: 'build', error_code: null, result_json: { status } };
  const html = renderToStaticMarkup(<UnderstandingStatusNotice data={{ source_status: 'not_reviewed', source_reviewed: false, latest_run: run }} />);
  expect(html).toContain(expected);
  expect(html).not.toContain('原图复核通过');
  expect(html).not.toContain('解析已生成');
});

it('explains stale configuration reviews and directs the user to explicit re-review', () => {
  const html = renderToStaticMarkup(<UnderstandingStatusNotice data={{ source_status: 'stale', source_reviewed: false, review_stale_reason: 'configuration_changed', latest_run: null }} />);
  expect(html).toContain('提取或复核的代码、模板或配置已更新');
  expect(html).toContain('历史复核结论已失效');
  expect(html).toContain('会调用模型');
});

it('does not invalidate a current confirmed review in the UI', () => {
  const html = renderToStaticMarkup(<UnderstandingStatusNotice data={{ source_status: 'confirmed', source_reviewed: true, latest_run: null }} />);
  expect(html).toBe('');
});

it('renders full original wording, line breaks and escaped content independently of mathematics', () => {
  const text = '已知抛物线y=x²+b（b为常数）。\n（1）求顶点坐标。\n<script>alert(1)</script>';
  const html = renderToStaticMarkup(<OriginalProblemText text={text} />);
  expect(html).toContain('已知抛物线y=x²+b（b为常数）。\n（1）求顶点坐标。');
  expect(html).toContain('&lt;script&gt;'); expect(html).not.toContain('<script>');
  expect(html).not.toContain('definitions');
});

it('does not invent missing historical source wording', () => {
  const html = renderToStaticMarkup(<OriginalProblemText />);
  expect(html).toContain('此版本尚未保存原题文字');
});

it('renders schema-valid mathematics even when compilation failed, including missing figures', () => {
  const html = renderToStaticMarkup(<CandidateTree node={{ label: '(1)', facts: ['t+', '<script>'], uncertainties: [{ kind: 'missing_figure', text: '图1缺失' }], children: [{ label: '(2)', goals: [{ kind: 'find_value', expression: 't' }] }] }} locate={vi.fn()} />);
  expect(html).toContain('t+'); expect(html).toContain('图1缺失'); expect(html).toContain('find_value');
  expect(html).toContain('&lt;script&gt;'); expect(html).not.toContain('<script>');
});
it('renders historical JSON differences without requiring a compiled IR', () => {
  const html = renderToStaticMarkup(<Diff before={{ root: { facts: ['x>0'] } }} after={{ root: { facts: ['x≥0'] } }} />);
  expect(html).toContain('/root/facts/0'); expect(html).toContain('x≥0');
});
