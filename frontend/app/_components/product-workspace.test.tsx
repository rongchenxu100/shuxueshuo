import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { expect, it, vi } from 'vitest';
import { ProblemListItem } from './product-workspace';

const problem = {
  id: '11111111-1111-4111-8111-111111111111', title: null, latest_build_id: null, current_page_build_id: null,
  updated_at: '2026-09-17T05:08:00Z', source_filename: '规范化图片 (1).png', statement_text: null,
  presentation: { title: '已知函数f(x)=x²+bx+c，g(x)=2x−1。', title_kind: 'source_text' as const,
    image_source_id: '22222222-2222-4222-8222-222222222222', phase: 'understanding' as const,
    status: 'unsupported', reason: null, result_id: '33333333-3333-4333-8333-333333333333' },
};

it('shows original source wording and the processing outcome without a generated page', () => {
  const html = renderToStaticMarkup(<ProblemListItem problem={problem} selected={false} disabled={false} unread onSelect={vi.fn()} />);
  expect(html).toContain('已知函数f(x)=x²+bx+c，g(x)=2x−1。');
  expect(html).toContain('题意已提取 · 暂不支持题型');
  expect(html).toContain('有新的处理结果，未读');
  expect(html).not.toContain('规范化图片');
  expect(html).not.toContain('尚未生成');
});

it('shows the source thumbnail before there is extractable text', () => {
  const value = { ...problem, presentation: { ...problem.presentation, title: '待提取题目', title_kind: 'image' as const, status: 'not_started', result_id: null } };
  const html = renderToStaticMarkup(<ProblemListItem problem={value} selected={false} disabled={false} unread={false} onSelect={vi.fn()} />);
  expect(html).toContain('原题缩略图'); expect(html).toContain('/source-images/');
  expect(html).toContain('已上传 · 待提取'); expect(html).not.toContain('规范化图片');
});
