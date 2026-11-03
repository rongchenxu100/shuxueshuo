import test from 'node:test';
import assert from 'node:assert/strict';
import {generate} from '../build-public-knowledge-graph.mjs';
import {noScriptRedirect, redirectPage} from '../lib/public-knowledge-compat.mjs';
import {compatibilityHref, legacyGraphHref} from '../../site/assets/knowledge-next/compat.mjs';

const {outputs, compatibility, teaching} = await generate();
const graph = JSON.parse(outputs.get('graph.json'));

test('the release fingerprint appears only in the central release manifest', () => {
  const version = JSON.parse(outputs.get('teaching/version.json')).content_version;
  for (const [name, body] of [...outputs, ...compatibility]) {
    if (name === 'teaching/version.json') continue;
    assert.ok(!body.includes(version), name);
    assert.ok(!body.includes('knowledge-content-version'), name);
  }
});

test('temporary URLs are redirect-only pages and preserve browsing and preview context', () => {
  for (const [name, html] of compatibility) {
    if (!name.endsWith('.html')) continue;
    assert.match(html, /compat-config/);
    assert.match(html, /<head>.*<noscript><meta http-equiv="refresh" content="0;url=\/knowledge\/[^\"]*"><\/noscript><\/head>/s);
    assert.doesNotMatch(html.replace(/<noscript>.*?<\/noscript>/gs, ''), /http-equiv="refresh"/);
    assert.ok(!html.includes('class="entry"'), name);
  }
  assert.equal(compatibilityHref('/knowledge/amgm-formula/', 'https://site/knowledge-next/amgm-formula/?preview=1&graph=%2Fknowledge-next%2F%3Fscope%3Dsection-2-2#formula'), '/knowledge/amgm-formula/?preview=1&graph=%2Fknowledge%2F%3Fscope%3Dsection-2-2#formula');
  assert.equal(compatibilityHref('/knowledge/method-homogeneous/#degree', 'https://site/knowledge/homogeneous-expression/?q=test#old'), '/knowledge/method-homogeneous/?q=test#degree');
  assert.throws(() => compatibilityHref('https://evil.test/knowledge/', 'https://site/knowledge/'));
});

test('no-script fallback keeps the fixed destination and never races script navigation', () => {
  const target = '/knowledge/method-homogeneous/?scope=section-2-2&preview=1#degree';
  const fallback = noScriptRedirect(target);
  assert.equal(fallback, '<noscript><meta http-equiv="refresh" content="0;url=/knowledge/method-homogeneous/?scope=section-2-2&amp;preview=1#degree"></noscript>');
  assert.ok(redirectPage(target).includes(fallback));
  for (const [name, html] of outputs) {
    if (!name.endsWith('.html')) continue;
    const config = html.match(/<script id="(?:compat-config|node-page-config)" type="application\/json">(.*?)<\/script>/s);
    if (!config) continue;
    const value = JSON.parse(config[1]);
    const destination = value.target || value.redirectHref;
    if (!destination) continue;
    assert.ok(html.includes(noScriptRedirect(destination)), name);
    assert.doesNotMatch(html.replace(/<noscript>.*?<\/noscript>/gs, ''), /http-equiv="refresh"/, name);
  }
  // Ambiguous aliases must still offer a choice rather than selecting a node.
  assert.doesNotMatch(outputs.get('case-merge/index.html'), /http-equiv="refresh"/);
});

test('old topic/hash links select actual nodes and ambiguous splits remain a choice', () => {
  const next = new URL(legacyGraphHref(graph, teaching.migration, 'https://site/knowledge/?topic=basic-inequality&preview=1#amgm-formula'), 'https://site');
  assert.equal(next.pathname, '/knowledge/chapters/compulsory-1-ch2/');
  assert.equal(next.searchParams.get('scope'), 'section-2-2');
  assert.equal(next.searchParams.get('node'), 'amgm-formula');
  assert.equal(next.searchParams.get('preview'), '1');
  assert.equal(legacyGraphHref(graph, teaching.migration, 'https://site/knowledge/#strand-function'), null);
  assert.equal(legacyGraphHref(graph, teaching.migration, 'https://site/knowledge/?preview=1#case-merge'), '/knowledge/case-merge/?preview=1');
  const split = outputs.get('case-merge/index.html');
  assert.ok(!split.includes('compat-config'));
  for (const ref of teaching.migration.nodes.find(row => row.legacy === 'case-merge').targets) {
    const [id, entry] = ref.split('#');
    assert.ok(split.includes(`/knowledge/${id}/#${entry}`));
  }
});

test('published problem inventory has exact identities and paths, not inferred prefixes', () => {
  const inventory = JSON.parse(outputs.get('teaching/problems.json'));
  const expected = teaching.topics.flatMap(topic => Object.entries(topic.problems).map(([id, problem]) => [id, {topic: topic.id, path: problem.path}]));
  assert.deepEqual(inventory.problems, Object.fromEntries(expected));
  assert.equal(inventory.content_version, undefined);
  assert.ok(!inventory.problems['inequality-practice-q04']);
  const amgm = outputs.get('amgm-formula/index.html');
  assert.ok([...outputs.values()].some(html => html.includes('打开原题</a>')));
  assert.ok(!amgm.includes('关联预览</a>'));
});
