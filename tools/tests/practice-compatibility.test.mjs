import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import {tmpdir} from 'node:os';
import {execFileSync} from 'node:child_process';
import {exportContent} from '../export-public-knowledge.mjs';
import {practiceCompatibility} from '../lib/public-knowledge-export.mjs';
import {pageContractHash, checkPracticeCompatibility} from '../../site/assets/learning/practice-compatibility.mjs';

const rows = await exportContent();
const root = path.resolve(import.meta.dirname, '../..');

test('every published HTML/bundle matches its private grading contract and Python version', async () => {
  const expected = [];
  for (const problem of rows.practice_problems) {
    const html = await fs.readFile(path.join(root, 'site', problem.path, 'index.html'), 'utf8');
    const config = JSON.parse(html.match(/<script[^>]*id="(?:practice-config|graph-walk-page)"[^>]*>([\s\S]*?)<\/script>/)[1]);
    const page = config.bundleUrl ? JSON.parse(await fs.readFile(path.join(root, 'site', config.bundleUrl), 'utf8')) : config;
    const version = practiceCompatibility(problem);
    assert.equal(await pageContractHash(page), version.page_contract_hash, problem.id);
    expected.push(version);
  }
  const dir = await fs.mkdtemp(path.join(tmpdir(), 'practice-parity-'));
  try {
    const fixture = path.join(dir, 'problems.json');
    await fs.writeFile(fixture, JSON.stringify(rows.practice_problems));
    const result = execFileSync(path.join(root, 'server/.venv/bin/python'), ['-c',
      'import sys,json; from shuxueshuo_server.learning.compatibility import metadata; print(json.dumps([metadata(p) for p in json.load(open(sys.argv[1]))]))', fixture],
    {cwd: path.join(root, 'server'), encoding: 'utf8', timeout: 20000});
    assert.deepEqual(JSON.parse(result), expected);
  } finally { await fs.rm(dir, {recursive: true, force: true}); }
});

for (const pid of ['basic-inequality-q01', 'function-concepts-q23b-v2']) {
  const original = rows.practice_problems.find(row => row.id === pid);
  const version = practiceCompatibility(original);
  test(`${pid}: presentation updates preserve compatibility; steps, options and grading do not`, () => {
    const cosmetic = structuredClone(original);
    const lesson = cosmetic.problem_data._graph_walk || cosmetic.problem_data._lesson;
    lesson.bundleVersion = 'new-build'; lesson.version = 999;
    const steps = lesson.intro || Object.values(lesson.routes)[0].nodes;
    steps[0].title = '更清晰的标题'; steps[0].feedback = {correct: '很好'};
    steps[0].interaction.title = '请选择';
    assert.deepEqual(practiceCompatibility(cosmetic), version);
    for (const change of [
      step => { step.expected_answer = {one_of: ['new-answer']}; },
      step => { step.id = 'different-step'; },
      step => { step.interaction.field = 'different-input'; },
    ]) {
      const changed = structuredClone(original), course = changed.problem_data._graph_walk || changed.problem_data._lesson;
      change((course.intro || Object.values(course.routes)[0].nodes)[0]);
      assert.notEqual(practiceCompatibility(changed).practice_version, version.practice_version);
    }
    assert.notEqual(practiceCompatibility({...original, association_hash: 'changed'}).practice_version, version.practice_version);
  });
  test(`${pid}: unrelated release changes do not prevent recording; stale page does`, async () => {
    const course = original.problem_data._graph_walk
      ? {...original.problem_data._graph_walk, problem: {text: original.problem_data.statement}}
      : original.problem_data._lesson;
    const problem = {...version, content_version: 'old-release'};
    const calls = [];
    const read = async url => { calls.push(url); return {...version, content_version: 'new-release'}; };
    const access = await checkPracticeCompatibility(course, problem, read);
    assert.equal(access.practiceVersion, version.practice_version);
    assert.equal(access.contentVersion, 'new-release');
    assert.deepEqual(calls, [`/api/learning/content/problems/${pid}`]);
    const stale = structuredClone(course);
    (stale.intro || Object.values(stale.routes)[0].nodes)[0].expected_answer = {};
    await assert.rejects(checkPracticeCompatibility(stale, problem, read), /作答步骤或选项已更新/);
    await assert.rejects(checkPracticeCompatibility(course, problem, async () => ({practice_version: 'changed'})), /本题/);
  });
}
