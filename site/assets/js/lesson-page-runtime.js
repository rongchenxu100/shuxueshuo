/**
 * 互动题页公共运行时：步骤导航、滑块、缩略图、题目折叠、IntersectionObserver。
 * 题页在定义 STEPS / POLICIES / STEP_LABELS、diagramMarkupFor、drawMini 后调用
 * LessonPageRuntime.init({ ... })。
 *
 * 暴露：window.LessonPageRuntime
 */
(function (global) {
  "use strict";

  function esc(s) {
    return String(s)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;");
  }

  function readMathGroup(source, start) {
    if (source[start] !== "{") return null;
    let depth = 0;
    for (let index = start; index < source.length; index += 1) {
      if (source[index] === "{") depth += 1;
      if (source[index] === "}") depth -= 1;
      if (depth === 0) return { content: source.slice(start + 1, index), end: index + 1 };
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
    const source = String(value != null ? value : "");
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
            ? '<span class="math-blackboard">' + symbol + "</span>"
            : esc(group.content);
          cursor = group.end;
          continue;
        }
      }
      if (source.startsWith("\\text", cursor)) {
        const group = readMathAtom(source, cursor + "\\text".length);
        if (group) {
          markup += esc(group.content);
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
      if (source.startsWith("\\subsetneq", cursor)) {
        markup += "⊊";
        cursor += "\\subsetneq".length;
        continue;
      }
      if (source.startsWith("\\supsetneq", cursor)) {
        markup += "⊋";
        cursor += "\\supsetneq".length;
        continue;
      }
      if (source.startsWith("\\supseteq", cursor)) {
        markup += "⊇";
        cursor += "\\supseteq".length;
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
        ["\\infty", "∞"],
        ["\\in", "∈"],
        ["\\cap", "∩"],
        ["\\cup", "∪"],
        ["\\setminus", "∖"],
        ["\\mid", "|"],
        ["\\{", "{"],
        ["\\}", "}"],
        ["\\,", ""],
      ];
      const command = symbolCommands.find(function (item) {
        return source.startsWith(item[0], cursor);
      });
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

  function renderExponentText(value) {
    const source = String(value != null ? value : "");
    const exponentPattern = /e\^\(([^()]*)\)/g;
    let cursor = 0;
    let markup = "";
    let match;

    while ((match = exponentPattern.exec(source)) !== null) {
      markup += esc(source.slice(cursor, match.index));
      markup +=
        '<span class="derive-inline-power">e<sup>' +
        esc(match[1]) +
        "</sup></span>";
      cursor = match.index + match[0].length;
    }

    return markup + esc(source.slice(cursor));
  }

  function renderFormulaText(value) {
    const source = String(value != null ? value : "");
    const inlineMathPattern = /\\\((.*?)\\\)/g;
    let cursor = 0;
    let markup = "";
    let match;

    while ((match = inlineMathPattern.exec(source)) !== null) {
      markup += renderExponentText(source.slice(cursor, match.index));
      markup += '<span class="inline-math">' + renderMathExpression(match[1]) + "</span>";
      cursor = match.index + match[0].length;
    }

    return markup + renderExponentText(source.slice(cursor));
  }

  function stepHasDiagram(step) {
    return !step || step.showDiagram !== false;
  }

  function withoutStepWords(value) {
    return String(value != null ? value : "")
      .replace(/第\s*\d+\s*步\s*[：:]\s*/g, "")
      .trim();
  }

  function clamp(v, min, max) {
    return Math.max(min, Math.min(max, v));
  }

  function defaultFmt(v, precision) {
    const p = precision ?? 3;
    return Number(v)
      .toFixed(p)
      .replace(/\.?0+$/, "")
      .replace(/\.$/, "");
  }

  /**
   * @param {{ value: number, display: string }[]} landmarks
   * @param {number} [epsilon]
   * @param {number} [precision]
   */
  function createFmtFromLandmarks(landmarks, epsilon, precision) {
    const eps = epsilon ?? 0.004;
    if (!landmarks || !landmarks.length) {
      return function fmt(v) {
        return defaultFmt(v, precision);
      };
    }
    return function fmt(v) {
      const n = Number(v);
      for (let i = 0; i < landmarks.length; i += 1) {
        const item = landmarks[i];
        if (Math.abs(n - Number(item.value)) < eps) return String(item.display);
      }
      return defaultFmt(v, precision);
    };
  }

  function isMiniItemActive(item, activeT, miniEpsilon, rangeEpsilon) {
    const eps = rangeEpsilon ?? 0.0001;
    if (item.range && Array.isArray(item.range) && item.range.length >= 2) {
      const lo = Number(item.range[0]);
      const hi = Number(item.range[1]);
      const openLeft = Boolean(item.openLeft);
      const leftOk = openLeft ? activeT > lo + eps : activeT >= lo - eps;
      return leftOk && activeT <= hi + eps;
    }
    return Math.abs(activeT - Number(item.t)) < (miniEpsilon ?? 0.03);
  }

  function init(config) {
    const STEPS = config.steps || config.STEPS;
    const POLICIES = config.policies || config.POLICIES;
    const STEP_LABELS = config.stepLabels || config.STEP_LABELS;
    const diagramMarkupFor = config.diagramMarkupFor;
    const diagramMarkupForFrame = config.diagramMarkupForFrame || function (index, frame, activeT, localVars) {
      return diagramMarkupFor(index, activeT, Object.assign({}, localVars || {}));
    };
    const drawMini = config.drawMini;
    const groupTitle = typeof config.groupTitle === "function" ? config.groupTitle : null;
    const legendHtml = config.legendHtml ?? config.legendHTML ?? "";
    const sliderLabel = config.sliderLabel ?? "P 点 · t＝OP";
    const paramPrefix = config.paramLabelPrefix ?? "t=";
    const miniEpsilon = config.miniEpsilon ?? 0.03;
    const rangeEpsilon = config.rangeEpsilon ?? 0.0001;
    const viewBoxW = config.viewBoxWidth ?? 1080;
    const viewBoxH = config.viewBoxHeight ?? 760;
    const policyStepKey = config.policyStepKey ?? "id";
    const stepRangeStep = config.stepRangeStep ?? 0.001;
    const goToProblemMode = config.goToProblemMode ?? "doubleScroll";

    let fmt = config.fmt;
    if (typeof fmt !== "function") {
      fmt = createFmtFromLandmarks(config.paramLandmarks, config.paramLandmarkEpsilon, config.paramPrecision);
    }

    function paramLabelFor(index, value, localVars) {
      const baseLabel = paramPrefix + fmt(value);
      if (typeof config.paramLabelFormatter !== "function") return baseLabel;
      return String(config.paramLabelFormatter(index, value, localVars, baseLabel));
    }

    const stepCards = document.getElementById("stepCards");
    const stepNav = document.getElementById("stepNav");
    const mobileStepNav = document.getElementById("mobileStepNav");
    const problemCard = document.getElementById("problemCard");
    const problemToggle = document.getElementById("problemToggle");
    const railProgressText = document.getElementById("railProgressText");
    const railProgressFill = document.getElementById("railProgressFill");
    const mobileStepSheet = document.getElementById("mobileStepSheet");
    const mobileStepToggle = document.getElementById("mobileStepToggle");
    const mobileStepClose = document.getElementById("mobileStepClose");
    const mobileStepCount = document.getElementById("mobileStepCount");
    const mobileStepName = document.getElementById("mobileStepName");

    if (!stepCards || !stepNav || !STEPS || !POLICIES || !STEP_LABELS) {
      console.warn("LessonPageRuntime.init: missing DOM or STEPS/POLICIES/STEP_LABELS");
      return null;
    }

    let stepIndex = 0;
    let problemUserPreference = null;
    let stepObserver = null;
    const localVarsByStep = {};
    let animationState = null;
    let animationScrollLock = null;

    function defaultGroupTitle(section) {
      return section;
    }

    function renderStepNavMarkup() {
      const problemEntry =
        '<div class="step-group step-group-problem"><div class="step-group-title">题目</div><div class="step-dots">' +
        '<button class="step-dot" type="button" data-problem-nav="true" title="回到完整原题">原题</button></div></div>';
      const groups = [];
      STEPS.forEach(function (step) {
        let group = groups.find(function (item) {
          return item.section === step.section;
        });
        if (!group) {
          group = { section: step.section, steps: [] };
          groups.push(group);
        }
        group.steps.push(step);
      });
      return (
        problemEntry +
        groups
          .map(function (group) {
            const dots = group.steps
              .map(function (step, localIndex) {
                const index = STEPS.indexOf(step);
                const dot =
                  '<button class="step-dot ' +
                  (index < stepIndex ? "done " : "") +
                  (index === stepIndex ? "active" : "") +
                  '" type="button" data-step="' +
                  index +
                  '" title="' +
                  esc(withoutStepWords(step.title)) +
                  '">' +
                  renderFormulaText(withoutStepWords(STEP_LABELS[step[policyStepKey]])) +
                  "</button>";
                return localIndex === 0 ? dot : '<span class="step-connector"></span>' + dot;
              })
              .join("");
            const title = (groupTitle || defaultGroupTitle)(group.section);
            return (
              '<div class="step-group">' +
              (title ? '<div class="step-group-title">' + esc(title) + "</div>" : "") +
              '<div class="step-dots">' +
              dots +
              "</div></div>"
            );
          })
          .join("")
      );
    }

    function renderStepNav() {
      stepNav.innerHTML = renderStepNavMarkup();
      if (mobileStepNav) mobileStepNav.innerHTML = renderStepNavMarkup();
      if (railProgressText) railProgressText.textContent = stepIndex + 1 + " / " + STEPS.length;
      if (railProgressFill) railProgressFill.style.width = ((stepIndex + 1) / STEPS.length) * 100 + "%";
      if (mobileStepCount)
        mobileStepCount.textContent =
          STEPS[stepIndex].section + " · 步骤 " + (stepIndex + 1) + " / " + STEPS.length;
      if (mobileStepName)
        mobileStepName.innerHTML = renderFormulaText(
          withoutStepWords(STEP_LABELS[STEPS[stepIndex][policyStepKey]]),
        );
    }

    function renderMinisMarkup(step, activeT) {
      if (!step.minis) return "";
      const chips = step.minis
        .map(function (item) {
          const active = isMiniItemActive(item, activeT, miniEpsilon, rangeEpsilon);
          const rangeAttr = item.range ? esc(String(item.range[0]) + "," + String(item.range[1])) : "";
          const openLeftAttr = item.openLeft ? "true" : "";
          return (
            '<button class="mini-jump ' +
            (active ? "active" : "") +
            '" type="button" data-mini-t="' +
            esc(String(item.t)) +
            '"' +
            (rangeAttr ? ' data-mini-range="' + rangeAttr + '"' : "") +
            (openLeftAttr ? ' data-mini-open-left="' + openLeftAttr + '"' : "") +
            ">" +
            renderFormulaText(item.title) +
            "</button>"
          );
        })
        .join("");
      const cards = step.minis
        .map(function (item) {
          const active = isMiniItemActive(item, activeT, miniEpsilon, rangeEpsilon);
          const rangeAttr = item.range ? esc(String(item.range[0]) + "," + String(item.range[1])) : "";
          const openLeftAttr = item.openLeft ? "true" : "";
          return (
            '<div class="mini-card ' +
            (active ? "active" : "") +
            '" role="button" tabindex="0" data-mini-t="' +
            esc(String(item.t)) +
            '" data-mini-card-t="' +
            esc(String(item.t)) +
            '"' +
            (rangeAttr ? ' data-mini-range="' + rangeAttr + '"' : "") +
            (openLeftAttr ? ' data-mini-open-left="' + openLeftAttr + '"' : "") +
            "><h3>" +
            renderFormulaText(item.title) +
            "</h3>" +
            drawMini(item.t, item, step) +
            "<p>" +
            renderFormulaText(item.caption) +
            "</p></div>"
          );
        })
        .join("");
      return (
        '<div class="mini-boundaries"><div class="mini-jump-row">' +
        chips +
        '</div><div class="mini-preview-strip">' +
        cards +
        "</div></div>"
      );
    }

    function localVarsForStep(index, step) {
      if (!localVarsByStep[index]) {
        localVarsByStep[index] = Object.assign({}, (step.localControls && step.localControls.values) || {});
      }
      return localVarsByStep[index];
    }

    function controlValue(sourceValue, control) {
      const scale = control.scale == null ? 1 : Number(control.scale);
      return Number(sourceValue || 0) * scale;
    }

    function formatControlValue(v, control) {
      const precision = control.precision == null ? 3 : Number(control.precision);
      return (control.prefix || "") + defaultFmt(v, precision) + (control.suffix || "");
    }

    function renderLocalControlsMarkup(step, index) {
      const cfg = step.localControls;
      if (!cfg || !Array.isArray(cfg.controls) || !cfg.controls.length) return "";
      const vars = localVarsForStep(index, step);
      const rows = cfg.controls
        .map(function (control, controlIndex) {
          const source = Number(vars[control.var] ?? 0);
          const value = controlValue(source, control);
          const stepAttr = control.step == null ? "0.001" : String(control.step);
          const id = "localControl-" + index + "-" + controlIndex;
          return (
            '<div class="step-slider-row step-point-control">' +
            '<label for="' +
            esc(id) +
            '">' +
            esc(control.label) +
            "</label>" +
            '<input id="' +
            esc(id) +
            '" type="range" min="' +
            esc(String(control.min)) +
            '" max="' +
            esc(String(control.max)) +
            '" step="' +
            esc(stepAttr) +
            '" value="' +
            esc(String(value)) +
            '" data-local-control-step="' +
            index +
            '" data-local-control-index="' +
            controlIndex +
            '" data-local-control-var="' +
            esc(control.var) +
            '" data-local-control-scale="' +
            esc(String(control.scale == null ? 1 : control.scale)) +
            '">' +
            '<span class="step-t-value" data-local-control-label="' +
            index +
            "-" +
            controlIndex +
            '">' +
            esc(formatControlValue(value, control)) +
            "</span></div>"
          );
        })
        .join("");
      return (
        '<div class="step-local-tools step-point-tools" data-local-controls="' +
        index +
        '">' +
        rows +
        (cfg.note ? '<div class="step-local-note">' + esc(cfg.note) + "</div>" : "") +
        "</div>"
      );
    }

    function stepAnimation(step) {
      const animation = step && step.animation;
      if (!animation || animation.mode === "none" || !Array.isArray(animation.beats) || !animation.beats.length) {
        return null;
      }
      return animation;
    }

    function renderAnimationButtonMarkup(step, index) {
      const animation = stepAnimation(step);
      if (!animation) return "";
      const trigger = animation.trigger || {};
      return (
        '<button class="step-animation-button" type="button" data-animation-open="' +
        index +
        '">' +
        esc(trigger.label || "播放演示") +
        "</button>"
      );
    }

    function renderDeriveLine(pair) {
      if (!Array.isArray(pair) || pair.length < 2) return "";
      const ref = pair[2];
      const refMarkup =
        ref && ref.refStep
          ? '<button class="derive-ref" type="button" data-step-ref="' +
            esc(String(ref.refStep)) +
            '" title="' +
            esc(ref.title || "跳转到引用步骤") +
            '">' +
            esc(ref.refLabel || "回看") +
            "</button>"
          : "";
      return (
        '<div class="derive-line"><strong>' +
        renderFormulaText(pair[0]) +
        "</strong>" +
        renderFormulaText(pair[1]) +
        refMarkup +
        "</div>"
      );
    }

    function renderReasoningLine(item) {
      if (!item || !item.text || !new Set(["because", "therefore"]).has(item.kind)) return "";
      const isBecause = item.kind === "because";
      return (
        '<div class="derive-line is-reasoning">' +
        '<span class="derive-logic-symbol' + (isBecause ? "" : " is-result") +
        '" aria-label="' + (isBecause ? "因为" : "所以") + '">' +
        (isBecause ? "∵" : "∴") +
        "</span>" +
        renderFormulaText(item.text) +
        "</div>"
      );
    }

    function renderStepTable(step) {
      const table = step && step.table;
      if (!table || !Array.isArray(table.headers) || !Array.isArray(table.rows)) return "";
      return (
        '<div class="lesson-table-wrap"><table class="lesson-reasoning-table">' +
        (table.caption ? "<caption>" + renderFormulaText(table.caption) + "</caption>" : "") +
        "<thead><tr>" +
        table.headers.map(function (header) {
          return '<th scope="col">' + renderFormulaText(header) + "</th>";
        }).join("") +
        "</tr></thead><tbody>" +
        table.rows.map(function (row) {
          return "<tr>" + row.map(function (cell, index) {
            const tag = index === 0 ? "th" : "td";
            const scope = index === 0 ? ' scope="row"' : "";
            return "<" + tag + scope + ">" + renderFormulaText(cell) + "</" + tag + ">";
          }).join("") + "</tr>";
        }).join("") +
        "</tbody></table></div>"
      );
    }

    function renderStepVisual(step) {
      const visual = step && step.visual;
      if (!visual || !visual.kind) return "";
      const ariaLabel = esc(visual.ariaLabel || "解题示意图");

      if (visual.kind === "number-line-difference") {
        return (
          '<figure class="lesson-step-visual lesson-step-number-line">' +
          '<svg viewBox="0 0 720 260" role="img" aria-label="' + ariaLabel + '">' +
          '<g class="lesson-number-line-axis">' +
          '<line x1="130" y1="62" x2="602" y2="62"/><path d="M602 62l-12-7v14z"/>' +
          '<line x1="130" y1="127" x2="602" y2="127"/><path d="M602 127l-12-7v14z"/>' +
          '<line x1="130" y1="192" x2="602" y2="192"/><path d="M602 192l-12-7v14z"/>' +
          '</g>' +
          '<g class="lesson-number-line-labels"><text x="62" y="68">A</text><text x="62" y="133">B</text><text x="38" y="198">B∖A</text></g>' +
          '<g class="lesson-number-line-segment is-a"><line x1="360" y1="62" x2="550" y2="62"/><circle cx="360" cy="62" r="8"/><circle cx="550" cy="62" r="8"/></g>' +
          '<g class="lesson-number-line-segment is-b"><line x1="170" y1="127" x2="455" y2="127"/><circle cx="170" cy="127" r="8"/><circle class="is-closed" cx="455" cy="127" r="8"/></g>' +
          '<g class="lesson-number-line-segment is-result"><line x1="170" y1="192" x2="360" y2="192"/><circle cx="170" cy="192" r="8"/><circle class="is-closed" cx="360" cy="192" r="8"/></g>' +
          '<g class="lesson-number-line-ticks">' +
          '<line x1="170" y1="184" x2="170" y2="200"/><text x="170" y="232">0</text>' +
          '<line x1="360" y1="184" x2="360" y2="200"/><text x="360" y="232">1</text>' +
          '<line x1="455" y1="184" x2="455" y2="200"/><text x="455" y="232">3/2</text>' +
          '<line x1="550" y1="184" x2="550" y2="200"/><text x="550" y="232">2</text>' +
          '</g></svg><figcaption>逐行比较 A、B 与 B∖A：0 不取，1 取到，所以结果为 (0,1]。</figcaption></figure>'
        );
      }

      if (visual.kind === "number-line-practice-parameter") {
        return (
          '<figure class="lesson-step-visual lesson-step-number-line lesson-step-number-line-parameter">' +
          '<svg viewBox="0 0 720 220" role="img" aria-label="' + ariaLabel + '">' +
          '<g class="lesson-number-line-axis">' +
          '<line x1="92" y1="104" x2="644" y2="104"/><path d="M644 104l-12-7v14z"/>' +
          '</g>' +
          '<g class="lesson-number-line-segment is-result">' +
          '<circle class="is-closed" cx="230" cy="104" r="9"/>' +
          '<line x1="418" y1="104" x2="628" y2="104"/><circle class="is-closed" cx="418" cy="104" r="9"/>' +
          '</g>' +
          '<g class="lesson-number-line-ticks">' +
          '<line x1="230" y1="92" x2="230" y2="116"/><text x="230" y="150">0</text>' +
          '<line x1="418" y1="92" x2="418" y2="116"/><text x="418" y="150">9/8</text>' +
          '<text class="lesson-number-line-set-label" x="360" y="42">{0} ∪ [9/8,+∞)</text>' +
          '</g></svg><figcaption>参数集由孤立点 0 与从 9/8 开始的闭射线组成。</figcaption></figure>'
        );
      }

      if (visual.kind === "number-line-intersection-nonempty") {
        return (
          '<figure class="lesson-step-visual lesson-step-number-line">' +
          '<svg viewBox="0 0 720 280" role="img" aria-label="' + ariaLabel + '">' +
          '<g class="lesson-number-line-axis">' +
          '<line x1="108" y1="76" x2="636" y2="76"/><path d="M636 76l-12-7v14z"/>' +
          '<line x1="108" y1="164" x2="636" y2="164"/><path d="M636 164l-12-7v14z"/>' +
          '</g>' +
          '<g class="lesson-number-line-labels"><text x="54" y="82">A</text><text x="54" y="170">B</text></g>' +
          '<g class="lesson-number-line-segment is-a"><line x1="350" y1="76" x2="620" y2="76"/><circle class="is-closed" cx="350" cy="76" r="9"/></g>' +
          '<g class="lesson-number-line-segment is-b"><line x1="218" y1="164" x2="474" y2="164"/><circle class="is-closed" cx="218" cy="164" r="9"/><circle class="is-closed" cx="474" cy="164" r="9"/></g>' +
          '<g class="lesson-number-line-segment is-result"><line x1="350" y1="208" x2="474" y2="208"/><circle class="is-closed" cx="350" cy="208" r="8"/><circle class="is-closed" cx="474" cy="208" r="8"/></g>' +
          '<g class="lesson-number-line-ticks">' +
          '<line x1="218" y1="154" x2="218" y2="174"/><text x="218" y="196">1/2</text>' +
          '<line x1="350" y1="66" x2="350" y2="86"/><text x="350" y="48">1</text>' +
          '<line x1="474" y1="154" x2="474" y2="174"/><text x="474" y="196">2a−1</text>' +
          '<text class="lesson-number-line-set-label" x="412" y="252">公共部分存在 ⇔ 2a−1 ≥ 1</text>' +
          '</g></svg><figcaption>B 的右端点达到或越过 A 的左端点 1 时，两集合有公共点；临界点 1 两边都取到。</figcaption></figure>'
        );
      }

      if (visual.kind === "number-line-intersection-empty") {
        return (
          '<figure class="lesson-step-visual lesson-step-number-line">' +
          '<svg viewBox="0 0 720 280" role="img" aria-label="' + ariaLabel + '">' +
          '<g class="lesson-number-line-axis">' +
          '<line x1="88" y1="76" x2="642" y2="76"/><path d="M642 76l-12-7v14z"/>' +
          '<line x1="88" y1="164" x2="642" y2="164"/><path d="M642 164l-12-7v14z"/>' +
          '</g>' +
          '<g class="lesson-number-line-labels"><text x="42" y="82">A</text><text x="42" y="170">C</text></g>' +
          '<line x1="350" y1="38" x2="350" y2="206" stroke="currentColor" stroke-dasharray="6 7" opacity=".35"/>' +
          '<g class="lesson-number-line-segment is-a"><line x1="350" y1="76" x2="556" y2="76"/><circle class="is-closed" cx="350" cy="76" r="9"/><circle cx="556" cy="76" r="9"/></g>' +
          '<g class="lesson-number-line-segment is-b"><line x1="104" y1="164" x2="350" y2="164"/><circle cx="350" cy="164" r="9"/></g>' +
          '<g class="lesson-number-line-ticks">' +
          '<line x1="350" y1="66" x2="350" y2="86"/><text x="350" y="48">3</text>' +
          '<line x1="556" y1="66" x2="556" y2="86"/><text x="556" y="48">7</text>' +
          '<text x="350" y="198">2a+1 ≤ 3</text>' +
          '<text class="lesson-number-line-set-label" x="366" y="246">C 的开端点不越过 3，A ∩ C = ∅</text>' +
          '</g></svg><figcaption>等号时 C 的右端点是 3，但 C 不含 3；A 从 3 开始且包含 3，因此两集合仍无交集。</figcaption></figure>'
        );
      }

      if (visual.kind === "number-line-subset-left-branch") {
        return (
          '<figure class="lesson-step-visual lesson-step-number-line">' +
          '<svg viewBox="0 0 720 286" role="img" aria-label="' + ariaLabel + '">' +
          '<g class="lesson-number-line-axis">' +
          '<line x1="88" y1="76" x2="642" y2="76"/><path d="M642 76l-12-7v14z"/>' +
          '<line x1="88" y1="164" x2="642" y2="164"/><path d="M642 164l-12-7v14z"/>' +
          '</g>' +
          '<g class="lesson-number-line-labels"><text x="44" y="82">A</text><text x="44" y="170">B</text></g>' +
          '<g class="lesson-number-line-segment is-a">' +
          '<line x1="102" y1="76" x2="318" y2="76"/><path d="M96 76l14-9v18z" fill="currentColor"/><circle class="is-closed" cx="318" cy="76" r="9"/>' +
          '<line x1="474" y1="76" x2="626" y2="76"/><circle class="is-closed" cx="474" cy="76" r="9"/>' +
          '</g>' +
          '<g class="lesson-number-line-segment is-b"><line x1="170" y1="164" x2="318" y2="164"/><circle class="is-closed" cx="170" cy="164" r="9"/><circle class="is-closed" cx="318" cy="164" r="9"/></g>' +
          '<g class="lesson-number-line-ticks">' +
          '<line x1="318" y1="66" x2="318" y2="86"/><text x="318" y="48">−1</text>' +
          '<line x1="474" y1="66" x2="474" y2="86"/><text x="474" y="48">5</text>' +
          '<text x="170" y="202">2a</text><text x="318" y="202">a+2 ≤ −1</text>' +
          '<text class="lesson-number-line-set-label" x="360" y="252">B 整体落在左支 ⇒ a ≤ −3</text>' +
          '</g></svg><figcaption>非空区间 B 要完整放入左支，只需让 B 的最右端 a+2 不超过 −1。</figcaption></figure>'
        );
      }

      if (visual.kind === "number-line-subset-right-branch") {
        return (
          '<figure class="lesson-step-visual lesson-step-number-line">' +
          '<svg viewBox="0 0 720 286" role="img" aria-label="' + ariaLabel + '">' +
          '<g class="lesson-number-line-axis">' +
          '<line x1="88" y1="76" x2="642" y2="76"/><path d="M642 76l-12-7v14z"/>' +
          '<line x1="88" y1="164" x2="642" y2="164"/><path d="M642 164l-12-7v14z"/>' +
          '</g>' +
          '<g class="lesson-number-line-labels"><text x="44" y="82">A</text><text x="44" y="170">B</text></g>' +
          '<g class="lesson-number-line-segment is-a">' +
          '<line x1="102" y1="76" x2="318" y2="76"/><path d="M96 76l14-9v18z" fill="currentColor"/><circle class="is-closed" cx="318" cy="76" r="9"/>' +
          '<line x1="474" y1="76" x2="626" y2="76"/><circle class="is-closed" cx="474" cy="76" r="9"/>' +
          '</g>' +
          '<g class="lesson-number-line-segment is-b"><line x1="474" y1="164" x2="574" y2="164"/><circle class="is-closed" cx="474" cy="164" r="9"/><circle class="is-closed" cx="574" cy="164" r="9"/></g>' +
          '<g class="lesson-number-line-ticks">' +
          '<line x1="318" y1="66" x2="318" y2="86"/><text x="318" y="48">−1</text>' +
          '<line x1="474" y1="66" x2="474" y2="86"/><text x="474" y="48">5</text>' +
          '<text x="474" y="202">2a ≥ 5</text><text x="574" y="202">a+2</text>' +
          '<text class="lesson-number-line-set-label" x="360" y="252">a ≥ 5/2 与非空条件 a ≤ 2 矛盾</text>' +
          '</g></svg><figcaption>B 若完整放入右支，左端必须不小于 5；但这与 B 非空所需的 a≤2 不能同时成立。</figcaption></figure>'
        );
      }

      if (visual.kind === "number-line-union-open-intervals") {
        return (
          '<figure class="lesson-step-visual lesson-step-number-line">' +
          '<svg viewBox="0 0 720 300" role="img" aria-label="' + ariaLabel + '">' +
          '<g class="lesson-number-line-axis">' +
          '<line x1="100" y1="64" x2="638" y2="64"/><path d="M638 64l-12-7v14z"/>' +
          '<line x1="100" y1="142" x2="638" y2="142"/><path d="M638 142l-12-7v14z"/>' +
          '<line x1="100" y1="220" x2="638" y2="220"/><path d="M638 220l-12-7v14z"/>' +
          '</g>' +
          '<g class="lesson-number-line-labels"><text x="50" y="70">A</text><text x="50" y="148">B</text><text x="40" y="226">A∪B</text></g>' +
          '<g class="lesson-number-line-segment is-a"><line x1="180" y1="64" x2="470" y2="64"/><circle cx="180" cy="64" r="9"/><circle cx="470" cy="64" r="9"/></g>' +
          '<g class="lesson-number-line-segment is-b"><line x1="398" y1="142" x2="544" y2="142"/><circle cx="398" cy="142" r="9"/><circle cx="544" cy="142" r="9"/></g>' +
          '<g class="lesson-number-line-segment is-result"><line x1="180" y1="220" x2="544" y2="220"/><circle cx="180" cy="220" r="9"/><circle cx="544" cy="220" r="9"/></g>' +
          '<g class="lesson-number-line-ticks">' +
          '<text x="180" y="278">−2</text><text x="398" y="278">1</text><text x="470" y="278">2</text><text x="544" y="278">3</text>' +
          '</g></svg><figcaption>A、B 在 (1,2) 重叠，所以并集连成一段；最外侧端点 −2、3 都不取。</figcaption></figure>'
        );
      }

      if (visual.kind === "number-line-complement-in-universe") {
        return (
          '<figure class="lesson-step-visual lesson-step-number-line">' +
          '<svg viewBox="0 0 720 340" role="img" aria-label="' + ariaLabel + '">' +
          '<g class="lesson-number-line-axis">' +
          '<line x1="82" y1="68" x2="642" y2="68"/><path d="M642 68l-12-7v14z"/>' +
          '<line x1="82" y1="156" x2="642" y2="156"/><path d="M642 156l-12-7v14z"/>' +
          '<line x1="82" y1="244" x2="642" y2="244"/><path d="M642 244l-12-7v14z"/>' +
          '</g>' +
          '<g class="lesson-number-line-labels"><text x="42" y="74">U</text><text x="34" y="162">A∪B</text><text x="28" y="250">补集</text></g>' +
          '<g class="lesson-number-line-segment is-a"><line x1="96" y1="68" x2="568" y2="68"/><path d="M90 68l14-9v18z" fill="currentColor"/><circle class="is-closed" cx="568" cy="68" r="9"/></g>' +
          '<g class="lesson-number-line-segment is-b"><line x1="246" y1="156" x2="490" y2="156"/><circle class="is-closed" cx="246" cy="156" r="9"/><circle class="is-closed" cx="490" cy="156" r="9"/></g>' +
          '<g class="lesson-number-line-segment is-result">' +
          '<line x1="96" y1="244" x2="246" y2="244"/><path d="M90 244l14-9v18z" fill="currentColor"/><circle cx="246" cy="244" r="9"/>' +
          '<line x1="490" y1="244" x2="568" y2="244"/><circle cx="490" cy="244" r="9"/><circle class="is-closed" cx="568" cy="244" r="9"/>' +
          '</g>' +
          '<g class="lesson-number-line-ticks"><text x="246" y="306">−1</text><text x="490" y="306">4</text><text x="568" y="306">5</text></g>' +
          '</svg><figcaption>补集只能在全集 U 内取：删去 [−1,4] 后，−1、4 改为空心端点，U 的端点 5 仍保留。</figcaption></figure>'
        );
      }

      if (visual.kind === "number-line-complement-intersection") {
        return (
          '<figure class="lesson-step-visual lesson-step-number-line">' +
          '<svg viewBox="0 0 720 340" role="img" aria-label="' + ariaLabel + '">' +
          '<g class="lesson-number-line-axis">' +
          '<line x1="82" y1="68" x2="642" y2="68"/><path d="M642 68l-12-7v14z"/>' +
          '<line x1="82" y1="156" x2="642" y2="156"/><path d="M642 156l-12-7v14z"/>' +
          '<line x1="82" y1="244" x2="642" y2="244"/><path d="M642 244l-12-7v14z"/>' +
          '</g>' +
          '<g class="lesson-number-line-labels"><text x="30" y="70">C<tspan baseline-shift="sub" font-size="14">ℝ</tspan>A</text><text x="42" y="162">B</text><text x="24" y="250">交集</text></g>' +
          '<g class="lesson-number-line-segment is-a">' +
          '<line x1="96" y1="68" x2="350" y2="68"/><path d="M90 68l14-9v18z" fill="currentColor"/><circle cx="350" cy="68" r="9"/>' +
          '<line x1="430" y1="68" x2="626" y2="68"/><circle cx="430" cy="68" r="9"/>' +
          '</g>' +
          '<g class="lesson-number-line-segment is-b"><line x1="210" y1="156" x2="560" y2="156"/><circle class="is-closed" cx="210" cy="156" r="9"/><circle class="is-closed" cx="560" cy="156" r="9"/></g>' +
          '<g class="lesson-number-line-segment is-result">' +
          '<line x1="210" y1="244" x2="350" y2="244"/><circle class="is-closed" cx="210" cy="244" r="9"/><circle cx="350" cy="244" r="9"/>' +
          '<line x1="430" y1="244" x2="560" y2="244"/><circle cx="430" cy="244" r="9"/><circle class="is-closed" cx="560" cy="244" r="9"/>' +
          '</g>' +
          '<g class="lesson-number-line-ticks"><text x="210" y="306">−1</text><text x="350" y="306">1</text><text x="430" y="306">2</text><text x="560" y="306">4</text></g>' +
          '</svg><figcaption>先在实数集中删去 [1,2]，再限制到 B=[−1,4]；1、2 被删去，−1、4 保留。</figcaption></figure>'
        );
      }

      if (visual.kind === "number-line-parameter-union") {
        return (
          '<figure class="lesson-step-visual lesson-step-number-line">' +
          '<svg viewBox="0 0 720 300" role="img" aria-label="' + ariaLabel + '">' +
          '<g class="lesson-number-line-axis">' +
          '<line x1="100" y1="64" x2="638" y2="64"/><path d="M638 64l-12-7v14z"/>' +
          '<line x1="100" y1="142" x2="638" y2="142"/><path d="M638 142l-12-7v14z"/>' +
          '<line x1="100" y1="220" x2="638" y2="220"/><path d="M638 220l-12-7v14z"/>' +
          '</g>' +
          '<g class="lesson-number-line-labels"><text x="50" y="70">A</text><text x="50" y="148">B</text><text x="40" y="226">A∪B</text></g>' +
          '<g class="lesson-number-line-segment is-a"><line x1="398" y1="64" x2="544" y2="64"/><circle cx="398" cy="64" r="9"/><circle cx="544" cy="64" r="9"/></g>' +
          '<g class="lesson-number-line-segment is-b"><line x1="180" y1="142" x2="470" y2="142"/><circle cx="180" cy="142" r="9"/><circle cx="470" cy="142" r="9"/></g>' +
          '<g class="lesson-number-line-segment is-result"><line x1="180" y1="220" x2="544" y2="220"/><circle cx="180" cy="220" r="9"/><circle cx="544" cy="220" r="9"/></g>' +
          '<g class="lesson-number-line-ticks"><text x="180" y="278">−2</text><text x="398" y="278">1</text><text x="470" y="278">2</text><text x="544" y="278">3</text></g>' +
          '</svg><figcaption>m=−1 时 B=(−2,2)，它与 A=(1,3) 重叠，因此并集从 −2 连续延伸到 3。</figcaption></figure>'
        );
      }

      if (visual.kind === "number-line-parameter-containment") {
        return (
          '<figure class="lesson-step-visual lesson-step-number-line">' +
          '<svg viewBox="0 0 720 300" role="img" aria-label="' + ariaLabel + '">' +
          '<g class="lesson-number-line-axis">' +
          '<line x1="92" y1="86" x2="642" y2="86"/><path d="M642 86l-12-7v14z"/>' +
          '<line x1="92" y1="174" x2="642" y2="174"/><path d="M642 174l-12-7v14z"/>' +
          '</g>' +
          '<g class="lesson-number-line-labels"><text x="48" y="92">A</text><text x="48" y="180">B</text></g>' +
          '<g class="lesson-number-line-segment is-a"><line x1="300" y1="86" x2="480" y2="86"/><circle cx="300" cy="86" r="9"/><circle cx="480" cy="86" r="9"/></g>' +
          '<g class="lesson-number-line-segment is-b"><line x1="180" y1="174" x2="574" y2="174"/><circle cx="180" cy="174" r="9"/><circle cx="574" cy="174" r="9"/></g>' +
          '<g class="lesson-number-line-ticks">' +
          '<text x="180" y="214">2m ≤ 1</text><text x="300" y="54">1</text><text x="480" y="54">3</text><text x="574" y="214">1−m ≥ 3</text>' +
          '<text class="lesson-number-line-set-label" x="377" y="266">A ⊆ B ⇒ m ≤ −2</text>' +
          '</g></svg><figcaption>B 的左端不越过 1、右端不早于 3，才能完整包住 A；开端点相等时仍满足包含。</figcaption></figure>'
        );
      }

      if (visual.kind === "number-line-parameter-disjoint") {
        return (
          '<figure class="lesson-step-visual lesson-step-number-line">' +
          '<svg viewBox="0 0 720 340" role="img" aria-label="' + ariaLabel + '">' +
          '<g class="lesson-number-line-axis">' +
          '<line x1="92" y1="76" x2="642" y2="76"/><path d="M642 76l-12-7v14z"/>' +
          '<line x1="92" y1="164" x2="642" y2="164"/><path d="M642 164l-12-7v14z"/>' +
          '</g>' +
          '<g class="lesson-number-line-labels"><text x="48" y="82">A</text><text x="30" y="170">B非空</text></g>' +
          '<g class="lesson-number-line-segment is-a"><line x1="350" y1="76" x2="520" y2="76"/><circle cx="350" cy="76" r="9"/><circle cx="520" cy="76" r="9"/></g>' +
          '<g class="lesson-number-line-segment is-b"><line x1="180" y1="164" x2="350" y2="164"/><circle cx="180" cy="164" r="9"/><circle cx="350" cy="164" r="9"/></g>' +
          '<g class="lesson-number-line-ticks">' +
          '<text x="180" y="206">2m</text><text x="350" y="44">1</text><text x="350" y="206">1−m ≤ 1</text><text x="520" y="44">3</text>' +
          '<text class="lesson-number-line-set-label" x="360" y="256">非空左置：0 ≤ m &lt; 1/3</text>' +
          '<text class="lesson-number-line-set-label" x="360" y="304">再并入 B=∅ 的 m ≥ 1/3，得到 m ≥ 0</text>' +
          '</g></svg><figcaption>B 非空时停在 A 左侧；B 为空时也自动无交集。两类参数范围取并集。</figcaption></figure>'
        );
      }

      if (visual.kind === "number-line-cover-fixed-interval") {
        return (
          '<figure class="lesson-step-visual lesson-step-number-line">' +
          '<svg viewBox="0 0 720 300" role="img" aria-label="' + ariaLabel + '">' +
          '<g class="lesson-number-line-axis">' +
          '<line x1="92" y1="86" x2="642" y2="86"/><path d="M642 86l-12-7v14z"/>' +
          '<line x1="92" y1="174" x2="642" y2="174"/><path d="M642 174l-12-7v14z"/>' +
          '</g>' +
          '<g class="lesson-number-line-labels"><text x="48" y="92">A</text><text x="48" y="180">B</text></g>' +
          '<g class="lesson-number-line-segment is-a"><line x1="320" y1="86" x2="480" y2="86"/><circle class="is-closed" cx="320" cy="86" r="9"/><circle class="is-closed" cx="480" cy="86" r="9"/></g>' +
          '<g class="lesson-number-line-segment is-b"><line x1="180" y1="174" x2="574" y2="174"/><circle class="is-closed" cx="180" cy="174" r="9"/><circle class="is-closed" cx="574" cy="174" r="9"/></g>' +
          '<g class="lesson-number-line-ticks">' +
          '<text x="180" y="214">a ≤ 0</text><text x="320" y="54">0</text><text x="480" y="54">2</text><text x="574" y="214">3−2a ≥ 2</text>' +
          '<text class="lesson-number-line-set-label" x="377" y="266">A ⊆ B ⇒ a ≤ 0</text>' +
          '</g></svg><figcaption>B 必须覆盖 A=[0,2]：左端不大于 0，右端不小于 2。</figcaption></figure>'
        );
      }

      if (visual.kind === "number-line-not-subset-cases") {
        return (
          '<figure class="lesson-step-visual lesson-step-number-line">' +
          '<svg viewBox="0 0 720 350" role="img" aria-label="' + ariaLabel + '">' +
          '<g class="lesson-number-line-axis">' +
          '<line x1="106" y1="64" x2="642" y2="64"/><path d="M642 64l-12-7v14z"/>' +
          '<line x1="106" y1="150" x2="642" y2="150"/><path d="M642 150l-12-7v14z"/>' +
          '<line x1="106" y1="236" x2="642" y2="236"/><path d="M642 236l-12-7v14z"/>' +
          '</g>' +
          '<g class="lesson-number-line-labels"><text x="58" y="70">A</text><text x="46" y="156">B左越界</text><text x="46" y="242">B右越界</text></g>' +
          '<g class="lesson-number-line-segment is-a"><line x1="300" y1="64" x2="460" y2="64"/><circle class="is-closed" cx="300" cy="64" r="9"/><circle class="is-closed" cx="460" cy="64" r="9"/></g>' +
          '<g class="lesson-number-line-segment is-b"><line x1="190" y1="150" x2="400" y2="150"/><circle class="is-closed" cx="190" cy="150" r="9"/><circle class="is-closed" cx="400" cy="150" r="9"/></g>' +
          '<g class="lesson-number-line-segment is-result"><line x1="360" y1="236" x2="570" y2="236"/><circle class="is-closed" cx="360" cy="236" r="9"/><circle class="is-closed" cx="570" cy="236" r="9"/></g>' +
          '<g class="lesson-number-line-ticks">' +
          '<text x="190" y="190">a &lt; 0</text><text x="300" y="36">0</text><text x="460" y="36">2</text><text x="570" y="276">3−2a &gt; 2</text>' +
          '<text class="lesson-number-line-set-label" x="380" y="324">两种越界条件取并集 ⇒ a &lt; 1/2</text>' +
          '</g></svg><figcaption>先排除空集。B 非空且不是 A 的子集，等价于 B 至少从左端或右端越出 A。</figcaption></figure>'
        );
      }

      if (visual.kind === "number-line-practice-union-overlap") {
        return (
          '<figure class="lesson-step-visual lesson-step-number-line">' +
          '<svg viewBox="0 0 720 310" role="img" aria-label="' + ariaLabel + '">' +
          '<g class="lesson-number-line-axis"><line x1="90" y1="66" x2="642" y2="66"/><path d="M642 66l-12-7v14z"/><line x1="90" y1="150" x2="642" y2="150"/><path d="M642 150l-12-7v14z"/><line x1="90" y1="234" x2="642" y2="234"/><path d="M642 234l-12-7v14z"/></g>' +
          '<g class="lesson-number-line-labels"><text x="48" y="72">A</text><text x="48" y="156">B</text><text x="26" y="240">A∪B</text></g>' +
          '<g class="lesson-number-line-segment is-a"><line x1="180" y1="66" x2="470" y2="66"/><circle cx="180" cy="66" r="9"/><circle cx="470" cy="66" r="9"/></g>' +
          '<g class="lesson-number-line-segment is-b"><line x1="290" y1="150" x2="574" y2="150"/><circle class="is-closed" cx="290" cy="150" r="9"/><circle cx="574" cy="150" r="9"/></g>' +
          '<g class="lesson-number-line-segment is-result"><line x1="180" y1="234" x2="574" y2="234"/><circle cx="180" cy="234" r="9"/><circle cx="574" cy="234" r="9"/></g>' +
          '<g class="lesson-number-line-ticks"><text x="180" y="286">−2</text><text x="290" y="286">−1</text><text x="470" y="286">2</text><text x="574" y="286">3</text></g>' +
          '</svg><figcaption>A 与 B 有重叠，合并后从 −2 连续延伸到 3，两个最外端点均不取。</figcaption></figure>'
        );
      }

      if (visual.kind === "number-line-practice-complement-interval") {
        return (
          '<figure class="lesson-step-visual lesson-step-number-line">' +
          '<svg viewBox="0 0 720 280" role="img" aria-label="' + ariaLabel + '">' +
          '<g class="lesson-number-line-axis"><line x1="82" y1="82" x2="642" y2="82"/><path d="M82 82l12-7v14z"/><path d="M642 82l-12-7v14z"/><line x1="82" y1="190" x2="642" y2="190"/><path d="M82 190l12-7v14z"/><path d="M642 190l-12-7v14z"/></g>' +
          '<g class="lesson-number-line-labels"><text x="42" y="88">A</text><text x="16" y="196">C<tspan baseline-shift="sub" font-size="14">ℝ</tspan>A</text></g>' +
          '<g class="lesson-number-line-segment is-a"><line x1="240" y1="82" x2="500" y2="82"/><circle cx="240" cy="82" r="9"/><circle class="is-closed" cx="500" cy="82" r="9"/></g>' +
          '<g class="lesson-number-line-segment is-result"><line x1="88" y1="190" x2="240" y2="190"/><circle class="is-closed" cx="240" cy="190" r="9"/><line x1="500" y1="190" x2="636" y2="190"/><circle cx="500" cy="190" r="9"/></g>' +
          '<g class="lesson-number-line-ticks"><text x="240" y="238">−2</text><text x="500" y="238">3</text><text class="lesson-number-line-set-label" x="370" y="268">(−∞,−2] ∪ (3,+∞)</text></g>' +
          '</svg><figcaption>A 不取 −2、取 3，所以补集取 −2、不取 3。</figcaption></figure>'
        );
      }

      if (visual.kind === "number-line-practice-finite-subset-ray") {
        return (
          '<figure class="lesson-step-visual lesson-step-number-line">' +
          '<svg viewBox="0 0 720 340" role="img" aria-label="' + ariaLabel + '">' +
          '<g class="lesson-number-line-axis">' +
          '<line x1="92" y1="66" x2="642" y2="66"/><path d="M642 66l-12-7v14z"/>' +
          '<line x1="92" y1="158" x2="642" y2="158"/><path d="M92 158l12-7v14z"/><path d="M642 158l-12-7v14z"/>' +
          '<line x1="92" y1="250" x2="642" y2="250"/><path d="M92 250l12-7v14z"/><path d="M642 250l-12-7v14z"/>' +
          '</g>' +
          '<g class="lesson-number-line-labels"><text x="48" y="72">A</text><text x="48" y="164">B</text><text x="52" y="256">a的范围</text></g>' +
          '<g class="lesson-number-line-segment is-a"><circle class="is-closed" cx="270" cy="66" r="9"/><circle class="is-closed" cx="420" cy="66" r="9"/></g>' +
          '<g class="lesson-number-line-segment is-b"><line x1="98" y1="158" x2="540" y2="158"/><circle cx="540" cy="158" r="9"/></g>' +
          '<g class="lesson-number-line-segment is-result"><line x1="420" y1="250" x2="636" y2="250"/><circle cx="420" cy="250" r="9"/><path d="M636 250l-12-7v14z" fill="currentColor"/></g>' +
          '<g class="lesson-number-line-ticks">' +
          '<text x="270" y="108">−2</text><text x="420" y="108">1</text><text x="540" y="200">a</text><text x="420" y="294">1</text>' +
          '<text class="lesson-number-line-set-label" x="534" y="294">a &gt; 1</text>' +
          '</g>' +
          '</svg><figcaption>先在 A 的数轴上标出 −2、1，再让 B=(−∞,a) 覆盖这两个点；最后在参数轴上得到 a&gt;1。</figcaption></figure>'
        );
      }

      if (visual.kind === "number-line-practice-a-minus-b") {
        return (
          '<figure class="lesson-step-visual lesson-step-number-line">' +
          '<svg viewBox="0 0 720 310" role="img" aria-label="' + ariaLabel + '">' +
          '<g class="lesson-number-line-axis"><line x1="82" y1="66" x2="642" y2="66"/><path d="M642 66l-12-7v14z"/><line x1="82" y1="150" x2="642" y2="150"/><path d="M82 150l12-7v14z"/><path d="M642 150l-12-7v14z"/><line x1="82" y1="234" x2="642" y2="234"/><path d="M642 234l-12-7v14z"/></g>' +
          '<g class="lesson-number-line-labels"><text x="42" y="72">A</text><text x="42" y="156">B</text><text x="24" y="240">A∖B</text></g>' +
          '<g class="lesson-number-line-segment is-a"><line x1="210" y1="66" x2="500" y2="66"/><circle cx="210" cy="66" r="9"/><circle class="is-closed" cx="500" cy="66" r="9"/></g>' +
          '<g class="lesson-number-line-segment is-b"><line x1="88" y1="150" x2="300" y2="150"/><circle cx="300" cy="150" r="9"/><line x1="590" y1="150" x2="636" y2="150"/><circle cx="590" cy="150" r="9"/></g>' +
          '<g class="lesson-number-line-segment is-result"><line x1="300" y1="234" x2="500" y2="234"/><circle class="is-closed" cx="300" cy="234" r="9"/><circle class="is-closed" cx="500" cy="234" r="9"/></g>' +
          '<g class="lesson-number-line-ticks"><text x="210" y="286">−2</text><text x="300" y="286">−1</text><text x="500" y="286">3</text><text x="590" y="286">5</text></g>' +
          '</svg><figcaption>从 A=(−2,3] 中删去属于 B 的 (−2,−1)，保留端点 −1，得到 [−1,3]。</figcaption></figure>'
        );
      }

      if (visual.kind === "venn-two-counts") {
        return (
          '<figure class="lesson-step-visual lesson-step-venn">' +
          '<svg viewBox="0 0 720 320" role="img" aria-label="' + ariaLabel + '">' +
          '<rect class="lesson-venn-universe" x="42" y="24" width="636" height="260" rx="12"/>' +
          '<circle class="lesson-venn-set is-left" cx="304" cy="154" r="126"/>' +
          '<circle class="lesson-venn-set is-right" cx="416" cy="154" r="126"/>' +
          '<g class="lesson-venn-text">' +
          '<text class="is-label" x="248" y="302">田赛 A</text><text class="is-label" x="414" y="302">径赛 B</text>' +
          '<text x="244" y="164">8</text><text x="360" y="164">8</text><text x="476" y="164">15</text>' +
          '<text class="is-outside" x="610" y="72">10</text>' +
          '</g></svg><figcaption>先填交集 8，再得到田赛仅参加 8、径赛仅参加 15；圆外 10 人未参赛。</figcaption></figure>'
        );
      }

      if (visual.kind === "venn-day-one-two-counts") {
        return (
          '<figure class="lesson-step-visual lesson-step-venn">' +
          '<svg viewBox="0 0 720 320" role="img" aria-label="' + ariaLabel + '">' +
          '<rect class="lesson-venn-universe" x="42" y="24" width="636" height="260" rx="12"/>' +
          '<circle class="lesson-venn-set is-left" cx="304" cy="154" r="126"/>' +
          '<circle class="lesson-venn-set is-right" cx="416" cy="154" r="126"/>' +
          '<g class="lesson-venn-text">' +
          '<text class="is-label" x="238" y="302">第一天 D₁</text><text class="is-label" x="425" y="302">第二天 D₂</text>' +
          '<text x="244" y="164">16</text><text x="360" y="164">3</text><text x="476" y="164">10</text>' +
          '</g></svg><figcaption>第一天的 19 种由“独有 16 种”和“两天共有 3 种”组成，所以 19−3=16。</figcaption></figure>'
        );
      }

      if (visual.kind === "venn-min-union") {
        return (
          '<figure class="lesson-step-visual lesson-step-venn lesson-step-venn-min">' +
          '<svg viewBox="0 0 720 340" role="img" aria-label="' + ariaLabel + '">' +
          '<rect class="lesson-venn-universe" x="42" y="24" width="636" height="282" rx="12"/>' +
          '<text class="lesson-venn-partition-title" x="360" y="54">以第二天 D₂ 为基准，分成互不重叠的两块</text>' +
          '<line class="lesson-venn-partition-line" x1="330" y1="72" x2="330" y2="286"/>' +
          '<ellipse class="lesson-venn-set is-day-two" cx="184" cy="178" rx="108" ry="94"/>' +
          '<circle class="lesson-venn-set is-outside-one" cx="505" cy="184" r="112"/>' +
          '<circle class="lesson-venn-set is-outside-three" cx="505" cy="184" r="76"/>' +
          '<g class="lesson-venn-text">' +
          '<text class="is-label" x="184" y="136">第二天售出的商品</text><text x="184" y="176">D₂ = 13</text>' +
          '<text class="is-note" x="184" y="210">其中已经包含与第 1、3 天重合的商品</text>' +
          '<text class="is-label" x="505" y="92">第二天之外</text>' +
          '<text class="is-label" x="505" y="132">D₁∖D₂ = 16</text>' +
          '<text class="is-label" x="505" y="190">D₃∖D₂ = 14</text>' +
          '<text class="is-note is-emphasis" x="505" y="286">最省的摆法：14 种全部包含在 16 种中</text>' +
          '</g></svg><figcaption>先保留第二天的 13 种；在第二天之外，14 种全部落入已有的 16 种中，不再增加新的种类，所以最少为 13+16=29。</figcaption></figure>'
        );
      }

      return "";
    }

    function renderAllSteps() {
      if (typeof config.beforeRenderAllSteps === "function") config.beforeRenderAllSteps();
      stepCards.innerHTML = STEPS.map(function (step, index) {
        const sid = step[policyStepKey];
        const policy = POLICIES[sid] || { movable: false, range: [step.t, step.t], reason: "" };
        const activeT = clamp(step.t, policy.range[0], policy.range[1]);
        const localVars = localVarsForStep(index, step);
        const deriveSource = Array.isArray(step.reasoning) && step.reasoning.length
          ? step.reasoning
          : step.derive;
        const derive = deriveSource
          .map(function (item) {
            return Array.isArray(step.reasoning) && step.reasoning.length
              ? renderReasoningLine(item)
              : renderDeriveLine(item);
          })
          .join("");
        const reasoningTable = renderStepTable(step);
        const stepVisual = renderStepVisual(step);
        const minis = renderMinisMarkup(step, activeT);
        const localControls = renderLocalControlsMarkup(step, index);
        const animationButton = renderAnimationButtonMarkup(step, index);
        const stepAttr = policy.step != null ? String(policy.step) : String(stepRangeStep);
        const tools = policy.movable
          ? '<div class="step-local-tools" data-step-tools="' +
            index +
            '"><div class="step-slider-row">' +
            '<label for="stepRange-' +
            esc(String(sid)) +
            '">' +
            esc(sliderLabel) +
            "</label>" +
            '<input id="stepRange-' +
            esc(String(sid)) +
            '" type="range" min="' +
            policy.range[0] +
            '" max="' +
            policy.range[1] +
            '" step="' +
            stepAttr +
            '" value="' +
            activeT +
            '" data-step-range="' +
            index +
            '">' +
            '<span class="step-t-value" data-step-t-label="' +
            index +
            '">' +
            esc(paramLabelFor(index, activeT, localVars)) +
            "</span></div>" +
            '<div class="step-local-note">' +
            esc(policy.reason || "") +
            "</div></div>"
          : "";
        const hasDiagram = stepHasDiagram(step);
        const diagram = hasDiagram
          ? '<div class="step-card-diagram"><div class="svg-wrap"><svg viewBox="0 0 ' +
            viewBoxW +
            " " +
            viewBoxH +
            '" aria-label="' +
            esc(withoutStepWords(step.title)) +
            '">' +
            diagramMarkupFor(index, activeT, localVars) +
            '</svg></div>' +
            (step.hideLegend ? "" : '<div class="legend">' + legendHtml + "</div>") +
            animationButton +
            tools +
            localControls +
            minis +
            '</div>'
          : "";
        return (
          '<article class="card lesson-step-card" id="step-' +
          esc(String(sid)) +
          '" data-step-index="' +
          index +
          '">' +
          '<div class="step-card-head"><div class="step-card-title"><div class="step-section">' +
          esc(step.section) +
          "</div><h2>" +
          renderFormulaText(withoutStepWords(step.title)) +
          '</h2></div><div class="step-card-index">' +
          (index + 1) +
          "/" +
          STEPS.length +
          '</div></div><div class="step-card-body' +
          (hasDiagram ? "" : " step-card-body-text-only") +
          '">' +
          diagram +
          '<div class="step-card-panel">' +
          stepVisual +
          reasoningTable +
          '<div class="derive-list">' +
          derive +
          "</div></div></div></article>"
        );
      }).join("");
      renderStepNav();
      observeSteps();
      if (typeof config.afterRenderAllSteps === "function") config.afterRenderAllSteps();
    }

    function updateProblemToggle() {
      if (!problemToggle || !problemCard) return;
      problemToggle.textContent = problemCard.classList.contains("collapsed") ? "展开完整题目" : "收起完整题目";
    }

    function syncProblemCardForInteraction() {
      if (problemUserPreference !== null) return;
      if (problemCard) problemCard.classList.add("collapsed");
      updateProblemToggle();
    }

    function setProblemVisibility(collapsed, user) {
      if (!problemCard) return;
      problemCard.classList.toggle("collapsed", collapsed);
      if (user) problemUserPreference = collapsed ? "collapsed" : "expanded";
      updateProblemToggle();
    }

    /**
     * 原南开页面默认展示题面答案 chip（样式通过 .answer-chip.show 控制）。
     * 统一运行时后这里补回该行为，避免题面答案被隐藏。
     */
    function showProblemAnswers() {
      if (!problemCard) return;
      problemCard.querySelectorAll(".answer-chip").forEach(function (el) {
        el.classList.add("show");
      });
    }

    function setActiveStep(next, options) {
      options = options || {};
      stepIndex = clamp(next, 0, STEPS.length - 1);
      document.querySelectorAll(".lesson-step-card").forEach(function (card, index) {
        card.classList.toggle("active-step", index === stepIndex);
      });
      renderStepNav();
      if (options.scroll) {
        const el = document.getElementById("step-" + STEPS[stepIndex][policyStepKey]);
        if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    }

    function setStep(next) {
      syncProblemCardForInteraction();
      setActiveStep(next, { scroll: true });
    }

    function goToProblem() {
      setProblemVisibility(false, true);
      if (!problemCard) return;
      if (goToProblemMode === "doubleScroll") {
        problemCard.scrollIntoView({ behavior: "auto", block: "start" });
        requestAnimationFrame(function () {
          problemCard.scrollIntoView({ behavior: "smooth", block: "start" });
        });
      } else {
        problemCard.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    }

    function closeMobileStepSheet() {
      if (!mobileStepSheet) return;
      mobileStepSheet.classList.remove("open");
      mobileStepSheet.setAttribute("aria-hidden", "true");
    }

    function openMobileStepSheet() {
      if (!mobileStepSheet) return;
      mobileStepSheet.classList.add("open");
      mobileStepSheet.setAttribute("aria-hidden", "false");
    }

    function syncMiniActiveClasses(card, nextT) {
      if (!card) return;
      card.querySelectorAll("[data-mini-t]").forEach(function (el) {
        const rangeStr = el.dataset.miniRange;
        const openLeft = el.dataset.miniOpenLeft === "true";
        let active = false;
        if (rangeStr) {
          const parts = rangeStr.split(",").map(Number);
          const lo = parts[0];
          const hi = parts[1];
          active = openLeft ? nextT > lo + rangeEpsilon : nextT >= lo - rangeEpsilon;
          active = active && nextT <= hi + rangeEpsilon;
        } else {
          active = Math.abs(Number(el.dataset.miniT) - nextT) < miniEpsilon;
        }
        el.classList.toggle("active", active);
      });
    }

    function updateStepDiagram(index, value, allowFixedState) {
      const step = STEPS[index];
      const sid = step[policyStepKey];
      const policy = POLICIES[sid];
      if (!policy || (!policy.movable && !allowFixedState)) return;
      const nextT = clamp(Number(value), policy.range[0], policy.range[1]);
      const card = document.querySelector('.lesson-step-card[data-step-index="' + index + '"]');
      const svgEl = card ? card.querySelector("svg") : null;
      const labelEl = card ? card.querySelector('[data-step-t-label="' + index + '"]') : null;
      const rangeEl = card ? card.querySelector('[data-step-range="' + index + '"]') : null;
      if (svgEl) svgEl.innerHTML = diagramMarkupFor(index, nextT, localVarsByStep[index]);
      if (labelEl) labelEl.textContent = paramLabelFor(index, nextT, localVarsByStep[index]);
      if (rangeEl && Number(rangeEl.value) !== nextT) rangeEl.value = String(nextT);
      syncMiniActiveClasses(card, nextT);
    }

    function currentStepT(card, index) {
      const rangeEl = card ? card.querySelector('[data-step-range="' + index + '"]') : null;
      if (rangeEl) return Number(rangeEl.value);
      return STEPS[index] ? STEPS[index].t : 0;
    }

    function updateLocalControl(index, controlIndex, value) {
      const step = STEPS[index];
      const cfg = step && step.localControls;
      const control = cfg && cfg.controls && cfg.controls[controlIndex];
      if (!step || !control) return;
      const scale = control.scale == null ? 1 : Number(control.scale);
      const vars = localVarsForStep(index, step);
      vars[control.var] = Number(value) / scale;

      const card = document.querySelector('.lesson-step-card[data-step-index="' + index + '"]');
      if (!card) return;
      (cfg.controls || []).forEach(function (item, i) {
        const v = controlValue(vars[item.var], item);
        const input = card.querySelector('[data-local-control-index="' + i + '"]');
        const label = card.querySelector('[data-local-control-label="' + index + "-" + i + '"]');
        if (input && Number(input.value) !== v) input.value = String(v);
        if (label) label.textContent = formatControlValue(v, item);
      });
      const svgEl = card.querySelector("svg");
      if (svgEl) svgEl.innerHTML = diagramMarkupFor(index, currentStepT(card, index), vars);
    }

    function ensureAnimationModal() {
      let modal = document.getElementById("lessonAnimationModal");
      if (modal) return modal;
      modal = document.createElement("div");
      modal.id = "lessonAnimationModal";
      modal.className = "lesson-animation-modal";
      modal.setAttribute("aria-hidden", "true");
      modal.innerHTML =
        '<div class="lesson-animation-backdrop" data-animation-action="close"></div>' +
        '<div class="lesson-animation-dialog" role="dialog" aria-modal="true" aria-label="动画演示">' +
        '<div class="lesson-animation-head">' +
        '<div class="lesson-animation-kicker">动画演示</div>' +
        '<button class="lesson-animation-close" type="button" data-animation-action="close" aria-label="关闭动画">×</button>' +
        '</div><div class="lesson-animation-body">' +
        '<div class="lesson-animation-canvas"><svg viewBox="0 0 ' +
        viewBoxW +
        " " +
        viewBoxH +
        '"></svg></div>' +
        '<div class="lesson-animation-side"><div class="lesson-animation-derive"></div></div>' +
        '</div><div class="lesson-animation-controls">' +
        '<button type="button" data-animation-action="prev">上一段</button>' +
        '<button type="button" class="primary" data-animation-action="play">播放</button>' +
        '<button type="button" data-animation-action="next">下一段</button>' +
        '<button type="button" data-animation-action="replay">重播</button>' +
        '<span class="lesson-animation-progress"></span>' +
        "</div></div>";
      document.body.appendChild(modal);
      modal.addEventListener("click", function (event) {
        const target = event.target.closest("[data-animation-action]");
        if (!target) return;
        const action = target.dataset.animationAction;
        if (action === "close") closeAnimationModal();
        else if (action === "prev") stepAnimationFrame(-1);
        else if (action === "next") stepAnimationFrame(1);
        else if (action === "play") playAnimation();
        else if (action === "replay") replayAnimation();
      });
      modal.addEventListener("wheel", function (event) {
        if (!modal.classList.contains("open")) return;
        if (event.target.closest(".lesson-animation-derive")) {
          event.stopPropagation();
          return;
        }
        event.preventDefault();
      }, { passive: false });
      return modal;
    }

    function openAnimationModal(index) {
      const step = STEPS[index];
      const animation = stepAnimation(step);
      if (!animation) return;
      stopAnimationTimer();
      animationState = {
        index: index,
        beatIndex: 0,
        progress: 0,
        playing: false,
        timer: null,
        raf: null,
        startedAt: null
      };
      const modal = ensureAnimationModal();
      lockAnimationPageScroll();
      modal.classList.add("open");
      modal.setAttribute("aria-hidden", "false");
      renderAnimationModal();
      const play = modal.querySelector('[data-animation-action="play"]');
      if (play) play.focus();
    }

    function closeAnimationModal() {
      stopAnimationTimer();
      const modal = document.getElementById("lessonAnimationModal");
      if (modal) {
        modal.classList.remove("open");
        modal.setAttribute("aria-hidden", "true");
      }
      unlockAnimationPageScroll();
      animationState = null;
    }

    function lockAnimationPageScroll() {
      if (animationScrollLock) return;
      const scrollY = window.scrollY || document.documentElement.scrollTop || 0;
      animationScrollLock = {
        scrollY: scrollY,
        bodyPosition: document.body.style.position,
        bodyTop: document.body.style.top,
        bodyWidth: document.body.style.width,
        bodyOverflow: document.body.style.overflow
      };
      document.body.style.position = "fixed";
      document.body.style.top = "-" + scrollY + "px";
      document.body.style.width = "100%";
      document.body.style.overflow = "hidden";
    }

    function unlockAnimationPageScroll() {
      if (!animationScrollLock) return;
      const scrollY = animationScrollLock.scrollY || 0;
      document.body.style.position = animationScrollLock.bodyPosition || "";
      document.body.style.top = animationScrollLock.bodyTop || "";
      document.body.style.width = animationScrollLock.bodyWidth || "";
      document.body.style.overflow = animationScrollLock.bodyOverflow || "";
      animationScrollLock = null;
      window.scrollTo(0, scrollY);
    }

    function stopAnimationTimer() {
      if (!animationState) return;
      if (animationState.timer) {
        clearTimeout(animationState.timer);
        animationState.timer = null;
      }
      if (animationState.raf) {
        cancelAnimationFrame(animationState.raf);
        animationState.raf = null;
      }
      animationState.startedAt = null;
    }

    function currentAnimation() {
      if (!animationState) return null;
      const step = STEPS[animationState.index];
      const animation = stepAnimation(step);
      if (!animation) return null;
      return { step: step, animation: animation };
    }

    function renderAnimationModal() {
      const current = currentAnimation();
      const modal = document.getElementById("lessonAnimationModal");
      if (!current || !modal) return;
      const beats = current.animation.beats;
      const beat = beats[animationState.beatIndex] || beats[0];
      const index = animationState.index;
      const card = document.querySelector('.lesson-step-card[data-step-index="' + index + '"]');
      const activeT = currentStepT(card, index);
      const transition = beat.transition || {};
      const eased = easeAnimationProgress(animationState.progress, transition.easing);
      const vars = varsForBeat(index, current.step, beat, eased);
      const renderBeat = cumulativeAnimationBeat(beats, animationState.beatIndex, eased);
      const svg = modal.querySelector("svg");
      const derive = modal.querySelector(".lesson-animation-derive");
      const progress = modal.querySelector(".lesson-animation-progress");
      const play = modal.querySelector('[data-animation-action="play"]');
      if (svg) svg.innerHTML = diagramMarkupForFrame(index, renderBeat, activeT, vars);
      if (derive) {
        derive.innerHTML = cumulativeAnimationDerive(beats, animationState.beatIndex);
        derive.scrollTop = derive.scrollHeight;
      }
      if (progress) progress.textContent = animationState.beatIndex + 1 + " / " + beats.length;
      if (play) play.textContent = animationState.playing ? "暂停" : "播放";
    }

    function cumulativeAnimationBeat(beats, activeIndex, progress) {
      const activeBeat = beats[activeIndex] || beats[0] || {};
      const combinedPatch = {
        add: [],
        hide: [],
        state_overrides: []
      };
      const maxIndex = Math.max(0, activeIndex);
      for (let beatIndex = 0; beatIndex <= maxIndex; beatIndex += 1) {
        const beat = beats[beatIndex] || {};
        const patch = beat.scene_patch || {};
        const transition = beat.transition || {};
        if (patch.replace_add && beatIndex === 0) {
          combinedPatch.add = [];
          combinedPatch.replace_add = true;
        }
        const itemProgress = beatIndex === activeIndex ? progress : 1;
        const itemEffect = transition.type || "cut";
        (patch.add || []).forEach(function (item) {
          const next = Object.assign({}, item, {
            animation_progress: itemProgress,
            enter_effect: itemEffect
          });
          combinedPatch.add.push(next);
        });
        if (Array.isArray(patch.hide)) {
          combinedPatch.hide = combinedPatch.hide.concat(patch.hide);
        }
        if (Array.isArray(patch.state_overrides)) {
          combinedPatch.state_overrides = combinedPatch.state_overrides.concat(patch.state_overrides);
        }
        if (patch.pointOverrides) {
          combinedPatch.pointOverrides = Object.assign({}, combinedPatch.pointOverrides || {}, patch.pointOverrides);
        }
        if (patch.conclusionBox) combinedPatch.conclusionBox = patch.conclusionBox;
      }
      return Object.assign({}, activeBeat, {
        animation_progress: progress,
        enter_effect: ((activeBeat.transition || {}).type) || "cut",
        scene_patch: combinedPatch
      });
    }

    function cumulativeAnimationDerive(beats, activeIndex) {
      const rows = [];
      beats.forEach(function (beat, beatIndex) {
        if (beatIndex > activeIndex) return;
        (beat.derive || []).forEach(function (line) {
          const label = Array.isArray(line) ? line[0] : "";
          const text = Array.isArray(line) ? line[1] : line;
          const content = [label, text].filter(Boolean).join(" ");
          rows.push(
            '<div class="derive-line animation-derive-line ' +
              (beatIndex === activeIndex ? "active" : "past") +
              '"><span>' +
              esc(content) +
              "</span></div>"
          );
        });
      });
      return rows.join("");
    }

    function stepAnimationFrame(delta) {
      const current = currentAnimation();
      if (!current) return;
      stopAnimationTimer();
      animationState.playing = false;
      const length = current.animation.beats.length;
      animationState.beatIndex = clamp(animationState.beatIndex + delta, 0, length - 1);
      animationState.progress = 1;
      renderAnimationModal();
    }

    function replayAnimation() {
      if (!animationState) return;
      stopAnimationTimer();
      animationState.beatIndex = 0;
      animationState.progress = 0;
      animationState.playing = true;
      renderAnimationModal();
      scheduleAnimationBeat();
    }

    function playAnimation() {
      const current = currentAnimation();
      if (!current) return;
      if (animationState.playing) {
        animationState.playing = false;
        stopAnimationTimer();
        renderAnimationModal();
        return;
      }
      const currentBeat = current.animation.beats[animationState.beatIndex] || {};
      if (animationState.progress >= 1 && animationState.beatIndex >= current.animation.beats.length - 1) {
        animationState.beatIndex = 0;
        animationState.progress = 0;
      } else if (animationState.progress >= 1 && currentBeat) {
        animationState.beatIndex += 1;
        animationState.progress = 0;
      }
      animationState.playing = true;
      renderAnimationModal();
      scheduleAnimationBeat();
    }

    function scheduleAnimationBeat() {
      const current = currentAnimation();
      if (!current || !animationState.playing) return;
      const beats = current.animation.beats;
      const beat = beats[animationState.beatIndex] || {};
      const transition = beat.transition || {};
      const transitionMs = Math.max(1, Number(transition.duration_ms || 1));
      stopAnimationTimer();
      function tick(timestamp) {
        if (!animationState || !animationState.playing) return;
        if (animationState.startedAt == null) {
          animationState.startedAt = timestamp - animationState.progress * transitionMs;
        }
        animationState.progress = clamp((timestamp - animationState.startedAt) / transitionMs, 0, 1);
        renderAnimationModal();
        if (animationState.progress < 1) {
          animationState.raf = requestAnimationFrame(tick);
          return;
        }
        const holdMs = Math.max(0, Number(beat.duration_ms || transitionMs) - transitionMs);
        animationState.timer = setTimeout(function () {
          if (!animationState || !animationState.playing) return;
          if (animationState.beatIndex >= beats.length - 1) {
            animationState.playing = false;
            renderAnimationModal();
            return;
          }
          animationState.beatIndex += 1;
          animationState.progress = 0;
          animationState.startedAt = null;
          renderAnimationModal();
          scheduleAnimationBeat();
        }, holdMs);
      }
      animationState.raf = requestAnimationFrame(tick);
    }

    function easeAnimationProgress(progress, easing) {
      const p = clamp(Number(progress || 0), 0, 1);
      if (easing === "easeInOutCubic") {
        return p < 0.5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2;
      }
      return p;
    }

    function varsForBeat(index, step, beat, progress) {
      const vars = Object.assign({}, localVarsForStep(index, step));
      const localTweens = ((beat.transition || {}).local_vars) || {};
      Object.keys(localTweens).forEach(function (key) {
        const payload = localTweens[key] || {};
        if (Array.isArray(payload.keyframes) && payload.keyframes.length) {
          const value = valueForKeyframes(payload.keyframes, progress);
          if (Number.isFinite(value)) vars[key] = value;
          return;
        }
        const from = Number(payload.from);
        const to = Number(payload.to);
        if (Number.isFinite(from) && Number.isFinite(to)) {
          vars[key] = from + (to - from) * progress;
        }
      });
      return vars;
    }

    function valueForKeyframes(keyframes, progress) {
      const p = clamp(Number(progress || 0), 0, 1);
      const frames = keyframes
        .map(function (frame) {
          return { at: Number(frame.at), value: Number(frame.value) };
        })
        .filter(function (frame) {
          return Number.isFinite(frame.at) && Number.isFinite(frame.value);
        })
        .sort(function (a, b) { return a.at - b.at; });
      if (!frames.length) return NaN;
      if (p <= frames[0].at) return frames[0].value;
      for (let index = 1; index < frames.length; index += 1) {
        const prev = frames[index - 1];
        const next = frames[index];
        if (p <= next.at) {
          const span = Math.max(0.000001, next.at - prev.at);
          const local = clamp((p - prev.at) / span, 0, 1);
          return prev.value + (next.value - prev.value) * local;
        }
      }
      return frames[frames.length - 1].value;
    }

    function observeSteps() {
      if (stepObserver) stepObserver.disconnect();
      stepObserver = new IntersectionObserver(
        function (entries) {
          const visible = entries
            .filter(function (entry) {
              return entry.isIntersecting;
            })
            .sort(function (a, b) {
              return b.intersectionRatio - a.intersectionRatio;
            })[0];
          if (!visible) return;
          const next = Number(visible.target.dataset.stepIndex);
          if (Number.isInteger(next) && next !== stepIndex) setActiveStep(next);
        },
        { rootMargin: "-20% 0px -55% 0px", threshold: [0.15, 0.3, 0.55] }
      );
      document.querySelectorAll(".lesson-step-card").forEach(function (card) {
        stepObserver.observe(card);
      });
      setActiveStep(stepIndex);
    }

    stepNav.addEventListener("click", function (event) {
      const problemTarget = event.target.closest("button[data-problem-nav]");
      if (problemTarget) {
        goToProblem();
        return;
      }
      const target = event.target.closest("button[data-step]");
      if (target) setStep(Number(target.dataset.step));
    });
    if (mobileStepNav) {
      mobileStepNav.addEventListener("click", function (event) {
        const problemTarget = event.target.closest("button[data-problem-nav]");
        if (problemTarget) {
          closeMobileStepSheet();
          goToProblem();
          return;
        }
        const target = event.target.closest("button[data-step]");
        if (target) {
          setStep(Number(target.dataset.step));
          closeMobileStepSheet();
        }
      });
    }
    if (mobileStepToggle) mobileStepToggle.addEventListener("click", openMobileStepSheet);
    if (mobileStepClose) mobileStepClose.addEventListener("click", closeMobileStepSheet);
    if (mobileStepSheet) {
      mobileStepSheet.addEventListener("click", function (event) {
        if (event.target === mobileStepSheet) closeMobileStepSheet();
      });
    }
    stepCards.addEventListener("input", function (event) {
      const localTarget = event.target.closest("input[data-local-control-step]");
      if (localTarget) {
        updateLocalControl(Number(localTarget.dataset.localControlStep), Number(localTarget.dataset.localControlIndex), localTarget.value);
        return;
      }
      const target = event.target.closest("input[data-step-range]");
      if (target) updateStepDiagram(Number(target.dataset.stepRange), target.value);
    });
    stepCards.addEventListener("click", function (event) {
      const animationTarget = event.target.closest("[data-animation-open]");
      if (animationTarget) {
        openAnimationModal(Number(animationTarget.dataset.animationOpen));
        return;
      }
      const refTarget = event.target.closest("[data-step-ref]");
      if (refTarget) {
        const targetIndex = STEPS.findIndex(function (step) {
          return String(step[policyStepKey]) === String(refTarget.dataset.stepRef);
        });
        if (targetIndex >= 0) setStep(targetIndex);
        return;
      }
      const target = event.target.closest("[data-mini-t]");
      if (!target) return;
      const card = target.closest(".lesson-step-card");
      updateStepDiagram(Number(card && card.dataset.stepIndex), target.dataset.miniT, true);
    });
    stepCards.addEventListener("keydown", function (event) {
      if (event.key !== "Enter" && event.key !== " ") return;
      const target = event.target.closest("[data-mini-t]");
      if (!target) return;
      event.preventDefault();
      const card = target.closest(".lesson-step-card");
      updateStepDiagram(Number(card && card.dataset.stepIndex), target.dataset.miniT, true);
    });
    if (problemToggle && problemCard) {
      problemToggle.addEventListener("click", function () {
        setProblemVisibility(!problemCard.classList.contains("collapsed"), true);
      });
    }
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && animationState) closeAnimationModal();
    });
    updateProblemToggle();
    showProblemAnswers();
    renderAllSteps();

    return {
      renderAllSteps,
      renderStepNav,
      updateStepDiagram,
      goToProblem,
      getStepIndex: function () {
        return stepIndex;
      },
      setStepIndex: function (i) {
        stepIndex = i;
      }
    };
  }

  global.LessonPageRuntime = {
    init,
    esc,
    clamp,
    defaultFmt,
    createFmtFromLandmarks,
    isMiniItemActive,
    renderFormulaText,
    stepHasDiagram,
    withoutStepWords
  };
})(window);
