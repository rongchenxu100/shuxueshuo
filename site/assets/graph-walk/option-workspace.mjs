/** Learning progress is derived from accepted decisions, never solver completion. */
export function optionProgress(bundle, state) {
  const route = bundle.routes[state.run?.route], steps = route?.steps || [];
  const declared = route?.option_workspaces || bundle.option_workspaces || route?.completion?.original_choice?.options || [];
  const groups = new Map(declared.filter(row => typeof row.option_id === 'string' && row.option_id)
    .map(row => [row.option_id, {...row, steps: []}]));
  for (const step of steps) {
    const context = step.option_context;
    if (!context) continue;
    if (!groups.has(context.option_id)) groups.set(context.option_id, {...context, steps: []});
    groups.get(context.option_id).steps.push(step);
  }
  const completed = new Set((state.run?.completed || []).map(row => row.decision));
  const current = steps[state.run?.completed?.length || 0];
  let precedingComplete = state.introCompleted?.length === bundle.intro.length;
  const options = [...groups.values()].map(row => {
    const verdict = row.steps.find(step => step.option_context.phase === 'verdict');
    const complete = Boolean(verdict?.interaction.type === 'choice' &&
      row.steps.at(-1) === verdict && row.steps.some(step => step.option_context.phase === 'evidence') &&
      row.steps.every(step => completed.has(step.id)));
    const unlocked = precedingComplete;
    precedingComplete &&= complete;
    return {...row, complete, unlocked, current: current?.option_context?.option_id === row.option_id};
  });
  const final = steps.find(step => step.interaction.type === 'original_choice_exact_set');
  return {options, current: current?.option_context?.option_id || null,
    finalReady: Boolean(final && options.length && options.every(row => row.complete)),
    finalPassed: Boolean(final && completed.has(final.id)),
    finalCurrent: current?.id === final?.id && Boolean(final)};
}

export function optionPrerequisitesPassed(bundle, state, decision) {
  if (!decision.require_complete_options) return true;
  const progress = optionProgress(bundle, state);
  const required = decision.require_complete_options;
  return Array.isArray(required) && required.length > 0 && new Set(required).size === required.length &&
    progress.options.length === required.length && required.every(id => progress.options.some(row => row.option_id === id && row.complete));
}

export function hasOptionWorkspaces(bundle, state) {
  return optionProgress(bundle, state).options.length > 0;
}
