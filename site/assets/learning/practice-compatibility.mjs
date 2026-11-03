// Version the exercise the student actually opened, independently of site releases.
// Keep this projection aligned with learning/compatibility.py (cross-language tests).
const decorative = new Set(['note', 'hint', 'description', 'title', 'caption', 'method_notes']);
function inputs(value) {
  if (Array.isArray(value)) return value.map(inputs);
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value)
    .filter(([key]) => !decorative.has(key)).map(([key, item]) => [key, inputs(item)]));
  return value;
}
const fields = ['id', 'question', 'interaction', 'expected_answer', 'route_by_answer',
  'route_id', 'option_context', 'target_ref', 'require_complete_options', 'select_relation',
  'matching', 'alternatives', 'verdicts'];
function decision(value) {
  const result = Object.fromEntries(fields.filter(key => Object.hasOwn(value, key))
    .map(key => [key, key === 'interaction' ? inputs(value[key]) : value[key]]));
  if (!Object.keys(value.alternatives || {}).length) delete result.alternatives;
  if (value.interaction.layout !== 'connections') delete result.verdicts;
  if (value.source === 'original_choice' && (value.interaction.type === 'original_choice_exact_set' ||
      value.require_complete_options || ['set_equality', 'range_domain_options'].includes(value.matching))) result.source = value.source;
  return result;
}
export function pageContract(lesson, statement = lesson.problem?.text) {
  const native = Boolean(lesson.problemId);
  return {schema: 'practice-page/v1', id: lesson.problemId || lesson.id,
    runtime: native ? 'graph-walk' : 'practice',
    ...(native ? {statement, intro: lesson.intro.map(decision)} : {}),
    routes: Object.fromEntries(Object.entries(lesson.routes).map(([id, route]) => [id,
      (native ? route.steps : Array.isArray(route) ? route : route.nodes).map(decision)]))};
}
export function teachingContract(data) {
  const lesson = data._graph_walk || data._lesson;
  const page = pageContract(lesson, data.statement);
  if (data._graph_walk) return {page};
  return {page, problem: lesson.problem, initial_state: lesson.initial_state,
    criteria: Object.fromEntries(Object.entries(lesson.routes).map(([id, route]) => [id,
      route.nodes.map(node => Object.fromEntries(['required_evidence', 'criteria']
        .filter(key => Object.hasOwn(node, key)).map(key => [key, node[key]])))]))};
}
export function stableJson(value) {
  if (Array.isArray(value)) return '[' + value.map(stableJson).join(',') + ']';
  if (value && typeof value === 'object') return '{' + Object.keys(value).sort()
    .filter(key => value[key] !== undefined).map(key => JSON.stringify(key) + ':' + stableJson(value[key])).join(',') + '}';
  return JSON.stringify(value);
}
export async function pageContractHash(lesson) {
  const bytes = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(stableJson(pageContract(lesson))));
  return [...new Uint8Array(bytes)].map(byte => byte.toString(16).padStart(2, '0')).join('');
}
export async function checkPracticeCompatibility(lesson, problem, read) {
  const hash = await pageContractHash(lesson);
  if (!problem.practice_version || problem.page_contract_hash !== hash) {
    throw Error('本题的作答步骤或选项已更新，请刷新本题后再保存。');
  }
  const current = await read(`/api/learning/content/problems/${encodeURIComponent(problem.id)}`);
  if (current.practice_version !== problem.practice_version) {
    throw Error('本题的学习内容尚未同步，暂不能保存本题进度；仍可继续练习。');
  }
  return {practiceVersion: problem.practice_version, contentVersion: current.content_version};
}
