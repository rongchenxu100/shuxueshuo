/** Original exam choices are matched by the verified solver, never inferred from prose in the UI. */
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
  if (choice.kind === 'single_choice') return choice.correct_labels.length === 1 ? choice : null;
  if (choice.selection_mode !== 'multiple' || !['equal', 'different'].includes(choice.select_relation) ||
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
      expected.correct_labels.some(label => !labels.includes(label))) throw new Error('原题多选评分契约无效，请重新加载。');
  return Array.isArray(answer) && answer.every(value => typeof value === 'string') &&
    new Set(answer).size === answer.length && answer.every(label => labels.includes(label)) &&
    answer.length === expected.correct_labels.length && expected.correct_labels.every(label => answer.includes(label));
}
