import fs from 'node:fs/promises';
import path from 'node:path';

const assert = (value, message) => { if (!value) throw Error(message); };
const copy = value => structuredClone(value);

export function nativePracticeContract(bundle) {
  const decision = value => {
    const contract = Object.fromEntries(['id', 'title', 'question', 'interaction', 'expected_answer',
      'feedback', 'route_by_answer', 'source_regions', 'stream_steps', 'condition_number_lines', 'completion_number_line', 'endpoint_checks',
      'option_context', 'target_ref', 'require_complete_options', 'select_relation'].filter(key => Object.hasOwn(value, key)).map(key => [key, copy(value[key])]));
    if (value.interaction.type === 'original_choice_exact_set' ||
        value.source === 'original_choice' && value.interaction.type === 'choice' && value.require_complete_options) {
      contract.source = value.source;
    }
    // Keep valid unexpanded choices in the server grading contract without
    // changing the frozen identity of courses that have no such alternatives.
    if (Object.keys(value.alternatives || {}).length) contract.alternatives = copy(value.alternatives);
    return contract;
  };
  return {schema: 'graph-walk-practice/v1', problemId: bundle.problemId, bundleVersion: bundle.bundleVersion,
    intro: bundle.intro.map(decision), routes: Object.fromEntries(Object.entries(bundle.routes).map(([id, route]) =>
      [id, {method: route.method, steps: route.steps.map(decision)}]))};
}

export function projectGraphWalkTeaching(bundle, nodes) {
  assert(bundle.stream?.interaction_protocol === 'graph-step-interaction/v1', '课包缺少正式交互协议');
  assert(bundle.bundleVersion && bundle.problemId && bundle.intro?.length, '图谱课包身份不完整');
  const byId = new Map(nodes.map(node => [node.id, node])), routes = {};
  const refsFor = (decision, routeId) => {
    const refs = new Set();
    for (const id of decision.effects?.nodes || []) if (['knowledge', 'skill', 'method'].includes(byId.get(id)?.kind)) refs.add(id);
    for (const ref of decision.stream_steps || []) {
      const math = bundle.stream.math_steps.find(step => step.target_ref === bundle.stream.target_ref && step.route_id === routeId
        && step.step_id === ref.step_id && step.math_step_sha256 === ref.math_step_sha256);
      assert(math?.local_check === 'passed', `交互没有已验证数学来源：${decision.id}`);
      if (math.method_ref) refs.add(math.method_ref);
      for (const [key, calls] of Object.entries(bundle.stream.step_calls || {})) {
        const [callRoute, stepId] = JSON.parse(key);
        if (callRoute !== routeId || stepId !== ref.step_id) continue;
        for (const call of calls) {
          if (call.ref && ['method', 'skill'].includes(byId.get(call.ref.split('#')[0])?.kind)) refs.add(call.ref);
          for (const basis of call.usedBasis || []) refs.add(basis);
        }
      }
    }
    for (const region of decision.source_regions?.regions || []) for (const ref of region.basis_refs || []) refs.add(ref);
    return [...refs];
  };
  for (const [id, route] of Object.entries(bundle.routes || {})) {
    assert(route.available !== false && route.math_complete && route.interactions_complete && route.completion?.status === 'verified',
      `未完成双重校验的路线不能编译专题课包：${id}`);
    assert(byId.get(route.method)?.kind === 'method' && route.steps.length, `课包路线无有效方法或交互：${id}`);
    const steps = [...bundle.intro, ...route.steps];
    assert(new Set(steps.map(step => step.id)).size === steps.length, `课包步骤身份重复：${id}`);
    routes[id] = {label: route.label || byId.get(route.method).label, methods: [route.method],
      steps: Object.fromEntries(steps.map((step, index) => {
        const refs = refsFor(step, id);
        return [step.id, {title: step.title, position: index + 1, refs,
          ...(!refs.length ? {reason: '读取题意、确认题型或方法；本步不记录具体能力掌握。'} : {})}];
      }))};
  }
  assert(Object.keys(routes).length, '课包没有完整路线');
  return {statement: bundle.problem.text, routes, contract: nativePracticeContract(bundle)};
}

export async function loadGraphWalkProblem(root, pid, problem, nodes) {
  assert(/^\/data\/graph-walk\/[a-z][a-z0-9-]*\.json$/.test(problem.bundle), `课包路径无效：${pid}`);
  const file = path.join(root, 'site', problem.bundle), bundle = JSON.parse(await fs.readFile(file, 'utf8'));
  assert(bundle.problemId === pid, `课包题目身份不一致：${pid}`);
  const html = await fs.readFile(path.join(root, 'site', problem.path, 'index.html'), 'utf8');
  const embedded = html.match(/<script[^>]*id="graph-walk-page"[^>]*>([\s\S]*?)<\/script>/);
  assert(embedded, `题页缺少 graph-walk-page：${pid}`);
  const config = JSON.parse(embedded[1]);
  assert(config.problemId === pid && config.bundleUrl === problem.bundle, `题页与课包身份不符：${pid}`);
  const projected = projectGraphWalkTeaching(bundle, nodes);
  return {...projected, bundle};
}
