// Validate generated semantic specs before embedding them in a lesson page.
export function validateExpressionRewrite(spec) {
  const fail = message => { throw new Error(`expression-rewrite: ${message}`); };
  const formula = value => {
    if (!value || typeof value.latex !== 'string') fail('missing formula');
    const ids = new Set();
    let count = 0;
    const visit = (node, depth = 0) => {
      if (!node || ++count > 256 || depth > 32 || typeof node.id !== 'string' || ids.has(node.id)) fail('invalid tree');
      ids.add(node.id);
      const arity = {symbol:0, integer:0, neg:1, pos:1, add:2, sub:2, mul:2, div:2, pow:2}[node.op];
      if (arity === undefined || (node.children || []).length !== arity) fail('invalid operation');
      if (!arity && typeof node.text !== 'string') fail('missing leaf');
      for (const child of node.children || []) visit(child, depth+1);
    };
    visit(value.tree);
    return ids;
  };
  formula(spec.source); formula(spec.result);
  if (!Array.isArray(spec.conditionCards) || !Array.isArray(spec.transitions) || spec.transitions.length < 1 || spec.transitions.length > 11) fail('invalid transitions');
  const cards = new Set();
  for (const c of spec.conditionCards) {
    if (typeof c.id !== 'string' || typeof c.latex !== 'string' || cards.has(c.id)) fail('invalid condition card');
    cards.add(c.id);
  }
  const transitions = new Set();
  for (const t of spec.transitions) {
    if (typeof t.id !== 'string' || transitions.has(t.id)) fail('duplicate transition');
    transitions.add(t.id);
    if (!['combine_fractions','substitute_condition','equivalent_rewrite'].includes(t.operation)) fail('unsupported classification');
    const refs = {before:formula(t.before), after:formula(t.after)};
    for (const [side,key] of [['before','localBefore'],['after','localAfter']]) {
      if (!Array.isArray(t[key]?.nodeIds) || t[key].nodeIds.some(id => !refs[side].has(id))) fail('invalid local reference');
    }
    if (!Array.isArray(t.highlights) || t.highlights.some(h=>!refs[h.side]?.has(h.nodeId))) fail('invalid highlight');
    if (!Array.isArray(t.conditionCardIds) || t.conditionCardIds.some(id=>!cards.has(id))) fail('unknown condition');
    if (!Array.isArray(t.unchanged) || t.unchanged.some(u=>!refs.before.has(u.beforeNodeId) || !refs.after.has(u.afterNodeId))) fail('invalid unchanged reference');
  }
  if (!Array.isArray(spec.beats) || spec.beats.length < 3 || spec.beats.length > 13) fail('invalid beats');
  for (const beat of spec.beats) {
    if (!['focus','transform','result'].includes(beat.kind)) fail('unsupported beat');
    if (beat.kind !== 'result' && !transitions.has(beat.transitionId)) fail('unknown transition');
  }
  return spec;
}
