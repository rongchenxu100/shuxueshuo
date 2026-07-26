function esc(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
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

function renderMathExpression(value) {
  const source = String(value ?? "");
  let markup = "";
  let cursor = 0;
  while (cursor < source.length) {
    if (source.startsWith("\\frac", cursor)) {
      const numerator = readMathGroup(source, cursor + 5);
      const denominator = numerator && readMathGroup(source, numerator.end);
      if (numerator && denominator) {
        markup += '<span class="math-fraction"><span class="math-numerator">' + renderMathExpression(numerator.content) + '</span><span class="math-denominator">' + renderMathExpression(denominator.content) + "</span></span>";
        cursor = denominator.end;
        continue;
      }
    }
    if (source.startsWith("\\sqrt", cursor)) {
      const radicand = readMathGroup(source, cursor + 5);
      if (radicand) {
        markup += '<span class="math-radical"><span class="math-radical-symbol">√</span><span class="math-radicand">' + renderMathExpression(radicand.content) + "</span></span>";
        cursor = radicand.end;
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
      const exponent = source.slice(cursor + 1).match(/^[+-]?(?:\d+(?:\.\d+)?|[A-Za-z])/);
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
