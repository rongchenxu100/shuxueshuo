/* Two modes:
   ?search=<id>  live: polls the local /api/search stage-one run for a chosen crop (run_site.py).
   ?demo=ok|multi|fixed|figure|unclear|unsupported|error  prototype: plays a mocked stage-one run.
   The extracted problem is shown as soon as it passes code checks; the source review keeps
   running and either confirms it, corrects it, or withdraws it into a failure card. */
const params = new URLSearchParams(location.search);
const searchId = params.get('search');
const demo = params.get('demo') || 'ok';
const $ = selector => document.querySelector(selector);
const session = window.SearchSession;
const searchFetch = (...args) => session.request(...args);
let privateStopped = false;
let liveTicket = 0;
let retryRequestId = null;
let retryPending = false;
let lessonRetryIntent = null;
let lessonRetryPending = false;
let lessonRetryAccepted = false;
let progressOwner = null;
let retakePending = false;
let questionFigures = null, figureRenderer = null;
let disposeQuestionFigures = () => {}, disposeFailedFigures = () => {};
const started = performance.now();

const Q01 = '若不等式 $-x^2+2x+3\\le a^2-3a$ 对任意实数 $x$ 恒成立，求实数 $a$ 的取值范围。';
const Q01_MISREAD = '若不等式 $-x^2+2x+3\\le a^2-3$ 对任意实数 $x$ 恒成立，求实数 $a$ 的取值范围。';
const Q10 = '已知函数 $f(x)=x^2-2ax+3$。\n（1）若对任意 $x\\in\\mathbb{R}$，$f(x)\\ge 0$ 恒成立，求实数 $a$ 的取值范围；\n（2）若存在 $x\\in[1,2]$，使得 $f(x)<0$ 成立，求实数 $a$ 的取值范围。';
const RANGE_A = [{kind: 'find_range', symbol: 'a'}];
const Q01_ROOT = {facts: ['∀x∈ℝ: -x^2+2*x+3 <= a^2-3*a'], goals: RANGE_A};
const Q01_MISREAD_ROOT = {facts: ['∀x∈ℝ: -x^2+2*x+3 <= a^2-3'], goals: RANGE_A};
const Q10_ROOT = {definitions: ['f(x) = x^2-2*a*x+3'], children: [
  {label: '（1）', facts: ['∀x∈ℝ: f(x) >= 0'], goals: RANGE_A},
  {label: '（2）', facts: ['∃x∈[1,2]: f(x) < 0'], goals: RANGE_A},
]};

const FAILS = {
  figure: {
    icon: '!', title: '题图或选项不完整', text: '请把完整题干和全部选项拍在同一张图中；跨页题暂不支持合并。', actions: ['retake'],
  },
  unclear: {
    icon: '!', title: '有一处没看清', text: '拍正、避开反光，再拍一次。',
    quote: '“$a^2-3a$”中 $a$ 右上角的数字被反光挡住了', actions: ['retake'],
  },
  unsupported: {
    icon: '?', tone: 'gray', title: '这道题暂不支持', text: '这类题暂不支持，可以换一道题或查看示例。', actions: ['other', 'demo'],
  },
  error: {
    icon: '↻', tone: 'gray', title: '识别没有成功', text: '是我们这边的问题，请重试。', actions: ['retry', 'retake'],
  },
};

/* extract: ms until the extraction is shown (or fails); review: ms the background review takes.
   preview is what extraction showed; text is what review settled on. */
const SCENARIOS = {
  ok: {sample: 'sample-q01.png', extract: 2200, review: 2400, text: Q01, root: Q01_ROOT, lesson: 'demo-lesson-q01.json'},
  multi: {sample: 'sample-q10.png', extract: 2600, review: 2600, text: Q10, parts: ['（1）', '（2）'], root: Q10_ROOT, lesson: 'demo-lesson-q10.json'},
  fixed: {sample: 'sample-q01.png', extract: 2200, review: 3600, preview: Q01_MISREAD, previewRoot: Q01_MISREAD_ROOT, text: Q01, root: Q01_ROOT, lesson: 'demo-lesson-q01.json'},
  figure: {sample: 'sample-q01.png', extract: 2200, review: 2200, preview: Q01, previewRoot: Q01_ROOT, fail: FAILS.figure},
  unclear: {sample: 'sample-q01.png', extract: 2200, review: 2400, preview: Q01, previewRoot: Q01_ROOT, fail: FAILS.unclear},
  unsupported: {sample: 'sample-q01.png', extract: 2400, fail: FAILS.unsupported},
  error: {sample: 'sample-q01.png', extract: 2200, review: 3000, preview: Q01, previewRoot: Q01_ROOT, fail: FAILS.error},
};
const scenario = SCENARIOS[demo] || SCENARIOS.ok;

function renderMath(root) {
  window.renderMathInElement?.(root, {delimiters: [
    {left: '$$', right: '$$', display: true}, {left: '$', right: '$', display: false},
    {left: '\\[', right: '\\]', display: true}, {left: '\\(', right: '\\)', display: false},
  ], throwOnError: false});
}

function toast(text) {
  const el = $('#sq-toast');
  el.textContent = text; el.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { el.hidden = true; }, 2400);
}

const escape = text => text.replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
const phaseItems = () => [...document.querySelectorAll('#pq-phases li')];
const partName = label => `第${label.replace(/[（）()]/g, '')}问`;

function setPhotos(src) {
  for (const img of ['#pq-photo', '#pq-thumb-img', '#pq-fail-img', '#pq-viewer-img']) $(img).src = src;
}

function renderInlineFigures(targetRef = null) {
  disposeQuestionFigures();
  disposeQuestionFigures = () => {};
  const host = $('#pq-figures');
  host.hidden = true;
  const options = {searchId, targetRef};
  const view = figureRenderer.projectFigures(questionFigures, options);
  // The full crop already has a thumbnail/viewer. Only required diagrams belong in the question body.
  if (!view.rows.length) return;
  disposeQuestionFigures = figureRenderer.mountQuestionFigures(host, questionFigures, options);
  host.hidden = false;
}

async function showQuestionFigures(status, active) {
  disposeQuestionFigures(); disposeFailedFigures(); questionFigures = null;
  disposeQuestionFigures = () => {}; disposeFailedFigures = () => {};
  $('#pq-figures').hidden = true; $('#pq-fail-figures').hidden = true;
  $('.pq-fail-photo').hidden = false;
  // Only old servers lacking both fields use the old image contract.
  if (!status.figures && !status.figure_error) { setPhotos(`/api/search/problems/${searchId}/image`); return; }
  for (const img of ['#pq-photo', '#pq-thumb-img', '#pq-fail-img', '#pq-viewer-img']) $(img).removeAttribute('src');
  try {
    if (status.figure_error) throw new Error('图片已变更或不可用，请重新打开题目。');
    figureRenderer ||= await import('/assets/practice/question-figures.mjs?v=20261102-g0');
    if (!active()) return;
    const view = figureRenderer.projectFigures(status.figures, {searchId});
    questionFigures = status.figures;
    setPhotos(view.source.image_url);
    renderInlineFigures();
  } catch (error) {
    if (!active()) return;
    $('#pq-figures').textContent = status.figure_error ? '图片已变更或不可用，请重新打开题目。' : '题图暂时无法显示，请重新打开题目。';
    $('#pq-figures').hidden = false;
  }
}

function showFailedFigures() {
  if (!questionFigures || !figureRenderer) {
    if (!$('#pq-figures').hidden) {
      $('#pq-fail-figures').textContent = $('#pq-figures').textContent;
      $('#pq-fail-figures').hidden = false;
      $('.pq-fail-photo').hidden = true;
    }
    return;
  }
  disposeFailedFigures();
  disposeFailedFigures = figureRenderer.mountQuestionFigures($('#pq-fail-figures'), questionFigures, {searchId});
  $('#pq-fail-figures').hidden = false;
  $('.pq-fail-photo').hidden = true;
}

/* ---------- 题意整理：阶段①的条件与所求 ---------- */
const TEX = {
  '∧': '\\text{ 且 }', '∨': '\\text{ 或 }', '⊆': '\\subseteq ', '⊊': '\\subsetneqq ', '⊇': '\\supseteq ',
  '⊋': '\\supsetneqq ', '∅': '\\varnothing ', 'ℝ': '\\mathbb{R}', '∞': '\\infty ', '∀': '\\forall ',
  '∃': '\\exists ', '∈': '\\in ', '∉': '\\notin ', '∩': '\\cap ', '∪': '\\cup ',
  ':': '\\colon ', '°': '^\\circ ', '∠': '\\angle ', '△': '\\triangle ', '⟂': '\\perp ', '∥': '\\parallel ',
};

/* Index of the bracket closing the one at text[open]. Interval ends may pair ( with ] or [ with ),
   so all of ( [ { count as openers and ) ] } as closers. Returns -1 when unbalanced. */
function closing(text, open, onComma) {
  let depth = 0;
  for (let j = open; j < text.length; j++) {
    if ('([{'.includes(text[j])) depth++;
    else if (')]}'.includes(text[j]) && --depth === 0) return j;
    else if (text[j] === ',' && depth === 1) onComma?.(j);
  }
  return -1;
}

/* Rewrite name(a, b) calls, innermost-safe: arguments are split at top-level commas. */
function calls(text, name, render) {
  let out = '';
  let i = 0;
  const pattern = new RegExp(`\\b${name}\\(`, 'g');
  for (let match; (match = pattern.exec(text));) {
    const open = match.index + name.length;
    const args = [];
    let start = open + 1;
    const j = closing(text, open, comma => { args.push(text.slice(start, comma)); start = comma + 1; });
    if (j < 0) break;
    args.push(text.slice(start, j));
    out += text.slice(i, match.index) + render(...args.map(arg => calls(arg.trim(), name, render)));
    i = j + 1;
    pattern.lastIndex = i;
  }
  return out + text.slice(i);
}

const GROUP_OPEN = '\u0001';
const GROUP_CLOSE = '\u0002';
const skip = (text, p) => { while (text[p] === ' ') p++; return p; };

/* End of the primary operand at text[p], following notation_parser.expr: a bracket group, |…|,
   √ with a number or group, a number, or a name with optional min_{…} hint and call arguments.
   Returns -1 when the text there is not a primary. */
function primaryEnd(text, p) {
  if ('([{'.includes(text[p])) return closing(text, p) + 1 || -1;
  if (text[p] === '|') {
    for (let j = p + 1, depth = 0; j < text.length; j++) {
      if ('([{'.includes(text[j])) depth++;
      else if (')]}'.includes(text[j])) depth--;
      else if (text[j] === '|' && depth === 0) return j + 1;
    }
    return -1;
  }
  if (text[p] === '√') return primaryEnd(text, skip(text, p + 1));
  const number = /^\d+(?:\.\d+)?/.exec(text.slice(p));
  if (number) return p + number[0].length;
  const name = /^[A-Za-z\u0370-\u03ff][A-Za-z0-9_\u0370-\u03ff]*/.exec(text.slice(p));
  if (!name) return -1;
  let end = p + name[0].length;
  if (/^(?:min|max)_$/.test(name[0]) && text[skip(text, end)] === '{') end = closing(text, skip(text, end)) + 1;
  if (end && text[skip(text, end)] === '(') end = closing(text, skip(text, end)) + 1;
  return end || -1;
}

/* The operand after the ^ at text[k], as the parser reads it: unary signs, a primary, then any
   further ^ (right-associative), so x^-2^2 is x^(-(2^2)) and x^(-2)^2 is x^((-2)^2).
   Returns [notation with grouped powers, end] or null. */
function exponent(text, k) {
  let p = skip(text, k + 1);
  let sign = '';
  for (; text[p] && '+-−'.includes(text[p]); p = skip(text, p + 1)) if (text[p] !== '+') sign = sign ? '' : '-';
  const end = primaryEnd(text, p);
  if (end < 0) return null;
  let body = powers(text.slice(p, end));
  const q = skip(text, end);
  const next = text[q] === '^' ? exponent(text, q) : null;
  if (next) return [`${sign}${body}^${GROUP_OPEN}${next[0]}${GROUP_CLOSE}`, next[1]];
  if (!sign && text[p] === '(' && end - 1 === closing(text, p)) body = body.slice(1, -1);
  return [sign + body, end];
}

/* x^(2-a) → x^{2-a}, x ^ 12 → x^{12}, x^2^3 → x^{2^{3}}: TeX only raises the next token.
   Groups are marked with control characters until the notation's own braces are escaped. */
function powers(text) {
  let out = '';
  let i = 0;
  for (let k = text.indexOf('^'); k >= 0; k = text.indexOf('^', i)) {
    const found = exponent(text, k);
    out += text.slice(i, k).trimEnd() + '^';
    if (found) { out += GROUP_OPEN + found[0] + GROUP_CLOSE; i = found[1]; } else i = k + 1;
  }
  return out + text.slice(i);
}

/* Same symbol normalization as notation_parser.clean; order matters (** before *). */
const CLEAN = [
  ['−', '-'], ['–', '-'], ['×', '*'], ['÷', '/'], ['≤', '<='], ['≥', '>='], ['≠', '!='],
  [':=', '='], ['≔', '='], ['≡', '='], ['²', '^2'], ['³', '^3'], ['：', ':'], ['，', ','],
  ['（', '('], ['）', ')'], ['⊥', '⟂'], ['⫋', '⊊'], ['⫌', '⊋'], ['Ø', '∅'], ['**', '^'],
];

/* Follow notation_parser's token boundaries before removing whitespace: 2 sqrt(4) and
   2sqrt(4) both mean 2*sqrt(4), but digits inside a name (x_12, a2sqrt) stay in that name. */
function normalizeNotation(expr) {
  const clean = CLEAN.reduce((text, [a, b]) => text.replaceAll(a, b), expr.normalize('NFC'));
  const tokens = clean.match(/\d+(?:\.\d+)?|[A-Za-z\u0370-\u03ff][A-Za-z0-9_\u0370-\u03ff]*|\S/g) || [];
  return tokens.map((token, i) => {
    const coefficient = i > 0 && /^\d+(?:\.\d+)?$/.test(tokens[i - 1]);
    const operand = /^[A-Za-z\u0370-\u03ff]/.test(token) || ['(', '∠', '√'].includes(token);
    return (coefficient && operand ? '*' : '') + token;
  }).join('');
}

/* Drop one outer (...) when it only groups the whole factor for division. */
function unwrapParens(body) {
  const text = body.trim();
  return text[0] === '(' && closing(text, 0) === text.length - 1 ? text.slice(1, -1) : text;
}

/* Matching '{' for the '}' at close, or -1 when unbalanced. */
function openingBrace(text, close) {
  for (let j = close - 1, depth = 1; j >= 0; j--) {
    if (text[j] === '}') depth++;
    else if (text[j] === '{' && --depth === 0) return j;
  }
  return -1;
}

/* Index after the '}' that closes the '{' at open, or -1 when unbalanced. */
function closingBrace(text, open) {
  for (let j = open + 1, depth = 1; j < text.length; j++) {
    if (text[j] === '{') depth++;
    else if (text[j] === '}' && --depth === 0) return j + 1;
  }
  return -1;
}

/* One display factor ending just before `end` (usually a top-level /): primary, then ^{}/_{}. */
function leftFactor(text, end) {
  let edge = end;
  while (edge > 0 && text[edge - 1] === ' ') edge--;
  let p = edge;
  while (p > 0 && text[p - 1] === '}') {
    const open = openingBrace(text, p - 1);
    if (open < 1 || (text[open - 1] !== '^' && text[open - 1] !== '_')) break;
    p = open - 1;
  }
  if (p <= 0) return null;
  if (text[p - 1] === ')') {
    for (let j = p - 2, depth = 1; j >= 0; j--) {
      if (text[j] === ')') depth++;
      else if (text[j] === '(' && --depth === 0) return {start: j, end: edge};
    }
    return null;
  }
  if (text.slice(Math.max(0, p - 7), p) === '\\right|') {
    const open = text.lastIndexOf('\\left|', p);
    return open >= 0 ? {start: open, end: edge} : null;
  }
  if (text[p - 1] === '}') {
    const open = openingBrace(text, p - 1);
    if (open >= 5 && text.slice(open - 5, open) === '\\sqrt') return {start: open - 5, end: edge};
  }
  if (/\d/.test(text[p - 1])) {
    let j = p - 1;
    while (j > 0 && /[\d.]/.test(text[j - 1])) j--;
    return {start: j, end: edge};
  }
  if (/[A-Za-z\u0370-\u03ff]/.test(text[p - 1])) {
    let j = p - 1;
    while (j > 0 && /[A-Za-z0-9_\u0370-\u03ff]/.test(text[j - 1])) j--;
    return {start: j, end: edge};
  }
  return null;
}

/* One display factor starting at `start` (just after /): optional signs, primary, ^{}/_{}. */
function rightFactor(text, start) {
  let p = skip(text, start);
  const from = p;
  while (text[p] && '+-−'.includes(text[p])) p = skip(text, p + 1);
  let end = -1;
  if (text.startsWith('\\sqrt{', p)) end = closingBrace(text, p + 5);
  else if (text.startsWith('\\left|', p)) {
    const close = text.indexOf('\\right|', p + 6);
    end = close < 0 ? -1 : close + 7;
  } else if ('([{'.includes(text[p])) end = closing(text, p) + 1 || -1;
  else {
    const number = /^\d+(?:\.\d+)?/.exec(text.slice(p));
    if (number) end = p + number[0].length;
    else {
      const name = /^[A-Za-z\u0370-\u03ff][A-Za-z0-9_\u0370-\u03ff]*/.exec(text.slice(p));
      end = name ? p + name[0].length : -1;
    }
  }
  if (end < 0) return null;
  while (true) {
    const q = skip(text, end);
    if (!text.startsWith('^{', q) && !text.startsWith('_{', q)) break;
    end = closingBrace(text, q + 1);
    if (end < 0) return null;
  }
  return {start: from, end};
}

/* A lone digit/digit becomes \frac even inside intervals; chained 1/2/3 stays inline. */
function numberFractions(s) {
  return s.replace(/(\d+)\/(\d+)/g, (match, top, bottom, at) => {
    const before = s.slice(0, at), after = s.slice(at + match.length);
    if (/[\w.^]$/.test(before) || /^[\w.^/]/.test(after)) return match;
    if (/\/[+\-−\s]*$/.test(before)) return match;
    return `\\frac{${top}}{${bottom}}`;
  });
}

/* Top-level algebraic a/b becomes \frac when that slash is not part of a longer chain.
   Division is left-associative, so a/2/3 and sqrt(4)/2/3 keep every slash. */
function algebraicFractions(s) {
  const slashes = [];
  for (let i = 0, depth = 0; i < s.length; i++) {
    if ('([{'.includes(s[i])) depth++;
    else if (')]}'.includes(s[i])) depth--;
    else if (s[i] === '/' && depth === 0) slashes.push(i);
  }
  if (!slashes.length) return s;
  let out = '', cursor = 0;
  for (const at of slashes) {
    if (at < cursor) continue;
    const left = leftFactor(s, at), right = rightFactor(s, at + 1);
    if (!left || !right || s.slice(left.end, at).trim() !== '') continue;
    let before = left.start;
    while (before > 0 && s[before - 1] === ' ') before--;
    while (before > 0 && '+-−'.includes(s[before - 1])) before--;
    while (before > 0 && s[before - 1] === ' ') before--;
    if (before > 0 && s[before - 1] === '/') continue;
    let next = right.end;
    while (next < s.length && s[next] === ' ') next++;
    while (next < s.length && '+-−'.includes(s[next])) next++;
    while (next < s.length && s[next] === ' ') next++;
    if (next < s.length && s[next] === '/') continue;
    out += s.slice(cursor, left.start)
      + `\\frac{${unwrapParens(s.slice(left.start, left.end))}}{${unwrapParens(s.slice(right.start, right.end))}}`;
    cursor = right.end;
  }
  return out + s.slice(cursor);
}

function fractions(s) {
  return algebraicFractions(numberFractions(s));
}

/* Catalog notation (Unicode, explicit or numeric implicit multiplication) to display TeX. */
function tex(expr) {
  const clean = normalizeNotation(expr);
  let s = powers(clean).replace(/[{}]/g, c => '\\' + c).replaceAll(GROUP_OPEN, '{').replaceAll(GROUP_CLOSE, '}');
  // The first bar after "\{x∈domain" separates a set-builder; other bars are absolute values.
  s = s.replace(/(\\\{\s*[A-Za-z]\w*\s*∈[^|]*?)\|/g, '$1\\mid ');
  s = calls(s, 'abs', arg => `\\left|${arg}\\right|`);
  s = calls(s, 'sum', arg => `\\left(${arg}\\text{ 的元素之和}\\right)`);
  // Keep the whole remainder grouped so mod(n,3)^2 squares the remainder, not the divisor.
  const operand = arg => (/[+\-−*/]/.test(arg) ? `(${arg})` : arg);
  s = calls(s, 'mod', (n, k) => `(${operand(n)}\\bmod ${operand(k)})`);
  s = calls(s, 'sqrt', arg => `\\sqrt{${arg}}`);
  s = fractions(s);
  const inlineDivision = s.includes('/');
  return s
    .replace(/\b(min|max)_\\\{([^}]*?)\\\}/g, '\\$1_{$2}')
    .replace(/√\(([^()]*)\)/g, '\\sqrt{$1}')
    .replace(/√(\d+(?:\.\d+)?)/g, '\\sqrt{$1}')
    .replace(/\b(min|max|tan)(?=\()/g, '\\$1')
    .replace(/\b(area|length|segment|line|ray|midpoint|axis|vertex)(?=\()/g, '\\operatorname{$1}')
    .replace(/\b([xy])_axis\b/g, '$1\\text{轴}')
    .replace(/\b(min|max)_([A-Za-z0-9]+)/g, '\\$1_{$2}')
    .replace(/([A-Za-z0-9\u0370-\u03ff])_([A-Za-z0-9]+)/g, '$1_{$2}')
    .replace(/(\d)\s*\*\s*(?=\d)/g, '$1\\times ')
    .replace(/([}A-Za-z)])\s*\*\s*(?=\d)/g, '$1\\cdot ')
    .replace(/([A-Z])\s*\*\s*(?=[A-Z])/g, '$1\\cdot ')
    // With inline division, keep multiplication explicit: a/2*x must not look like a/(2*x).
    .replace(/\s*\*\s*/g, inlineDivision ? '\\cdot ' : '')
    .replace(/<=/g, '\\le ').replace(/>=/g, '\\ge ').replace(/!=/g, '\\ne ')
    .replace(/[∧∨⊆⊊⊇⊋∅ℝ∞∀∃∈∉∩∪:°∠△⟂∥]/g, c => TEX[c]);
}

const math = expr => `$${escape(tex(expr))}$`;
const knownLine = expr => (/[\u4e00-\u9fff]/.test(expr) ? escape(expr) : math(expr));
const GOALS = {
  find_function_formula: g => `${math(`${g.function}(${g.variable})`)} 的解析式${g.requested_domain ? `（所求范围 ${math(g.requested_domain)}）` : ''}`,
  find_domain: g => `${math(g.object)} 的定义域${g.input_domain ? `（题设范围 ${math(g.input_domain)}）` : ''}`,
  find_abstract_domain: g => `${math(g.target_call)} 的定义域${g.input_domain ? `（题设另限外层自变量范围 ${math(g.input_domain)}）` : ''}`,
  find_abstract_range: g => `${math(g.target_call)} 的值域`,
  find_translation_range: g => `${math(g.function_relation.split('=')[0])} 在 ${math(g.input_domain)} 上的值域`,
  find_abstract_domain_parameter: g => `${math(g.parameter)} 的取值范围`,
  find_range: g => g.relation
    ? `满足 ${math(g.expression)} 的 ${math(g.symbol)} 的取值范围`
    : g.object
    ? `${math(g.object)} 的值域${g.input_domain ? `（题设输入范围 ${math(g.input_domain)}）` : ''}`
    : `${math(g.symbol)} 的取值范围`,
  find_value: g => `${math(g.expression)} 的值`,
  check_constant: g => `${math(g.expression)} 是否为定值`,
  finite_sum: g => (g.terms || []).map(term => term.index
    ? `$\\sum_{${escape(tex(term.index))}=${escape(String(term.lower))}}^{${escape(String(term.upper))}} ${escape(tex(term.expression))}$`
    : math(term.expression)).join(' + ') + ' 的和',
  find_count: g => `满足条件的集合 ${math(g.symbol)} 的个数`,
  find_minimum: g => `${math(g.expression)} 的最小值`,
  find_maximum: g => `${math(g.expression)} 的最大值`,
  find_coordinates: g => `点 ${math(g.object)} 的坐标`,
  find_equation: g => `${math(g.object)} 的解析式`,
};
const goalLine = goal => (GOALS[goal.kind]?.(goal) ?? escape(goal.expression || goal.symbol || goal.object || ''))
  + (goal.in_terms_of?.length ? `（用含 ${goal.in_terms_of.map(math).join('、')} 的式子表示）` : '');

function meaningBlocks(scope, title, blocks) {
  const known = [...(scope.definitions || []), ...(scope.facts || [])].map(knownLine);
  const abstractGivens = new Set();
  const relationGivens = new Set();
  const goals = (scope.goals || []).map(goal => {
    const requirement = goal.required_monotonicity;
    // A stated condition belongs in the question. Difference quotient/product conditions
    // remain in the original facts; do not present their inferred direction as a given.
    if (goal.kind === 'find_range' && requirement && (!requirement.basis || requirement.basis.kind === 'stated')) {
      const subject = requirement.function ? `${requirement.function}(${requirement.variable})` : requirement.expression;
      const direction = {increasing: '严格递增', decreasing: '严格递减'}[requirement.direction];
      return `求使 ${math(subject)} 在 ${math(requirement.input_domain)} 上${direction}的 ${goalLine(goal)}`;
    }
    if (goal.relation && ['find_function_formula', 'find_value', 'find_range'].includes(goal.kind)) {
      const givens = [];
      const type = {linear: '一次函数', quadratic: '二次函数'}[goal.function_type];
      if (type) givens.push(`${math(goal.function)} 是${type}`);
      if (goal.declared_domain) givens.push(`${math(goal.function)} 的定义域为 ${math(goal.declared_domain)}`);
      const variables = goal.relation_variables || [goal.variable];
      const domain = goal.relation_domain ? `对任意 ${math(`${variables.join(',')}∈${goal.relation_domain}`)}，` : '';
      givens.push(`${domain}${math(goal.relation)}`);
      givens.push(...(goal.additional_relations || []).map(math));
      const given = givens.join('；');
      const prefix = relationGivens.has(given) ? '' : `已知 ${given}；`;
      relationGivens.add(given);
      return `${prefix}求 ${goalLine(goal)}`;
    }
    if (goal.kind === 'find_translation_range') {
      return `已知 ${math(goal.function_relation)}，${math(goal.periodic_function)} 定义在 ${math(goal.periodic_domain)} 上、以 ${math(goal.period)} 为周期；基础区间 ${math(goal.known_domain)} 上的值域为 ${math(goal.known_range)}；求 ${goalLine(goal)}`;
    }
    if (['find_abstract_domain', 'find_abstract_range', 'find_abstract_domain_parameter'].includes(goal.kind)) {
      let given = goal.strength === 'meaningful_only'
        ? `${math(goal.known_call)} 在 ${math(goal.known_domain)} 上有意义`
        : `${math(goal.known_call)} 的定义域为 ${math(goal.known_domain)}`;
      if (goal.known_range) given += `，值域为 ${math(goal.known_range)}`;
      const prefix = abstractGivens.has(given) ? '' : `已知 ${given}；`;
      abstractGivens.add(given);
      if (goal.kind === 'find_abstract_domain_parameter') {
        return `${prefix}在题设给定输入范围内，求使 ${math(goal.target_call)} 的各调用有共同合法 ${math(goal.variable)} 的参数 ${goalLine(goal)}`;
      }
      return `${prefix}求 ${goalLine(goal)}`;
    }
    if (goal.kind === 'check_constant') return `判断 ${goalLine(goal)}`;
    if (goal.kind !== 'compare_functions') return `求 ${goalLine(goal)}`;
    if (goal.mode === 'pair') return '判断题给的两个函数是否为同一函数';
    const relation = {equal: '表示同一函数', different: '表示不同函数'}[goal.select_relation];
    if (!relation) return '逐项比较两个函数的定义域与对应关系，确认原题的选择要求';
    return `逐项判断两个函数是否相同，再选出${relation}的${goal.selection_mode === 'multiple' ? '全部' : ''}选项`;
  });
  const bits = [];
  if (known.length) bits.push(known.join('；'));
  if (goals.length) bits.push(goals.join('；'));
  if (bits.length) blocks.push(`<p>${title ? `<b>${escape(title)}</b>` : ''}<span>${bits.join('。')}</span></p>`);
  for (const child of scope.children || []) {
    const label = child.label || '';
    const name = title && title !== '题干' ? `${title} ${label}` : (/^[（(]\d+[）)]$/.test(label) ? partName(label) : label);
    meaningBlocks(child, name, blocks);
  }
  return blocks;
}

function renderMeaning() {
  const box = $('#pq-meaning');
  const bundle = goals()[lesson.part]?.walk?.bundle;
  if (bundle?.problem?.normalization_decision && bundle.problem.source_meaning) {
    const saved = lesson.teaching;
    const current = saved?.problem_id === bundle.problemId && saved.base_bundle_version === bundle.bundleVersion
      ? saved.context : null;
    const normalized = current?.transformed === true;
    const text = normalized ? bundle.problem.normalized_text : bundle.problem.source_meaning;
    $('#pq-meaning-title').textContent = normalized ? '转化后的条件与目标' : '原命题与目标';
    $('#pq-meaning-body').innerHTML = `<p><span>${escape(text)}</span></p>`;
    box.hidden = false;
    renderMath(box);
    return;
  }
  $('#pq-meaning-title').textContent = '题意整理';
  const root = shown.root;
  const blocks = root ? meaningBlocks(root, root.children?.length ? '题干' : '', []) : [];
  box.hidden = !blocks.length;
  $('#pq-meaning-body').innerHTML = blocks.join('');
  renderMath(box);
}

/* ---------- 结果卡：先展示，后核对 ---------- */
const shown = {text: null, parts: [], root: null};

function setVerify(state) {
  const badge = $('#pq-verify');
  badge.hidden = false;
  badge.dataset.state = state;
  badge.textContent = {checking: '正在核对原图', ok: '已核对原图', fixed: '已按原图修正'}[state];
  const checking = state === 'checking';
  $('#pq-quota').hidden = checking;
  $('#pq-next').hidden = !checking;
  $('#pq-start').hidden = checking;
}

function renderText() {
  const lines = shown.text.split('\n').map(line => line.trim()).filter(Boolean);
  $('#pq-text').innerHTML = lines.map(line => `<p>${escape(line)}</p>`).join('');
  renderMath($('#pq-text'));
  renderMeaning();
  renderTabs();
}

/* Show or update the problem and its meaning; returns true when an already shown version changed. */
function showProblem(text, parts, root = null) {
  const same = shown.text === text && JSON.stringify(shown.root) === JSON.stringify(root);
  const changed = shown.text !== null && !same;
  if (same && String(shown.parts) === String(parts)) return false;
  Object.assign(shown, {text, parts, root});
  $('#pq-scan').hidden = true;
  $('#pq-result').hidden = false;
  renderText();
  if (changed) {
    for (const el of [$('#pq-text'), $('#pq-meaning')]) {
      el.classList.remove('is-fixed'); void el.offsetWidth; el.classList.add('is-fixed');
    }
  }
  return changed;
}

function settle(text, parts, root) {
  const fixed = showProblem(text, parts, root) || shown.fixed;
  setVerify(fixed ? 'fixed' : 'ok');
  if (fixed) toast('核对原图时修正了识别结果');
}

function withdraw(fail) {
  if (!$('#pq-result').hidden) {
    $('#pq-result').hidden = true;
    fail = {...fail, text: `已收回识别结果。${fail.text}`};
  }
  showFail(fail);
}

/* ---------- 图谱解题（阶段②） ----------
   The server sends one graph-walk bundle and AI replay per resolved part. After stage one the
   student picks 自己做 or 看 AI 解题; the problem card then moves into the walk layout and the
   Demo engine renders the steps and the graph. Part buttons switch bundles; the engine keeps each
   part's progress. */
const WALK = '/assets/graph-walk/walk.mjs?v=20261105-scroll-preserve';
const STREAM = '/assets/graph-walk/stage-three-stream.mjs?v=20261022-original-choice';
const lesson = {data: null, actor: null, part: -1, engine: null, opened: false};
let streamMount = null, streamTransport = null, streamIdentity = '', streamTicket = 0, partTicket = 0;
let streamProjection = '', streamPreparing = null;
let streamApplying = Promise.resolve();
const progressScope = () => progressOwner && progressOwner === session.user?.id ? session.scope(searchId) : null;
const pageProgressKey = () => searchId && progressScope() ? `${progressScope()}page` : null;

function savePageProgress(view) {
  if (privateStopped) return;
  const goal = goals()[lesson.part];
  if (!goal?.walk || view.problem_id !== goal.walk.bundle.problemId ||
      view.base_bundle_version !== goal.walk.bundle.bundleVersion) return;
  if (lesson.data?.stream && (!goal?.walk || view.target_ref !== goal.target_ref)) return;
  if (goal?.walk && view.problem_id === goal.walk.bundle.problemId &&
      view.base_bundle_version === goal.walk.bundle.bundleVersion) {
    lesson.teaching = {problem_id: view.problem_id, base_bundle_version: view.base_bundle_version,
      context: view.teaching_context};
    renderMeaning();
  }
  lesson.actor = view.actor;
  renderGoalCompletion(view, goal);
  if (pageProgressKey() && session.writable(searchId)) try { localStorage.setItem(pageProgressKey(), JSON.stringify({actor: view.actor, part: lesson.part,
    run_id: lesson.data?.stream?.run_id, lesson_version: lesson.data?.stream?.lesson_version})); } catch {}
}

function updateStreamView(view) {
  if (privateStopped || !lesson.engine || !lesson.data?.stream || view.run_id !== lesson.data.stream.run_id ||
      view.lesson_version !== lesson.data.stream.lesson_version) return;
  const goal = goals()[lesson.part];
  const ticket = streamTicket;
  if (!goal?.walk || lesson.engine.walkView().target_ref !== goal.target_ref) return;
  const projection = JSON.stringify([view.run_id, view.lesson_version, lesson.part,
    view.selection_chunks, view.math_steps, view.trajectories, view.interaction_protocol, view.interaction_states,
    view.interactions, view.completions, view.route_statuses, view.goals]);
  if (projection !== streamProjection) {
    streamProjection = projection;
    streamApplying = lesson.engine.updateStreamSelection(view);
  }
  // QA can arrive after all decisions are complete, without changing the
  // mathematical projection. Attach it independently after the view update.
  void streamApplying.then(() => {
    if (privateStopped || ticket !== streamTicket || streamProjection !== projection || lesson.engine.walkView().target_ref !== goal.target_ref) return;
    for (const chunk of view.qa || []) lesson.engine.attachStreamQA(chunk);
  }).catch(() => {
    if (privateStopped || ticket !== streamTicket || streamProjection !== projection) return;
    streamProjection = '';
    $('#pq-stream-status').hidden = false;
    $('#pq-stream-status').textContent = '解题过程暂时无法更新，正在重新连接。';
  });
}

async function prepareStream() {
  const descriptor = lesson.data?.stream;
  if (!descriptor) { $('#pq-stream').hidden = true; return; }
  const key = JSON.stringify([descriptor.run_id, descriptor.lesson_version]);
  if (key === streamIdentity && streamMount) return streamPreparing;
  const ticket = ++streamTicket;
  streamTransport?.stop(); streamMount?.stop(); streamMount = null; streamProjection = '';
  streamApplying = Promise.resolve();
  streamIdentity = key;
  const host = $('#pq-stream'); host.replaceChildren(); host.hidden = true;
  const module = await import(STREAM);
  if (ticket !== streamTicket) return;
  streamMount = module.mountStageThreeStream(descriptor);
  streamTransport = module.connectStageThreeStream(streamMount.consumer, descriptor, {
    fetch: searchFetch,
    onUpdate: view => { if (ticket === streamTicket) { updateStreamView(view); $('#pq-stream-status').hidden = true; } },
    onError: () => { if (ticket === streamTicket) { $('#pq-stream-status').hidden = false;
      $('#pq-stream-status').textContent = '连接暂时中断，已到达的步骤可以继续阅读，正在重连。'; } },
  });
  streamPreparing = streamTransport.start();
  await streamPreparing;
}

function goalName(goal) {
  return goal.label && /^[（(]\d+[）)]$/.test(goal.label) ? partName(goal.label) : goal.label;
}

function goalState(goal) {
  if (goal.status === 'unsupported') return 'unsupported';
  return goal.walk ? 'ready' : 'failed';
}

const goals = () => lesson.data?.goals || [];
const authoredGoal = ref => typeof ref === 'string' ? ref.split('/').slice(2).reduce((node, key) => node?.[key], shown.root) : null;

/* One scope can ask for several things (a range and a minimum); each goal then gets its own tab. */
function goalTitle(goal) {
  const part = escape(goalName(goal) || '');
  const siblings = goals().filter(other => other.scope === goal.scope);
  if (siblings.length < 2) return part;
  const authored = authoredGoal(goal.target_ref);
  const what = authored ? `${authored.kind === 'check_constant' ? '判断' : '求'} ${goalLine(authored)}` : `目标 ${siblings.indexOf(goal) + 1}`;
  return part ? `${part} · ${what}` : what;
}

/* Tabs follow the lesson's goals once they arrive; before that, stage one's parts preview them. */
function renderTabs() {
  const tabs = $('#pq-parts');
  const items = goals().length
    ? goals().map((goal, index) => [index, goalTitle(goal)])
    : shown.parts.map(label => [-1, escape(partName(label))]);
  tabs.hidden = items.length < 2;
  tabs.innerHTML = items.length < 2 ? '' : items.map(([index, html]) =>
    `<button type="button" data-part="${index}">${html}</button>`).join('');
  renderMath(tabs);
  markPartTabs();
}

function markPartTabs() {
  for (const button of document.querySelectorAll('#pq-parts [data-part]')) {
    const index = Number(button.dataset.part);
    const goal = goals()[index];
    button.dataset.state = goal ? goalState(goal) : '';
    button.setAttribute('aria-pressed', String(lesson.opened && index === lesson.part));
  }
}

function noteHtml(goal) {
  const siblings = goals().filter(other => other.scope === goal?.scope);
  const which = siblings.length > 1 ? '这个目标' : goals().length > 1 ? '这一问' : '这道题';
  if (goal?.status === 'unsupported') {
    const authored = authoredGoal(goal.target_ref);
    const message = authored?.kind === 'find_abstract_range'
      ? `求 ${goalLine(authored)} 这个目标暂未支持。`
      : `${which}暂不支持。`;
    const continuation = goals().some(other => other !== goal && other.walk)
      ? '可以切换上方标签，继续学习本题已支持的目标。'
      : authored?.kind === 'find_abstract_range' ? '' : '可以换一道题。';
    const text = continuation === '可以换一道题。' ? `${message.slice(0, -1)}，${continuation}` : message + continuation;
    return `<section class="pq-part" data-state="unsupported"><p class="pq-part-note">${text}</p></section>`;
  }
  const message = goal?.status === 'resolved' && goal.primary
    ? `${which}的学习页面生成失败，请重试。`
    : goal?.status === 'selection_failed' && !goal.primary
      ? `${which}没判断出题型，请重试。`
      : `暂时无法获取${which}的解题步骤，请重试。`;
  return `<section class="pq-part" data-state="failed"><p class="pq-part-note">${message}</p>
    <div class="pq-fail-actions"><button type="button" class="sq-primary" data-lesson-retry>重试</button><a class="sq-ghost" href="./">重新拍照</a></div></section>`;
}

/* A walk completes one target. An unsupported sibling must stay visible even
   after the supported target has finished its own route. */
function renderGoalCompletion(view, goal) {
  if (!view.done || goals().length < 2) return;
  const host = $('#gw-completion');
  const heading = $('#gw-completion .gw-completion h2');
  if (!host || !heading) return;
  const authored = authoredGoal(goal.target_ref);
  heading.innerHTML = `${authored ? `求 ${goalLine(authored)}` : goalTitle(goal)} · ${view.actor === 'replay' ? '这个目标回放已结束' : '这个目标已完成'}`;
  const unsupported = goals().filter(other => other !== goal && other.status === 'unsupported');
  const message = unsupported.length
    ? unsupported.map(other => {
      const target = authoredGoal(other.target_ref);
      return `${target ? `求 ${goalLine(target)}` : goalTitle(other) || '另一个目标'}暂未支持`;
    }).join('；') + '。本次完成的是当前目标的解答。'
    : '其他目标可通过上方标签切换查看。';
  host.querySelector?.('[data-pq-goal-note]')?.remove();
  const note = document.createElement('p');
  note.className = 'pq-part-note';
  note.dataset.pqGoalNote = 'true';
  note.innerHTML = message;
  host.append(note);
  renderMath(host);
}

const LOST = `<section class="pq-part" data-state="failed"><p class="pq-part-note">连不上服务器，暂时拿不到解题步骤</p>
  <div class="pq-fail-actions"><button type="button" class="sq-primary" data-lesson-resume>重新连接</button></div></section>`;
const WAITING = '<p class="gw-ai-status is-thinking" role="status"><span class="gw-ai-dot" aria-hidden="true"></span>正在判断题型…</p>';

/* In walk mode a note replaces the steps and hides the graph; before it, notes sit under the card. */
function showNote(html) {
  $('#pq-stream').hidden = true;
  if (!lesson.opened) { $('#pq-lesson').innerHTML = html; renderMath($('#pq-lesson')); return; }
  lesson.engine?.parkWalk();
  document.body.dataset.part = 'note';
  document.body.dataset.graph = 'hidden';
  $('#gw-ready').hidden = false;
  $('#gw-completion').innerHTML = '';
  $('#gw-steps').innerHTML = html;
  renderMath($('#gw-steps'));
}

/* A retry or a resumed poll can bring back a lesson after a failure note replaced the choice. */
function offerStart() {
  if (lesson.opened) return;
  $('#pq-lesson').innerHTML = '';
  $('#pq-start').hidden = $('#pq-verify').dataset.state === 'checking';
}

function showLesson(data) {
  if (privateStopped) return;
  if (lessonRetryAccepted && !lessonNeedsPolling(data)) {
    lessonRetryIntent = null;
    lessonRetryAccepted = false;
  }
  if (data.execution_status === 'unavailable') {
    unavailableStatus({outcome: 'unavailable', statement: shown.text});
    return;
  }
  const action = $('#pq-stream-action');
  action.hidden = !searchId || !(data.execution_status === 'not_started' ||
    (data.stream && ['interrupted', 'error'].includes(data.execution_status)));
  action.textContent = data.execution_status === 'not_started' ? '生成解题步骤' : '继续计算';
  if (data.status === 'running' && !data.goals?.length) {
    lesson.data = null;
    renderTabs();
    $('#pq-start-note').hidden = false;
    offerStart();
    if (lesson.opened) showNote(WAITING);
    return;
  }
  $('#pq-start-note').hidden = true;
  if (data.status === 'input_error' || data.status === 'error' || !data.goals?.length) {
    lesson.data = null;
    renderTabs();
    $('#pq-start').hidden = true;
    showNote(noteHtml(null));
    return;
  }
  const previous = lesson.data;
  lesson.data = data;
  renderTabs();
  const first = data.goals.findIndex(goal => goal.walk);
  if (first < 0) {
    // Nothing to walk in any part: no choice to offer, just say why.
    $('#pq-start').hidden = true;
    showNote(data.goals.map(goal => (data.goals.length > 1 ? `<h2 class="pq-part-title">${goalTitle(goal)}</h2>` : '') + noteHtml(goal)).join(''));
    return;
  }
  if (lesson.part < 0 || !data.goals[lesson.part]) lesson.part = first;
  renderMeaning();
  markPartTabs();
  if (lesson.opened) {
    const same = previous?.stream?.run_id === data.stream?.run_id && previous?.stream?.lesson_version === data.stream?.lesson_version &&
      previous?.goals?.[lesson.part]?.walk?.bundle.bundleVersion === data.goals[lesson.part]?.walk?.bundle.bundleVersion;
    if (!same || !lesson.mounted) openPart(lesson.part);
  } else {
    let saved;
    if (pageProgressKey()) try { saved = JSON.parse(localStorage.getItem(pageProgressKey()) || 'null'); } catch {}
    if (data.stream && saved?.run_id === data.stream.run_id && saved?.lesson_version === data.stream.lesson_version) {
      if (data.goals[saved.part]) lesson.part = saved.part;
      void enterWalk(saved.actor === 'replay' ? 'replay' : 'student');
    } else offerStart();
  }
}

function lessonLost() {
  $('#pq-start-note').hidden = true;
  $('#pq-start').hidden = true;
  showNote(LOST);
}

/* practice.css styles bare elements, so it downloads inert (media=print) and applies only once the walk opens. */
function loadPracticeStyles() {
  const link = document.createElement('link');
  link.rel = 'stylesheet';
  link.media = 'print';
  link.href = '/assets/practice/practice.css';
  const loaded = new Promise(resolve => { link.onload = link.onerror = resolve; });
  $('#pq-walk-css').before(link);
  return loaded.then(() => link);
}

let teachingCheck = null;
async function ensureCurrentTeaching() {
  if (!searchId || !lesson.data?.stream) return true;
  if (teachingCheck) return teachingCheck;
  const ticket = liveTicket;
  teachingCheck = (async () => {
    const active = () => !privateStopped && ticket === liveTicket;
    const response = await searchFetch(`/api/search/problems/${searchId}/lesson/current`, {method: 'POST'});
    if (!active()) return false;
    const current = await response.json();
    if (!response.ok && !['lesson.running', 'lesson.stale_run', 'lesson.already_current'].includes(current.detail)) throw Error('暂时无法获取最新解题步骤，请稍后重试。');
    if (!current.updating && response.ok) return true;
    $('#pq-start').hidden = true;
    showNote('<p class="gw-ai-status is-thinking" role="status">正在更新解题步骤…</p>');
    // This upgrades a lesson version, never a live step sequence. The old run
    // remains readable by ID; the new one reuses saved recognition without LLM.
    const deadline = Date.now() + 120000;
    while (active() && Date.now() < deadline) {
      await wait(800);
      const status = await searchFetch(`/api/search/problems/${searchId}`, {cache: 'no-store'});
      if (!active()) return false;
      if (!status.ok) throw Error('暂时无法获取最新解题步骤，请稍后重试。');
      const data = await status.json();
      if (!active()) return false;
      if (data.user_id !== session.user?.id) return false;
      if (!data.lesson) throw Error('暂时无法获取解题步骤，请重新打开题目。');
      if (lessonNeedsPolling(data.lesson)) continue;
      if (data.lesson.execution_status !== 'completed') throw Error('解题步骤更新未完成，请稍后重试。');
      lesson.data = data.lesson;
      return true;
    }
    if (active()) throw Error('解题步骤仍在更新，请稍后重新打开题目。');
    return false;
  })();
  try { return await teachingCheck; }
  finally { teachingCheck = null; }
}

let enteringWalk = false;
async function enterWalk(actor) {
  const ticket = liveTicket;
  if (privateStopped) return;
  if (lesson.opened || enteringWalk) return;
  enteringWalk = true;
  try {
    if (!await ensureCurrentTeaching()) return;
  } catch (error) {
    if (!privateStopped && ticket === liveTicket) { offerStart(); toast(error.message); }
    return;
  } finally { enteringWalk = false; }
  if (privateStopped || ticket !== liveTicket) return;
  lesson.actor = actor;
  lesson.opened = true;
  // Switch only with styles and engine in hand, so the first walk frame already has its final layout.
  const [engine, styles] = await Promise.all([import(WALK), loadPracticeStyles()]);
  if (privateStopped || ticket !== liveTicket) return;
  lesson.engine = engine;
  const swap = () => {
    if (privateStopped || ticket !== liveTicket) return;
    styles.media = 'all';
    document.body.classList.add('gw-page');
    document.body.dataset.actor = actor;
    // revealGraph opens the graph column once a step is confirmed; until then the steps stay centred.
    document.body.dataset.graph = 'hidden';
    const card = $('.pq-card');
    card.classList.add('problem-card');
    $('.gw-lesson').prepend(card);
    $('#gw-main').insertBefore($('#pq-parts'), $('#gw-ready'));
    $('#main').hidden = true;
    $('#gw-main').hidden = false;
    $('#gw-ready').hidden = false;
    window.scrollTo(0, 0);
  };
  if (document.startViewTransition && !matchMedia('(prefers-reduced-motion: reduce)').matches) {
    await document.startViewTransition(swap).updateCallbackDone;
  } else swap();
  if (privateStopped || ticket !== liveTicket) return;
  if (lesson.data) openPart(lesson.part);
  else showNote($('#pq-start-note').hidden ? noteHtml(null) : WAITING);
}

async function openPart(index) {
  if (privateStopped) return;
  const ticket = ++partTicket;
  lesson.part = index;
  renderMeaning();
  markPartTabs();
  const goal = goals()[index];
  if (questionFigures && figureRenderer) {
    renderInlineFigures(goal?.target_ref || null);
  }
  if (!lesson.engine) return;
  if (!goal?.walk) { showNote(noteHtml(goal)); return; }
  delete document.body.dataset.part;
  // The first bundle opens on the chosen actor; later ones keep whatever the student switched to.
  const actor = lesson.mounted ? lesson.engine.walkActor() : lesson.actor;
  lesson.mounted = true;
  await prepareStream();
  if (ticket !== partTicket) return;
  const stream = lesson.data.stream ? {...streamMount.consumer.view(), target_ref: goal.target_ref} : null;
  $('#pq-stream').hidden = true;
  await lesson.engine.mountWalk({bundle: goal.walk.bundle, replay: goal.walk.replay, actor,
    figureManifest: questionFigures, figureSearchId: searchId,
    revealGraph: true, practicePage: null, stream, onState: view => { if (ticket === partTicket) savePageProgress(view); },
    progressScope: searchId ? progressScope() : null, fetch: searchId ? searchFetch : undefined});
  if (ticket !== partTicket) return;
  if (stream) { streamProjection = ''; updateStreamView(streamMount.consumer.view()); savePageProgress(lesson.engine.walkView()); }
}

async function retryLesson() {
  if (privateStopped || lessonRetryPending || lessonRetryAccepted || !session.user) return;
  if (!searchId) return toast('原型不能重试');
  const ticket = liveTicket;
  const owner = session.user.id;
  if (lessonRetryIntent?.owner !== owner) lessonRetryIntent = {owner, id: crypto.randomUUID()};
  const active = () => !privateStopped && ticket === liveTicket && session.user?.id === owner;
  lessonRetryPending = true;
  for (const button of document.querySelectorAll('[data-lesson-retry]')) button.disabled = true;
  try {
    const response = await searchFetch(`/api/search/problems/${searchId}/lesson`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({client_request_id: lessonRetryIntent.id}),
    });
    if (!active()) return;
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      if (!active()) return;
      if (body?.detail === 'search.request_retired') lessonRetryIntent = null;
      return toast(window.SearchErrors.message(body?.detail, '重试失败，请稍后再试'));
    }
    lessonRetryAccepted = true;
    resumeLesson();
  } catch {
    if (active()) toast('重试失败，请稍后再试');
  } finally {
    if (active()) {
      lessonRetryPending = false;
      for (const button of document.querySelectorAll('[data-lesson-retry]')) button.disabled = lessonRetryAccepted;
    }
  }
}

async function continueCalculation() {
  const descriptor = lesson.data?.stream;
  if (!searchId || privateStopped) return;
  const ticket = liveTicket;
  const action = $('#pq-stream-action'); action.disabled = true;
  const url = descriptor ? descriptor.snapshot_url.replace(/\/snapshot$/, '/resume') : `/api/search/problems/${searchId}/lesson/start`;
  try {
    const response = await searchFetch(url, {method: 'POST'});
    if (privateStopped || ticket !== liveTicket) return;
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      if (privateStopped || ticket !== liveTicket) return;
      return toast(window.SearchErrors.message(body?.detail, '暂时无法继续计算，请稍后重试'));
    }
    action.hidden = true;
    void pollLesson();
    await streamTransport?.refresh();
  } catch { if (!privateStopped && ticket === liveTicket) toast('暂时无法继续计算，请稍后重试'); }
  finally { if (!privateStopped && ticket === liveTicket) action.disabled = false; }
}

const LESSON_MISSES = 10;
const LESSON_STATUS_POLL_MS = 3000;
let lessonPoll = 0;
const lessonNeedsPolling = data => data.status === 'running' || ['starting', 'running'].includes(data.execution_status);

async function pollLesson() {
  if (privateStopped) return;
  const ticket = ++lessonPoll;
  let hasStream = Boolean(lesson.data?.stream);
  // A quiet event stream cannot report a worker that died before its final
  // commit. Keep monitoring execution metadata without remounting its cards.
  for (let misses = 0; misses < LESSON_MISSES || hasStream;) {
    await wait(hasStream ? LESSON_STATUS_POLL_MS : 800);
    if (ticket !== lessonPoll) return;
    const response = await searchFetch(`/api/search/problems/${searchId}`, {cache: 'no-store'}).catch(() => null);
    const status = response?.ok ? await response.json().catch(() => null) : null;
    if (ticket !== lessonPoll) return;
    if (response?.status === 404) { unavailable('这条拍题记录不存在或已删除。'); return; }
    if (status && ['expired', 'disabled', 'unavailable'].includes(status.outcome)) { unavailableStatus(status); return; }
    if (!status) { misses += 1; continue; }
    if (status.user_id !== session.user?.id) { unavailable('账号状态已变更，请重新打开这道题。'); return; }
    misses = 0;
    if (status.lesson && (status.lesson.status !== 'running' || status.lesson.goals?.length)) {
      showLesson(status.lesson);
      hasStream = Boolean(status.lesson.stream);
      if (lessonNeedsPolling(status.lesson)) continue;
      return;
    }
  }
  lessonLost();
}

function resumeLesson() {
  if (privateStopped) return;
  if (!lesson.data?.stream) showLesson({status: 'running'});
  pollLesson();
}

/* ---------- 原型 ---------- */
async function runDemo() {
  setPhotos((params.has('fresh') && sessionStorage.getItem('sq-image')) || scenario.sample);
  const items = phaseItems();
  items[0].dataset.state = 'doing';
  if (params.get('hold') === '0') return;
  await wait(scenario.extract);
  if (!scenario.review) { items[0].dataset.state = 'stop'; await wait(500); return showFail(scenario.fail); }
  items[0].dataset.state = 'done';
  showProblem(scenario.preview || scenario.text, scenario.parts || [], scenario.previewRoot || scenario.root);
  setVerify('checking');
  if (params.get('hold') === '1') return;
  await wait(scenario.review);
  if (scenario.fail) return withdraw(scenario.fail);
  settle(scenario.text, scenario.parts || [], scenario.root);
  if (!scenario.lesson) return;
  showLesson({status: 'running'});
  const [data] = await Promise.all([fetch(scenario.lesson).then(r => r.json()), wait(1800)]);
  showLesson(data);
}

/* ---------- 实时：本地 /api/search ---------- */
let liveCrop = null;
let pollLost = false;

/* Lost polling: the run may still be going, so reload and keep polling the same search.
   A run that ended in failure never reruns, so submit the same page crop as a new search. */
async function retry() {
  if (privateStopped || retryPending || !session.user) return;
  if (pollLost || !liveCrop) return location.reload();
  const ticket = liveTicket;
  const owner = session.user.id;
  const active = () => !privateStopped && ticket === liveTicket && session.user?.id === owner;
  const button = $('[data-retry]');
  retryPending = true;
  button.disabled = true;
  try {
    retryRequestId ||= crypto.randomUUID();
    const response = await searchFetch('/api/search/problems', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({page_id: liveCrop.page_id, box: liveCrop.box, client_request_id: retryRequestId}),
    });
    const body = await response.json().catch(() => ({}));
    if (!active()) return;
    if (response.ok) { location.href = `problem.html?search=${body.search_id}`; return; }
    if (body.detail === 'search.request_retired') retryRequestId = null;
    toast(window.SearchErrors.message(body.detail, '重试失败，请稍后再试'));
  } catch {
    if (active()) toast('重试失败，请稍后再试');
  } finally {
    if (active()) { retryPending = false; button.disabled = false; }
  }
}

async function runLive() {
  if (privateStopped) return;
  const ticket = ++liveTicket;
  const items = phaseItems();
  items[0].dataset.state = 'doing';
  let status;
  let misses = 0;
  let photosVersion = null;
  for (;;) {
    try {
      const response = await searchFetch(`/api/search/problems/${searchId}`, {cache: 'no-store'});
      if (ticket !== liveTicket || privateStopped) return;
      if (response.status === 404) { unavailable('这条拍题记录不存在或已删除。'); return; }
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      status = await response.json();
      if (ticket !== liveTicket || privateStopped) return;
      if (!status.user_id || status.user_id !== session.user?.id) { unavailable('登录状态无法确认，请返回后重新打开。'); return; }
      progressOwner = status.user_id;
      if (['expired', 'disabled', 'unavailable'].includes(status.outcome)) { unavailableStatus(status); return; }
      const figureVersion = status.figures?.content_id || status.figure_error || 'legacy';
      if (photosVersion !== figureVersion) {
        await showQuestionFigures(status, () => ticket === liveTicket && !privateStopped && status.user_id === session.user?.id);
        if (ticket !== liveTicket || privateStopped) return;
        photosVersion = figureVersion;
      }
      liveCrop = status.crop || liveCrop;
      misses = 0;
    } catch (error) {
      if (ticket !== liveTicket || privateStopped || error.name === 'AbortError') return;
      if (++misses < 5) { await wait(1500); continue; }
      pollLost = true;
      status = {state: 'done', outcome: 'error', status: `poll: ${error}`};
    }
    const extracted = status.calls?.some(call => call.stage === 'extract' && call.status === 'completed');
    if (extracted && items[0].dataset.state === 'doing') { items[0].dataset.state = 'done'; items[1].dataset.state = 'doing'; }
    if (status.preview?.original_text) {
      const first = shown.text === null;
      if (showProblem(status.preview.original_text, status.preview.parts, status.preview.root)) shown.fixed = true;
      if (first) { setVerify('checking'); shown.previewAt = performance.now(); }
    }
    if (status.state === 'done') break;
    await wait(800);
    if (ticket !== liveTicket || privateStopped) return;
  }
  if (status.outcome !== 'ok') {
    if ($('#pq-result').hidden) {
      const stopAt = items.findIndex(item => item.dataset.state === 'doing');
      items[Math.max(0, stopAt)].dataset.state = 'stop';
      await wait(500);
      if (ticket !== liveTicket || privateStopped) return;
    }
    const fail = {...FAILS[status.outcome] || FAILS.error};
    if (status.error_code === 'identity.unrepresented_figure') Object.assign(fail, {
      title: '图像题暂未完整识别', text: '题目中的图形还没有核对完成，暂时不能开始解题。', actions: ['other'],
    });
    if (['identity.incomplete_choices', 'identity.incomplete_problem'].includes(status.error_code)) Object.assign(fail, {
      ...FAILS.figure, title: status.error_code === 'identity.incomplete_choices' ? '选项尚未确认完整' : '题目尚未确认完整',
    });
    const finding = status.outcome === 'unclear' && (status.findings?.find(f => ['unreadable', 'ambiguous'].includes(f.kind)) || status.findings?.[0]);
    fail.quote = finding ? (finding.source_excerpt ? `“${finding.source_excerpt}”：${finding.message}` : finding.message) : null;
    withdraw(fail);
    showFailedFigures();
    devCheck(status, '#pq-fail');
    return;
  }
  if (shown.text === null) {
    for (const item of items) item.dataset.state = 'done';
    await wait(300);
    if (ticket !== liveTicket || privateStopped) return;
  }
  settle(status.original_text || '', status.parts || [], status.root);
  devCheck(status, '#pq-result');
  if (status.lesson) {
    showLesson(status.lesson);
    if (lessonNeedsPolling(status.lesson)) pollLesson();
  }
}

/* Developer panel: proves which image reached stage one and what came back. */
function devCheck(status, container) {
  if (!['localhost', '127.0.0.1', '[::1]'].includes(location.hostname)) return;
  const check = status.image_check;
  const short = hash => (hash || '').slice(0, 12);
  const shownAfter = shown.previewAt ? `${((shown.previewAt - started) / 1000).toFixed(1)} 秒（复核前）` : '复核后才展示';
  const rows = [
    ['阶段① 状态', status.status || '—'],
    ['图片核对', check ? `${check.verified ? '✓ 一致' : '✗ 不一致'}：预处理图 ${short(check.question_sha256)}${check.original_sha256 ? ` · 原裁图 ${short(check.original_sha256)}` : ''} · 送入模型 ${check.sent_image_sha256.map(short).join(', ') || '无'}` : '—'],
    ['裁剪', status.crop ? `${status.crop.crop_size.join('×')} px · ${Math.round((status.crop.bytes || 0) / 1024)} KB，框 ${status.crop.box.map(v => v.toFixed(3)).join(', ')}` : '—'],
    ['模型调用', (status.calls || []).map(call => `${call.stage}:${call.status}`).join(' → ') || '—'],
    ['特征', status.features ? `${status.features.length} 项 · ${[...new Set(status.features.map(f => f.feature_id))].join('、')}` : '—'],
    ['原题展示', shownAfter],
    ['阶段① 耗时', status.elapsed_seconds ? `${status.elapsed_seconds} 秒` : '—'],
  ];
  if (status.findings?.length) rows.push(['复核发现', status.findings.map(f => `${f.kind}：${f.message}`).join('；')]);
  const panel = document.createElement('details');
  panel.className = 'pq-devcheck';
  panel.open = true;
  panel.innerHTML = `<summary>开发核对（只在本地出现）</summary><dl>${rows.map(([k, v]) => `<dt>${k}</dt><dd>${escape(String(v))}</dd>`).join('')}</dl>`;
  $(container).append(panel);
}

const ACTIONS = {
  retake: '<a class="sq-primary" href="./">重新拍照</a>',
  retry: '<button type="button" class="sq-primary" data-retry>重试</button>',
  other: '<a class="sq-primary" href="./">换一道题</a>',
  demo: '<a class="sq-ghost" href="/lab/graph-walk/quadratic-always-q01/">看能学的题</a>',
};

function showFail(fail) {
  $('#pq-scan').hidden = true;
  $('#pq-fail').hidden = false;
  $('#pq-fail-icon').textContent = fail.icon;
  if (fail.tone) $('#pq-fail-icon').dataset.tone = fail.tone;
  $('#pq-fail-title').textContent = fail.title;
  $('#pq-fail-text').textContent = fail.text;
  if (fail.quote) { $('#pq-fail-quote').hidden = false; $('#pq-fail-quote').textContent = fail.quote; renderMath($('#pq-fail-quote')); }
  $('#pq-fail-actions').innerHTML = fail.actions
    .map((action, index) => index ? ACTIONS[action].replace('sq-primary', 'sq-ghost') : ACTIONS[action])
    .join('');
}

function stopPrivateLesson() {
  privateStopped = true;
  liveTicket++; lessonPoll++; streamTicket++; partTicket++;
  streamTransport?.stop(); streamMount?.stop();
  lesson.engine?.disposeWalk();
  disposeQuestionFigures(); disposeFailedFigures(); questionFigures = null;
  $('#pq-figures').hidden = true; $('#pq-fail-figures').hidden = true;
  lesson.data = null;
  lesson.teaching = null;
  shown.text = null; shown.parts = []; shown.root = null;
  liveCrop = null;
  retryRequestId = null;
  retryPending = false;
  lessonRetryIntent = null;
  lessonRetryPending = false;
  lessonRetryAccepted = false;
  progressOwner = null;
  for (const selector of ['#pq-photo', '#pq-thumb-img', '#pq-fail-img', '#pq-viewer-img']) $(selector)?.removeAttribute('src');
  for (const selector of ['#pq-text', '#pq-meaning-body', '#pq-lesson', '#pq-fail-quote', '#gw-steps', '#pq-stream', '#gw-ready']) $(selector)?.replaceChildren();
  for (const selector of ['#pq-result', '#pq-scan', '#gw-main']) $(selector).hidden = true;
  $('#pq-viewer').close();
}

function unavailable(message) {
  stopPrivateLesson();
  $('.pq-fail-photo').hidden = true;
  $('#main').hidden = false;
  showFail({icon: '!', title: '暂时无法打开这道题', text: message, actions: ['retake']});
}

function unavailableStatus(status) {
  const message = status.outcome === 'disabled' ? '题目已下线，请重新拍摄。'
    : status.outcome === 'unavailable' ? '课程文件或运行记录不可用，无法继续学习。请重新拍摄。'
      : '原图已到期清除。解析已随原图到期清除，重新拍摄可再次学习。';
  unavailable(message);
  if (status.statement) {
    $('#pq-fail-quote').textContent = status.statement;
    $('#pq-fail-quote').hidden = false;
    renderMath($('#pq-fail-quote'));
  }
}

async function deleteAndRetake() {
  if (!searchId || !session.user || privateStopped || retakePending) return;
  const userId = session.user.id;
  retakePending = true;
  $('#pq-misread').disabled = true;
  try {
    const detailResponse = await searchFetch(`/api/search/problems/${searchId}`, {cache: 'no-store'});
    if (!detailResponse.ok) throw new Error();
    const detail = await detailResponse.json();
    if (privateStopped || session.user?.id !== userId) return;
    if (detail.user_id !== userId) throw new Error();
    const message = detail.problem_id
      ? '删除你拍过的这道题的全部已关联记录、照片和已可学习课程后重新拍摄？其他题目不受影响，来源整页仍按原 24 小时期限保留。'
      : '删除这条拍题记录和照片后重新拍摄？其他记录不受影响，来源整页仍按原 24 小时期限保留。';
    if (!window.confirm(message) || privateStopped || session.user?.id !== userId) return;
    const response = await searchFetch(`/api/search/problems/${searchId}`, {method: 'DELETE'});
    if (!response.ok) throw new Error();
    const data = await response.json();
    if (privateStopped || session.user?.id !== userId) return;
    stopPrivateLesson();
    session.clearProgress(userId, data.deleted_search_ids);
    location.href = 'camera.html';
  } catch (error) {
    if (!privateStopped && session.user?.id === userId && error.name !== 'AbortError') toast('删除失败，请稍后重试');
  } finally {
    retakePending = false;
    if (!privateStopped) $('#pq-misread').disabled = false;
  }
}

document.addEventListener('DOMContentLoaded', async () => {
  $('#pq-thumb').addEventListener('click', () => $('#pq-viewer').showModal());
  $('#pq-misread').addEventListener('click', deleteAndRetake);
  // Before the walk opens a part button only picks which part opens first.
  $('#pq-parts').addEventListener('click', event => {
    const index = Number(event.target.closest('[data-part]')?.dataset.part ?? -1);
    if (!goals()[index] || index === lesson.part && lesson.opened) return;
    if (lesson.opened) openPart(index); else { lesson.part = index; markPartTabs(); }
  });
  $('#pq-start').addEventListener('click', event => {
    const button = event.target.closest('[data-actor]');
    if (button) enterWalk(button.dataset.actor);
  });
  $('#pq-stream-action').addEventListener('click', continueCalculation);
  document.addEventListener('click', event => {
    if (event.target.closest('[data-retry]')) retry();
    if (event.target.closest('[data-lesson-retry]')) retryLesson();
    if (event.target.closest('[data-lesson-resume]')) resumeLesson();
  });
  if (searchId) {
    $('.sq-proto-note').hidden = true;
    window.addEventListener('pagehide', stopPrivateLesson);
    window.addEventListener('pageshow', event => { if (event.persisted) location.reload(); });
    await session.init((_next, previous) => {
      if (!previous) return;
      stopPrivateLesson();
      location.href = './';
    });
    window.addEventListener('search-records-deleted', event => {
      if (event.detail.user_id === session.user?.id && event.detail.search_ids.includes(searchId)) unavailable('这条拍题记录已删除。');
    });
    try {
      if (!await session.login()) { location.href = './'; return; }
      await runLive();
    } catch { if (!privateStopped) unavailable('登录服务暂不可用，请稍后重试。'); }
  } else {
    $('#pq-misread').hidden = true;
    runDemo();
  }
});
