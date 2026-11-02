// The authored map shows possible approaches; the shared grader checks this problem.
const h = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

export function connectedMethodAnswer(decision, method) {
  const edge = decision.interaction.connections?.find(item => item.method === method);
  return {checks: [edge?.cue || ''], method: edge ? method : '', confirmed: 0};
}

export function methodConnectionsHTML(decision, answer, interactive) {
  const component = decision.interaction, connections = component.connections || [];
  const rows = component.checks[0].options.map(cue => {
    const methods = connections.filter(edge => edge.cue === cue.value)
      .map(edge => component.methods.find(method => method.value === edge.method)).filter(Boolean);
    if (!methods.length) return '';
    const selected = methods.some(method => method.value === answer.method);
    return `<div class="gw-method-map-row" data-method-map-row>
      <div class="gw-method-cue${selected ? ' is-selected' : ''}" data-method-cue="${h(cue.value)}"><strong>${h(cue.label)}</strong>${cue.note ? `<span data-math-text>${h(cue.note)}</span>` : ''}</div>
      <svg class="gw-method-link-lines" aria-hidden="true">${methods.map(method => `<g data-method-edge="${h(method.value)}" class="${method.value === answer.method ? 'is-selected' : ''}"><path class="gw-method-link-path"/><path class="gw-method-link-arrow"/></g>`).join('')}</svg>
      <div class="gw-method-choices">${methods.map(method => {
        const picked = method.value === answer.method, tag = interactive ? 'button' : 'div';
        return `<${tag} class="gw-method-node${picked ? ' is-selected' : ''}" data-method-node="${h(method.value)}"${interactive ? ` type="button" data-card-method="${h(method.value)}" aria-pressed="${picked}"` : ''}><strong>${h(method.label)}</strong>${picked ? `<span class="gw-method-picked-state">${interactive ? '已选择' : '✓ 本题选择'}</span>` : ''}</${tag}>`;
      }).join('')}</div>
    </div>`;
  }).join('');
  const selected = component.methods.find(method => method.value === answer.method);
  const explanation = !interactive && selected ? `<div class="gw-method-map-explanation"><p data-math-text>${h(decision.verdicts?.[selected.value]?.message)}</p>${component.methods.filter(method => method.value !== selected.value && decision.verdicts?.[method.value]?.value === 'fit').map(method => `<p class="gw-method-also" data-math-text>${h(decision.verdicts[method.value].message)}</p>`).join('')}</div>` : '';
  return `<div class="gw-method-connections" data-method-connections role="group" aria-label="${interactive ? '选法关系图' : '已确认的选法关系图'}"><div class="gw-method-map-head"><span>题目线索</span><span>可尝试的方法</span></div>${rows}</div>${explanation}`;
}

// Geometry is display-only. All authored edges are drawn before a choice is made.
export function mountMethodConnections(root) {
  const cards = [...root.querySelectorAll('[data-method-connections]')];
  if (!cards.length) return () => {};
  const draw = () => cards.forEach(card => card.querySelectorAll('[data-method-map-row]').forEach(row => {
    const svg = row.querySelector('.gw-method-link-lines'), cue = row.querySelector('[data-method-cue]');
    const box = row.getBoundingClientRect(), a = cue.getBoundingClientRect();
    if (!box.width || !box.height) { svg.setAttribute('hidden', ''); return; }
    svg.removeAttribute('hidden');
    svg.setAttribute('viewBox', `0 0 ${box.width} ${box.height}`);
    const methods = [...row.querySelectorAll('[data-method-node]')];
    svg.querySelectorAll('[data-method-edge]').forEach(edge => {
      const b = methods.find(method => method.dataset.methodNode === edge.dataset.methodEdge).getBoundingClientRect();
      const x1 = a.right-box.left+1, y1 = a.top+a.height/2-box.top;
      const x2 = b.left-box.left-3, y2 = b.top+b.height/2-box.top, mid = (x1+x2)/2;
      edge.querySelector('.gw-method-link-path').setAttribute('d', `M${x1},${y1} C${mid},${y1} ${mid},${y2} ${x2},${y2}`);
      edge.querySelector('.gw-method-link-arrow').setAttribute('d', `M${x2-5},${y2-3} L${x2},${y2} L${x2-5},${y2+3}`);
    });
  }));
  draw();
  const observer = typeof ResizeObserver === 'function' ? new ResizeObserver(draw) : null;
  cards.forEach(card => observer?.observe(card));
  return () => observer?.disconnect();
}
