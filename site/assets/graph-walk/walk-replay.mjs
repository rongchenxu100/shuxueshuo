import {methodAnswer} from './method-cards.mjs?v=20261030-range-selection';
// Static lessons and streamed AI playback answer the same verified decisions.
export function replayAnswer(decision, route) {
  const component = decision.interaction, expected = decision.expected_answer || {};
  let answer;
  switch (component.type) {
    case 'read': answer = 'read'; break;
    case 'choice': answer = expected.one_of?.[0]; break;
    case 'multi': answer = expected.required; break;
    case 'original_choice_exact_set': answer = expected.correct_labels; break;
    case 'fill':
    case 'checklist': answer = expected.terms; break;
    case 'grid': answer = expected.cell; break;
    case 'method_cards': {
      const method = component.methods?.find(item => item.route === route);
      if (method) answer = methodAnswer(decision, method.value);
      break;
    }
    case 'plane': {
      // A nested method belongs to its parent route; its method value is explicit.
      const method = expected.method || component.methods?.find(item => item.route === route)?.value;
      if (expected.cell?.length === 2 && method) answer = [...expected.cell, method];
      break;
    }
  }
  return answer == null ? null : structuredClone(answer);
}

export function buildStreamReplay(bundle, {actions: initialActions = [], replayRoute, currentRoute} = {}) {
  const actions = structuredClone(initialActions);
  const selection = bundle.intro.find(item => item.id === 'D3');
  const available = id => bundle.routes[id]?.route_plan === 'planned' && bundle.routes[id]?.available !== false;
  const route = [replayRoute, currentRoute].find(available) || Object.keys(bundle.routes).find(available);
  const method = route && selection?.interaction.methods?.find(item => item.route === route);
  const selectionAnswer = method ? replayAnswer(selection, route) : null;
  if (selectionAnswer !== null) {
    // Stage two supplies the reading/type prefix. Stage three may insert
    // prerequisites before method selection (for example the effective domain).
    for (const decision of bundle.intro.slice(actions.length, bundle.intro.indexOf(selection))) {
      const answer = replayAnswer(decision, route);
      if (answer === null) return {schemaVersion: 2, problemId: bundle.problemId,
        bundleVersion: bundle.bundleVersion, status: 'partial', routes: [], actions};
      actions.push({decision: decision.id, answer});
    }
    actions.push({decision: selection.id, answer: selectionAnswer});
    for (const decision of bundle.routes[route].steps || []) {
      const answer = replayAnswer(decision, route);
      // An unfinished streamed contract must not fabricate an answer or skip a step.
      if (answer === null) break;
      actions.push({decision: decision.id, answer});
    }
  }
  return {schemaVersion: 2, problemId: bundle.problemId, bundleVersion: bundle.bundleVersion,
    status: 'partial', routes: selectionAnswer !== null ? [route] : [], actions};
}
