import fs from 'node:fs/promises';
import path from 'node:path';
import { isDeepStrictEqual } from 'node:util';
import { splitRef } from '../../site/assets/knowledge-next/model.mjs';
import { branches } from '../../site/assets/knowledge-next/teaching-model.mjs';
import { loadGraphWalkProblem } from './graph-walk-practice.mjs';

const json = async (file) => JSON.parse(await fs.readFile(file, 'utf8'));
const equal = (a, b, message) => {
  if (!isDeepStrictEqual(a, b)) throw Error(message);
};
const insist = (ok, message) => {
  if (!ok) throw Error(message);
};
const ids = (list) => list.map((x) => x.id);
export function checkRef(ref, nodes, kinds = ['knowledge', 'skill', 'method']) {
  insist(
    typeof ref === 'string' && /^[a-z][a-z0-9-]*(?:#[a-z][a-z0-9-]*)?$/.test(ref),
    `教学引用格式无效：${ref}`
  );
  const { id, entry } = splitRef(ref),
    node = nodes.find((n) => n.id === id);
  insist(node && kinds.includes(node.kind), `教学引用类型不符或节点不存在：${ref}`);
  if (entry)
    insist(
      ['entries', 'operations', 'steps', 'branches'].some((k) => node[k]?.some((x) => x.id === entry)),
      `教学引用条目失效：${ref}`
    );
  return node;
}

// New topics declare their own location, including before any exercise exists.
// Older sources keep the original library location without needing a migration.
export function topicPath(topic) {
  const value = topic.path ?? topic.legacyPath ?? Object.values(topic.problems || {})[0]?.path?.replace(/q\d+\/$/, '');
  insist(typeof value === 'string' && /^\/(?:[a-z0-9][a-z0-9-]*\/)+$/.test(value), `专题缺少有效站内目录路径：${topic.id}`);
  return value;
}

export function validateTopicSource(source, nodes) {
  insist(source.schemaVersion === 1 && typeof source.id === 'string' && /^[a-z][a-z0-9-]*$/.test(source.id), `专题身份不符：${source.id}`);
  insist(typeof source.label === 'string' && source.label.trim(), `专题名称缺失：${source.id}`);
  topicPath(source);
  insist(Array.isArray(source.groups), `专题分组缺失：${source.id}`);
  insist(source.problems && typeof source.problems === 'object' && !Array.isArray(source.problems), `专题题目清单无效：${source.id}`);
  insist(new Set(source.groups.map(g => g.id)).size === source.groups.length, `训练分组重复：${source.id}`);
  for (const group of source.groups) {
    insist(typeof group.id === 'string' && /^[a-z][a-z0-9-]*$/.test(group.id) && typeof group.label === 'string' && group.label.trim(), `专题分组无效：${source.id}`);
    insist(Array.isArray(group.problems), `分组题目清单无效：${source.id}/${group.id}`);
    insist(group.groupBy === undefined || group.groupBy === 'method', `未知题目分组方式：${source.id}/${group.id}`);
    if (group.type) checkRef(group.type, nodes, ['problem_type']);
  }
  equal([...new Set(source.groups.flatMap(g => g.problems))].sort(), Object.keys(source.problems).sort(), `训练分组未覆盖题目：${source.id}`);
  if (source.presentation !== undefined) {
    insist(source.presentation === 'topic-overview', `未知专题呈现方式：${source.id}`);
    insist(source.path?.startsWith('/topics/') && source.path !== '/topics/', `专题总览必须声明独立路径：${source.id}`);
    insist(typeof source.introduction === 'string' && source.introduction.trim(), `专题引入缺失：${source.id}`);
    insist(source.chapter && ['label', 'book', 'number', 'section'].every(key => typeof source.chapter[key] === 'string' && source.chapter[key].trim()), `专题章节信息缺失：${source.id}`);
    checkRef(source.chapter.ref, nodes, ['section']);
    insist(Array.isArray(source.knowledge) && source.knowledge.length > 0, `专题知识入口缺失：${source.id}`);
    insist(new Set(source.knowledge).size === source.knowledge.length, `专题知识入口重复：${source.id}`);
    source.knowledge.forEach(ref => {
      checkRef(ref, nodes, ['knowledge']);
      insist(!ref.includes('#'), `专题知识入口须引用完整节点：${source.id}/${ref}`);
    });
    insist(source.groups.every(group => group.type), `专题总览分组缺少题型：${source.id}`);
  }
  return source;
}

export function validateSelector(tree, fields, validateLeaf, label) {
  insist(tree && typeof tree === 'object', `缺少关联：${label}`);
  function walk(t, used = new Set()) {
    if (!t.field) {
      validateLeaf(t);
      return;
    }
    insist(!used.has(t.field) && fields.has(t.field), `选择字段不存在或重复：${label}/${t.field}`);
    const keys = Object.keys(t.options || {});
    insist(
      keys.length && keys.every((k) => fields.get(t.field).includes(k)),
      `选择分支不存在：${label}/${t.field}`
    );
    // All accepted choices must have a branch. Wrong choices can have no effective association.
    insist(
      fields.get(t.field).accepted.every((k) => keys.includes(k)),
      `遗漏有效选择分支：${label}/${t.field}`
    );
    for (const v of Object.values(t.options)) walk(v, new Set([...used, t.field]));
  }
  walk(tree);
}

export async function loadTeaching(root, nodes, manifest) {
  const dir = path.join(root, 'site/data/knowledge-next/topics');
  const names = (await fs.readdir(dir)).filter((f) => f.endsWith('.json')).sort();
  const topics = [],
    lessons = new Map(),
    reverse = {},
    counts = { problems: 0, routes: 0, steps: 0, tips: 0 };
  const add = (ref, usage) => {
    (reverse[ref] ||= []).push(usage);
  };
  for (const name of names) {
    const source = await json(path.join(dir, name)),
      topic = structuredClone(source);
    insist(source.schemaVersion === 1 && name === `${source.id}.json`, `专题身份不符：${name}`);
    validateTopicSource(source, nodes);
    for (const [pid, problem] of Object.entries(topic.problems)) {
      counts.problems++;
      insist(/^\/(?:[a-z0-9][a-z0-9-]*\/)+$/.test(problem.path), `题页必须使用站内目录路径：${pid}`);
      insist(!lessons.has(pid), `题目身份在多个专题中重复：${pid}`);
      if (problem.runtime === 'graph-walk') {
        const projected = await loadGraphWalkProblem(root, pid, problem, nodes);
        problem.statement = projected.statement;
        problem.routes = projected.routes;
        lessons.set(pid, {runtime: 'graph-walk', ...projected.contract});
        insist(problem.types?.length, `题型缺失：${pid}`);
        for (const ref of problem.types) {
          insist(checkRef(ref, nodes, ['problem_type']).status !== 'planned', `练习不能关联待建设题型：${pid}/${ref}`);
          add(ref, {topic: topic.id, problem: pid});
        }
        for (const [rid, route] of Object.entries(problem.routes)) {
          counts.routes++;
          route.methods.forEach(ref => checkRef(ref, nodes, ['method']));
          for (const [sid, step] of Object.entries(route.steps)) {
            counts.steps++;
            for (const ref of step.refs) {
              checkRef(ref, nodes);
              add(ref, {topic: topic.id, problem: pid, route: rid, step: sid, conditions: {}});
            }
          }
        }
        continue;
      }
      insist(problem.runtime === undefined, `未知题页运行时：${pid}`);
      const html = await fs.readFile(path.join(root, `site${problem.path}index.html`), 'utf8');
      const config = html.match(/<script[^>]*id="practice-config"[^>]*>([\s\S]*?)<\/script>/);
      insist(config, `题页缺少 practice-config：${pid} / ${problem.path}`);
      const lesson = JSON.parse(config[1]);
      const teacher = await json(path.join(root, `server/shuxueshuo_server/tutor_demo/lessons/${pid}.json`));
      insist(lesson.id === pid, `题目身份与题页不符：${pid}`);
      equal(
        [lesson.id, lesson.version, lesson.methods],
        [teacher.id, teacher.version, teacher.methods],
        `教学身份或路线契约不符：${pid}`
      );
      equal(Object.keys(problem.routes), Object.keys(lesson.routes), `路线集合不符：${pid}`);
      equal(Object.keys(teacher.routes), Object.keys(lesson.routes), `教师路线集合不符：${pid}`);
      lessons.set(pid, lesson);
      problem.statement = teacher.problem.statement;
      insist(problem.types.length > 0, `题型缺失：${pid}`);
      for (const ref of problem.types) {
        const type = checkRef(ref, nodes, ['problem_type']);
        insist(type.status !== 'planned', `练习不能关联待建设题型：${pid}/${ref}`);
        add(ref, { topic: topic.id, problem: pid });
      }
      for (const [rid, route] of Object.entries(problem.routes)) {
        counts.routes++;
        const steps = lesson.routes[rid],
          teacherSteps = teacher.routes[rid].nodes;
        equal(ids(steps), ids(teacherSteps), `教师步骤顺序不符：${pid}/${rid}`);
        equal(Object.keys(route.steps), ids(steps), `步骤集合或顺序不符：${pid}/${rid}`);
        const fields = new Map();
        for (const step of steps)
          if (step.interaction.type === 'choice') {
            const values = step.interaction.options.map((o) => o.value);
            values.accepted = step.expected_answer.one_of;
            fields.set(step.interaction.field, values);
          }
        const refs = (kinds) => (list) => {
          insist(
            Array.isArray(list) && new Set(list).size === list.length,
            `引用须为不重复的数组：${pid}/${rid}`
          );
          for (const ref of list) checkRef(ref, nodes, kinds);
        };
        validateSelector(
          route.methods,
          fields,
          (list) => {
            refs(['method'])(list);
            insist(list.length && list.every((r) => !r.includes('#')), `路线必须引用完整方法：${pid}/${rid}`);
          },
          pid
        );
        route.label = lesson.methods.find((m) => m.id === rid).label;
        for (const b of branches(route.methods))
          for (const ref of b.value)
            add(ref, { topic: topic.id, problem: pid, route: rid, conditions: b.conditions });
        for (const [position, step] of steps.entries()) {
          counts.steps++;
          const mapped = route.steps[step.id],
            location = `${pid}/${rid}/${step.id}`;
          for (const key of ['title', 'question', 'interaction', 'expected_answer', 'feedback'])
            equal(step[key], teacherSteps[position][key], `教学契约不符：${location}/${key}`);
          mapped.title = step.title;
          mapped.position = position + 1;
          validateSelector(mapped.refs, fields, refs(), location);
          insist(
            branches(mapped.refs).every((b) => b.value.length) || mapped.reason,
            `无关联步骤必须说明原因：${location}`
          );
          // Associations may only use choices already available at this step.
          const available = new Set(
            steps
              .slice(0, position + 1)
              .filter((s) => s.interaction.type === 'choice')
              .map((s) => s.interaction.field)
          );
          for (const b of [...branches(mapped.refs), ...branches(mapped.tip)])
            insist(
              Object.keys(b.conditions).every((f) => available.has(f)),
              `引用未来步骤选择：${location}`
            );
          if (mapped.tip)
            validateSelector(
              mapped.tip,
              fields,
              (tip) => {
                checkRef(tip.ref, nodes);
                if (!tip.resource) {
                  insist(!tip.case, `无图解资源不能指定 case：${location}`);
                  return;
                }
                const resource = manifest.resources[tip.resource];
                insist(resource, `图解资源失效：${location}/${tip.resource}`);
                insist(
                  !tip.case || resource.cases?.includes(tip.case),
                  `图解 case 失效：${location}/${tip.case}`
                );
              },
              location
            );
          for (const tip of branches(mapped.tip)) {
            counts.tips++;
            // Test all compatible ref branches, not the union of unrelated branches.
            const compatible = branches(mapped.refs).filter((b) =>
              Object.entries(b.conditions).every(
                ([f, v]) => !(f in tip.conditions) || tip.conditions[f] === v
              )
            );
            insist(
              compatible.length && compatible.every((b) => b.value.includes(tip.value.ref)),
              `提示未登记在当前选择的步骤关联里：${location}/${tip.value.ref}`
            );
          }
          for (const b of branches(mapped.refs))
            for (const ref of b.value)
              add(ref, {
                topic: topic.id,
                problem: pid,
                route: rid,
                step: step.id,
                conditions: b.conditions
              });
        }
      }
    }
    topics.push(topic);
  }
  const migration = await json(path.join(root, 'site/data/knowledge-next/migration.json'));
  insist(
    new Set(migration.nodes.map((n) => n.legacy)).size === migration.nodes.length,
    '旧新节点身份清单重复'
  );
  for (const row of migration.nodes) {
    insist(
      ['reuse', 'retype', 'entry', 'split'].includes(row.action) && row.reason && row.targets.length,
      `旧新身份决策缺失：${row.legacy}`
    );
    row.targets.forEach((ref) => checkRef(ref, nodes));
  }
  Object.values(migration.legacyRefs).forEach((ref) => checkRef(ref, nodes));
  const drills = await loadDrills(root, nodes);
  return { topics, reverse, counts, lessons, drills, migration };
}

export async function loadDrills(root, nodes) {
  const base = path.join(root, 'server/shuxueshuo_server/learning'),
    dir = path.join(base, 'drills-next');
  const migration = await json(path.join(dir, 'migration.json')),
    items = new Map(),
    sets = [];
  function itemCheck(item, node) {
    insist(
      typeof item.id === 'string' && /^[a-z][a-z0-9-]*$/.test(item.id) && !items.has(item.id),
      `小题身份无效或冲突：${item.id}`
    );
    if (item.origin)
      insist(
        item.origin.node && item.origin.item && item.id === `${item.origin.node}--${item.origin.item}`,
        `迁移小题来源身份不符：${item.id}`
      );
    if (node) checkRef(node + (item.entry ? `#${item.entry}` : ''), nodes, ['knowledge', 'skill', 'method', 'problem_type']);
    insist(['choice', 'multi'].includes(item.type) && item.question, `小题题干或类型不符：${item.id}`);
    const values = item.options.map((o) => o.value),
      answer = item.type === 'multi' ? item.answer : [item.answer];
    insist(values.length >= 2 && new Set(values).size === values.length, `小题选项冲突：${item.id}`);
    insist(
      Array.isArray(answer) &&
        answer.length &&
        new Set(answer).size === answer.length &&
        answer.every((v) => values.includes(v)),
      `小题答案无效：${item.id}`
    );
    insist(
      item.options.every((o) => o.label && (answer.includes(o.value) || o.feedback)),
      `小题干扰项缺少反馈：${item.id}`
    );
    items.set(item.id, { item, node });
  }
  for (const f of (await fs.readdir(path.join(dir, 'sets'))).filter((f) => f.endsWith('.json')).sort()) {
    const set = await json(path.join(dir, 'sets', f));
    insist(f === `${set.node}.json`, `小题集文件名不符：${f}`);
    set.items.forEach((i) => itemCheck(i, set.node));
    sets.push({ node: set.node, count: set.items.length, eligible: set.items.length >= 5 });
  }
  for (const i of (await json(path.join(dir, 'retired.json'))).items) itemCheck(i, null);
  const migrated = [...items.values()].filter(({ item }) => item.origin);
  equal(
    migration.records.map((r) => r.id).sort(),
    migrated.map(({ item }) => item.id).sort(),
    '小题迁移记录缺失或重复'
  );
  for (const row of migration.records) {
    const { item, node } = items.get(row.id);
    equal(row.origin, item.origin, `小题来源不符：${row.id}`);
    insist(
      ['keep', 'reassign', 'revise', 'merge', 'retire'].includes(row.action) && row.reason,
      `小题迁移动作无效：${row.id}`
    );
    equal(
      row.target || null,
      node ? node + (item.entry ? `#${item.entry}` : '') : null,
      `小题去向不符：${row.id}`
    );
    insist((row.action === 'retire') === !node, `小题停用状态不符：${row.id}`);
  }
  equal(migration.sourceCount, migration.records.length, '小题迁移来源数量与清单不符');
  // Public audit contains provenance and targets only; never answers or grading rules.
  return {
    sets,
    records: migration.records,
    sourceCount: migrated.length,
    newCount: items.size - migrated.length,
    totalCount: items.size,
    active: [...items.values()].filter((i) => i.node).length,
    retired: [...items.values()].filter((i) => !i.node).length
  };
}
