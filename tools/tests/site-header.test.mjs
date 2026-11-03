import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {join} from 'node:path';
import test from 'node:test';
import {SECTIONS, siteChrome, siteHeader, siteSubbar} from '../lib/site-header.mjs';
import {pages, render} from '../sync-site-header.mjs';

const site = file => readFileSync(join(import.meta.dirname, '../../site', file), 'utf8');
const navLinks = html => [...html.match(/<nav class="site-nav"[^>]*>(.*?)<\/nav>/)[1].matchAll(/<a href="([^"]+)"[^>]*>([^<]+)<\/a>/g)]
  .map(m => [m[1], m[2]]);
const current = html => html.match(/<nav class="site-nav"[^>]*>.*?<\/nav>/)[0].match(/aria-current="(\w+)">([^<]+)</)?.slice(1) ?? null;

test('main nav has the five agreed sections in order', () => {
  assert.deepEqual(SECTIONS.map(s => [s.href, s.label]), [
    ['/', '首页'], ['/lab/search/', '拍题学'], ['/nav/', '初中题库'], ['/topics/', '高中专题'], ['/knowledge/', '知识图谱'],
  ]);
  assert.deepEqual(navLinks(siteHeader()), SECTIONS.map(s => [s.href, s.label]));
  assert.equal(current(siteHeader()), null);
  assert.deepEqual(current(siteHeader({section: 'topics', exact: true})), ['page', '高中专题']);
  assert.deepEqual(current(siteHeader({section: 'topics'})), ['true', '高中专题']);
  assert.match(siteHeader(), /<div class="site-header-account" data-site-auth><\/div>/);
});

test('subbar renders tabs or breadcrumbs with tools and width', () => {
  const tabs = siteSubbar({tabs: [{id: 'a', label: 'A', href: '/a/'}, {id: 'b', label: 'B', href: '/b/'}], current: 'b'});
  assert.match(tabs, /<a href="\/a\/">A<\/a><a href="\/b\/" aria-current="page">B<\/a>/);
  const crumbs = siteSubbar({crumbs: [{label: '高中专题', href: '/topics/'}, {label: 'Q01'}], tools: '<button>x</button>', width: '824px'});
  assert.match(crumbs, /style="--site-subbar-width:824px"/);
  assert.match(crumbs, /<li><a href="\/topics\/">高中专题<\/a><\/li><li><span aria-current="page">Q01<\/span><\/li>/);
  assert.match(crumbs, /<div class="site-subbar-tools"><button>x<\/button><\/div>/);
  assert.equal(siteChrome({section: 'home'}), siteHeader({section: 'home'}));
});

test('hand-written pages are in sync with the shared header', () => {
  const list = pages();
  assert.ok(list.length >= 48);
  for (const [file, spec] of list) {
    const html = site(file);
    assert.equal(render(html, spec, file), html, `${file} 需要运行 node tools/sync-site-header.mjs`);
    assert.equal(html.match(/<header class="site-header"/g).length, 1, file);
    assert.match(html, /<link rel="stylesheet" href="\/assets\/css\/site-header\.css\?v=\d+">/, file);
  }
});

test('pages highlight the expected section', () => {
  assert.deepEqual(current(site('index.html')), ['page', '首页']);
  assert.deepEqual(current(site('lab/search/index.html')), ['page', '拍题学']);
  assert.deepEqual(current(site('nav/index.html')), ['page', '初中题库']);
  assert.deepEqual(current(site('topics/index.html')), ['page', '高中专题']);
  assert.deepEqual(current(site('senior-high/index.html')), ['true', '高中专题']);
  assert.deepEqual(current(site('1/q01/index.html')), ['true', '高中专题']);
  assert.equal(current(site('mistake-book/index.html')), null);
  assert.match(site('senior-high/index.html'), /<a href="\/senior-high\/" aria-current="page">解析题库<\/a>/);
  assert.match(site('2/q03/index.html'), /<a href="\/2\/">恒成立问题<\/a><\/li><li><span aria-current="page">Q03<\/span>/);
  assert.match(site('topics/index.html'), /class="site-tabs"[^>]*>[\s\S]*?<a href="\/senior-high\/">解析题库<\/a>/);
});

test('generated knowledge pages use the shared header and section tabs', () => {
  for (const [file, tab] of [['knowledge/index.html', '知识图谱'], ['knowledge/3d/index.html', '3D 知识图谱'], ['knowledge/nodes/index.html', '全部节点']]) {
    const html = site(file);
    assert.deepEqual(current(html), ['true', '知识图谱'], file);
    assert.match(html, new RegExp(`<nav class="site-tabs" aria-label="知识图谱">.*aria-current="page">${tab}</a>`), file);
    assert.doesNotMatch(html, /topbar-links/, file);
  }
});
