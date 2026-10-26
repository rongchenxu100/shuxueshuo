// Presentation only: positions are produced by S3, never rediscovered from math text.
const escape = value => String(value).replace(/[&<>"']/g, ch => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[ch]));
const key = value => JSON.stringify(value);

export function expressionRegionsHTML(source, selected = []) {
  if (!source) return '';
  const root = source.expression_ast;
  if (!Array.isArray(root) || !Array.isArray(source.regions)) throw Error('expression_regions.missing_source');
  const regions = new Map();
  for (const region of source.regions) {
    if (!Array.isArray(region.ast_path) || !region.source_ref || !region.condition_id) throw Error('expression_regions.invalid_reference');
    let node = root;
    for (const position of region.ast_path) {
      if (!Number.isInteger(position) || position < 1 || !Array.isArray(node)) throw Error('expression_regions.invalid_path');
      node = node[position];
    }
    if (!Array.isArray(node)) throw Error('expression_regions.unresolved_reference');
    const at = key(region.ast_path);
    regions.set(at, [...(regions.get(at) || []), region]);
  }
  const render = (node, at = [], depth = 0) => {
    if (!Array.isArray(node) || depth > 40) throw Error('expression_regions.invalid_ast');
    const child = index => render(node[index], [...at, index], depth + 1), type = node[0];
    let html;
    if (type === 'bound') {
      const symbol = source.bound_symbols?.[node[1]];
      if (typeof symbol !== 'string' || !symbol) throw Error('expression_regions.missing_bound_symbol');
      html = `<span class="gw-expr-token">${escape(symbol)}</span>`;
    }
    else if (['number', 'name', 'symbol'].includes(type)) html = `<span class="gw-expr-token">${escape(node[1])}</span>`;
    else if (type === '/') html = `<span class="gw-expr-fraction"><span>${child(1)}</span><span>${child(2)}</span></span>`;
    else if (type === 'call' && node[1] === 'sqrt') html = `<span class="gw-expr-root"><span aria-hidden="true">√</span><span>${child(2)}</span></span>`;
    else if (['+', '-', '*'].includes(type)) html = `<span class="gw-expr-binary">${at.length ? '(' : ''}${child(1)}<span>${type === '*' ? '·' : type === '-' ? '−' : '+'}</span>${child(2)}${at.length ? ')' : ''}</span>`;
    else if (type === 'neg') html = `<span>−${child(1)}</span>`;
    else if (type === '^') {
      const group = ['neg', '^', '/'].includes(node[1]?.[0]) || node[1]?.[0] === 'number' && String(node[1][1]).startsWith('-');
      html = `<span>${group ? '(' : ''}${child(1)}${group ? ')' : ''}<sup>${child(2)}</sup></span>`;
    }
    else throw Error('expression_regions.unsupported_ast');
    const related = regions.get(key(at)) || [];
    const active = related.filter(region => selected.includes(region.option_value || region.condition_id));
    return `<span class="gw-expr-node${active.length ? ' is-highlighted' : ''}"${related.length ? ` data-source-ref="${escape(related[0].source_ref)}"` : ''}>${html}</span>`;
  };
  return `<figure class="gw-expression-regions"><figcaption>对照原式中的位置</figcaption><div role="img" aria-label="${escape(source.expression || '原式')}">${render(root)}</div></figure>`;
}
