import {pageContract, stableJson} from '../../site/assets/learning/practice-compatibility.mjs';

const same = (left, right) => stableJson(left) === stableJson(right);
// SVG titles may use Unicode exponents instead of caret notation. Normalize
// only that typography for comparison; keep conditions and geometry strict.
function visualContent(value) {
  if (Array.isArray(value)) return value.map(visualContent);
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([key, item]) => [key,
    key === 'title' && typeof item === 'string'
      ? item.replace(/[⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻]+/g, exponent => '^' + [...exponent]
        .map(char => '0123456789+-'['⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻'.indexOf(char)]).join(''))
      : visualContent(item)]));
  return value;
}
// Notes help explain a choice but do not change its value or grading. Match
// them with the same tolerance as pageContract, retaining the fresh wording.
const optionContent = ({value, note, hint, description, ...content}) => visualContent(content);

function instructionalGraph(graph) {
  if (graph?.kind !== 'piecewise_curve' || !Array.isArray(graph.params?.segments)) return visualContent(graph);
  // Trend markers repeat earlier confirmed answers on the helper plot. Adding
  // that guidance does not change the plotted function or the current answer.
  const {caption, ...result} = graph;
  if (graph.params) {
    const {description, interval_marks, ...params} = graph.params;
    result.params = params;
  }
  return visualContent(result);
}

// A fresh verified execution has new proof/interaction identities and shuffles
// its choices. Neither is a reason to invalidate a published student's answers.
// Reuse only the public identifiers, after comparing the complete grading
// contract. The fresh stream and its proof hashes are never rewritten.
function alignOptions(current, previous, answers) {
  if (!Array.isArray(current) || !Array.isArray(previous) || current.length !== previous.length) return null;
  if ([current, previous].some(options => new Set(options.map(option => option.value)).size !== options.length)) return null;
  if (same(current, previous)) return current;
  const remaining = [...current], result = [];
  for (const old of previous) {
    const matches = remaining.filter(option => same(optionContent(option), optionContent(old)));
    if (matches.length !== 1) return null; // Ambiguous labels/graphs must not transfer answers.
    const option = matches[0];
    if (answers.has(option.value) && answers.get(option.value) !== old.value) return null;
    answers.set(option.value, old.value);
    result.push({...option, value: old.value});
    remaining.splice(remaining.indexOf(option), 1);
  }
  return result;
}

function alignDecision(current, previous) {
  // A graph or source diagram can supply conditions that are absent from the
  // question string. Keep those just as strict as the text/answer comparison.
  if (!same(instructionalGraph(current.graph), instructionalGraph(previous.graph))) return null;
  for (const key of ['stem_board', 'question_note', 'source_regions', 'figure_choices',
    'condition_number_lines', 'completion_number_line', 'endpoint_checks']) {
    if (!same(visualContent(current[key]), visualContent(previous[key]))) return null;
  }
  const next = structuredClone(current), answers = new Map();
  const component = next.interaction, old = previous.interaction;
  if (!component || !old || component.type !== old.type) return null;
  if (component.options) {
    component.options = alignOptions(component.options, old.options, answers);
    if (!component.options) return null;
  }
  if (component.slots) {
    if (component.slots.length !== old.slots?.length) return null;
    for (let i = 0; i < component.slots.length; i++) {
      const slot = component.slots[i];
      if (!slot.options) continue;
      slot.options = alignOptions(slot.options, old.slots[i].options, answers);
      if (!slot.options) return null;
    }
  }
  // Only the generated field name may follow a generated decision ID. Authored
  // semantic field names and every other interaction property still compare.
  if (component.field === current.id && old.field === previous.id) component.field = previous.id;
  for (const key of ['one_of', 'required', 'allowed', 'terms']) {
    if (Array.isArray(next.expected_answer?.[key])) {
      next.expected_answer[key] = next.expected_answer[key].map(value => answers.get(value) ?? value);
    }
  }
  next.id = previous.id;
  return next;
}

export function preserveCourseIdentity(current, previous) {
  if (!previous || current.problemId !== previous.problemId || !previous.bundleVersion ||
      !same(current.problem?.figures, previous.problem?.figures) ||
      !same(Object.keys(current.routes), Object.keys(previous.routes))) return current;
  const candidate = structuredClone(current);
  const pairs = [[candidate.intro, previous.intro], ...Object.keys(candidate.routes).map(route =>
    [candidate.routes[route].steps, previous.routes[route].steps])];
  for (const [steps, oldSteps] of pairs) {
    if (!Array.isArray(oldSteps) || steps.length !== oldSteps.length) return current;
    for (let i = 0; i < steps.length; i++) {
      const aligned = alignDecision(steps[i], oldSteps[i]);
      if (!aligned) return current;
      steps[i] = aligned;
    }
  }
  if (!same(pageContract(candidate), pageContract(previous))) return current;
  // Completion is outside the input contract but still part of the lesson.
  for (const id of Object.keys(candidate.routes)) {
    const route = candidate.routes[id], old = previous.routes[id];
    if (!same(route.completion?.answer, old.completion?.answer) ||
        !same(route.methods || [route.method], old.methods || [old.method])) return current;
  }
  candidate.bundleVersion = previous.bundleVersion;
  return candidate;
}

export function requireCourseIdentity(current, previous) {
  const aligned = preserveCourseIdentity(current, previous);
  if (previous?.problemId === current.problemId && aligned === current) {
    throw Error(`${current.problemId}: teaching contract changed; allocate a new course ID before rebuilding`);
  }
  return aligned;
}
