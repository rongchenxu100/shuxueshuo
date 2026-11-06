// Pairing cards: each clue sits with its method so students see the link in one unit.
const h = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

export function connectedMethodAnswer(decision, method) {
  const edge = decision.interaction.connections?.find(item => item.method === method);
  return {checks: [edge?.cue || ''], method: edge ? method : '', confirmed: 0};
}

function methodBody(method, note, picked, interactive) {
  return `<strong>${h(method.label)}</strong>${note ? `<span class="gw-method-note" data-math-text>${h(note)}</span>` : ''}${picked ? `<span class="gw-method-picked-state">${interactive ? '已选择' : '✓ 本题选择'}</span>` : ''}`;
}

export function methodConnectionsHTML(decision, answer, interactive) {
  const component = decision.interaction, connections = component.connections || [];
  const pairs = component.checks[0].options.map(cue => {
    const methods = connections.filter(edge => edge.cue === cue.value)
      .map(edge => component.methods.find(method => method.value === edge.method)).filter(Boolean);
    if (!methods.length) return '';
    const selected = methods.some(method => method.value === answer.method);
    const cueBlock = `<div class="gw-method-cue" data-method-cue="${h(cue.value)}"><strong>${h(cue.label)}</strong>${cue.note ? `<span data-math-text>${h(cue.note)}</span>` : ''}</div>`;
    const arrow = `<div class="gw-method-pair-arrow" aria-hidden="true"><span></span></div>`;
    if (methods.length === 1) {
      const method = methods[0];
      const note = component.method_notes?.[method.value];
      const unavailable = !method.route && decision.verdicts?.[method.value]?.value === 'fit';
      const picked = method.value === answer.method;
      const tag = interactive ? 'button' : 'div';
      const attrs = interactive
        ? ` type="button" data-card-method="${h(method.value)}" aria-pressed="${picked}"${unavailable ? ' disabled aria-disabled="true"' : ''}`
        : '';
      return `<${tag} class="gw-method-pair${picked ? ' is-selected' : ''}" data-method-map-row data-method-node="${h(method.value)}"${attrs}>${cueBlock}${arrow}<div class="gw-method-node">${methodBody(method, note, picked, interactive)}</div></${tag}>`;
    }
    const choices = methods.map(method => {
      const picked = method.value === answer.method;
      const note = component.method_notes?.[method.value];
      const unavailable = !method.route && decision.verdicts?.[method.value]?.value === 'fit';
      const tag = interactive ? 'button' : 'div';
      return `<${tag} class="gw-method-node${picked ? ' is-selected' : ''}" data-method-node="${h(method.value)}"${interactive ? ` type="button" data-card-method="${h(method.value)}" aria-pressed="${picked}"${unavailable ? ' disabled aria-disabled="true"' : ''}` : ''}>${methodBody(method, note, picked, interactive)}</${tag}>`;
    }).join('');
    return `<div class="gw-method-pair${selected ? ' is-selected' : ''}" data-method-map-row>${cueBlock}${arrow}<div class="gw-method-choices">${choices}</div></div>`;
  }).join('');
  const selected = component.methods.find(method => method.value === answer.method);
  const explanation = !interactive && selected ? `<div class="gw-method-map-explanation"><p data-math-text>${h(decision.verdicts?.[selected.value]?.message)}</p>${component.methods.filter(method => method.value !== selected.value && decision.verdicts?.[method.value]?.value === 'fit').map(method => `<p class="gw-method-also" data-math-text>${h(decision.verdicts[method.value].message)}</p>`).join('')}</div>` : '';
  return `<div class="gw-method-connections" data-method-connections role="group" aria-label="${interactive ? '选法配对卡' : '已确认的选法配对'}">${pairs}</div>${explanation}`;
}

// Pairing cards use CSS connectors; keep the mount hook for callers that still expect it.
export function mountMethodConnections(root) {
  const cards = [...root.querySelectorAll('[data-method-connections]')];
  if (!cards.length) return () => {};
  // Legacy SVG edge drawing only runs when old link-line markup is present.
  const rows = cards.flatMap(card => [...card.querySelectorAll('[data-method-map-row]')])
    .filter(row => row.querySelector('.gw-method-link-lines'));
  if (!rows.length) return () => {};
  const draw = () => rows.forEach(row => {
    const svg = row.querySelector('.gw-method-link-lines'), cue = row.querySelector('.gw-method-cue');
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
  });
  draw();
  const observer = typeof ResizeObserver === 'function' ? new ResizeObserver(draw) : null;
  rows.forEach(row => observer?.observe(row));
  return () => observer?.disconnect();
}
