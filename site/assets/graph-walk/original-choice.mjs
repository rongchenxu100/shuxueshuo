/** Original exam choices are matched by the verified solver, never inferred from prose in the UI. */
const SET_ANSWER_KINDS = new Set(['find_range', 'find_domain', 'match_domain', 'find_abstract_domain',
  'find_abstract_domain_parameter', 'find_abstract_range', 'find_translation_range']);

function mathValue(value) {
  return typeof value === 'string' ? Boolean(value.trim()) : value && typeof value === 'object' &&
    !Array.isArray(value) && ['expression', 'latex'].some(key => typeof value[key] === 'string' && value[key].trim());
}

function exactMathValue(value) {
  return mathValue(value) && typeof value === 'object' && Object.hasOwn(value, 'exact') && value.exact != null;
}

function derivedAnswer(answer) {
  if (answer?.kind !== 'derived_answer') return false;
  if (answer.request_kind === 'identity') return answer.status === 'set' && exactMathValue(answer.set);
  if (answer.request_kind === 'expression') return answer.status === 'value' && exactMathValue(answer.value);
  if (answer.request_kind === 'compare_set') return answer.status === 'boolean' && typeof answer.value === 'boolean';
  if (answer.request_kind !== 'extremum' || !['minimum', 'maximum', 'infimum', 'supremum'].includes(answer.quantity)) return false;
  return (answer.status === 'attained' || answer.status === 'not_attained' && ['infimum', 'supremum'].includes(answer.quantity)) &&
    exactMathValue(answer.value);
}

function singleAnswer(answer) {
  if (answer?.kind === 'derived_answer') return derivedAnswer(answer) && answer.status !== 'set';
  // Older certified set choices predate the explicit set_equality matching field.
  if (SET_ANSWER_KINDS.has(answer?.kind)) return answer.status === 'set' && mathValue(answer.set);
  if (['find_minimum', 'find_maximum'].includes(answer?.kind)) return answer.status === 'attained' && mathValue(answer.value);
  return answer?.kind === 'find_extrema_expression' && answer.status === 'value' && exactMathValue(answer.value);
}

export function matchedOriginalChoice(completion, targetRef = completion?.target_ref || completion?.identity?.[0]) {
  const choice = completion?.original_choice;
  if (completion?.status !== 'verified' || completion.available === false ||
      choice?.status !== 'matched' || !['single_choice', 'multiple_choice'].includes(choice.kind) ||
      typeof choice.target_ref !== 'string' || choice.target_ref !== targetRef ||
      !Array.isArray(choice.options) || choice.options.length < 2 ||
      !Array.isArray(choice.correct_labels)) return null;
  if (choice.options.some(option => typeof option?.label !== 'string' || !option.label ||
      typeof option.text !== 'string' || !option.text.trim())) return null;
  const labels = new Set(choice.options.map(option => option.label));
  if (labels.size !== choice.options.length || new Set(choice.correct_labels).size !== choice.correct_labels.length ||
      choice.correct_labels.some(label => !labels.has(label))) return null;
  const single = choice.kind === 'single_choice';
  if (single && choice.correct_labels.length !== 1) return null;
  if (['set_equality', 'range_domain_options'].includes(choice.matching)) {
    const keys = ['status', 'kind', 'matching', 'selection_mode', 'target_ref', 'options', 'correct_labels'];
    const validAnswer = choice.matching === 'range_domain_options'
      ? completion.answer?.kind === 'select_range_domain' && completion.answer.status === 'complete' &&
        Array.isArray(completion.answer.correct_labels) &&
        completion.answer.correct_labels.length === choice.correct_labels.length &&
        completion.answer.correct_labels.every(label => choice.correct_labels.includes(label))
      : completion.answer?.status === 'set' && (completion.answer.kind === 'derived_answer'
        ? derivedAnswer(completion.answer) : SET_ANSWER_KINDS.has(completion.answer.kind) && mathValue(completion.answer.set));
    if (!validAnswer || Object.keys(choice).length !== keys.length ||
        keys.some(key => !Object.hasOwn(choice, key)) ||
        !(single ? choice.selection_mode === 'single' : ['multiple', 'unspecified'].includes(choice.selection_mode)) ||
        choice.options.some(option => Object.keys(option).sort().join(',') !== 'label,text')) return null;
    return choice;
  }
  if (choice.matching !== undefined) return null;
  const comparison = completion.answer?.kind === 'compare_functions' ||
    choice.option_verdicts !== undefined || choice.select_relation !== undefined;
  if (single && !comparison) return singleAnswer(completion.answer) ? choice : null;
  const validMode = single ? choice.selection_mode === 'single' : ['multiple', 'unspecified'].includes(choice.selection_mode);
  if (!validMode || !['equal', 'different'].includes(choice.select_relation) ||
      !Array.isArray(choice.option_verdicts) || choice.option_verdicts.length !== choice.options.length) return null;
  const ids = new Set(choice.options.map(option => option.option_id));
  if (ids.size !== choice.options.length || [...ids].some(id => typeof id !== 'string' || !id)) return null;
  if (choice.option_verdicts.some((row, index) => row.option_id !== choice.options[index].option_id ||
      row.label !== choice.options[index].label || !['equal', 'different'].includes(row.verdict) ||
      typeof row.reason !== 'string' || !row.reason.trim())) return null;
  const selected = choice.option_verdicts.filter(row => row.verdict === choice.select_relation).map(row => row.label);
  if (selected.length !== choice.correct_labels.length || selected.some(label => !choice.correct_labels.includes(label))) return null;
  return choice;
}

/** Exact original-answer grading has no optional-choice/required-subset semantics. */
export function exactOriginalAnswer(decision, answer) {
  const expected = decision?.expected_answer;
  const labels = decision?.interaction?.options?.map(option => option.value);
  if (decision?.source !== 'original_choice' || decision.interaction.type !== 'original_choice_exact_set' ||
      !expected || Object.keys(expected).sort().join(',') !== 'correct_labels,option_labels' ||
      !Array.isArray(expected.correct_labels) || !Array.isArray(expected.option_labels) || !Array.isArray(labels) ||
      [labels, expected.correct_labels, expected.option_labels].some(values => values.some(label => typeof label !== 'string' || !label)) ||
      new Set(labels).size !== labels.length || new Set(expected.option_labels).size !== expected.option_labels.length ||
      labels.length !== expected.option_labels.length || labels.some(label => !expected.option_labels.includes(label)) ||
      new Set(expected.correct_labels).size !== expected.correct_labels.length ||
      expected.correct_labels.some(label => !labels.includes(label))) throw new Error('原题选项评分契约无效，请重新加载。');
  return Array.isArray(answer) && answer.every(value => typeof value === 'string') &&
    new Set(answer).size === answer.length && answer.every(label => labels.includes(label)) &&
    answer.length === expected.correct_labels.length && expected.correct_labels.every(label => answer.includes(label));
}
