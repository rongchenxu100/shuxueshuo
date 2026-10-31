// When changing methods, carry only the engine's confirmed answers into that route's attempt.
export function routeRecordActions(bundle, view, action, previousRoute) {
  const route = view.route || Object.keys(bundle.routes)[0];
  if (!bundle.routes[route]) throw Error('无法保存未知路线。');
  const carried = previousRoute !== route ? (view.practice_answers || [])
    .filter(record => record.decision !== action?.decision).map(record => structuredClone(record)) : [];
  return {route, actions: [...carried, ...(action ? [structuredClone(action)] : [])]};
}
