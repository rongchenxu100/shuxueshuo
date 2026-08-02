function esc(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

const EXAM_SOURCE_PATTERN = /(月考|期中|期末|联考|段考|质量监测|模拟|统考|调研|测试|考试|高考|会考|诊断)/;

export function examSourceLabel(value) {
  const source = String(value ?? "").trim();
  if (!/^20\d{2}\b/.test(source) || !EXAM_SOURCE_PATTERN.test(source)) return "";
  return source;
}

function readMathGroup(source, start) {
  if (source[start] !== "{") return null;
  let depth = 0;
  for (let index = start; index < source.length; index += 1) {
    if (source[index] === "{") depth += 1;
    if (source[index] === "}") depth -= 1;
    if (depth === 0) {
      return { content: source.slice(start + 1, index), end: index + 1 };
    }
  }
  return null;
}

function readMathAtom(source, start) {
  const group = readMathGroup(source, start);
  if (group) return group;
  if (start >= source.length) return null;
  return { content: source[start], end: start + 1 };
}

function renderMathExpression(value) {
  const source = String(value ?? "");
  let markup = "";
  let cursor = 0;
  while (cursor < source.length) {
    if (source.startsWith("\\frac", cursor)) {
      const numerator = readMathAtom(source, cursor + 5);
      const denominator = numerator && readMathAtom(source, numerator.end);
      if (numerator && denominator) {
        markup += '<span class="math-fraction"><span class="math-numerator">' + renderMathExpression(numerator.content) + '</span><span class="math-denominator">' + renderMathExpression(denominator.content) + "</span></span>";
        cursor = denominator.end;
        continue;
      }
    }
    if (source.startsWith("\\sqrt", cursor)) {
      let radicandStart = cursor + 5;
      let rootIndex = "";
      if (source[radicandStart] === "[") {
        const closing = source.indexOf("]", radicandStart + 1);
        if (closing >= 0) {
          rootIndex = source.slice(radicandStart + 1, closing);
          radicandStart = closing + 1;
        }
      }
      const radicand = readMathAtom(source, radicandStart);
      if (radicand) {
        const rootSymbol = rootIndex === "3" ? "∛" : "√";
        markup += '<span class="math-radical"><span class="math-radical-symbol">' + rootSymbol + '</span><span class="math-radicand">' + renderMathExpression(radicand.content) + "</span></span>";
        cursor = radicand.end;
        continue;
      }
    }
    if (source.startsWith("\\mathbb", cursor)) {
      let symbolStart = cursor + 7;
      while (/\s/.test(source[symbolStart] || "")) symbolStart += 1;
      const group = readMathAtom(source, symbolStart);
      if (group) {
        const symbols = { N: "ℕ", Z: "ℤ", Q: "ℚ", R: "ℝ", C: "ℂ" };
        const symbol = symbols[group.content];
        markup += symbol
          ? `<span class="math-blackboard">${symbol}</span>`
          : esc(group.content);
        cursor = group.end;
        continue;
      }
    }
    if (source.startsWith("\\nsubseteq", cursor)) {
      markup += "⊄";
      cursor += "\\nsubseteq".length;
      continue;
    }
    if (source.startsWith("\\subseteq", cursor)) {
      markup += "⊆";
      cursor += "\\subseteq".length;
      continue;
    }
    const symbolCommands = [
      ["\\varnothing", "∅"],
      [
        "\\notin",
        '<span class="math-notin" role="img" aria-label="不属于"><svg viewBox="0 0 18 18" aria-hidden="true" focusable="false"><path d="M15 3H9C5.3 3 3 5.5 3 9s2.3 6 6 6h6M3.7 9h10.8M4.5 16L14 2"/></svg></span>',
      ],
      ["\\middle|", "|"],
      ["\\Delta", "Δ"],
      ["\\ldots", "…"],
      ["\\pi", "π"],
      ["\\cdot", "·"],
      ["\\left", ""],
      ["\\right", ""],
      ["\\not=", "≠"],
      ["\\iff", "⇔"],
      ["\\ne", "≠"],
      ["\\le", "≤"],
      ["\\ge", "≥"],
      ["\\pm", "±"],
      ["\\in", "∈"],
      ["\\mid", "|"],
      ["\\{", "{"],
      ["\\}", "}"],
      ["\\,", ""],
    ];
    const command = symbolCommands.find(([name]) => source.startsWith(name, cursor));
    if (command) {
      markup += command[1];
      cursor += command[0].length;
      continue;
    }
    if (source[cursor] === "_") {
      const group = readMathGroup(source, cursor + 1);
      if (group) {
        markup += "<sub>" + renderMathExpression(group.content) + "</sub>";
        cursor = group.end;
        continue;
      }
      if (/[A-Za-z0-9]/.test(source[cursor + 1] || "")) {
        markup += "<sub>" + esc(source[cursor + 1]) + "</sub>";
        cursor += 2;
        continue;
      }
    }
    if (source[cursor] === "^") {
      const group = readMathGroup(source, cursor + 1);
      if (group) {
        markup += "<sup>" + renderMathExpression(group.content) + "</sup>";
        cursor = group.end;
        continue;
      }
      if (source[cursor + 1] === "(") {
        const closingIndex = source.indexOf(")", cursor + 2);
        if (closingIndex >= 0) {
          markup += "<sup>" + renderMathExpression(source.slice(cursor + 2, closingIndex)) + "</sup>";
          cursor = closingIndex + 1;
          continue;
        }
      }
      const exponent = source.slice(cursor + 1).match(/^[+-]?(?:\d+(?:\.\d+)?|[A-Za-z*])/);
      if (exponent) {
        markup += "<sup>" + esc(exponent[0]) + "</sup>";
        cursor += exponent[0].length + 1;
        continue;
      }
    }
    markup += esc(source[cursor]);
    cursor += 1;
  }
  return markup;
}

export function renderInlineMathText(value) {
  const source = String(value ?? "");
  const pattern = /\\\((.*?)\\\)/g;
  let cursor = 0;
  let markup = "";
  let match;
  while ((match = pattern.exec(source)) !== null) {
    markup += esc(source.slice(cursor, match.index));
    markup += `<span class="inline-math">${renderMathExpression(match[1])}</span>`;
    cursor = match.index + match[0].length;
  }
  return markup + esc(source.slice(cursor));
}

export function renderSetFigure(figure = {}) {
  if (figure.kind === "venn-two") {
    const shade = figure.shade === "A-only" ? "A-only" : "B-only";
    const maskId = shade === "A-only" ? "venn-a-minus-b-mask" : "venn-b-minus-a-mask";
    const includedCircle = shade === "A-only"
      ? '<circle cx="213" cy="120" r="76" fill="white"/>'
      : '<circle cx="267" cy="120" r="76" fill="white"/>';
    const excludedCircle = shade === "A-only"
      ? '<circle cx="267" cy="120" r="76" fill="black"/>'
      : '<circle cx="213" cy="120" r="76" fill="black"/>';
    return `
      <figure class="set-figure">
        <svg viewBox="0 0 480 250" role="img" aria-label="${esc(figure.ariaLabel || "两个集合的 Venn 图")}">
          <defs>
            <mask id="${maskId}" maskUnits="userSpaceOnUse" x="0" y="0" width="480" height="250">
              <rect x="0" y="0" width="480" height="250" fill="black"/>
              ${includedCircle}
              ${excludedCircle}
            </mask>
          </defs>
          <rect class="set-figure-universe" x="34" y="22" width="412" height="202" rx="4"/>
          <rect class="set-figure-shade" x="0" y="0" width="480" height="250" mask="url(#${maskId})"/>
          <circle class="set-figure-set" cx="213" cy="120" r="76"/>
          <circle class="set-figure-set" cx="267" cy="120" r="76"/>
          <text x="192" y="205">A</text>
          <text x="285" y="205">B</text>
          <text x="414" y="48">U</text>
        </svg>
        ${figure.caption ? `<figcaption>${esc(figure.caption)}</figcaption>` : ""}
      </figure>
    `;
  }
  if (figure.kind === "venn-classification") {
    return `
      <figure class="set-figure is-classification">
        <svg viewBox="0 0 600 330" role="img" aria-label="${esc(figure.ariaLabel || "四边形分类的 Venn 图")}">
          <rect class="set-figure-universe" x="34" y="24" width="532" height="270" rx="4"/>
          <ellipse class="set-figure-set" cx="300" cy="150" rx="190" ry="112"/>
          <ellipse class="set-figure-set" cx="250" cy="142" rx="92" ry="72"/>
          <ellipse class="set-figure-set" cx="350" cy="142" rx="92" ry="72"/>
          <text x="48" y="278">四边形</text>
          <text x="214" y="251">平行四边形</text>
          <text x="190" y="148">菱形</text>
          <text x="378" y="148">矩形</text>
          <text x="270" y="148">正方形</text>
        </svg>
        ${figure.caption ? `<figcaption>${esc(figure.caption)}</figcaption>` : ""}
      </figure>
    `;
  }
  return "";
}

function plainMathText(value) {
  return String(value ?? "")
    .replace(/\\\((.*?)\\\)/g, "$1")
    .replace(/\\(?:frac|sqrt)\b/g, "")
    .replace(/[{}\\]/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

export function splitChoiceText(value) {
  const source = String(value ?? "");
  const optionPattern = /(?:^|[\s　])([A-D])\.\s*/g;
  const matches = [];
  let match;

  while ((match = optionPattern.exec(source)) !== null) {
    matches.push({
      index: match.index + (match[0].length - match[0].trimStart().length),
      label: match[1],
      contentStart: optionPattern.lastIndex,
    });
  }

  if (matches.length !== 4 || matches.map((item) => item.label).join("") !== "ABCD") {
    return null;
  }

  const options = matches.map((item, index) => ({
    label: item.label,
    text: source.slice(
      item.contentStart,
      index + 1 < matches.length ? matches[index + 1].index : source.length,
    ).trim(),
  }));
  const lengths = options.map((option) => plainMathText(option.text).length);

  return {
    stem: source.slice(0, matches[0].index).trim(),
    options,
    stacked: Math.max(...lengths) > 12 || lengths.reduce((sum, length) => sum + length, 0) > 48,
  };
}

export function buildKeyPointsHtml(keyPoints) {
  if (!keyPoints || !Array.isArray(keyPoints.items) || keyPoints.items.length === 0) return "";
  const title = keyPoints.title || "解题要点";
  const lead = keyPoints.lead
    ? `<p class="lesson-key-points-lead">${renderInlineMathText(keyPoints.lead)}</p>`
    : "";
  const items = keyPoints.items
    .map((item) => `<li>${renderInlineMathText(item)}</li>`)
    .join("");
  return `<aside class="lesson-key-points" aria-label="${esc(title)}"><div class="lesson-key-points-title">${esc(title)}</div><div class="lesson-key-points-content">${lead}<ol>${items}</ol></div></aside>`;
}
