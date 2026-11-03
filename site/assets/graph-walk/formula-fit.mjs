/* Responsive presentation only: keep every mathematical term and its order. */
export function gatheredRows(source) {
  const match = source.trim().match(/^(\\displaystyle\s*)?\\begin\{gathered\}([\s\S]*)\\end\{gathered\}$/);
  if (!match) return [source];
  const body = match[2], rows = [];
  let braces = 0, environments = 0, start = 0;
  // A nested cases/matrix, text group or escaped brace belongs to its original row.
  for (const token of body.matchAll(/\\(?:begin|end)\{[^}]+\}|\\[a-zA-Z]+|\\[\s\S]|[{}&]/g)) {
    const value = token[0];
    if (value.startsWith('\\begin{')) environments++;
    else if (value.startsWith('\\end{')) environments--;
    else if (value === '{') braces++;
    else if (value === '}') braces--;
    else if (!braces && !environments && value === '&') return [source];
    else if (!braces && !environments && value === '\\\\') {
      // Preserve explicit row spacing as authored instead of treating it as math.
      if (/^\s*\[/.test(body.slice(token.index + 2))) return [source];
      rows.push(body.slice(start, token.index).trim());
      start = token.index + 2;
    }
    if (braces < 0 || environments < 0) return [source];
  }
  rows.push(body.slice(start).trim());
  if (braces || environments || rows.some(row => !row)) return [source];
  return rows.map(row => `\\displaystyle ${row}`);
}

export function renderFittedFormula(node, source, render) {
  const lines = gatheredRows(source).map(value => {
    const line = node.ownerDocument.createElement('div');
    line.className = 'gw-formula-line';
    // Keep a coefficient with its following factor when the equation wraps.
    const display = value.replace(/\\(?:cdot|times)(?![a-zA-Z])/g, operator => `${operator}\\nobreak `);
    render(line, `$${display}$`);
    return line;
  });
  node.replaceChildren(...lines);
  node.dataset.fittedFormula = 'true';
}

/** Keep short equations on one line. Longer ones use KaTeX's own safe breaks
 * at relations/binary operators; fractions, exponents and brackets stay intact.
 */
export function fitFormulaLines(node) {
  const available = node.clientWidth - 2; // rounding/italic-glyph allowance
  if (available <= 0) return; // collapsed or not mounted yet
  const view = node.ownerDocument.defaultView;
  for (const line of node.querySelectorAll('.gw-formula-line')) {
    line.style.fontSize = '';
    line.dataset.wrap = 'false';
    const math = line.querySelector('.katex-html');
    if (!math) continue;
    const fontSize = parseFloat(view.getComputedStyle(line).fontSize);
    const natural = math.getBoundingClientRect().width;
    if (natural <= available || !natural) continue;
    let scale = available / natural;
    if (fontSize * scale < 16) {
      line.dataset.wrap = 'true';
      const chunks = [...math.children].filter(child => child.classList.contains('katex-base'));
      const widest = Math.max(0, ...chunks.map(chunk => chunk.getBoundingClientRect().width));
      scale = widest ? Math.min(1, available / widest) : scale;
    }
    line.style.fontSize = `${Math.floor(fontSize * scale * 100) / 100}px`;
  }
}

/** One observer per walk, including cached cards, late fonts and details toggles. */
export function createFormulaFitter(document) {
  const view = document.defaultView;
  if (!view?.requestAnimationFrame) return {refresh() {}, dispose() {}};
  const widths = new Map();
  let frame = null, disposed = false, force = false;
  const update = () => {
    frame = null;
    if (disposed) return;
    const current = new Set(document.querySelectorAll('[data-fitted-formula]'));
    for (const node of widths.keys()) {
      if (!current.has(node)) { observer?.unobserve(node); widths.delete(node); }
    }
    for (const node of current) {
      if (!widths.has(node)) observer?.observe(node);
      const width = node.clientWidth;
      if (force || width !== widths.get(node)) fitFormulaLines(node);
      widths.set(node, width);
    }
    force = false;
  };
  const refresh = () => {
    if (!disposed && frame === null) frame = view.requestAnimationFrame(update);
  };
  const remeasure = () => { force = true; refresh(); };
  const observer = view.ResizeObserver ? new view.ResizeObserver(entries => {
    if (entries.some(({target}) => target.clientWidth !== widths.get(target))) refresh();
  }) : null;
  document.addEventListener('toggle', refresh, true);
  view.addEventListener('resize', refresh);
  document.fonts?.addEventListener('loadingdone', remeasure);
  document.fonts?.ready.then(remeasure);
  return {
    refresh,
    dispose() {
      disposed = true;
      if (frame !== null) view.cancelAnimationFrame(frame);
      observer?.disconnect(); widths.clear();
      document.removeEventListener('toggle', refresh, true);
      view.removeEventListener('resize', refresh);
      document.fonts?.removeEventListener('loadingdone', remeasure);
    },
  };
}
