// Render checked set geometry supplied by the mathematics stage. No set parsing
// or endpoint evaluation happens here; this only adapts typed display values.
const requireValue = (ok, name) => { if (!ok) throw Error(`domain_visuals.${name}`); };
const escape = value => String(value).replace(/[&<>"']/g, ch => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[ch]));

export function domainNumberLineGraph(line) {
  requireValue(line && typeof line.label === 'string' && typeof line.variable === 'string', 'identity');
  requireValue(Array.isArray(line.bounds) && line.bounds.length === 2 && line.bounds.every(Number.isFinite)
    && line.bounds[0] < line.bounds[1] && Number.isFinite(line.bounds[1] - line.bounds[0]), 'bounds');
  requireValue(Array.isArray(line.intervals) && Array.isArray(line.points) && Array.isArray(line.ticks), 'geometry');
  const pieces = line.intervals.map(interval => {
    requireValue([interval.left, interval.right].every(value => value === null || Number.isFinite(value))
      && typeof interval.left_closed === 'boolean' && typeof interval.right_closed === 'boolean'
      && (interval.left === null || interval.right === null || interval.left < interval.right)
      && (interval.left !== null || !interval.left_closed) && (interval.right !== null || !interval.right_closed), 'interval');
    return {from: interval.left, to: interval.right, left_closed: interval.left_closed, right_closed: interval.right_closed};
  });
  const point = value => {
    requireValue(Number.isFinite(value.at) && typeof value.label === 'string', 'point');
    return {x: value.at, label: value.label};
  };
  const points = line.points.map(point), ticks = line.ticks.map(value => { point(value); return [value.at, value.label]; });
  const marks = [...new Set([...ticks.map(tick => tick[0]), ...points.map(item => item.x),
    ...pieces.flatMap(piece => [piece.from, piece.to]).filter(value => value !== null)])].sort((a, b) => a - b);
  // numberLine uses a 288 px axis and 12 px diameter endpoint marks. Keep
  // all shared ticks distinguishable; a formula is safer than overlapping dots.
  const width = line.bounds[1] - line.bounds[0];
  if (marks.some((value, index) => index > 0 && (value - marks[index - 1]) / width * 288 < 16)) return null;
  return {kind: 'number_line', caption: `$${line.label}$`, params: {bounds: [...line.bounds], pieces,
    points, ticks,
    variable: line.variable, title: line.label, description: line.label}};
}

export function endpointChecksHTML(checks) {
  if (checks === undefined) return '';
  requireValue(Array.isArray(checks), 'endpoint_checks');
  const items = checks.map(check => {
    requireValue(check && typeof check === 'object' && !Array.isArray(check)
      && Number.isFinite(check.at) && typeof check.label === 'string' && typeof check.included === 'boolean'
      && typeof check.holds === 'boolean' && check.passed === true && typeof check.reason === 'string'
      && Array.isArray(check.sources), 'unverified_endpoint');
    return `<li><strong data-math-text>$${escape(check.label)}$：${check.included ? '可以取到' : '不能取到'}</strong><p data-math-text>${escape(check.reason)}</p></li>`;
  }).join('');
  return items ? `<section class="gw-endpoint-checks"><h3>检查端点</h3><ul>${items}</ul></section>` : '';
}
