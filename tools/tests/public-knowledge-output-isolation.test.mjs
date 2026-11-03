import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {generate, repoRoot} from '../build-public-knowledge-graph.mjs';

test('editing one knowledge entry changes only its detail, preview and central release', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'knowledge-output-isolation-'));
  try {
    await fs.mkdir(path.join(root, 'site/data'), {recursive:true});
    await fs.cp(path.join(repoRoot, 'site/data/knowledge-next'), path.join(root, 'site/data/knowledge-next'), {recursive:true});
    await fs.symlink(path.join(repoRoot, 'site/data/graph-walk'), path.join(root, 'site/data/graph-walk'), 'dir');
    for (const part of ['assets', '1', '2', 'topics']) {
      await fs.symlink(path.join(repoRoot, 'site', part), path.join(root, 'site', part), 'dir');
    }
    await fs.symlink(path.join(repoRoot, 'server'), path.join(root, 'server'), 'dir');
    const before = await generate(root);
    const id = 'function-monotonicity-operations';
    const file = path.join(root, 'site/data/knowledge-next/nodes', `${id}.json`);
    const node = JSON.parse(await fs.readFile(file, 'utf8'));
    node.entries[0].body.push('补充一条解释，其他知识点和题目保持原样。');
    await fs.writeFile(file, JSON.stringify(node));
    const after = await generate(root);
    const changed = [...after.outputs].filter(([name, body]) => body !== before.outputs.get(name)).map(([name]) => name).sort();
    assert.deepEqual(changed, [`${id}/index.html`, `teaching/nodes/${id}.json`, 'teaching/version.json'].sort());
    assert.deepEqual(after.compatibility, before.compatibility);

    // A changed label propagates to real references, not an unused all-node
    // dictionary embedded in every article.
    node.label += '（测试）';
    await fs.writeFile(file, JSON.stringify(node));
    const renamed = await generate(root);
    assert.notEqual(renamed.outputs.get('graph.json'), after.outputs.get('graph.json'));
    assert.equal(renamed.outputs.get('amgm-formula/index.html'), before.outputs.get('amgm-formula/index.html'));
    for (const [name, body] of before.outputs) if (/^teaching\/(problems|topics)\//.test(name)) {
      assert.equal(renamed.outputs.get(name), body, name);
    }
    const config = JSON.parse(renamed.outputs.get(`${id}/index.html`).match(/id="node-page-config" type="application\/json">(.*?)<\/script>/s)[1]);
    assert.equal(config.labels, undefined);
    assert.equal(config.links, undefined);
  } finally {
    await fs.rm(root, {recursive:true, force:true});
  }
});
