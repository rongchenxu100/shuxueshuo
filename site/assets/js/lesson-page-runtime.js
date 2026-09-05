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
        ["\\nRightarrow", "⇏"],
        ["\\Rightarrow", "⇒"],
        ["\\Leftrightarrow", "⇔"],
        ["\\leftarrow", "←"],
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

  function renderSvgSetExpression(value) {
    return esc(value).replaceAll(
      "CℝA",
      'C<tspan baseline-shift="sub" font-size="65%">ℝ</tspan>A',
    );
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

      if (visual.kind === "symmetric-reduction-flow") {
        const goal = visual.goal || {};
        const checks = Array.isArray(visual.symmetryChecks) ? visual.symmetryChecks : [];
        const substitution = visual.substitution || {};
        const elimination = visual.elimination || {};
        const closure = visual.closure || {};
        const preparation = visual.preparation || {};
        const hasPreparation = visual.variant === "normalize-before-symmetry";
        const checkIndex = hasPreparation ? "03" : "02";
        const substitutionIndex = hasPreparation ? "04" : "03";
        const eliminationIndex = hasPreparation ? "05" : "04";
        const closureIndex = hasPreparation ? "06" : "05";
        const definitions = Array.isArray(substitution.definitions) ? substitution.definitions : [];
        const endpoints = Array.isArray(closure.endpoints) ? closure.endpoints : [];
        const conditionFlow = Array.isArray(preparation.conditionFlow) ? preparation.conditionFlow : [];
        return (
          '<figure class="lesson-step-visual lesson-step-symmetric-reduction" role="group" aria-label="' + ariaLabel + '">' +
            '<div class="symmetric-reduction-heading"><h3>' + renderFormulaText(visual.title || "用对称结构消元") + '</h3>' +
              (visual.methodTag ? '<span>' + esc(visual.methodTag) + '</span>' : '') +
            '</div>' +
            '<section class="symmetric-reduction-goal"><small>01 看目标</small><strong>' + renderFormulaText(goal.expression || "") + '</strong><p>' + esc(goal.task || "") + '</p></section>' +
            (hasPreparation ? '<div class="symmetric-reduction-down" aria-hidden="true">↓</div><section class="symmetric-reduction-preparation"><header><small>02 观察变形</small><strong>先把不对称系数配成统一结构</strong></header><div class="symmetric-reduction-preparation-observation"><p>' + renderFormulaText(preparation.observation || "") + '</p><strong>' + renderFormulaText(preparation.substitution || "") + '</strong><b>' + renderFormulaText(preparation.target || "") + '</b></div><div class="symmetric-reduction-preparation-chain">' + conditionFlow.map(function (item) { return '<span>' + renderFormulaText(item) + '</span>'; }).join('<i aria-hidden="true">→</i>') + '</div><p class="symmetric-reduction-preparation-conclusion">✓ ' + renderFormulaText(preparation.conclusion || "") + '</p></section><div class="symmetric-reduction-down" aria-hidden="true">↓</div>' : '') +
            '<section class="symmetric-reduction-check"><header><small>' + checkIndex + ' 验对称</small><strong>目标与条件要分别交换 ' + esc(hasPreparation ? (visual.symmetryVariables || '两个新变量') : 'x、y') + ' 检查</strong></header><div>' +
              checks.map(function (item) {
                return '<article><span>' + esc(item.label || "") + '</span><div><b>' + renderFormulaText(item.original || "") + '</b><i aria-hidden="true">x ↔ y</i><b>' + renderFormulaText(item.swapped || "") + '</b></div><strong>✓ ' + esc(item.verdict || "") + '</strong></article>';
              }).join("") +
            '</div></section>' +
            '<div class="symmetric-reduction-down" aria-hidden="true">↓</div>' +
            '<section class="symmetric-reduction-substitution"><header><small>' + substitutionIndex + ' 换元</small><strong>把两个变量换元成和与积</strong></header>' +
              '<div class="symmetric-reduction-definitions">' + definitions.map(function (item) { return '<b>' + renderFormulaText(item) + '</b>'; }).join('<i aria-hidden="true">＋</i>') + '</div>' +
              '<div class="symmetric-reduction-chain"><span>' + renderFormulaText(substitution.identity || "") + '</span><i aria-hidden="true">→</i><span>' + renderFormulaText(substitution.condition || "") + '</span><i aria-hidden="true">→</i><strong>' + renderFormulaText(substitution.solved || "") + '</strong></div>' +
            '</section>' +
            '<div class="symmetric-reduction-down" aria-hidden="true">↓</div>' +
            '<section class="symmetric-reduction-elimination"><header><small>' + eliminationIndex + ' 消元</small><strong>' + esc(elimination.label || "应用基本不等式消元") + '</strong></header>' +
              '<div class="symmetric-reduction-relation"><small>' + renderFormulaText(elimination.relationLabel || "先建立和与积的关系") + '</small><strong>' + renderFormulaText(elimination.relation || "") + '</strong><p>' + renderFormulaText(elimination.basis || "") + '</p></div>' +
              '<div class="symmetric-reduction-substitute"><small>' + renderFormulaText(elimination.substitutionLabel || "再代入上一步结果") + '</small><div><span>' + renderFormulaText(elimination.substituted || "") + '</span><i aria-hidden="true">→</i><span>' + renderFormulaText(elimination.expanded || "") + '</span><i aria-hidden="true">→</i><span>' + renderFormulaText(elimination.simplified || "") + '</span><i aria-hidden="true">→</i><strong>' + renderFormulaText(elimination.range || "") + '</strong></div></div>' +
            '</section>' +
            '<div class="symmetric-reduction-down" aria-hidden="true">↓</div>' +
            '<section class="symmetric-reduction-closure"><header><small>' + closureIndex + ' ' + esc(closure.label || '验端点') + '</small><strong>' + renderFormulaText(closure.question || "") + '</strong></header>' +
              '<div class="symmetric-reduction-equality-condition"><small>' + esc(closure.equalityLabel || "基本不等式取等") + '</small><strong>' + renderFormulaText(closure.equalityCondition || "") + '</strong></div>' +
              '<div class="symmetric-reduction-endpoints' + (endpoints.length === 1 ? ' is-single' : '') + '">' + endpoints.map(function (item) {
                return '<article><span>' + renderFormulaText(item.value || "") + '</span><p>' + renderFormulaText(item.boundaryCondition || "") + '</p><i aria-hidden="true">↓</i><strong>' + renderFormulaText(item.witness || "") + '</strong><small>' + renderFormulaText(item.verification || "") + '</small></article>';
              }).join("") + '</div>' +
              '<p class="symmetric-reduction-conclusion">' + renderFormulaText(closure.conclusion || "") + '</p>' +
            '</section>' +
            (visual.caption ? '<figcaption>' + renderFormulaText(visual.caption) + '</figcaption>' : '') +
          '</figure>'
        );
      }

      if (visual.kind === "symmetric-objective-reduction") {
        const goal = visual.goal || {};
        const symmetry = visual.symmetryCheck || {};
        const pairing = visual.pairing || {};
        const reduction = visual.reduction || {};
        const equality = visual.equality || {};
        const terms = Array.isArray(pairing.terms) ? pairing.terms : [];
        return (
          '<figure class="lesson-step-visual lesson-step-symmetric-objective" role="group" aria-label="' + ariaLabel + '">' +
            '<div class="symmetric-objective-heading"><h3>' + renderFormulaText(visual.title || "对称目标降维") + '</h3>' +
              (visual.methodTag ? '<span>' + esc(visual.methodTag) + '</span>' : '') +
            '</div>' +
            '<section class="symmetric-objective-goal"><small>01 看目标</small><strong>' + renderFormulaText(goal.expression || "") + '</strong><p>' + esc(goal.task || "") + '</p></section>' +
            '<div class="symmetric-objective-down" aria-hidden="true">↓</div>' +
            '<section class="symmetric-objective-check"><header><small>02 验对称</small><strong>交换 a、b，检查目标是否保持不变</strong></header><div><b>' + renderFormulaText(symmetry.original || "") + '</b><i aria-hidden="true">a ↔ b</i><b>' + renderFormulaText(symmetry.swapped || "") + '</b></div><p>✓ ' + esc(symmetry.verdict || "") + '</p></section>' +
            '<div class="symmetric-objective-down" aria-hidden="true">↓</div>' +
            '<section class="symmetric-objective-pairing"><header><small>03 对称配对</small><strong>' + esc(pairing.label || "") + '</strong></header><div class="symmetric-objective-terms">' + terms.map(function (term, index) { return '<b class="is-' + (index ? 'second' : 'first') + '">' + renderFormulaText(term) + '</b>'; }).join('<span class="symmetric-objective-term-plus"><i aria-hidden="true">+</i><small>相加</small></span>') + '</div><p>' + renderFormulaText(pairing.inequality || "") + '</p><div class="symmetric-objective-product-reduction"><span>' + renderFormulaText(pairing.productVariable || "") + '</span><i aria-hidden="true">→</i><strong>' + renderFormulaText(pairing.reduced || "") + '</strong></div></section>' +
            '<div class="symmetric-objective-down" aria-hidden="true">↓</div>' +
            '<section class="symmetric-objective-reduction"><header><small>04 降维配方</small><strong>把二元目标压成关于 p 的一元式</strong></header><div><span>' + renderFormulaText(reduction.original || "") + '</span><i aria-hidden="true">→</i><span>' + renderFormulaText(reduction.lowerBound || "") + '</span><i aria-hidden="true">→</i><span>' + renderFormulaText(reduction.completion || "") + '</span><i aria-hidden="true">→</i><strong>' + renderFormulaText(reduction.conclusion || "") + '</strong></div></section>' +
            '<div class="symmetric-objective-down" aria-hidden="true">↓</div>' +
            '<section class="symmetric-objective-equality"><header><small>05 验等号</small><strong>两个取等条件必须同时成立</strong></header><div class="symmetric-objective-equality-conditions"><p><span>对称配对取等</span><b>' + renderFormulaText(equality.pairingCondition || "") + '</b></p><i class="symmetric-objective-logical-and">且</i><p><span>一元配方取等</span><b>' + renderFormulaText(equality.completionCondition || "") + '</b></p></div><div class="symmetric-objective-equality-result"><span>联立</span><strong>' + renderFormulaText(equality.result || "") + '</strong><i aria-hidden="true">→</i><b>' + renderFormulaText(equality.verification || "") + '</b></div><p class="symmetric-objective-conclusion">' + renderFormulaText(visual.conclusion || "") + '</p></section>' +
            (visual.caption ? '<figcaption>' + renderFormulaText(visual.caption) + '</figcaption>' : '') +
          '</figure>'
        );
      }

      if (visual.kind === "fixed-product-construction-flow") {
        const goal = visual.goal || {};
        const initialCheck = visual.initialCheck || {};
        const clue = visual.clue || {};
        const construction = visual.construction || {};
        const fixedPair = visual.fixedPair || {};
        const application = visual.application || {};
        const equality = visual.equality || {};
        if (visual.variant === "homogeneous-reduction") {
          const degreeBalance = visual.degreeBalance || {};
          const constructionTerms = Array.isArray(construction.positiveTerms) ? construction.positiveTerms : [];
          const mappings = Array.isArray(application.mappings) ? application.mappings : [];
          const degreeConnectors = Array.isArray(degreeBalance.connectors) && degreeBalance.connectors.length === 2
            ? degreeBalance.connectors
            : ["×", "→"];
          const slot = function (shape, compact) {
            const safeShape = shape === "circle" ? "circle" : "square";
            return '<span class="homogeneous-detail-slot is-' + safeShape + (compact ? ' is-compact' : '') + '"></span>';
          };
          const markedTerm = function (item, index) {
            const shape = item?.shape === "circle" || index === 1 ? "circle" : "square";
            return '<mark class="homogeneous-detail-term is-' + shape + '">' + renderFormulaText(item?.value || "") + '</mark>';
          };
          const degreeCard = function (item, className) {
            return '<article class="' + className + '"><span>' + esc(item?.label || "") + '</span><strong>' + renderFormulaText(item?.expression || "") + '</strong>' +
              '<b>' + esc(item?.degreeText || ((item?.degree || "") + " 次")) + '</b><p>' + renderFormulaText(item?.scale || "") + '</p><small>' + esc(item?.note || "") + '</small></article>';
          };
          const fixedTermsColored = constructionTerms.map(function (item, index) { return markedTerm(item, index); }).join('<i aria-hidden="true">×</i>');
          const initialCheckClass = initialCheck.status === "viable" ? "is-alternative" : "is-obstacle";
          const initialCheckOperator = initialCheck.operator || "×";
          const mappedSlots = mappings.map(function (mapping, index) {
            const shape = mapping.shape === "circle" || index === 1 ? "circle" : "square";
            return '<div>' + slot(shape, false) + '<i aria-hidden="true">←</i><strong>' + renderFormulaText(mapping.value || "") + '</strong><small>' + renderFormulaText(mapping.condition || "") + ' ✓</small></div>';
          }).join("");
          return (
            '<figure class="lesson-step-visual lesson-step-homogeneous-flow" role="group" aria-label="' + ariaLabel + '">' +
              '<div class="fixed-flow-heading"><h3>' + renderFormulaText(visual.title || "配齐次式") + '</h3>' +
                (visual.methodTag ? '<span>' + esc(visual.methodTag) + '</span>' : '') +
              '</div>' +
              '<div class="homogeneous-detail-intro">' +
                '<section><small>01 看目标</small><strong>' + renderFormulaText(goal.expression || "") + '</strong><p>' + esc(goal.task || "") + '</p></section>' +
                '<i aria-hidden="true">→</i>' +
                '<section class="' + initialCheckClass + '"><small>' + esc(initialCheck.label || "02 试直接应用") + '</small><div class="fixed-flow-term-product">' +
                  (Array.isArray(initialCheck.terms) ? initialCheck.terms.map(function (term) { return '<b>' + renderFormulaText(term) + '</b>'; }).join('<span aria-hidden="true">' + esc(initialCheckOperator) + '</span>') : '') +
                  '</div><strong>' + renderFormulaText(initialCheck.product || "") + '</strong><p>' + esc(initialCheck.verdict || "") + '</p></section>' +
              '</div>' +
              '<div class="fixed-flow-down" aria-hidden="true">↓</div>' +
              '<section class="homogeneous-degree-panel"><header><small>03 看次数</small><strong>' + esc(clue.question || "判断目标与条件的齐次次数") + '</strong></header>' +
                '<div class="homogeneous-degree-cards">' + degreeCard(degreeBalance.target, "is-target") + '<i aria-hidden="true">' + esc(degreeConnectors[0]) + '</i>' +
                  degreeCard(degreeBalance.condition, "is-condition") + '<i aria-hidden="true">' + esc(degreeConnectors[1]) + '</i>' + degreeCard(degreeBalance.result, "is-zero") + '</div>' +
                '<p class="homogeneous-degree-note"><b>' + renderFormulaText(clue.condition || "") + '</b><span>' + renderFormulaText(clue.observation || "") + '</span></p>' +
              '</section>' +
              '<div class="fixed-flow-down" aria-hidden="true">↓</div>' +
              '<section class="homogeneous-construction-panel"><header><small>04 配齐次</small><strong>' + esc(visual.strategy || construction.label || "") + '</strong></header>' +
                '<div class="homogeneous-construction-identity"><strong>' + renderFormulaText(construction.identity || "") + '</strong><p>' + renderFormulaText(construction.identityNote || "") + '</p></div>' +
                '<div class="homogeneous-expansion-board"><header><small>05 展开圈项</small><strong>常数项与准备应用基本不等式的正项表达式分开</strong></header>' +
                  '<div class="homogeneous-expanded-formula"><span class="is-constant">' + renderFormulaText(construction.constant || "") + '</span><i>＋</i>' +
                    constructionTerms.map(function (item, index) { return (index ? '<i>＋</i>' : '') + markedTerm(item, index); }).join("") + '</div>' +
                  '<p>' + renderFormulaText(construction.ratio || "") + '</p>' +
                '</div>' +
              '</section>' +
              '<div class="fixed-flow-down" aria-hidden="true">↓</div>' +
              '<section class="homogeneous-fixed-pair"><header><small>06 找定积</small><strong>' + esc(fixedPair.question || "") + '</strong></header>' +
                '<div>' + fixedTermsColored + '</div><p>' + renderFormulaText(fixedPair.product || "") + '</p><b>' + esc(fixedPair.verdict || "定积构造成功") + '</b>' +
              '</section>' +
              '<div class="fixed-flow-down" aria-hidden="true">↓</div>' +
              '<div class="fixed-flow-finish homogeneous-finish">' +
                '<section><small>07 用基本不等式</small>' +
                  '<div class="homogeneous-amgm-template"><div>' + slot("square", false) + '<i>＋</i>' + slot("circle", false) + '<b>≥</b><strong>2√</strong><span class="is-radicand">' + slot("square", true) + '<em>·</em>' + slot("circle", true) + '</span></div><p>两个彩色槽位表示两个完整的正项表达式</p></div>' +
                  '<div class="homogeneous-amgm-mappings">' + mappedSlots + '</div>' +
                  '<p>' + renderFormulaText(application.inequality || "") + '</p><p>' + renderFormulaText(application.combine || "") + '</p><strong>' + renderFormulaText(application.conclusion || "") + '</strong></section>' +
                '<section class="is-equality"><small>08 验等号</small>' +
                  '<div><span>两个槽位相等</span><p>' + renderFormulaText(equality.condition || "") + '</p></div>' +
                  '<i aria-hidden="true">↓</i><div><span>化简</span><p>' + renderFormulaText(equality.relation || "") + '</p></div>' +
                  '<i aria-hidden="true">↓</i><div><span>联立题设</span><strong>' + renderFormulaText(equality.result || "") + '</strong></div>' +
                '</section>' +
              '</div>' +
              (visual.caption ? '<figcaption>' + renderFormulaText(visual.caption) + '</figcaption>' : '') +
            '</figure>'
          );
        }
        const rows = Array.isArray(construction.rows) ? construction.rows : [];
        const columns = Array.isArray(construction.columns) ? construction.columns : [];
        const cells = Array.isArray(construction.cells) ? construction.cells : [];
        const matrixRows = rows.map(function (row, rowIndex) {
          return '<tr><th scope="row">' + renderFormulaText(row) + '</th>' + columns.map(function (_column, columnIndex) {
            const cell = cells[rowIndex] && cells[rowIndex][columnIndex] ? cells[rowIndex][columnIndex] : {};
            const role = cell.role === "constructed" ? "is-constructed" : "is-constant";
            return '<td class="' + role + '">' + renderFormulaText(cell.text || "") + '</td>';
          }).join("") + '</tr>';
        }).join("");
        const substitutions = Array.isArray(construction.substitutions) ? construction.substitutions : [];
        const constructionBody = construction.kind === "completion"
          ? '<div class="fixed-flow-completion-board">' +
              '<div class="fixed-flow-completion-pair"><span>分母提示配对项</span><b>' + renderFormulaText(construction.givenTerm || "") + '</b><i aria-hidden="true">↔</i><strong>' + renderFormulaText(construction.matchingTerm || "") + '</strong></div>' +
              '<div class="fixed-flow-completion-step"><span>原式补出这个正项</span><b>' + renderFormulaText(construction.identity || "") + '</b></div>' +
              (construction.expanded ? '<p class="fixed-flow-expanded">' + renderFormulaText(construction.expanded) + '</p>' : '') +
              '<div class="fixed-flow-substitution-focus"><span>乘积固定的正项和</span><b>' + renderFormulaText(construction.focus || "") + '</b><i aria-hidden="true">+</i><span>保留常数</span><strong>' + renderFormulaText(construction.constant || "") + '</strong></div>' +
              (construction.simplification ? '<p class="fixed-flow-completion-note"><span>换元只做简写</span>' + renderFormulaText(construction.simplification) + '</p>' : '') +
            '</div>'
          : construction.kind === "grouping"
            ? '<div class="fixed-flow-substitution-board fixed-flow-grouping-board">' +
              '<div class="fixed-flow-substitution-maps">' +
                '<div><b>前两项</b><span aria-hidden="true">→</span><strong>' + renderFormulaText(construction.identity || "") + '</strong><small>先通分，主动制造 ab</small></div>' +
                '<div><b>' + renderFormulaText(construction.identity || "") + '</b><span aria-hidden="true">→</span><strong>' + renderFormulaText(construction.expanded || "") + '</strong><small>再代入题设 ab=1</small></div>' +
              '</div>' +
              '<div class="fixed-flow-substitution-focus"><span>原式重新分组</span><b>' + renderFormulaText(construction.focus || "") + '</b><i aria-hidden="true">✓</i><span>正项条件</span><strong>' + renderFormulaText(construction.positive || "") + '</strong></div>' +
              '</div>'
          : construction.kind === "substitution"
            ? '<div class="fixed-flow-substitution-board">' +
              '<div class="fixed-flow-substitution-maps">' + substitutions.map(function (item) {
                return '<div><b>' + renderFormulaText(item.source || "") + '</b><span aria-hidden="true">→</span><strong>' + renderFormulaText(item.target || "") + '</strong><small>' + renderFormulaText(item.note || "") + '</small></div>';
              }).join("") + '</div>' +
              '<p class="fixed-flow-identity">' + renderFormulaText(construction.identity || "") + '</p>' +
              (construction.expanded ? '<p class="fixed-flow-expanded">' + renderFormulaText(construction.expanded) + '</p>' : '') +
              '<div class="fixed-flow-substitution-focus"><span>新的正项和</span><b>' + renderFormulaText(construction.focus || "") + '</b><i aria-hidden="true">+</i><span>保留常数</span><strong>' + renderFormulaText(construction.constant || "") + '</strong></div>' +
              '</div>'
            : '<p class="fixed-flow-identity">' + renderFormulaText(construction.identity || "") + '</p>' +
              (construction.expanded ? '<p class="fixed-flow-expanded">' + renderFormulaText(construction.expanded) + '</p>' : '') +
              '<div class="fixed-flow-matrix-wrap"><table><thead><tr><th></th>' + columns.map(function (column) { return '<th scope="col">' + renderFormulaText(column) + '</th>'; }).join("") + '</tr></thead><tbody>' + matrixRows + '</tbody></table></div>' +
              '<p class="fixed-flow-constant-sum">' + renderFormulaText(construction.constantSum || "") + '<span>交叉项是接下来要检查的新正项</span></p>';
        const termProduct = Array.isArray(initialCheck.terms)
          ? initialCheck.terms.map(function (term) { return '<b>' + renderFormulaText(term) + '</b>'; }).join('<span aria-hidden="true">×</span>')
          : "";
        const fixedTerms = Array.isArray(fixedPair.terms)
          ? fixedPair.terms.map(function (term) { return '<b>' + renderFormulaText(term) + '</b>'; }).join('<span aria-hidden="true">×</span>')
          : "";
        const applicationMappings = Array.isArray(application.mappings) ? application.mappings : [];
        return (
          '<figure class="lesson-step-visual lesson-step-fixed-product-flow" role="group" aria-label="' + ariaLabel + '">' +
            '<div class="fixed-flow-heading"><h3>' + renderFormulaText(visual.title || "构造固定乘积") + '</h3>' +
              (visual.methodTag ? '<span>' + esc(visual.methodTag) + '</span>' : '') +
            '</div>' +
            '<div class="fixed-flow-intro">' +
              '<section><small>01 看目标</small><strong>' + renderFormulaText(goal.expression || "") + '</strong><p>' + esc(goal.task || "") + '</p></section>' +
              '<i aria-hidden="true">→</i>' +
              '<section class="is-strategy"><small>02 定策略</small><strong>' + esc(visual.strategy || "构造定积") + '</strong><p>基本不等式需要两个正项的乘积固定</p></section>' +
              '<i aria-hidden="true">→</i>' +
              '<section class="is-obstacle"><small>03 查定积</small><div class="fixed-flow-term-product">' + termProduct + '</div><strong>' + renderFormulaText(initialCheck.product || "") + '</strong><p>' + esc(initialCheck.verdict || "") + '</p></section>' +
            '</div>' +
            '<div class="fixed-flow-down" aria-hidden="true">↓</div>' +
            '<section class="fixed-flow-clue"><header><small>04 找线索</small><strong>' + esc(clue.question || "") + '</strong></header>' +
              '<div><b>' + renderFormulaText(clue.condition || "") + '</b><p>' + renderFormulaText(clue.observation || "") + '</p></div>' +
            '</section>' +
            '<div class="fixed-flow-down" aria-hidden="true">↓</div>' +
            '<section class="fixed-flow-construction"><header><small>05 做构造</small><strong>' + esc(construction.label || "") + '</strong></header>' +
              constructionBody +
            '</section>' +
            '<div class="fixed-flow-down" aria-hidden="true">↓</div>' +
            '<section class="fixed-flow-discovery"><header><small>06 找定积</small><strong>' + esc(fixedPair.question || "") + '</strong></header>' +
              '<div class="fixed-flow-pair">' + fixedTerms + '</div>' +
              '<p>' + renderFormulaText(fixedPair.product || "") + '</p><b class="fixed-flow-success">' + esc(fixedPair.verdict || "定积构造成功") + '</b>' +
            '</section>' +
            '<div class="fixed-flow-down" aria-hidden="true">↓</div>' +
            '<div class="fixed-flow-finish">' +
              '<section><small>07 用基本不等式</small>' +
                (application.template ? '<div class="fixed-flow-amgm-template"><span>公式模板</span><b>' + renderFormulaText(application.template) + '</b></div>' : '') +
                (applicationMappings.length ? '<div class="fixed-flow-amgm-mappings">' + applicationMappings.map(function (mapping) {
                  return '<div><b>' + renderFormulaText(mapping.slot || "") + '</b><span aria-hidden="true">←</span><strong>' + renderFormulaText(mapping.value || "") + '</strong></div>';
                }).join("") + '</div>' : '') +
                '<p>' + renderFormulaText(application.inequality || "") + '</p><p>' + renderFormulaText(application.combine || "") + '</p><strong>' + renderFormulaText(application.conclusion || "") + '</strong></section>' +
              '<section class="is-equality"><small>08 验等号</small>' +
                '<div><span>等号要求</span><p>' + renderFormulaText(equality.condition || "") + '</p></div>' +
                '<i aria-hidden="true">↓</i>' +
                '<div><span>化简</span><p>' + renderFormulaText(equality.relation || "") + '</p></div>' +
                '<i aria-hidden="true">↓</i>' +
                '<div><span>联立题设</span><strong>' + renderFormulaText(equality.result || "") + '</strong></div>' +
              '</section>' +
            '</div>' +
            (visual.caption ? '<figcaption>' + renderFormulaText(visual.caption) + '</figcaption>' : '') +
          '</figure>'
        );
      }

      if (visual.kind === "substitution-homogeneous-lifecycle" || visual.kind === "substitution-basic-inequality-lifecycle" || visual.kind === "elimination-basic-inequality-lifecycle") {
        const substitution = visual.substitution || {};
        const elimination = visual.elimination || {};
        const homogeneous = visual.homogeneous || {};
        const basicInequality = visual.basicInequality || {};
        const restoration = visual.restoration || {};
        const usesElimination = visual.kind === "elimination-basic-inequality-lifecycle";
        const usesBasicInequality = visual.kind !== "substitution-homogeneous-lifecycle";
        const inequalityMethod = usesBasicInequality ? basicInequality : homogeneous;
        const mappings = Array.isArray(substitution.mappings) ? substitution.mappings : [];
        const rearrangement = substitution.rearrangement || null;
        const degrees = Array.isArray(homogeneous.degrees) ? homogeneous.degrees : [];
        const positiveTerms = Array.isArray(inequalityMethod.positiveTerms) ? inequalityMethod.positiveTerms : [];
        const mappingCards = mappings.map(function (mapping) {
          return '<article><small>' + esc(mapping.sourceLabel || "原分母整体") + '</small><strong>' + renderFormulaText(mapping.source || "") + '</strong><i aria-hidden="true">→</i><b>' + renderFormulaText(mapping.target || "") + '</b><p><span>保留逆关系</span>' + renderFormulaText(mapping.reverse || "") + '</p></article>';
        }).join('<span class="substitution-lifecycle-pair-and">且</span>');
        const mappingGridClass = mappings.length === 1 ? " substitution-lifecycle-mappings is-single" : " substitution-lifecycle-mappings";
        const conditionFlow = Array.isArray(rearrangement?.conditionFlow) ? rearrangement.conditionFlow : [];
        const conditionFlowBlock = conditionFlow.length ? (
          '<div class="substitution-lifecycle-condition-flow"><span>整理条件</span><div>' + conditionFlow.map(function (formula, index) {
            return (index ? '<i aria-hidden="true">→</i>' : '') + '<strong>' + renderFormulaText(formula) + '</strong>';
          }).join("") + '</div></div>'
        ) : "";
        const rearrangementBlock = rearrangement ? (
          '<div class="substitution-lifecycle-rearrangement">' +
            '<div><span>②</span><strong>' + esc(rearrangement.label || "整理换元后的目标") + '</strong></div>' +
            conditionFlowBlock +
            '<p class="substitution-lifecycle-rearrangement-before"><small>换元后</small><strong>' + renderFormulaText(rearrangement.before || "") + '</strong></p>' +
            '<div class="substitution-lifecycle-rearrangement-identities"><p>' + renderFormulaText((rearrangement.identities || [])[0] || "") + '</p><i aria-hidden="true">且</i><p>' + renderFormulaText((rearrangement.identities || [])[1] || "") + '</p></div>' +
            '<p class="substitution-lifecycle-rearrangement-result"><small>整理得</small><strong>' + renderFormulaText(rearrangement.result || "") + '</strong></p>' +
          '</div>'
        ) : "";
        const degreeCards = degrees.map(function (item, index) {
          const className = index === degrees.length - 1 ? " is-result" : "";
          return (index ? '<i aria-hidden="true">' + (index === 1 ? "×" : "→") + '</i>' : '') + '<article class="' + className.trim() + '"><span>' + esc(item.label || "") + '</span><strong>' + renderFormulaText(item.expression || "") + '</strong><b>' + esc(item.degree || "") + ' 次</b></article>';
        }).join("");
        const termCards = positiveTerms.map(function (item) {
          return '<article><strong>' + renderFormulaText(item.value || "") + '</strong><small>' + renderFormulaText(item.condition || "") + ' ✓</small></article>';
        }).join('<i aria-hidden="true">＋</i>');
        const solutionBlock = usesBasicInequality ? (
          '<section class="substitution-lifecycle-inner is-basic-inequality"><header><div><small>02 基本不等式</small><strong>' + esc(basicInequality.label || "应用基本不等式求最值") + '</strong></div><span>' + esc(basicInequality.methodTag || "发现结构｜两正项乘积固定") + '</span></header>' +
            (basicInequality.observation ? '<p class="substitution-lifecycle-basic-observation">' + esc(basicInequality.observation) + '</p>' : '') +
            '<div class="substitution-lifecycle-amgm"><div class="substitution-lifecycle-positive-terms">' + termCards + '</div><p><span>' + esc(basicInequality.relationLabel || "乘积固定") + '</span>' + renderFormulaText(basicInequality.product || "") + '</p><strong>' + renderFormulaText(basicInequality.inequality || "") + '</strong><b>' + renderFormulaText(basicInequality.bound || "") + '</b></div>' +
            '<div class="substitution-lifecycle-inner-equality"><span>等号什么时候成立？</span><p>' + renderFormulaText(basicInequality.equality || "") + '</p><strong>' + renderFormulaText(basicInequality.equalitySolved || "") + '</strong></div>' +
          '</section>'
        ) : (
          '<section class="substitution-lifecycle-inner"><header><div><small>02 配齐次式</small><strong>' + esc(homogeneous.label || "配齐次式用定和求最值") + '</strong></div><span>' + esc(homogeneous.methodTag || "发现结构｜可以配齐次式") + '</span></header>' +
            '<div class="substitution-lifecycle-degrees">' + degreeCards + '</div>' +
            '<div class="substitution-lifecycle-identity"><span>乘入定和，配成 0 次齐次式</span><strong>' + renderFormulaText(homogeneous.identity || "") + '</strong></div>' +
            '<div class="substitution-lifecycle-amgm"><div class="substitution-lifecycle-positive-terms">' + termCards + '</div><p><span>乘积固定</span>' + renderFormulaText(homogeneous.product || "") + '</p><strong>' + renderFormulaText(homogeneous.inequality || "") + '</strong><b>' + renderFormulaText(homogeneous.bound || "") + '</b></div>' +
            '<div class="substitution-lifecycle-inner-equality"><span>等号什么时候成立？</span><p>' + renderFormulaText(homogeneous.equality || "") + '</p><strong>' + renderFormulaText(homogeneous.equalitySolved || "") + '</strong></div>' +
          '</section>'
        );
        const eliminationFlow = function (items) {
          return '<div>' + (Array.isArray(items) ? items : []).map(function (formula, index) {
            return (index ? '<i aria-hidden="true">→</i>' : '') + '<strong>' + renderFormulaText(formula) + '</strong>';
          }).join("") + '</div>';
        };
        const entryBlock = usesElimination ? (
          '<section class="substitution-lifecycle-forward elimination-lifecycle-forward"><header><small>01 消元</small><strong>' + esc(elimination.label || "利用条件消去一个变量") + '</strong><p>' + esc(elimination.observation || "") + '</p></header>' +
            '<div class="elimination-lifecycle-stages">' +
              '<article><header><span>①</span><strong>整理条件</strong></header>' + eliminationFlow(elimination.conditionFlow) + '<p>通分、展开并因式分解，让变量关系显形</p></article>' +
              '<article><header><span>②</span><strong>表示变量</strong></header>' + eliminationFlow(elimination.isolateFlow) + '<p>用一个原变量表示另一个原变量</p></article>' +
              '<article><header><span>③</span><strong>代入目标</strong></header>' + eliminationFlow(elimination.targetFlow) + '<p>把二元目标降成一元表达式</p></article>' +
            '</div>' +
            '<div class="substitution-lifecycle-transformed"><span>' + esc(elimination.handoffLabel || "消元后发现：可以应用基本不等式") + '</span><p><small>范围</small><strong>' + renderFormulaText(elimination.condition || "") + '</strong></p><p><small>一元目标</small><strong>' + renderFormulaText(elimination.target || "") + '</strong></p></div>' +
          '</section>'
        ) : (
          '<section class="substitution-lifecycle-forward"><header><small>01 换元</small><strong>' + esc(substitution.label || "把复杂分母进行换元") + '</strong><p>' + esc(substitution.observation || "") + '</p></header>' +
            (rearrangement ? '<div class="substitution-lifecycle-substep"><span>①</span><strong>' + esc(substitution.mappingActionLabel || "把完整分母换成新变量") + '</strong></div>' : '') +
            '<div class="' + mappingGridClass.trim() + '">' + mappingCards + '</div>' +
            rearrangementBlock +
            '<div class="substitution-lifecycle-transformed"><span>' + esc(substitution.handoffLabel || "换元后发现：可以配齐次式") + '</span><p><small>条件</small><strong>' + renderFormulaText(substitution.condition || "") + '</strong></p><p><small>目标</small><strong>' + renderFormulaText(substitution.target || "") + '</strong></p></div>' +
          '</section>'
        );
        return (
          '<figure class="lesson-step-visual lesson-step-substitution-lifecycle' + (usesElimination ? ' lesson-step-elimination-lifecycle' : '') + '" role="group" aria-label="' + ariaLabel + '">' +
            '<div class="substitution-lifecycle-heading"><div><span>方法路线</span><h3>' + renderFormulaText(visual.title || "换元、配齐次、还原等号") + '</h3></div><strong>' + esc(visual.methodTag || "换元法｜复杂分母换元") + '</strong></div>' +
            '<div class="substitution-lifecycle-shell">' +
              entryBlock +
              '<div class="substitution-lifecycle-handoff"><span>' + (usesElimination ? '接着解决消元后的一元最值问题' : '接着解决换元后的最值问题') + '</span><i aria-hidden="true">↓</i></div>' +
              solutionBlock +
              '<div class="substitution-lifecycle-handoff is-return"><span>' + (usesElimination ? '最后求出等号对应的 ' : '最后把取等条件还原成 ') + esc(restoration.variableLabel || "x、y") + '</span><i aria-hidden="true">↓</i></div>' +
              '<section class="substitution-lifecycle-restore"><header><small>03 ' + (usesElimination ? '回代等号' : '还原等号') + '</small><strong>' + esc(restoration.label || "求解等号成立条件") + '</strong></header>' +
                '<div class="substitution-lifecycle-restore-chain"><article><span>取等条件</span><strong>' + renderFormulaText(restoration.transformedEquality || "") + '</strong></article><i aria-hidden="true">→</i><article><span>联立新条件</span><strong>' + renderFormulaText(restoration.solved || "") + '</strong></article><i aria-hidden="true">→</i><article><span>使用逆关系</span><strong>' + renderFormulaText(restoration.reverse || "") + '</strong></article><i aria-hidden="true">→</i><article class="is-result"><span>还原结果</span><strong>' + renderFormulaText(restoration.result || "") + '</strong></article></div>' +
                '<p class="substitution-lifecycle-verification"><span>代回原题检验</span>' + renderFormulaText(restoration.verification || "") + ' ✓</p>' +
              '</section>' +
              '<p class="substitution-lifecycle-conclusion">' + renderFormulaText(visual.conclusion || "") + '</p>' +
            '</div>' +
            (visual.caption ? '<figcaption>' + renderFormulaText(visual.caption) + '</figcaption>' : '') +
          '</figure>'
        );
      }

      if (visual.kind === "repeated-basic-inequality-flow") {
        const count = visual.count || {};
        const variables = Array.isArray(count.variables) ? count.variables : [];
        const conditions = Array.isArray(count.conditions) ? count.conditions : [];
        const relationSources = Array.isArray(count.relationSources) ? count.relationSources : [];
        const relationCount = Number.isInteger(count.estimatedRelations) ? count.estimatedRelations : Number(count.estimatedRounds || 0);
        const preparations = Array.isArray(visual.preparations)
          ? visual.preparations
          : (visual.preparation ? [visual.preparation] : []);
        const rounds = Array.isArray(visual.rounds) ? visual.rounds : [];
        const equality = visual.equality || {};
        const equalityConditions = Array.isArray(equality.conditions) ? equality.conditions : [];
        const countList = function (items, emptyText) {
          return items.length
            ? items.map(function (item) { return '<b>' + renderFormulaText(item) + '</b>'; }).join("")
            : '<b class="is-empty">' + esc(emptyText) + '</b>';
        };
        const formulaFlow = function (items) {
          return (Array.isArray(items) ? items : []).map(function (item, index) {
            return (index ? '<i aria-hidden="true">→</i>' : '') + '<strong>' + renderFormulaText(item) + '</strong>';
          }).join("");
        };
        const countMarkup = '<section class="repeated-basic-count"><header><small>01 判断关系缺口</small><strong>题目还缺几条取等关系？</strong></header><div>' +
          '<article><span>' + variables.length + '</span><small>' + esc(count.variableLabel || "正变量") + '</small><div>' + countList(variables, "无") + '</div></article>' +
          '<i aria-hidden="true">−</i>' +
          '<article><span>' + conditions.length + '</span><small>有效等式条件</small><div>' + countList(conditions, "无") + '</div></article>' +
          '<i aria-hidden="true">＝</i>' +
          '<article class="is-result"><span>' + relationCount + '</span><small>待补取等关系</small><div>' + (relationSources.length ? countList(relationSources, "") : '<b>基本不等式 ×' + Number(count.estimatedRounds || rounds.length) + '</b>') + '</div></article>' +
          '</div><p>' + esc(count.note || "每次对两个正项应用基本不等式，通常补一条新的取等关系。") + '</p></section>';
        const preparationMarkup = preparations.map(function (preparation, index) {
          return (
            '<div class="repeated-basic-next is-start"><span>' + esc(preparation.handoffLabel || (index ? "继续整理，让配对结构显形" : "先把原式整理到便于观察")) + '</span><i aria-hidden="true">↓</i></div>' +
            '<section class="repeated-basic-preparation"><header><small>' + esc(preparation.stepNumber || String(index + 2).padStart(2, "0")) + ' ' + esc(preparation.stageLabel || "整理目标") + '</small><strong>' + esc(preparation.label || "先整理目标表达式") + '</strong></header>' +
              '<div class="repeated-basic-current"><span>' + esc(preparation.currentLabel || "原式") + '</span><strong>' + renderFormulaText(preparation.current || "") + '</strong></div>' +
              '<div class="repeated-basic-preparation-flow">' + formulaFlow(preparation.flow) + '</div>' +
              '<div class="repeated-basic-result"><span>' + esc(preparation.resultLabel || "整理结果") + '</span><strong>' + renderFormulaText(preparation.result || "") + '</strong><p>' + esc(preparation.insight || "") + '</p></div>' +
            '</section>'
          );
        }).join("");
        const roundMarkup = rounds.map(function (round, index) {
          const terms = Array.isArray(round.terms) ? round.terms : [];
          const afterward = round.afterward || null;
          const afterwardMarkup = afterward ? (
            '<div class="repeated-basic-next"><span>根据新式继续整理</span><i aria-hidden="true">↓</i></div>' +
            '<section class="repeated-basic-restructure"><header><small>' + esc(afterward.stepNumber || "") + ' 整理新式</small><strong>' + esc(afterward.label || "根据新结构重新分组") + '</strong></header>' +
              '<div class="repeated-basic-current"><span>当前式</span><strong>' + renderFormulaText(afterward.current || "") + '</strong></div>' +
              '<p class="repeated-basic-restructure-observation">' + esc(afterward.observation || "") + '</p>' +
              '<div class="repeated-basic-preparation-flow">' + formulaFlow(afterward.flow) + '</div>' +
              '<div class="repeated-basic-result"><span>整理结果</span><strong>' + renderFormulaText(afterward.result || "") + '</strong><p>' + esc(afterward.insight || "") + '</p></div>' +
              (afterward.equality ? '<div class="repeated-basic-equality-ticket"><span>' + esc(afterward.equalityLabel || "记录平方取零") + '</span><strong>' + renderFormulaText(afterward.equality) + '</strong></div>' : '') +
            '</section>'
          ) : '';
          return (
            '<section class="repeated-basic-round">' +
              '<header><small>' + esc(round.stepNumber || String(index + 2).padStart(2, "0")) + ' 第 ' + (index + 1) + ' 次</small><strong>' + esc(round.question || "这一次配哪两个正项？") + '</strong></header>' +
              '<div class="repeated-basic-current"><span>当前式</span><strong>' + renderFormulaText(round.current || "") + '</strong></div>' +
              '<div class="repeated-basic-pairing"><div>' +
                '<article><small>第一个正项</small><strong>' + renderFormulaText(terms[0] || "") + '</strong></article>' +
                '<i aria-hidden="true">＋</i>' +
                '<article><small>第二个正项</small><strong>' + renderFormulaText(terms[1] || "") + '</strong></article>' +
              '</div><p><span>为什么这样配？</span>' + esc(round.reason || "") + '</p></div>' +
              '<div class="repeated-basic-relation"><p><span>两项关系</span><strong>' + renderFormulaText(round.relation || "") + '</strong></p><i aria-hidden="true">→</i><p><span>应用基本不等式</span><strong>' + renderFormulaText(round.inequality || "") + '</strong></p></div>' +
              '<div class="repeated-basic-result"><span>代回原式</span><strong>' + renderFormulaText(round.result || "") + '</strong><p>' + esc(round.insight || "") + '</p></div>' +
              '<div class="repeated-basic-equality-ticket"><span>记录等号 ' + (index + 1) + '</span><strong>' + renderFormulaText(round.equality || "") + '</strong></div>' +
            '</section>' + afterwardMarkup +
            (index < rounds.length - 1 ? '<div class="repeated-basic-next"><span>继续观察新式</span><i aria-hidden="true">↓</i></div>' : '')
          );
        }).join("");
        return (
          '<figure class="lesson-step-visual lesson-step-repeated-basic" role="group" aria-label="' + ariaLabel + '">' +
            '<div class="repeated-basic-heading"><div><span>方法路线</span><h3>' + renderFormulaText(visual.title || "多次应用基本不等式") + '</h3></div><strong>' + esc(visual.methodTag || "多次应用基本不等式") + '</strong></div>' +
            countMarkup +
            preparationMarkup +
            '<div class="repeated-basic-next is-start"><span>开始逐层估计</span><i aria-hidden="true">↓</i></div>' +
            '<div class="repeated-basic-rounds">' + roundMarkup + '</div>' +
            '<div class="repeated-basic-next is-equality"><span>最后检查所有等号能否同时成立</span><i aria-hidden="true">↓</i></div>' +
            '<section class="repeated-basic-equality"><header><small>' + esc(equality.stepNumber || String(rounds.length + 2).padStart(2, "0")) + ' 求等条件</small><strong>' + esc(equality.label || "求解等号成立条件") + '</strong></header>' +
              '<div class="repeated-basic-equality-list">' + equalityConditions.map(function (item) { return '<article><span>' + esc(item.label || "条件") + '</span><strong>' + renderFormulaText(item.expression || "") + '</strong></article>'; }).join('<i aria-hidden="true">且</i>') + '</div>' +
              '<div class="repeated-basic-equality-solved"><span>联立求解</span><strong>' + renderFormulaText(equality.solved || "") + '</strong></div>' +
              '<p><span>代回原题检验</span>' + renderFormulaText(equality.verification || "") + ' ✓</p>' +
            '</section>' +
            '<p class="repeated-basic-conclusion">' + renderFormulaText(visual.conclusion || "") + '</p>' +
            (visual.caption ? '<figcaption>' + renderFormulaText(visual.caption) + '</figcaption>' : '') +
          '</figure>'
        );
      }

      if (visual.kind === "basic-inequality-structure-scan") {
        const condition = visual.condition || {};
        const target = visual.target || {};
        const organization = visual.organization || {};
        const pattern = visual.pattern || {};
        const renderPanel = function (panel, fallbackLabel) {
          return (
            '<article class="basic-structure-panel">' +
              '<span>' + esc(panel.label || fallbackLabel) + '</span>' +
              '<strong>' + renderFormulaText(panel.expression || "") + '</strong>' +
              (panel.tag ? '<em>' + esc(panel.tag) + '</em>' : '') +
            '</article>'
          );
        };
        const renderPatternTerm = function (term, fallbackShape) {
          const shape = term && term.shape === "circle" ? "circle" : fallbackShape;
          return '<span class="basic-structure-pattern-term is-' + shape + '">' + renderFormulaText(term?.value || "") + '</span>';
        };
        const renderPatternRow = function (row, fallbackTag) {
          return (
            '<div class="basic-structure-pattern-row">' +
              renderPatternTerm(pattern.first, "square") +
              '<i aria-hidden="true">' + esc(row?.operator || "") + '</i>' +
              renderPatternTerm(pattern.second, "circle") +
              '<em>' + esc(row?.tag || fallbackTag) + '</em>' +
            '</div>'
          );
        };
        const patternMarkup = pattern.first && pattern.second && pattern.condition && pattern.target
          ? '<section class="basic-structure-pattern" role="img" aria-label="' + esc(pattern.ariaLabel || "观察条件与目标的共同结构") + '">' +
              renderPatternRow(pattern.condition, "已知关系") +
              '<span class="basic-structure-pattern-link" aria-hidden="true">⇅</span>' +
              renderPatternRow(pattern.target, "求最值") +
            '</section>'
          : '';
        const organizationSteps = Array.isArray(organization.steps) ? organization.steps : [];
        const slotHint = organization.slotHint || {};
        const slotBox = '<span class="basic-structure-slot-box" aria-hidden="true"></span>';
        const scaledSlotBox = function (coefficient) {
          return (coefficient ? '<b class="basic-structure-slot-coefficient">' + renderFormulaText(coefficient) + '</b>' : '') + slotBox;
        };
        const organizationSlotHintMarkup = slotHint.numerator && slotHint.value
          ? '<section class="basic-structure-slot-hint" role="img" aria-label="' + esc(slotHint.ariaLabel || "看到常数除以方框，就尝试补出与分母配对的正项") + '">' +
              '<div class="basic-structure-slot-hint-main">' +
                '<div class="basic-structure-slot-rule">' +
                  '<span class="basic-structure-slot-fraction"><b>' + esc(slotHint.numerator) + '</b>' + slotBox + '</span>' +
                  '<i aria-hidden="true">→</i>' +
                  '<span class="basic-structure-slot-action">' + esc(slotHint.action || "补出") + scaledSlotBox(slotHint.actionCoefficient) + '</span>' +
                '</div>' +
                '<p>' + slotBox + '<span>＝</span><strong>' + renderFormulaText(slotHint.value) + '</strong></p>' +
              '</div>' +
              (slotHint.rewrite && slotHint.rewrite.source
                ? '<div class="basic-structure-slot-rewrite">' +
                    '<strong>' + esc(slotHint.rewrite.source) + '</strong>' +
                    '<i aria-hidden="true">＝</i>' +
                    scaledSlotBox(slotHint.rewrite.coefficient) +
                    '<span>' + renderFormulaText(slotHint.rewrite.remainder || "− 1") + '</span>' +
                    (slotHint.rewrite.note ? '<em>' + esc(slotHint.rewrite.note) + '</em>' : '') +
                  '</div>'
                : '') +
            '</section>'
          : '';
        const expandHint = organization.expandHint || {};
        const organizationExpandHintMarkup = expandHint.action
          ? '<section class="basic-structure-expand-hint" role="img" aria-label="' + esc(expandHint.ariaLabel || "分子是乘积时，先展开并圈出条件块") + '">' +
              '<div class="basic-structure-expand-rule">' +
                '<span class="basic-structure-expand-product" aria-hidden="true">' +
                  '(<span class="basic-structure-slot-box is-square"></span>+…)' +
                  '(<span class="basic-structure-slot-box is-circle"></span>+…)' +
                '</span>' +
                '<i aria-hidden="true">→</i>' +
                '<strong>' + esc(expandHint.action) + '</strong>' +
              '</div>' +
              (expandHint.note ? '<p>' + esc(expandHint.note) + '</p>' : '') +
            '</section>'
          : '';
        const combineHint = organization.combineHint || {};
        const organizationCombineHintMarkup = combineHint.action
          ? '<section class="basic-structure-combine-hint" role="img" aria-label="' + esc(combineHint.ariaLabel || "两项分居不同变量时先通分，让条件量出现在分母") + '">' +
              '<div class="basic-structure-combine-rule">' +
                '<span class="basic-structure-combine-sum" aria-hidden="true">' +
                  '<span class="basic-structure-slot-fraction is-compact"><b>1</b><span class="basic-structure-combine-denom"><span class="basic-structure-slot-box is-square"></span><i>a</i></span></span>' +
                  '<em>＋</em>' +
                  '<span class="basic-structure-slot-fraction is-compact"><b>1</b><span class="basic-structure-combine-denom"><span class="basic-structure-slot-box is-circle"></span><i>b</i></span></span>' +
                '</span>' +
                '<i aria-hidden="true">→</i>' +
                '<strong>' + esc(combineHint.action) + '</strong>' +
              '</div>' +
              '<p>' +
                (combineHint.mark ? '<em>' + esc(combineHint.mark) + '</em>' : '') +
                (combineHint.note ? '<span>' + esc(combineHint.note) + '</span>' : '') +
              '</p>' +
            '</section>'
          : '';
        const squareHint = organization.squareHint || {};
        const organizationSquareHintMarkup = squareHint.action && squareHint.result
          ? '<section class="basic-structure-square-hint" role="img" aria-label="' + esc(squareHint.ariaLabel || "目标与条件次数不齐时，先平方配次，再代入条件消元") + '">' +
              '<div class="basic-structure-square-rule">' +
                '<span>' + renderFormulaText(squareHint.source || "目标与条件次数不齐") + '</span>' +
                '<i aria-hidden="true">→</i>' +
                '<strong>' + esc(squareHint.action) + '</strong>' +
              '</div>' +
              '<p>' +
                '<strong>' + renderFormulaText(squareHint.result) + '</strong>' +
                (squareHint.note ? '<span>' + esc(squareHint.note) + '</span>' : '') +
              '</p>' +
            '</section>'
          : '';
        const baseHint = organization.baseHint || {};
        const baseRelations = Array.isArray(baseHint.relations) ? baseHint.relations : [];
        const organizationBaseHintMarkup = baseHint.kind === "common-base" && baseHint.source && baseHint.result
          ? '<section class="basic-structure-base-hint" role="img" aria-label="' + esc(baseHint.ariaLabel || "指数式底数不同时，先统一底数") + '">' +
              '<div class="basic-structure-base-model">' +
                '<article class="basic-structure-base-stage is-source">' +
                  '<span>' + esc(baseHint.sourceLabel || "底数不同") + '</span>' +
                  '<strong>' + renderFormulaText(baseHint.source) + '</strong>' +
                '</article>' +
                '<i aria-hidden="true">→</i>' +
                '<article class="basic-structure-base-stage is-relation">' +
                  '<span>' + esc(baseHint.relationLabel || "寻找共同底数") + '</span>' +
                  '<div>' + baseRelations.map(function (item) { return '<strong>' + renderFormulaText(item) + '</strong>'; }).join('<b aria-hidden="true">，</b>') + '</div>' +
                '</article>' +
                '<i aria-hidden="true">→</i>' +
                '<article class="basic-structure-base-stage is-result">' +
                  '<span>' + esc(baseHint.resultLabel || "统一底数") + '</span>' +
                  '<strong>' + renderFormulaText(baseHint.result) + '</strong>' +
                '</article>' +
              '</div>' +
              (baseHint.productExponent
                ? '<p class="basic-structure-base-insight">' +
                    '<span>' + esc(baseHint.productLabel || "乘积指数") + '</span>' +
                    '<strong>' + renderFormulaText(baseHint.productExponent) + '</strong>' +
                    '<i aria-hidden="true">↔</i>' +
                    '<b>' + esc(baseHint.targetLabel || "对照条件量") + '</b>' +
                  '</p>'
                : '') +
            '</section>'
          : '';
        const alignmentHint = organization.alignmentHint || {};
        const alignmentCondition = alignmentHint.condition || {};
        const alignmentTarget = alignmentHint.target || {};
        const renderAlignmentTerm = function (term, includeCoefficient) {
          const shape = term?.shape === "circle" ? "circle" : "square";
          return '<span class="basic-structure-alignment-composed-term">' +
            (includeCoefficient ? '<b>' + renderFormulaText(term?.coefficient || "") + '</b>' : '') +
            '<strong class="basic-structure-alignment-term is-' + shape + '">' + renderFormulaText(term?.value || "") + '</strong>' +
          '</span>';
        };
        const organizationAlignmentHintMarkup = alignmentHint.kind === "condition-positive-term-alignment" && alignmentCondition.first && alignmentCondition.second && alignmentTarget.first && alignmentTarget.second
          ? '<section class="basic-structure-alignment-hint" role="img" aria-label="' + esc(alignmentHint.ariaLabel || "对照条件中的完整正项配凑目标") + '">' +
              '<header><span>通用方法</span><strong>' + esc(alignmentHint.method || "对照条件配凑正项") + '</strong></header>' +
              '<div class="basic-structure-alignment-row is-condition">' +
                '<small>' + esc(alignmentHint.conditionLabel || "条件中提取完整正项") + '</small>' +
                '<div>' +
                  renderAlignmentTerm(alignmentCondition.first, false) +
                  '<i aria-hidden="true">·</i>' +
                  renderAlignmentTerm(alignmentCondition.second, false) +
                  '<i aria-hidden="true">＝</i>' +
                  '<strong class="basic-structure-alignment-fixed">' + renderFormulaText(alignmentCondition.fixed || "") + '</strong>' +
                '</div>' +
              '</div>' +
              '<div class="basic-structure-alignment-link"><i aria-hidden="true">↓</i><span>' + esc(alignmentHint.linkLabel || "沿用同一组完整正项") + '</span></div>' +
              '<div class="basic-structure-alignment-row is-target">' +
                '<small>' + esc(alignmentHint.targetLabel || "目标配凑") + '</small>' +
                '<div>' +
                  renderAlignmentTerm(alignmentTarget.first, true) +
                  '<i aria-hidden="true">＋</i>' +
                  renderAlignmentTerm(alignmentTarget.second, true) +
                  '<i aria-hidden="true">＋</i>' +
                  '<span class="basic-structure-alignment-constant"><b>' + renderFormulaText(alignmentTarget.constant || "") + '</b><em>' + esc(alignmentTarget.constantLabel || "常数旁置") + '</em></span>' +
                '</div>' +
              '</div>' +
              '<p class="basic-structure-alignment-product"><span>' + esc(alignmentHint.productLabel || "检查新定积") + '</span><strong>' + renderFormulaText(alignmentHint.product || "") + '</strong></p>' +
            '</section>'
          : '';
        const substitutionHint = organization.substitutionHint || {};
        const substitutionMappings = Array.isArray(substitutionHint.mappings) ? substitutionHint.mappings : [];
        const organizationSubstitutionHintMarkup = substitutionMappings.length
          ? '<section class="substitution-core-template method-core basic-structure-substitution-hint" role="img" aria-label="' + esc(substitutionHint.ariaLabel || "识别两个完整分母，分别令新变量整体换元") + '">' +
              '<div class="substitution-trigger-pair">' +
                substitutionMappings.map(function (mapping) {
                  const isRadical = mapping?.kind === "radical";
                  const sourceMarkup = isRadical
                    ? '<strong class="substitution-structure-display is-radical"><i class="substitution-structure-slot is-radical">' + renderFormulaText(mapping.source || "") + '</i></strong>'
                    : '<strong class="substitution-structure-display is-fraction"><sup>' + renderFormulaText(mapping.numerator || "") + '</sup><i>/</i><i class="substitution-structure-slot is-denominator">' + renderFormulaText(mapping.denominator || "") + '</i></strong>';
                  return '<article class="substitution-trigger-example is-' + (isRadical ? 'radical' : 'denominator') + '">' +
                    '<span>' + (isRadical ? '根号整体' : '完整分母') + '</span>' +
                    sourceMarkup +
                    '<i class="substitution-core-arrow" aria-hidden="true">↓</i>' +
                    '<div class="substitution-core-assign"><span>令</span><strong>' + renderFormulaText(mapping.variable || "") + '</strong><b>＝</b><i class="substitution-empty-slot is-compact">' + renderFormulaText(mapping.assignment || "") + '</i></div>' +
                  '</article>';
                }).join("") +
              '</div>' +
            '</section>'
          : '';
        const eliminationHint = organization.eliminationHint || {};
        const organizationEliminationHintMarkup = eliminationHint.variable && eliminationHint.isolated && eliminationHint.independentVariable && eliminationHint.targetBefore && eliminationHint.targetAfter
          ? '<section class="elimination-core-template method-core basic-structure-elimination-hint" role="img" aria-label="' + esc(eliminationHint.ariaLabel || "由条件表示一个变量，代入目标后降为一元式") + '">' +
              '<article class="elimination-isolate-card">' +
                '<span>由条件整式表示</span>' +
                '<strong class="elimination-isolate-formula">' + renderFormulaText(eliminationHint.variable) + '<b>＝</b><i class="elimination-structure-slot">' + renderFormulaText(eliminationHint.isolated) + '</i></strong>' +
                '<small>只含 ' + renderFormulaText(eliminationHint.independentVariable) + ' 的式子</small>' +
              '</article>' +
              '<i class="elimination-core-arrow" aria-hidden="true">↓</i>' +
              '<div class="elimination-target-flow">' +
                '<article class="elimination-target-chip is-before"><span>原目标</span><strong>' + renderFormulaText(eliminationHint.targetBefore) + '</strong></article>' +
                '<i class="elimination-target-arrow" aria-hidden="true">→</i>' +
                '<article class="elimination-target-chip is-after"><span>一元目标</span><strong>' + renderFormulaText(eliminationHint.targetAfter) + '</strong></article>' +
              '</div>' +
            '</section>'
          : '';
        const homogenizationHint = organization.homogenizationHint || {};
        const organizationHomogenizationHintMarkup = homogenizationHint.original && homogenizationHint.condition && homogenizationHint.result
          ? '<section class="homogeneous-slot-template method-core basic-structure-homogenization-hint" role="img" aria-label="' + esc(homogenizationHint.ariaLabel || "把目标整式与次数相反的定值式相乘，配成零次齐次式") + '">' +
              '<div class="homogeneous-slot-equation">' +
                '<article class="homogeneous-degree-source is-original">' +
                  '<div class="homogeneous-source-expression"><span>' + esc(homogenizationHint.originalLabel || "原有整式") + '</span><strong>' + renderFormulaText(homogenizationHint.original) + '</strong></div>' +
                  '<i class="homogeneous-source-arrow" aria-hidden="true"></i>' +
                  '<div class="homogeneous-degree-slot" aria-label="' + esc(homogenizationHint.originalDegree) + ' 次式"><sup>' + esc(homogenizationHint.originalDegree) + '</sup></div>' +
                '</article>' +
                '<b class="homogeneous-slot-operator is-product" aria-hidden="true">·</b>' +
                '<article class="homogeneous-degree-source is-condition">' +
                  '<div class="homogeneous-source-expression"><span>' + esc(homogenizationHint.conditionLabel || "乘入定值") + '</span><strong>' + renderFormulaText(homogenizationHint.condition) + '</strong></div>' +
                  '<i class="homogeneous-source-arrow" aria-hidden="true"></i>' +
                  '<div class="homogeneous-degree-slot" aria-label="' + esc(homogenizationHint.conditionDegree) + ' 次式"><sup>' + esc(homogenizationHint.conditionDegree) + '</sup></div>' +
                '</article>' +
                '<b class="homogeneous-slot-operator is-equals" aria-hidden="true">＝</b>' +
                '<article class="homogeneous-degree-result"><div class="homogeneous-degree-slot" aria-label="' + esc(homogenizationHint.resultDegree) + ' 次式"><sup>' + esc(homogenizationHint.resultDegree) + '</sup></div></article>' +
                '<i class="homogeneous-output-arrow" aria-hidden="true">→</i>' +
                '<article class="homogeneous-ratio-result"><span>' + esc(homogenizationHint.resultLabel || "0 次式") + '</span><strong>' + renderFormulaText(homogenizationHint.result) + '</strong></article>' +
                '<div class="homogeneous-general-balance">' + renderFormulaText(homogenizationHint.balance) + '</div>' +
              '</div>' +
            '</section>'
          : '';
        const localHomogenizationHint = organization.localHomogenizationHint || {};
        const localHomoScopes = Array.isArray(localHomogenizationHint.scopes) ? localHomogenizationHint.scopes : [];
        const organizationLocalHomogenizationHintMarkup = localHomogenizationHint.original && localHomogenizationHint.condition && localHomogenizationHint.result
          ? '<section class="basic-structure-local-homo-hint" role="img" aria-label="' + esc(localHomogenizationHint.ariaLabel || "局部乘入定值：只对被圈项使用配齐次核心公式") + '">' +
              '<header><strong>' + esc(localHomogenizationHint.method || "局部乘入定值") + '</strong></header>' +
              '<div class="homogeneous-slot-template method-core basic-structure-homogenization-hint">' +
                '<div class="homogeneous-slot-equation">' +
                  '<article class="homogeneous-degree-source is-original">' +
                    '<div class="homogeneous-source-expression"><span>' + esc(localHomogenizationHint.originalLabel || "圈出的项") + '</span><strong>' + renderFormulaText(localHomogenizationHint.original) + '</strong></div>' +
                    '<i class="homogeneous-source-arrow" aria-hidden="true"></i>' +
                    '<div class="homogeneous-degree-slot" aria-label="' + esc(localHomogenizationHint.originalDegree) + ' 次式"><sup>' + esc(localHomogenizationHint.originalDegree) + '</sup></div>' +
                  '</article>' +
                  '<b class="homogeneous-slot-operator is-product" aria-hidden="true">·</b>' +
                  '<article class="homogeneous-degree-source is-condition">' +
                    '<div class="homogeneous-source-expression"><span>' + esc(localHomogenizationHint.conditionLabel || "乘入定值") + '</span><strong>' + renderFormulaText(localHomogenizationHint.condition) + '</strong></div>' +
                    '<i class="homogeneous-source-arrow" aria-hidden="true"></i>' +
                    '<div class="homogeneous-degree-slot" aria-label="' + esc(localHomogenizationHint.conditionDegree) + ' 次式"><sup>' + esc(localHomogenizationHint.conditionDegree) + '</sup></div>' +
                  '</article>' +
                  '<b class="homogeneous-slot-operator is-equals" aria-hidden="true">＝</b>' +
                  '<article class="homogeneous-degree-result"><div class="homogeneous-degree-slot" aria-label="' + esc(localHomogenizationHint.resultDegree) + ' 次式"><sup>' + esc(localHomogenizationHint.resultDegree) + '</sup></div></article>' +
                  '<i class="homogeneous-output-arrow" aria-hidden="true">→</i>' +
                  '<article class="homogeneous-ratio-result"><span>' + esc(localHomogenizationHint.resultLabel || "0 次式") + '</span><strong>' + renderFormulaText(localHomogenizationHint.result) + '</strong></article>' +
                  '<div class="homogeneous-general-balance">' + renderFormulaText(localHomogenizationHint.balance) + '</div>' +
                '</div>' +
              '</div>' +
              (localHomoScopes.length
                ? '<div class="basic-structure-local-homo-scopes">' +
                    localHomoScopes.map(function (scope, index) {
                      return (index ? '<b aria-hidden="true">·</b>' : '') +
                        '<article><small>' + esc(scope.label || "") + '</small><strong>' + renderFormulaText(scope.expression || "") + '</strong></article>';
                    }).join("") +
                    (localHomogenizationHint.scopeNote ? '<em>' + esc(localHomogenizationHint.scopeNote) + '</em>' : '') +
                  '</div>'
                : '') +
            '</section>'
          : '';
        const termSpot = organization.termSpot || {};
        const termSpotFactors = Array.isArray(termSpot.factors) ? termSpot.factors : [];
        const renderTermSpotTerm = function (term) {
          const role = term?.role === "spot" ? "spot" : (term?.role === "keep" ? "keep" : "plain");
          return '<span class="basic-structure-term-spot-term is-' + role + '">' +
            '<strong>' + renderFormulaText(term?.value || "") + '</strong>' +
            (term?.mark ? '<em>' + esc(term.mark) + '</em>' : '') +
          '</span>';
        };
        const organizationTermSpotMarkup = termSpotFactors.length
          ? '<section class="basic-structure-term-spot" role="img" aria-label="' + esc(termSpot.ariaLabel || "在目标整式中圈出次数不齐的项") + '">' +
              (termSpot.label ? '<span>' + esc(termSpot.label) + '</span>' : '') +
              '<div class="basic-structure-term-spot-formula">' +
                termSpotFactors.map(function (factor, index) {
                  const terms = Array.isArray(factor?.terms) ? factor.terms : [];
                  return (index
                    ? '<b class="basic-structure-term-spot-join" aria-hidden="true">' + esc(termSpot.join || "·") + '</b>'
                    : '') +
                    '<article class="basic-structure-term-spot-factor">' +
                      '<i aria-hidden="true">(</i>' +
                      terms.map(function (term, termIndex) {
                        return (termIndex ? '<b aria-hidden="true">＋</b>' : '') + renderTermSpotTerm(term);
                      }).join("") +
                      '<i aria-hidden="true">)</i>' +
                    '</article>';
                }).join("") +
              '</div>' +
            '</section>'
          : '';
        const relationCountHint = organization.relationCountHint || {};
        const relationVariable = relationCountHint.variable || {};
        const relationCondition = relationCountHint.condition || {};
        const relationResult = relationCountHint.result || {};
        const organizationRelationCountMarkup = relationCountHint.variable && relationCountHint.condition && relationCountHint.result
          ? '<section class="basic-structure-relation-count" role="img" aria-label="' + esc(relationCountHint.ariaLabel || "变量数减去已有取等条件数，得到待补取等关系数") + '">' +
              '<div class="basic-structure-relation-equation">' +
                '<article class="is-variable"><span>' + esc(relationVariable.label || "变量数") + '</span><strong>' + renderFormulaText(relationVariable.value || "") + '</strong>' + (relationVariable.detail ? '<small>' + renderFormulaText(relationVariable.detail) + '</small>' : '') + '</article>' +
                '<i aria-hidden="true">−</i>' +
                '<article class="is-condition"><span>' + esc(relationCondition.label || "已有取等条件数") + '</span><strong>' + renderFormulaText(relationCondition.value || "") + '</strong>' + (relationCondition.detail ? '<small>' + renderFormulaText(relationCondition.detail) + '</small>' : '') + '</article>' +
                '<i aria-hidden="true">＝</i>' +
                '<article class="is-result"><span>' + esc(relationResult.label || "待补取等关系数") + '</span><strong>' + renderFormulaText(relationResult.value || "") + '</strong>' + (relationResult.detail ? '<small>' + renderFormulaText(relationResult.detail) + '</small>' : '') + '</article>' +
              '</div>' +
            '</section>'
          : '';
        const symmetryHint = organization.symmetryHint || {};
        const symmetryChecks = Array.isArray(symmetryHint.checks) ? symmetryHint.checks : [];
        const organizationSymmetryHintMarkup = symmetryChecks.length
          ? '<section class="symmetric-reduction-check basic-structure-symmetry-hint" role="img" aria-label="' + esc(symmetryHint.ariaLabel || "交换两个变量，校验目标与条件是否保持不变") + '">' +
              '<header><small>' + esc(symmetryHint.label || "交换检验") + '</small><strong>' + esc(symmetryHint.instruction || "交换 x、y，分别检查目标与条件") + '</strong></header><div>' +
                symmetryChecks.map(function (item) {
                  return '<article><span>' + esc(item.label || "") + '</span><div><b>' + renderFormulaText(item.original || "") + '</b><i aria-hidden="true">' + esc(symmetryHint.swap || "x ↔ y") + '</i><b>' + renderFormulaText(item.swapped || "") + '</b></div><strong>✓ ' + esc(item.verdict || "交换后不变") + '</strong></article>';
                }).join("") +
              '</div>' +
              (symmetryHint.conclusion ? '<p class="basic-structure-symmetry-conclusion">' + esc(symmetryHint.conclusion) + '</p>' : '') +
            '</section>'
          : '';
        const organizationStepMarkup = organizationSteps.map(function (item, index) {
          const stepItem = typeof item === "string" ? { expression: item } : (item || {});
          const expression = stepItem.expression || "";
          const marks = stepItem.marks || {};
          return (index ? '<i aria-hidden="true">→</i>' : '') +
            '<div class="basic-structure-org-step">' +
              (stepItem.label ? '<small>' + esc(stepItem.label) + '</small>' : '') +
              '<strong>' + renderFormulaText(expression) + '</strong>' +
              (marks.bracket || marks.bypass
                ? '<span class="basic-structure-org-marks">' +
                    (marks.bracket ? '<em>' + esc(marks.bracket) + '</em>' : '') +
                    (marks.bypass ? '<b>' + esc(marks.bypass) + '</b>' : '') +
                  '</span>'
                : '') +
            '</div>';
        }).join("");
        const organizationStepsMarkup = organizationSteps.length
          ? (organization.stepGroupLabel
            ? '<section class="basic-structure-step-group"><header>' + esc(organization.stepGroupLabel) + '</header><div class="basic-structure-org-steps">' + organizationStepMarkup + '</div></section>'
            : '<div class="basic-structure-org-steps">' + organizationStepMarkup + '</div>')
          : '';
        const organizationSequenceArrowMarkup = organization.stepGroupLabel && organizationSymmetryHintMarkup
          ? '<i class="basic-structure-sequence-arrow" aria-hidden="true">↓</i>'
          : '';
        const isMethodCoreOnly = Boolean(
          (organizationHomogenizationHintMarkup || organizationSubstitutionHintMarkup || organizationEliminationHintMarkup) &&
          !organizationSteps.length &&
          !organizationSlotHintMarkup &&
          !organizationExpandHintMarkup &&
          !organizationCombineHintMarkup &&
          !organizationSquareHintMarkup &&
          !organizationBaseHintMarkup &&
          !organizationAlignmentHintMarkup &&
          [organizationHomogenizationHintMarkup, organizationSubstitutionHintMarkup, organizationEliminationHintMarkup].filter(Boolean).length === 1 &&
          !organizationLocalHomogenizationHintMarkup &&
          !organizationTermSpotMarkup &&
          !organizationRelationCountMarkup &&
          !organizationSymmetryHintMarkup &&
          !organization.label &&
          !organization.motive &&
          !organization.note
        );
        const organizationMarkup = organizationSteps.length || organizationSlotHintMarkup || organizationExpandHintMarkup || organizationCombineHintMarkup || organizationSquareHintMarkup || organizationBaseHintMarkup || organizationAlignmentHintMarkup || organizationSubstitutionHintMarkup || organizationEliminationHintMarkup || organizationHomogenizationHintMarkup || organizationLocalHomogenizationHintMarkup || organizationTermSpotMarkup || organizationRelationCountMarkup || organizationSymmetryHintMarkup
          ? '<section class="basic-structure-organization' + (isMethodCoreOnly ? ' is-method-core-only' : '') + '">' +
              (organization.label ? '<span>' + esc(organization.label) + '</span>' : '') +
              (organization.motive ? '<p class="basic-structure-organization-motive">' + renderFormulaText(organization.motive) + '</p>' : '') +
              organizationTermSpotMarkup +
              organizationRelationCountMarkup +
              organizationSlotHintMarkup +
              organizationExpandHintMarkup +
              organizationCombineHintMarkup +
              organizationSquareHintMarkup +
              organizationBaseHintMarkup +
              organizationAlignmentHintMarkup +
              organizationSubstitutionHintMarkup +
              organizationEliminationHintMarkup +
              organizationStepsMarkup +
              organizationSequenceArrowMarkup +
              organizationSymmetryHintMarkup +
              organizationLocalHomogenizationHintMarkup +
              organizationHomogenizationHintMarkup +
              (organization.note ? '<p>' + renderFormulaText(organization.note) + '</p>' : '') +
            '</section>'
          : '';
        const structureHeading = visual.title
          ? '<div class="basic-structure-heading"><h3>' + renderFormulaText(visual.title) + '</h3></div>'
          : '';
        const focusMarkup = visual.showFocus === false
          ? ''
          : '<div class="basic-structure-focus">' +
              renderPanel(condition, "条件整式") +
              '<div class="basic-structure-lens" aria-hidden="true"><span>观察</span><strong>结构</strong></div>' +
              renderPanel(target, "目标整式") +
            '</div>' +
            '<i class="basic-structure-arrow" aria-hidden="true">↓</i>';
        return (
          '<figure class="lesson-step-visual lesson-step-basic-structure-scan" role="group" aria-label="' + esc(visual.ariaLabel || "观察结构") + '">' +
            structureHeading +
            focusMarkup +
            organizationMarkup +
            (organizationMarkup ? '<i class="basic-structure-arrow" aria-hidden="true">↓</i>' : '') +
            patternMarkup +
            '<p class="basic-structure-route">' +
              '<strong>' + esc(visual.reading || "") + '</strong>' +
              '<b>→</b>' +
              '<span>' + esc(visual.route || "") + '</span>' +
            '</p>' +
            (visual.caption ? '<figcaption>' + renderFormulaText(visual.caption) + '</figcaption>' : '') +
          '</figure>'
        );
      }

      if (visual.kind === "basic-inequality-mapping") {
        const mappings = Array.isArray(visual.mappings) ? visual.mappings : [];
        const firstMapping = mappings[0] || { slot: "a", value: "m", condition: "\\(m>0\\)" };
        const secondMapping = mappings[1] || { slot: "b", value: "n", condition: "\\(n>0\\)" };
        const firstValue = renderFormulaText(firstMapping.value || "m");
        const secondValue = renderFormulaText(secondMapping.value || "n");
        const mappedSum = visual.mappedSum
          ? renderFormulaText(visual.mappedSum)
          : firstValue + "+" + secondValue;
        const mappedProduct = visual.mappedProduct
          ? renderFormulaText(visual.mappedProduct)
          : firstValue + '<span class="basic-map-product-dot">·</span>' + secondValue;
        const mappedFractionClass = visual.mappedSum ? " is-wide" : "";
        const fixedSourceMarkup =
          '<div class="basic-map-fixed-source"><span class="basic-map-short-arrow">↑</span><small>' +
          esc(visual.fixedSourceLabel || "已知") + '</small><strong>' +
          renderFormulaText(visual.fixedCondition || "") + '</strong></div>';
        const fixedSourceTargetsProduct = visual.fixedSourceTarget === "product";
        const usesSumGeometricFormula = visual.formulaStyle === "sum-geometric";
        const usesSquareSumFormula = visual.formulaStyle === "square-sum";
        const fixedFormulaClass = fixedSourceTargetsProduct ? " has-product-fixed-source" : "";
        const fixedProductClusterClass = fixedSourceTargetsProduct ? " has-fixed-source" : "";
        const fixedSumClass = fixedSourceTargetsProduct ? "" : " is-fixed";
        const fixedProductMarkup = fixedSourceTargetsProduct
          ? '<span class="basic-map-product-target">' + mappedProduct + '</span>'
          : mappedProduct;
        const mappingSlot = function (mapping, order, compact) {
          const shape = mapping.shape === "square" || mapping.shape === "circle" ? mapping.shape : "";
          const classes = "basic-map-variable is-" + order + (shape ? " is-shape is-slot-" + shape : "") + (compact ? " is-compact" : "");
          return '<span class="' + classes + '">' + (shape ? "" : esc(mapping.slot || (order === "first" ? "a" : "b"))) + '</span>';
        };
        const firstSlotHtml = mappingSlot(firstMapping, "first", false);
        const secondSlotHtml = mappingSlot(secondMapping, "second", false);
        const firstCompactSlotHtml = mappingSlot(firstMapping, "first", true);
        const secondCompactSlotHtml = mappingSlot(secondMapping, "second", true);
        const conditionFlow = Array.isArray(visual.conditionFlow) ? visual.conditionFlow : [];
        const sourceGrid = visual.showPositiveStep ? '' :
          '<div class="basic-map-source-grid">' +
            '<div class="basic-map-source is-first"><span class="basic-map-short-arrow">↑</span><strong>' + firstValue + '</strong><em>' + renderFormulaText(firstMapping.condition) + ' ✓</em></div>' +
            '<span aria-hidden="true"></span>' +
            '<div class="basic-map-source is-second"><span class="basic-map-short-arrow">↑</span><strong>' + secondValue + '</strong><em>' + renderFormulaText(secondMapping.condition) + ' ✓</em></div>' +
          '</div>';
        const fractionTemplateFormula =
          '<div class="basic-map-formula-layout" aria-hidden="true">' +
            '<div class="basic-map-fraction-cluster">' +
              '<div class="basic-map-numerator-grid">' +
                firstSlotHtml +
                '<span class="basic-map-operator">+</span>' +
                secondSlotHtml +
              '</div>' +
              '<span class="basic-map-fraction-line"></span><span class="basic-map-denominator">2</span>' +
              sourceGrid +
            '</div>' +
            '<span class="basic-map-formula-tail"><span class="basic-map-relation">≥</span><span class="math-radical"><span class="math-radical-symbol">√</span><span class="math-radicand">' +
              firstCompactSlotHtml +
              secondCompactSlotHtml +
            '</span></span></span>' +
          '</div>';
        const sumTemplateSource = function (mapping, order, value) {
          const shape = mapping.shape === "square" || mapping.shape === "circle" ? mapping.shape : "";
          return '<div class="basic-map-source is-' + order + (shape ? ' is-slot-' + shape : '') + '">' +
            '<span class="basic-map-short-arrow">↑</span>' +
            '<strong>' + value + '</strong>' +
            '<em>' + renderFormulaText(mapping.condition) + ' ✓</em>' +
          '</div>';
        };
        const sumTemplateFormula =
          '<div class="basic-map-formula-layout is-sum-geometric has-source-actions" aria-hidden="true">' +
            '<div class="basic-map-formula-slot-stack">' + firstSlotHtml + sumTemplateSource(firstMapping, "first", firstValue) + '</div>' +
            '<span class="basic-map-operator">+</span>' +
            '<div class="basic-map-formula-slot-stack">' + secondSlotHtml + sumTemplateSource(secondMapping, "second", secondValue) + '</div>' +
            '<span class="basic-map-relation">≥</span><span>2</span>' +
            '<span class="math-radical"><span class="math-radical-symbol">√</span><span class="math-radicand">' +
              firstCompactSlotHtml + '<span class="basic-map-product-dot">·</span>' + secondCompactSlotHtml +
            '</span></span>' +
          '</div>';
        const squareSumTemplateFormula =
          '<div class="basic-map-formula-layout is-square-sum" aria-hidden="true">' +
            '<span class="basic-map-square-term">' + firstSlotHtml + '<sup>2</sup></span>' +
            '<span class="basic-map-operator">+</span>' +
            '<span class="basic-map-square-term">' + secondSlotHtml + '<sup>2</sup></span>' +
            '<span class="basic-map-relation">≥</span><span>2</span>' +
            firstCompactSlotHtml + '<span class="basic-map-product-dot">·</span>' + secondCompactSlotHtml +
          '</div>' +
          sourceGrid;
        const templateFormula = usesSquareSumFormula
          ? squareSumTemplateFormula
          : (usesSumGeometricFormula ? sumTemplateFormula : fractionTemplateFormula);
        const fractionMappedFormula =
          '<div class="basic-map-formula-layout basic-map-formula-layout-fixed' + fixedFormulaClass + '" aria-hidden="true">' +
            '<div class="basic-map-fixed-fraction' + mappedFractionClass + '">' +
              '<span class="basic-map-sum-target' + fixedSumClass + '">' + mappedSum + '</span>' +
              '<span class="basic-map-fraction-line"></span><span class="basic-map-denominator">2</span>' +
              (fixedSourceTargetsProduct ? '' : fixedSourceMarkup) +
            '</div>' +
            '<span class="basic-map-formula-tail"><span class="basic-map-relation">≥</span><span class="basic-map-product-cluster' + fixedProductClusterClass + '"><span class="math-radical"><span class="math-radical-symbol">√</span><span class="math-radicand">' +
              fixedProductMarkup +
            '</span></span>' + (fixedSourceTargetsProduct ? fixedSourceMarkup : '') + '</span></span>' +
          '</div>';
        const sumMappedFormula =
          '<div class="basic-map-formula-layout basic-map-formula-layout-fixed is-sum-geometric' + fixedFormulaClass + '" aria-hidden="true">' +
            '<div class="basic-map-fixed-sum-group"><span class="basic-map-sum-target' + fixedSumClass + '">' + mappedSum + '</span>' + (fixedSourceTargetsProduct ? '' : fixedSourceMarkup) + '</div>' +
            '<span class="basic-map-formula-tail"><span class="basic-map-relation">≥</span><span>2</span><span class="basic-map-product-cluster' + fixedProductClusterClass + '"><span class="math-radical"><span class="math-radical-symbol">√</span><span class="math-radicand">' + fixedProductMarkup + '</span></span>' + (fixedSourceTargetsProduct ? fixedSourceMarkup : '') + '</span></span>' +
          '</div>';
        const squareSumMappedFormula =
          '<div class="basic-map-formula-layout basic-map-formula-layout-fixed is-square-sum" aria-hidden="true"><strong>' +
            renderFormulaText(visual.mapped || "") +
          '</strong></div>';
        const mappedFormula = usesSquareSumFormula
          ? squareSumMappedFormula
          : (usesSumGeometricFormula ? sumMappedFormula : fractionMappedFormula);
        const positiveStepMarkup = visual.showPositiveStep
          ? '<div class="basic-map-positive-board"><div class="basic-map-board-heading"><span>识别正项</span></div><div class="basic-map-positive-items">' +
              '<article class="is-first"><strong>' + firstValue + '</strong><span>' + renderFormulaText(firstMapping.condition) + ' ✓</span></article>' +
              '<i aria-hidden="true">＋</i>' +
              '<article class="is-second"><strong>' + secondValue + '</strong><span>' + renderFormulaText(secondMapping.condition) + ' ✓</span></article>' +
            '</div></div>'
          : '';
        const mappingHeading = visual.title || visual.methodTag
          ? '<div class="basic-map-heading">' + (visual.title ? '<h3>' + renderFormulaText(visual.title) + '</h3>' : '') + (visual.methodTag ? '<span>' + esc(visual.methodTag) + '</span>' : '') + '</div>'
          : '';
        return (
          '<figure class="lesson-step-visual lesson-step-basic-inequality-map" role="group" aria-label="' + ariaLabel + '">' +
          mappingHeading +
          (conditionFlow.length ? '<div class="basic-map-condition-flow">' +
            '<strong>' + esc(visual.conditionFlowLabel || "先整理条件") + '</strong>' +
            '<div>' + conditionFlow.map(function (item, index) {
              return (index ? '<span aria-hidden="true">→</span>' : '') + '<b>' + renderFormulaText(item) + '</b>';
            }).join("") + '</div>' +
          '</div>' : '') +
          positiveStepMarkup +
          '<div class="basic-map-variable-board">' +
            '<div class="basic-map-board-heading"><span>' + esc(visual.templateLabel || "公式模板") + '</span><span class="basic-map-screen-reader">' + renderFormulaText(visual.template || "") + '</span></div>' +
            '<div class="basic-map-template-formula">' + templateFormula + '</div>' +
          '</div>' +
          '<div class="basic-map-fixed-board">' +
            '<div class="basic-map-board-heading"><span>' + esc(visual.stageLabel || "代入关系") + '</span><span class="basic-map-screen-reader">' + renderFormulaText(visual.mapped || "") + '</span></div>' +
            '<div class="basic-map-fixed-formula">' + mappedFormula + '</div>' +
          '</div>' +
          '<div class="basic-map-deduction">' +
            '<div><small>' + renderFormulaText(visual.replacementText || "代入关系") + '</small><strong>' + renderFormulaText(visual.replaced || "") + '</strong></div>' +
            '<span aria-hidden="true">→</span>' +
            '<div><small>' + renderFormulaText(visual.simplifyLabel || "化简") + '</small><strong>' + renderFormulaText(visual.substituted || "") + '</strong></div>' +
            '<span aria-hidden="true">→</span>' +
            '<div class="is-result"><small>' + renderFormulaText(visual.conclusionLabel || "得到界值") + '</small><strong>' + renderFormulaText(visual.conclusion || "") + '</strong></div>' +
          '</div>' +
          (visual.equalityTemplate && visual.equalityMapped && visual.equalityResult
            ? '<div class="basic-map-equality"><span>等号条件</span><div><strong>' + renderFormulaText(visual.equalityTemplate) + '</strong><i>映射为</i><strong>' + renderFormulaText(visual.equalityMapped) + '</strong><i>' + esc(visual.equalityContextLabel || "结合条件") + '</i><b>' + renderFormulaText(visual.equalityResult) + '</b></div></div>'
            : '') +
          (visual.caption ? '<figcaption>' + renderFormulaText(visual.caption) + '</figcaption>' : '') +
          '</figure>'
        );
      }

      if (visual.kind === "basic-inequality-equality-check") {
        const first = visual.first || {};
        const second = visual.second || {};
        const equalityItems = Array.isArray(visual.equalities) ? visual.equalities : [];
        const equalityTerm = function (term, fallbackShape) {
          const shape = term.shape === "circle" ? "circle" : fallbackShape;
          return '<span class="basic-equality-term is-' + shape + '">' + renderFormulaText(term.value || "") + '</span>';
        };
        const equalityTemplateMarkup = equalityItems.length
          ? '<section class="basic-equality-system' + (equalityItems.length === 3 ? ' is-three' : '') + '"><span>' + esc(visual.templateLabel || "联立取等条件") + '</span><div>' +
              equalityItems.map(function (item) {
                return '<article><header>' + esc(item.label || "取等条件") + '</header><div>' +
                  equalityTerm(item.first || {}, "square") + '<i aria-hidden="true">＝</i>' + equalityTerm(item.second || {}, "circle") +
                '</div><p><span>推出</span><strong>' + renderFormulaText(item.result || "") + '</strong></p></article>';
              }).join('<b aria-hidden="true">且</b>') +
            '</div></section>'
          : '<section class="basic-equality-template"><span>' + esc(visual.templateLabel || "基本不等式取等") + '</span><div>' + equalityTerm(first, "square") + '<i aria-hidden="true">＝</i>' + equalityTerm(second, "circle") + '</div></section>';
        const equalitySolveMarkup = equalityItems.length
          ? '<section class="basic-equality-system-solve"><span>联立求解</span><div>' +
              equalityItems.map(function (item, index) {
                return (index ? '<i aria-hidden="true">＋</i>' : '') + '<strong>' + renderFormulaText(item.result || "") + '</strong>';
              }).join('') +
              '<i aria-hidden="true">→</i><b>' + renderFormulaText(visual.solved || "") + '</b>' +
            '</div></section>'
          : '<section class="basic-equality-solve"><article><span>' + esc(visual.conditionLabel || "结合条件") + '</span><strong>' + renderFormulaText(visual.condition || "") + '</strong></article><i aria-hidden="true">＋</i><article><span>' + esc(visual.equalityLabel || "正项相等") + '</span><strong>' + renderFormulaText((first.value || "") + "=" + (second.value || "")) + '</strong></article><i aria-hidden="true">→</i><b>' + renderFormulaText(visual.solved || "") + '</b></section>';
        return (
          '<figure class="lesson-step-visual lesson-step-basic-equality-check" role="group" aria-label="' + esc(visual.ariaLabel || "验证取等") + '">' +
            equalityTemplateMarkup +
            '<i class="basic-equality-down" aria-hidden="true">↓</i>' +
            equalitySolveMarkup +
            '<section class="basic-equality-verify"><span>' + esc(visual.verificationLabel || "代回目标") + '</span><strong>' + renderFormulaText(visual.verification || "") + '</strong><i aria-hidden="true">✓</i></section>' +
            '<p class="basic-equality-conclusion">' + renderFormulaText(visual.conclusion || "") + '</p>' +
          '</figure>'
        );
      }

      if (visual.kind === "inequality-sign-chart") {
        const columns = Array.isArray(visual.columns) ? visual.columns : [];
        const rows = Array.isArray(visual.rows) ? visual.rows : [];
        const body = rows.map(function (row) {
          const selected = new Set(Array.isArray(row.selectedIndices) ? row.selectedIndices : []);
          return '<tr><th scope="row">' + renderFormulaText(row.label || "") + '</th>' +
            (Array.isArray(row.values) ? row.values : []).map(function (value, index) {
              return '<td class="' + (selected.has(index) ? 'is-selected' : '') + '">' + renderFormulaText(value) + '</td>';
            }).join("") + '</tr>';
        }).join("");
        const notes = Array.isArray(visual.notes) && visual.notes.length
          ? '<ol class="lesson-sign-chart-notes">' + visual.notes.map(function (note) {
            return '<li>' + renderFormulaText(note) + '</li>';
          }).join("") + '</ol>'
          : "";
        return (
          '<figure class="lesson-step-visual lesson-step-sign-chart" role="group" aria-label="' + ariaLabel + '">' +
          (visual.title ? '<h3>' + renderFormulaText(visual.title) + '</h3>' : '') +
          '<div class="lesson-sign-chart-scroll"><table class="lesson-sign-chart-table"><thead><tr>' +
          columns.map(function (column) { return '<th scope="col">' + renderFormulaText(column) + '</th>'; }).join("") +
          '</tr></thead><tbody>' + body + '</tbody></table></div>' +
          (visual.solution ? '<p class="lesson-sign-chart-solution"><strong>解集：</strong>' + renderFormulaText(visual.solution) + '</p>' : '') +
          notes +
          (visual.caption ? '<figcaption>' + renderFormulaText(visual.caption) + '</figcaption>' : '') +
          '</figure>'
        );
      }

      if (visual.kind === "option-counterexample-review") {
        const rows = Array.isArray(visual.rows) ? visual.rows : [];
        return (
          '<figure class="lesson-step-visual lesson-step-option-review" role="group" aria-label="' + ariaLabel + '">' +
          '<header><span>逐项验证</span><h3>' + renderFormulaText(visual.title || "用反例淘汰错误结论") + '</h3></header>' +
          (visual.intro ? '<p class="lesson-option-review-intro">' + renderFormulaText(visual.intro) + '</p>' : '') +
          '<div class="lesson-option-review-grid">' + rows.map(function (row) {
            const state = row.correct ? "is-correct" : "is-counterexample";
            return '<article class="' + state + '"><div class="lesson-option-review-option"><b>' + esc(row.option || "") + '</b><span>' + (row.correct ? "成立" : "反例") + '</span></div>' +
              '<p class="lesson-option-review-claim">' + renderFormulaText(row.judgment || "") + '</p>' +
              '<div class="lesson-option-review-example"><small>' + (row.correct ? "性质依据" : "代入数值") + '</small><strong>' + renderFormulaText(row.example || "") + '</strong></div>' +
              '<p class="lesson-option-review-calculation">' + renderFormulaText(row.calculation || "") + '</p></article>';
          }).join("") + '</div>' +
          (visual.caption ? '<figcaption>' + renderFormulaText(visual.caption) + '</figcaption>' : '') +
          '</figure>'
        );
      }

      if (visual.kind === "absolute-direct-rule-map") {
        const rules = Array.isArray(visual.rules) ? visual.rules : [];
        const ruleMarkup = rules.map(function (rule) {
          const mappings = Array.isArray(rule.mappings) ? rule.mappings : [];
          return (
            '<article class="lesson-absolute-direct-rule-card">' +
            '<header><span>' + esc(rule.index || "") + '</span><h4>' + esc(rule.name || "直接法") + '</h4></header>' +
            '<div class="lesson-absolute-direct-template"><small>公式模板</small><strong>' + renderFormulaText(rule.template || "") + '</strong></div>' +
            '<div class="lesson-absolute-direct-slots"><small>题目变量对号入座</small><div>' + mappings.map(function (mapping) {
              return '<b>' + renderFormulaText(mapping) + '</b>';
            }).join('<i aria-hidden="true">＋</i>') + '</div></div>' +
            '<div class="lesson-absolute-direct-substitute"><span>代入</span><strong>' + renderFormulaText(rule.substituted || "") + '</strong></div>' +
            '<div class="lesson-absolute-direct-solve"><span>解一次不等式</span><strong>' + renderFormulaText(rule.solved || "") + '</strong></div>' +
            '<p class="lesson-absolute-direct-set"><span>解集</span><b>' + renderFormulaText(rule.solution || "") + '</b></p>' +
            '</article>'
          );
        }).join("");
        const intersection = visual.intersection;
        const intersectionMarkup = intersection ? (
          '<section class="lesson-absolute-direct-intersection">' +
          '<span>' + esc(intersection.label || "取交集") + '</span>' +
          '<strong>' + renderFormulaText(intersection.expression || "") + '</strong>' +
          '<i aria-hidden="true">↓</i>' +
          '<b>' + renderFormulaText(intersection.result || "") + '</b>' +
          '</section>'
        ) : "";
        return (
          '<figure class="lesson-step-visual lesson-step-absolute-direct-map is-' + esc(visual.mode || "single") + '" role="group" aria-label="' + ariaLabel + '">' +
          '<header class="lesson-absolute-direct-map-header"><span>' + esc(visual.method || "直接法") + '</span><h3>' + esc(visual.title || "绝对值不等式直接法") + '</h3></header>' +
          (visual.intro ? '<p class="lesson-absolute-direct-map-intro">' + renderFormulaText(visual.intro) + '</p>' : '') +
          '<section class="lesson-absolute-direct-original"><span>题目结构</span><strong>' + renderFormulaText(visual.original || "") + '</strong></section>' +
          '<div class="lesson-absolute-direct-rule-grid">' + ruleMarkup + '</div>' +
          intersectionMarkup +
          (visual.caption ? '<figcaption>' + renderFormulaText(visual.caption) + '</figcaption>' : '') +
          '</figure>'
        );
      }

      if (visual.kind === "number-line-reasoning") {
        const ticks = Array.isArray(visual.ticks) ? visual.ticks : [];
        const rows = Array.isArray(visual.rows) ? visual.rows : [];
        const xFor = function (position) { return 48 + Math.max(0, Math.min(1, Number(position))) * 464; };
        const rowMarkup = rows.map(function (row) {
          const y = 48;
          const segments = Array.isArray(row.segments) ? row.segments : [];
          const segmentMarkup = segments.map(function (segment) {
            const x1 = xFor(segment.start);
            const x2 = xFor(segment.end);
            const leftRay = segment.left === "ray";
            const rightRay = segment.right === "ray";
            const leftPoint = leftRay ? '<path class="lesson-number-line-ray" d="M' + x1 + ' ' + y + 'l12-7v14z"></path>' : '<circle class="lesson-number-line-endpoint ' + (segment.left === "closed" ? "is-closed" : "is-open") + '" cx="' + x1 + '" cy="' + y + '" r="7"></circle>';
            const rightPoint = rightRay ? '<path class="lesson-number-line-ray" d="M' + x2 + ' ' + y + 'l-12-7v14z"></path>' : '<circle class="lesson-number-line-endpoint ' + (segment.right === "closed" ? "is-closed" : "is-open") + '" cx="' + x2 + '" cy="' + y + '" r="7"></circle>';
            return '<line class="lesson-number-line-selected" x1="' + x1 + '" y1="' + y + '" x2="' + x2 + '" y2="' + y + '"></line>' + leftPoint + rightPoint;
          }).join("");
          const tickMarkup = ticks.map(function (tick) {
            const x = xFor(tick.position);
            return '<line class="lesson-number-line-tick" x1="' + x + '" y1="39" x2="' + x + '" y2="57"></line><text x="' + x + '" y="78">' + esc(tick.label) + '</text>';
          }).join("");
          return '<article><header><span>' + esc(row.label || "") + '</span><strong>' + renderFormulaText(row.condition || "") + '</strong></header><svg viewBox="0 0 560 92" role="img" aria-label="' + esc(row.ariaLabel || row.label || "解集数轴") + '"><line class="lesson-number-line-axis" x1="34" y1="48" x2="530" y2="48"></line><path class="lesson-number-line-axis-arrow" d="M530 48l-9-6m9 6l-9 6"></path><g>' + segmentMarkup + '</g><g class="lesson-number-line-ticks">' + tickMarkup + '</g></svg><p>' + renderFormulaText(row.set || "") + '</p></article>';
        }).join("");
        const implication = visual.implicationCheck;
        const implicationMarkup = implication && Array.isArray(implication.directions) ? (
          '<section class="lesson-implication-check" aria-label="充分条件和必要条件的双向检验">' +
          '<header><span>双向检验</span><h4>' + renderFormulaText(implication.title || "两个方向分别判断") + '</h4></header>' +
          '<div class="lesson-implication-map">' +
          '<svg viewBox="0 0 640 280" role="img" aria-label="条件之间的充分性与必要性双向箭头图">' +
          '<defs>' +
          '<marker id="lessonImplicationArrowTrue" markerWidth="11" markerHeight="11" refX="9" refY="5.5" orient="auto"><path d="M0 0L11 5.5L0 11z"></path></marker>' +
          '<marker id="lessonImplicationArrowFalse" markerWidth="11" markerHeight="11" refX="9" refY="5.5" orient="auto"><path d="M0 0L11 5.5L0 11z"></path></marker>' +
          '</defs>' +
          implication.directions.map(function (direction, index) {
            const state = direction.holds ? "is-true" : "is-false";
            const path = index === 0 ? "M142 132 C220 38 420 38 498 132" : "M498 148 C420 242 220 242 142 148";
            const markX = index === 0 ? 424 : 216;
            const markY = index === 0 ? 67 : 213;
            const markPath = direction.holds
              ? '<path d="M' + (markX - 7) + ' ' + markY + 'l5 5 10-12"></path>'
              : '<path d="M' + (markX - 6) + ' ' + (markY - 6) + 'l12 12m0-12l-12 12"></path>';
            return '<path class="lesson-implication-curve ' + state + '" d="' + path + '" marker-end="url(#lessonImplicationArrow' + (direction.holds ? "True" : "False") + ')"></path>' +
              '<g class="lesson-implication-mark ' + state + '"><circle cx="' + markX + '" cy="' + markY + '" r="15"></circle>' + markPath + '</g>';
          }).join("") +
          '</svg>' +
          '<b class="lesson-implication-node is-left">' + esc(implication.directions[0].from || "") + '</b>' +
          '<b class="lesson-implication-node is-right">' + esc(implication.directions[0].to || "") + '</b>' +
          implication.directions.map(function (direction, index) {
            const state = direction.holds ? "is-true" : "is-false";
            const conditionKind = /充分/.test(direction.question || "") ? "充分？" : (/必要/.test(direction.question || "") ? "必要？" : "是否成立？");
            return '<article class="lesson-implication-direction ' + (index === 0 ? "is-top " : "is-bottom ") + state + '">' +
              '<p><b>' + esc(direction.from || "") + ' ⇒ ' + esc(direction.to || "") + '</b><span>' + conditionKind + '</span><em>' + (direction.holds ? "成立 ✓" : "不成立 ✕") + '</em></p>' +
              '<div><strong>' + renderFormulaText(direction.setRelation || "") + '</strong><span>' + renderFormulaText(direction.reasoning || "") + '</span></div>' +
              '</article>';
          }).join("") +
          '</div>' +
          (implication.conclusion ? '<p class="lesson-implication-conclusion">' + renderFormulaText(implication.conclusion) + '</p>' : '') +
          '</section>'
        ) : "";
        return (
          '<figure class="lesson-step-visual lesson-step-number-line-reasoning" role="group" aria-label="' + ariaLabel + '">' +
          '<header><span>' + esc(visual.method || "数轴") + '</span><h3>' + renderFormulaText(visual.title || "把条件画成解集") + '</h3></header>' +
          (visual.intro ? '<p class="lesson-number-line-reasoning-intro">' + renderFormulaText(visual.intro) + '</p>' : '') +
          '<div class="lesson-number-line-reasoning-rows">' + rowMarkup + '</div>' +
          implicationMarkup +
          (visual.relation ? '<p class="lesson-number-line-relation">' + renderFormulaText(visual.relation) + '</p>' : '') +
          (visual.caption ? '<figcaption>' + renderFormulaText(visual.caption) + '</figcaption>' : '') +
          '</figure>'
        );
      }

      if (visual.kind === "quadratic-integer-window") {
        const integers = Array.isArray(visual.integers) ? visual.integers : [];
        const pointXs = [156, 280, 404];
        return (
          '<figure class="lesson-step-visual lesson-step-quadratic-window" role="group" aria-label="' + ariaLabel + '">' +
          '<header><span>数形结合</span><h3>' + renderFormulaText(visual.title || "抛物线不高于 x 轴的区间") + '</h3></header>' +
          '<div class="lesson-quadratic-window-formulas"><b>' + renderFormulaText(visual.original || "") + '</b><span aria-hidden="true">⇔</span><strong>' + renderFormulaText(visual.completedSquare || "") + '</strong></div>' +
          '<svg viewBox="0 0 560 270" role="img" aria-label="开口向上的抛物线与整数点 2、3、4"><line class="lesson-quadratic-window-axis" x1="36" y1="154" x2="524" y2="154"></line><path class="lesson-number-line-axis-arrow" d="M524 154l-9-6m9 6l-9 6"></path><path class="lesson-quadratic-window-curve" d="M78 42 Q280 308 482 42"></path><line class="lesson-quadratic-window-band" x1="156" y1="154" x2="404" y2="154"></line><circle class="lesson-quadratic-window-root" cx="156" cy="154" r="7"></circle><circle class="lesson-quadratic-window-root" cx="404" cy="154" r="7"></circle>' + integers.map(function (value, index) { return '<circle class="lesson-quadratic-window-integer" cx="' + pointXs[index] + '" cy="214" r="9"></circle><text class="lesson-quadratic-window-integer-label" x="' + pointXs[index] + '" y="218">' + esc(value) + '</text>'; }).join("") + '<text class="lesson-quadratic-window-root-label" x="156" y="179">2</text><text class="lesson-quadratic-window-root-label" x="404" y="179">4</text><text class="lesson-quadratic-window-caption" x="280" y="252">闭区间 [2,4] 中恰有 2、3、4 三个整数</text></svg>' +
          '<p class="lesson-quadratic-window-result">' + renderFormulaText(visual.conclusion || "") + '</p>' +
          '</figure>'
        );
      }

      if (visual.kind === "quadratic-symmetric-integer-window") {
        const included = Array.isArray(visual.included) ? visual.included : [];
        const excluded = Array.isArray(visual.excluded) ? visual.excluded : [];
        const checks = Array.isArray(visual.checks) ? visual.checks : [];
        const points = [excluded[0]].concat(included, [excluded[1]]);
        const pointXs = [100, 210, 320, 430, 540];
        const pointMarkup = points.map(function (value, index) {
          const x = pointXs[index];
          const isIncluded = included.indexOf(value) >= 0;
          return isIncluded
            ? '<circle class="lesson-symmetric-window-point is-included" cx="' + x + '" cy="174" r="8"></circle><text class="lesson-symmetric-window-point-label" x="' + x + '" y="202">' + esc(value || "") + '</text>'
            : '<g class="lesson-symmetric-window-point is-excluded"><path d="M' + (x - 7) + ' 167l14 14m0-14l-14 14"></path></g><text class="lesson-symmetric-window-point-label" x="' + x + '" y="202">' + esc(value || "") + '</text>';
        }).join("");
        return (
          '<figure class="lesson-step-visual lesson-step-quadratic-symmetric-window" role="group" aria-label="利用抛物线对称轴确定整数解和参数范围">' +
          '<header><span>数形结合</span><h3>' + renderFormulaText(visual.title || "由对称轴锁定整数解") + '</h3></header>' +
          '<section class="lesson-symmetric-window-axis"><div><span>01 找对称轴</span><strong>' + renderFormulaText(visual.function || "") + '</strong></div><div><b>' + renderFormulaText(visual.axis || "") + '</b><p>' + renderFormulaText(visual.movement || "") + '</p></div></section>' +
          '<section class="lesson-symmetric-window-plot"><header><span>02 锁定整数解</span><strong>' + renderFormulaText(visual.lockStatement || "由对称性确定应保留的整数点") + '</strong></header>' +
          '<svg viewBox="0 0 640 275" role="img" aria-label="对称轴为 3 的抛物线示意图，整数 2、3、4 在解集中，1、5 被排除">' +
          '<line class="lesson-symmetric-window-x-axis" x1="52" y1="174" x2="588" y2="174"></line><path class="lesson-number-line-axis-arrow" d="M588 174l-9-6m9 6l-9 6"></path>' +
          '<line class="lesson-symmetric-window-symmetry-axis" x1="320" y1="28" x2="320" y2="238"></line><text class="lesson-symmetric-window-axis-label" x="333" y="46">对称轴</text>' +
          '<path class="lesson-symmetric-window-curve" d="M66 34 Q320 408 574 34"></path>' +
          '<line class="lesson-symmetric-window-band" x1="210" y1="174" x2="430" y2="174"></line>' + pointMarkup +
          '<path class="lesson-symmetric-window-pair is-inner" d="M210 224 Q320 254 430 224"></path><text class="lesson-symmetric-window-pair-label is-inner" x="320" y="262">' + esc(visual.innerPairLabel || "内侧对称点") + '</text>' +
          '<path class="lesson-symmetric-window-pair is-outer" d="M100 148 Q320 76 540 148"></path><text class="lesson-symmetric-window-pair-label is-outer" x="320" y="88">' + esc(visual.outerPairLabel || "外侧对称点") + '</text>' +
          '</svg><p><b>●</b> 保留 ' + esc(included.join("、")) + '　　<em>×</em> 排除相邻的 ' + esc(excluded.join("、")) + '</p></section>' +
          '<section class="lesson-symmetric-window-checks"><header><span>03 检查边界</span><strong>利用对称性，每一对只需检查一侧</strong></header><div>' + checks.map(function (check) {
            return '<article><span>' + esc(check.role || "边界点") + '</span><h4>' + renderFormulaText(check.condition || "") + '</h4><p>' + renderFormulaText(check.symmetry || "") + '</p><div>' + renderFormulaText(check.calculation || "") + '<i aria-hidden="true">⇒</i><b>' + renderFormulaText(check.result || "") + '</b></div></article>';
          }).join("") + '</div></section>' +
          '<div class="lesson-symmetric-window-result"><span>' + renderFormulaText(visual.range || "") + '</span><i aria-hidden="true">＋</i><span>' + renderFormulaText(visual.integerValues || "") + '</span><i aria-hidden="true">⇒</i><strong>' + renderFormulaText(visual.conclusion || "") + '</strong></div>' +
          '<figcaption>' + renderFormulaText(visual.caption || "先由对称性锁定整数点，再用内外边界确定参数。") + '</figcaption>' +
          '</figure>'
        );
      }

      if (visual.kind === "difference-factor-sign") {
        const factors = Array.isArray(visual.factors) ? visual.factors : [];
        return (
          '<figure class="lesson-step-visual lesson-step-factor-sign" role="group" aria-label="' + ariaLabel + '">' +
          '<header><span>作差法</span><h3>' + renderFormulaText(visual.title || "把差化成符号明确的因式") + '</h3></header>' +
          '<div class="lesson-factor-sign-chain"><b>' + renderFormulaText(visual.difference || "") + '</b><span aria-hidden="true">=</span><strong>' + renderFormulaText(visual.factorization || "") + '</strong></div>' +
          '<div class="lesson-factor-sign-cards">' + factors.map(function (factor) { return '<article><span>' + esc(factor.label || "因式") + '</span><strong>' + renderFormulaText(factor.expression || "") + '</strong><p>' + renderFormulaText(factor.sign || "") + '</p></article>'; }).join("") + '</div>' +
          '<div class="lesson-factor-sign-conclusion"><span aria-hidden="true">⇒</span><strong>' + renderFormulaText(visual.conclusion || "") + '</strong><p>' + renderFormulaText(visual.equality || "") + '</p></div>' +
          '</figure>'
        );
      }

      if (visual.kind === "product-range-plane") {
        return (
          '<figure class="lesson-step-visual lesson-step-product-plane" role="group" aria-label="' + ariaLabel + '">' +
          '<header><span>二维范围</span><h3>' + renderFormulaText(visual.title || "在取值矩形的角点寻找乘积极值") + '</h3></header>' +
          '<p class="lesson-product-plane-intro">' + renderFormulaText(visual.intro || "") + '</p>' +
          '<svg viewBox="0 0 560 320" role="img" aria-label="a 从负 2 到负 1、b 从 1 到 3 的开矩形及四个角点乘积"><defs><marker id="product-plane-arrow" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto"><path d="M0,0 L0,6 L7,3 z"></path></marker></defs><line class="lesson-product-plane-axis" x1="52" y1="260" x2="520" y2="260"></line><line class="lesson-product-plane-axis" x1="420" y1="286" x2="420" y2="36"></line><path class="lesson-number-line-axis-arrow" d="M520 260l-9-6m9 6l-9 6"></path><path class="lesson-number-line-axis-arrow" d="M420 36l-6 9m6-9l6 9"></path><rect class="lesson-product-plane-region" x="154" y="78" width="188" height="142" rx="4"></rect><g class="lesson-product-plane-corners"><circle cx="154" cy="78" r="7"></circle><circle cx="342" cy="78" r="7"></circle><circle cx="154" cy="220" r="7"></circle><circle cx="342" cy="220" r="7"></circle></g><g class="lesson-product-plane-labels"><text x="154" y="282">−2</text><text x="342" y="282">−1</text><text x="438" y="224">1</text><text x="438" y="82">3</text><text x="506" y="248">a</text><text x="438" y="48">b</text><text x="116" y="65">(−2)·3→−6</text><text x="364" y="65">(−1)·3→−3</text><text x="112" y="246">(−2)·1→−2</text><text x="354" y="246">(−1)·1→−1</text></g><path class="lesson-product-plane-min-arrow" d="M280 144 C238 119 202 98 166 83"></path><path class="lesson-product-plane-max-arrow" d="M280 164 C311 188 328 204 338 216"></path><text class="lesson-product-plane-min-text" x="266" y="125">最小端</text><text class="lesson-product-plane-max-text" x="286" y="197">最大端</text></svg>' +
          '<div class="lesson-product-plane-result"><b>' + renderFormulaText(visual.lower || "") + '</b><span aria-hidden="true">＜ ab ＜</span><b>' + renderFormulaText(visual.upper || "") + '</b></div>' +
          '<figcaption>' + renderFormulaText(visual.caption || "边界未取到，所以乘积的两个端点也不取。") + '</figcaption>' +
          '</figure>'
        );
      }

      if (visual.kind === "positive-interval-product-chain") {
        const normalize = visual.normalize || {};
        const multiply = visual.multiply || {};
        const restore = visual.restore || {};
        const multiplyRows = Array.isArray(multiply.rows) ? multiply.rows : [];
        const transformCard = function (number, title, source, factor, rule, result, className) {
          return '<section class="lesson-interval-product-transform ' + className + '"><header><span>' + number + '</span><h4>' + title + '</h4></header><div><strong>' + renderFormulaText(source || "") + '</strong><aside><b>' + renderFormulaText(factor || "") + '</b><small>' + renderFormulaText(rule || "") + '</small><i aria-hidden="true">⇒</i></aside><strong>' + renderFormulaText(result || "") + '</strong></div></section>';
        };
        return (
          '<figure class="lesson-step-visual lesson-step-positive-interval-product" role="group" aria-label="把负区间正化后使用同向正不等式相乘">' +
          '<header><span>不等式性质</span><h3>' + renderFormulaText(visual.title || "正化后相乘，再还原符号") + '</h3></header>' +
          transformCard("01", "正化负区间", normalize.source, normalize.factor, normalize.rule, normalize.result, "is-normalize") +
          '<section class="lesson-interval-product-multiply"><header><span>02</span><h4>同向正不等式相乘</h4></header>' +
          '<div class="lesson-interval-product-positive"><span>先检查正数条件</span><b>' + renderFormulaText(multiply.positivity || "") + '</b><em>✓</em></div>' +
          '<div class="lesson-interval-product-rows">' + multiplyRows.map(function (row) { return '<strong>' + renderFormulaText(row) + '</strong>'; }).join("") + '</div>' +
          '<p class="lesson-interval-product-rule"><span>性质</span>' + renderFormulaText(multiply.rule || "") + '</p>' +
          '<div class="lesson-interval-product-product"><strong>' + renderFormulaText(multiply.expanded || "") + '</strong><i aria-hidden="true">⇒</i><b>' + renderFormulaText(multiply.result || "") + '</b></div>' +
          '</section>' +
          transformCard("03", "还原乘积符号", restore.source, restore.factor, restore.rule, restore.result, "is-restore") +
          '<p class="lesson-interval-product-conclusion"><span>取值范围</span><strong>' + renderFormulaText(visual.conclusion || "") + '</strong></p>' +
          '<figcaption>' + renderFormulaText(visual.caption || "") + '</figcaption>' +
          '</figure>'
        );
      }

      if (visual.kind === "absolute-case-analysis") {
        const breakpoints = Array.isArray(visual.breakpoints) ? visual.breakpoints : [];
        const cases = Array.isArray(visual.cases) ? visual.cases : [];
        const graph = visual.graph || {};
        const xRange = Array.isArray(graph.xRange) ? graph.xRange : [-1, 1];
        const yRange = Array.isArray(graph.yRange) ? graph.yRange : [-1, 1];
        const pieces = Array.isArray(graph.pieces) ? graph.pieces : [];
        const ticks = Array.isArray(graph.ticks) ? graph.ticks : [];
        const solutionSegments = Array.isArray(graph.solutionSegments) ? graph.solutionSegments : [];
        const threshold = graph.threshold || {};
        const xMin = Number(xRange[0]);
        const xMax = Number(xRange[1]);
        const yMin = Number(yRange[0]);
        const yMax = Number(yRange[1]);
        const xFor = function (value) { return 54 + (Number(value) - xMin) / (xMax - xMin) * 452; };
        const yFor = function (value) { return 24 + (yMax - Number(value)) / (yMax - yMin) * 166; };
        const zeroX = xFor(Math.max(xMin, Math.min(xMax, 0)));
        const zeroY = yFor(Math.max(yMin, Math.min(yMax, 0)));
        const piecePaths = pieces.map(function (piece) {
          return 'M' + xFor(piece.from) + ' ' + yFor(piece.slope * piece.from + piece.intercept) +
            ' L' + xFor(piece.to) + ' ' + yFor(piece.slope * piece.to + piece.intercept);
        }).join(" ");
        const thresholdIntersections = [];
        pieces.forEach(function (piece) {
          if (Math.abs(piece.slope) < 1e-9) return;
          const value = (Number(threshold.value) - piece.intercept) / piece.slope;
          if (value >= piece.from - 1e-9 && value <= piece.to + 1e-9 && !thresholdIntersections.some(function (item) { return Math.abs(item - value) < 1e-8; })) {
            thresholdIntersections.push(value);
          }
        });
        const breakpointMarkup = breakpoints.map(function (point, index) {
          return '<article><span>零点 ' + (index + 1) + '</span><strong>' + renderFormulaText(point.equation || "") + '</strong><i aria-hidden="true">⇒</i><b>' + renderFormulaText(point.value || "") + '</b></article>';
        }).join("");
        const caseMarkup = cases.map(function (item) {
          return '<tr><th scope="row"><span>' + esc(item.index || "") + '</span><strong>' + renderFormulaText(item.interval || "") + '</strong></th>' +
            '<td>' + renderFormulaText(item.signs || "") + '</td><td>' + renderFormulaText(item.rewrite || "") + '</td>' +
            '<td><span>' + renderFormulaText(item.inequality || "") + '</span><b>' + renderFormulaText(item.result || "") + '</b></td></tr>';
        }).join("");
        const solutionMarkup = solutionSegments.map(function (segment) {
          const start = segment.start === null ? xMin : segment.start;
          const end = segment.end === null ? xMax : segment.end;
          const x1 = xFor(start);
          const x2 = xFor(end);
          const left = segment.left === "ray"
            ? '<path class="lesson-absolute-case-ray" d="M' + x1 + ' 226l12-7v14z"></path>'
            : '<circle class="lesson-absolute-case-endpoint ' + (segment.left === "closed" ? "is-closed" : "is-open") + '" cx="' + x1 + '" cy="226" r="6"></circle>';
          const right = segment.right === "ray"
            ? '<path class="lesson-absolute-case-ray" d="M' + x2 + ' 226l-12-7v14z"></path>'
            : '<circle class="lesson-absolute-case-endpoint ' + (segment.right === "closed" ? "is-closed" : "is-open") + '" cx="' + x2 + '" cy="226" r="6"></circle>';
          return '<line class="lesson-absolute-case-solution-line" x1="' + x1 + '" y1="226" x2="' + x2 + '" y2="226"></line>' + left + right;
        }).join("");
        const graphMarkup = (
          '<section class="lesson-absolute-case-graph"><header><span>03 图像核对</span><h4>把分段函数画出来，检查交点与解集</h4></header>' +
          '<svg viewBox="0 0 560 250" role="img" aria-label="由分类讨论结果绘制的分段函数图像与阈值线"><line class="lesson-absolute-case-axis" x1="34" y1="' + zeroY + '" x2="526" y2="' + zeroY + '"></line><line class="lesson-absolute-case-axis" x1="' + zeroX + '" y1="204" x2="' + zeroX + '" y2="16"></line><path class="lesson-number-line-axis-arrow" d="M526 ' + zeroY + 'l-9-6m9 6l-9 6"></path><path class="lesson-number-line-axis-arrow" d="M' + zeroX + ' 16l-6 9m6-9l6 9"></path>' +
          '<line class="lesson-absolute-case-threshold" x1="40" y1="' + yFor(threshold.value) + '" x2="520" y2="' + yFor(threshold.value) + '"></line><text class="lesson-absolute-case-threshold-label" x="510" y="' + (yFor(threshold.value) - 7) + '">' + esc(threshold.label || "") + '</text>' +
          '<path class="lesson-absolute-case-function" d="' + piecePaths + '"></path>' +
          '<g class="lesson-absolute-case-guides">' + breakpoints.map(function (point) { const x = xFor(point.numeric); return '<line x1="' + x + '" y1="26" x2="' + x + '" y2="204"></line>'; }).join("") + '</g>' +
          '<g class="lesson-absolute-case-intersections">' + thresholdIntersections.map(function (value) { return '<circle cx="' + xFor(value) + '" cy="' + yFor(threshold.value) + '" r="6"></circle>'; }).join("") + '</g>' +
          '<g class="lesson-absolute-case-ticks">' + ticks.map(function (tick) { const x = xFor(tick.value); return '<line x1="' + x + '" y1="' + (zeroY - 6) + '" x2="' + x + '" y2="' + (zeroY + 6) + '"></line><text x="' + x + '" y="' + (zeroY + 20) + '">' + esc(tick.label || "") + '</text>'; }).join("") + '</g>' +
          '<g class="lesson-absolute-case-solution">' + solutionMarkup + '</g><text class="lesson-absolute-case-axis-label" x="520" y="' + (zeroY - 10) + '">x</text><text class="lesson-absolute-case-axis-label" x="' + (zeroX + 10) + '" y="24">y</text></svg>' +
          '<p>交点由分段函数计算，不单独手填位置。</p></section>'
        );
        return (
          '<figure class="lesson-step-visual lesson-step-absolute-case-analysis" role="group" aria-label="绝对值不等式分类讨论与函数图像核对">' +
          '<header><span>' + esc(visual.method || "分类讨论法") + '</span><h3>' + esc(visual.title || "找零点分区，逐段去绝对值") + '</h3></header>' +
          (visual.intro ? '<p class="lesson-absolute-case-intro">' + renderFormulaText(visual.intro) + '</p>' : '') +
          '<section class="lesson-absolute-case-original"><span>题目结构</span><strong>' + renderFormulaText(visual.original || "") + '</strong></section>' +
          '<section class="lesson-absolute-case-breakpoints"><header><span>01 找零点</span><h4>零点把数轴切成 ' + (breakpoints.length + 1) + ' 个区间</h4></header><div>' + breakpointMarkup + '</div></section>' +
          '<section class="lesson-absolute-case-table"><header><span>02 分类讨论</span><h4>逐段判断符号、去绝对值并求解</h4></header><div><table><thead><tr><th>区间</th><th>内部符号</th><th>去绝对值</th><th>段内结果</th></tr></thead><tbody>' + caseMarkup + '</tbody></table></div></section>' +
          graphMarkup +
          '<section class="lesson-absolute-case-merge"><span>' + esc(visual.merge?.label || "合并各段") + '</span><strong>' + renderFormulaText(visual.merge?.result || "") + '</strong></section>' +
          (visual.caption ? '<figcaption>' + renderFormulaText(visual.caption) + '</figcaption>' : '') +
          '</figure>'
        );
      }

      if (visual.kind === "piecewise-threshold-graph") {
        const points = Array.isArray(visual.points) ? visual.points : [];
        const ticks = Array.isArray(visual.ticks) ? visual.ticks : [];
        const intersections = Array.isArray(visual.intersections) ? visual.intersections : [];
        const segments = Array.isArray(visual.solutionSegments) ? visual.solutionSegments : [];
        const xFor = function (value) { return 42 + Number(value) * 476; };
        const yFor = function (value) { return 32 + (1 - Number(value)) * 164; };
        const path = points.map(function (point, index) { return (index ? "L" : "M") + xFor(point.x) + " " + yFor(point.y); }).join(" ");
        return (
          '<figure class="lesson-step-visual lesson-step-piecewise-threshold" role="group" aria-label="' + ariaLabel + '">' +
          '<header><span>分段函数图像</span><h3>' + renderFormulaText(visual.title || "画出绝对值函数并与阈值比较") + '</h3></header>' +
          '<div class="lesson-piecewise-threshold-formulas">' + (visual.transformations || []).map(function (line) { return '<p>' + renderFormulaText(line) + '</p>'; }).join("") + '</div>' +
          '<svg viewBox="0 0 560 260" role="img" aria-label="' + esc(visual.graphAriaLabel || "分段折线与阈值线") + '"><line class="lesson-piecewise-x-axis" x1="30" y1="196" x2="532" y2="196"></line><line class="lesson-piecewise-y-axis" x1="280" y1="218" x2="280" y2="20"></line><path class="lesson-number-line-axis-arrow" d="M532 196l-9-6m9 6l-9 6"></path><path class="lesson-number-line-axis-arrow" d="M280 20l-6 9m6-9l6 9"></path><line class="lesson-piecewise-threshold-line" x1="38" y1="' + yFor(visual.thresholdY) + '" x2="522" y2="' + yFor(visual.thresholdY) + '"></line><text class="lesson-piecewise-threshold-label" x="500" y="' + (yFor(visual.thresholdY) - 8) + '">' + esc(visual.thresholdLabel || "") + '</text><path class="lesson-piecewise-function-line" d="' + path + '"></path><g class="lesson-piecewise-intersections">' + intersections.map(function (point) { return '<circle cx="' + xFor(point.x) + '" cy="' + yFor(point.y) + '" r="6"></circle>'; }).join("") + '</g><g class="lesson-piecewise-ticks">' + ticks.map(function (tick) { const x=xFor(tick.x); return '<line x1="' + x + '" y1="188" x2="' + x + '" y2="204"></line><text x="' + x + '" y="224">' + esc(tick.label) + '</text>'; }).join("") + '</g><g class="lesson-piecewise-solution-segments">' + segments.map(function (segment) { const x1=xFor(segment.start), x2=xFor(segment.end); return '<line x1="' + x1 + '" y1="242" x2="' + x2 + '" y2="242"></line>' + (segment.left === "ray" ? '<path d="M' + x1 + ' 242l12-7v14z"></path>' : '<circle class="' + (segment.left === "closed" ? "is-closed" : "is-open") + '" cx="' + x1 + '" cy="242" r="7"></circle>') + (segment.right === "ray" ? '<path d="M' + x2 + ' 242l-12-7v14z"></path>' : '<circle class="' + (segment.right === "closed" ? "is-closed" : "is-open") + '" cx="' + x2 + '" cy="242" r="7"></circle>'); }).join("") + '</g><text class="lesson-piecewise-axis-label" x="524" y="185">x</text><text class="lesson-piecewise-axis-label" x="293" y="28">y</text></svg>' +
          '<p class="lesson-piecewise-result"><span>读图</span><strong>' + renderFormulaText(visual.solution || "") + '</strong></p>' +
          '<figcaption>' + renderFormulaText(visual.caption || "") + '</figcaption>' +
          '</figure>'
        );
      }

      if (visual.kind === "polynomial-threading-graph") {
        const roots = Array.isArray(visual.roots) ? visual.roots : [];
        const signs = Array.isArray(visual.signs) ? visual.signs : [];
        const axisY = 96;
        const startX = 32;
        const endX = 528;
        const firstRootX = roots.length === 1 ? 280 : 118;
        const lastRootX = roots.length === 1 ? 280 : 442;
        const rootXs = roots.map(function (_root, index) {
          if (roots.length === 1) return firstRootX;
          return firstRootX + (lastRootX - firstRootX) * index / (roots.length - 1);
        });
        const signY = function (sign) { return sign === "+" ? 43 : 149; };
        const controlY = function (sign) { return sign === "+" ? 4 : 188; };
        const curveParts = [];
        if (rootXs.length) {
          curveParts.push(
            "M" + startX + " " + signY(signs[0]) +
            " C" + (rootXs[0] - 52) + " " + signY(signs[0]) +
            " " + (rootXs[0] - 24) + " " + axisY +
            " " + rootXs[0] + " " + axisY,
          );
          for (let index = 0; index < rootXs.length - 1; index += 1) {
            const middleX = (rootXs[index] + rootXs[index + 1]) / 2;
            curveParts.push(
              " Q" + middleX + " " + controlY(signs[index + 1]) +
              " " + rootXs[index + 1] + " " + axisY,
            );
          }
          const lastSign = signs[signs.length - 1];
          curveParts.push(
            " C" + (rootXs[rootXs.length - 1] + 24) + " " + axisY +
            " " + (endX - 52) + " " + signY(lastSign) +
            " " + endX + " " + signY(lastSign),
          );
        }
        const intervalBounds = [startX].concat(rootXs, [endX]);
        const selectedIntervals = signs.map(function (sign, index) {
          return sign === visual.selectSign ? index : -1;
        }).filter(function (index) { return index >= 0; });
        const intervalCurvePath = function (index) {
          if (index === 0) {
            return "M" + startX + " " + signY(signs[0]) +
              " C" + (rootXs[0] - 52) + " " + signY(signs[0]) +
              " " + (rootXs[0] - 24) + " " + axisY +
              " " + rootXs[0] + " " + axisY +
              " L" + startX + " " + axisY + " Z";
          }
          if (index === roots.length) {
            const lastRootX = rootXs[rootXs.length - 1];
            return "M" + lastRootX + " " + axisY +
              " C" + (lastRootX + 24) + " " + axisY +
              " " + (endX - 52) + " " + signY(signs[index]) +
              " " + endX + " " + signY(signs[index]) +
              " L" + endX + " " + axisY + " Z";
          }
          const leftX = rootXs[index - 1];
          const rightX = rootXs[index];
          return "M" + leftX + " " + axisY +
            " Q" + ((leftX + rightX) / 2) + " " + controlY(signs[index]) +
            " " + rightX + " " + axisY +
            " L" + leftX + " " + axisY + " Z";
        };
        const shades = selectedIntervals.map(function (index) {
          return '<path d="' + intervalCurvePath(index) + '"></path>';
        }).join("");
        const solutionSegments = selectedIntervals.map(function (index) {
          return '<line x1="' + intervalBounds[index] + '" y1="' + axisY + '" x2="' + intervalBounds[index + 1] + '" y2="' + axisY + '"></line>';
        }).join("");
        const rootPoints = roots.map(function (root, index) {
          return '<circle class="' + (visual.inclusive ? 'is-included' : 'is-excluded') + '" cx="' + rootXs[index] + '" cy="' + axisY + '" r="6"></circle>' +
            (root.multiplicity % 2 === 0 ? '<circle class="lesson-threading-even-ring" cx="' + rootXs[index] + '" cy="' + axisY + '" r="11"></circle>' : '');
        }).join("");
        const rootLabels = roots.map(function (root, index) {
          const parity = root.multiplicity % 2 === 0 ? "偶" : "奇";
          return '<text class="lesson-threading-root-value" x="' + rootXs[index] + '" y="122">' + esc(root.label) + '</text>' +
            '<text class="lesson-threading-root-order" x="' + rootXs[index] + '" y="139">（' + root.multiplicity + '次·' + parity + '）</text>';
        }).join("");
        const intervalSignXs = intervalBounds.slice(0, -1).map(function (left, index) {
          return (left + intervalBounds[index + 1]) / 2;
        });
        const signLabels = signs.map(function (sign, index) {
          return '<text x="' + intervalSignXs[index] + '" y="' + (sign === "+" ? 31 : 173) + '">' + (sign === "+" ? "+" : "−") + '</text>';
        }).join("");
        const facts = Array.isArray(visual.facts) && visual.facts.length
          ? '<ol class="lesson-threading-facts">' + visual.facts.map(function (fact) {
            return '<li>' + renderFormulaText(fact) + '</li>';
          }).join("") + '</ol>'
          : "";
        return (
          '<figure class="lesson-step-visual lesson-step-polynomial-threading" role="group" aria-label="' + ariaLabel + '">' +
          (visual.title ? '<h3>' + renderFormulaText(visual.title) + '</h3>' : '') +
          (visual.intro ? '<p class="lesson-threading-intro">' + renderFormulaText(visual.intro) + '</p>' : '') +
          '<p class="lesson-threading-standard"><span>标准化</span>' + renderFormulaText(visual.standardized || "") + '</p>' +
          '<svg viewBox="0 0 560 190" role="img" aria-label="' + ariaLabel + '">' +
          '<g class="lesson-threading-shades">' + shades + '</g>' +
          '<line class="lesson-threading-axis" x1="20" y1="' + axisY + '" x2="542" y2="' + axisY + '"></line>' +
          '<path class="lesson-threading-axis-arrow" d="M542 ' + axisY + 'l-9-6m9 6l-9 6"></path>' +
          '<g class="lesson-threading-solutions">' + solutionSegments + '</g>' +
          '<path class="lesson-threading-curve" d="' + curveParts.join("") + '"></path>' +
          '<g class="lesson-threading-start"><text x="402" y="16">从最右侧开始穿</text><path d="M520 22 C500 27 478 39 458 55"></path><path d="M458 55l4-10m-4 10l10-2"></path></g>' +
          '<g class="lesson-threading-points">' + rootPoints + '</g>' +
          '<g class="lesson-threading-labels">' + rootLabels + '</g>' +
          '<g class="lesson-threading-signs">' + signLabels + '</g>' +
          '</svg>' +
          facts +
          '<p class="lesson-threading-result"><span>' + renderFormulaText(visual.target || "") + '</span><strong>解集：' + renderFormulaText(visual.solution || "") + '</strong></p>' +
          (visual.caption ? '<figcaption>' + renderFormulaText(visual.caption) + '</figcaption>' : '') +
          '</figure>'
        );
      }

      if (visual.kind === "rational-threading-graph") {
        const roots = Array.isArray(visual.roots) ? visual.roots : [];
        const signs = Array.isArray(visual.signs) ? visual.signs : [];
        const axisY = 96;
        const startX = 32;
        const endX = 528;
        const firstRootX = roots.length === 1 ? 280 : 118;
        const lastRootX = roots.length === 1 ? 280 : 442;
        const rootXs = roots.map(function (_root, index) {
          if (roots.length === 1) return firstRootX;
          return firstRootX + (lastRootX - firstRootX) * index / (roots.length - 1);
        });
        const signY = function (sign) { return sign === "+" ? 42 : 150; };
        const controlY = function (sign) { return sign === "+" ? 4 : 188; };
        const curveParts = [];
        if (rootXs.length) {
          curveParts.push("M" + startX + " " + signY(signs[0]) + " C" + (rootXs[0] - 52) + " " + signY(signs[0]) + " " + (rootXs[0] - 24) + " " + axisY + " " + rootXs[0] + " " + axisY);
          for (let index = 0; index < rootXs.length - 1; index += 1) {
            curveParts.push(" Q" + ((rootXs[index] + rootXs[index + 1]) / 2) + " " + controlY(signs[index + 1]) + " " + rootXs[index + 1] + " " + axisY);
          }
          const lastSign = signs[signs.length - 1];
          curveParts.push(" C" + (rootXs[rootXs.length - 1] + 24) + " " + axisY + " " + (endX - 52) + " " + signY(lastSign) + " " + endX + " " + signY(lastSign));
        }
        const curvePath = curveParts.join("");
        const intervalBounds = [startX].concat(rootXs, [endX]);
        const intervalPath = function (index) {
          if (index === 0) return "M" + startX + " " + signY(signs[0]) + " C" + (rootXs[0] - 52) + " " + signY(signs[0]) + " " + (rootXs[0] - 24) + " " + axisY + " " + rootXs[0] + " " + axisY + " L" + startX + " " + axisY + " Z";
          if (index === roots.length) {
            const lastRootX = rootXs[rootXs.length - 1];
            return "M" + lastRootX + " " + axisY + " C" + (lastRootX + 24) + " " + axisY + " " + (endX - 52) + " " + signY(signs[index]) + " " + endX + " " + signY(signs[index]) + " L" + endX + " " + axisY + " Z";
          }
          const leftX = rootXs[index - 1];
          const rightX = rootXs[index];
          return "M" + leftX + " " + axisY + " Q" + ((leftX + rightX) / 2) + " " + controlY(signs[index]) + " " + rightX + " " + axisY + " L" + leftX + " " + axisY + " Z";
        };
        const selectedIntervals = signs.map(function (sign, index) {
          return sign === visual.selectSign ? index : -1;
        }).filter(function (index) { return index >= 0; });
        const shades = selectedIntervals.map(function (index) {
          return '<path d="' + intervalPath(index) + '"></path>';
        }).join("");
        const solutionSegments = selectedIntervals.map(function (index) {
          return '<line x1="' + intervalBounds[index] + '" y1="96" x2="' + intervalBounds[index + 1] + '" y2="96"></line>';
        }).join("");
        const rootPoints = roots.map(function (root, index) {
          const pointClass = root.kind === "denominator"
            ? "is-forbidden"
            : root.included
              ? "is-included"
              : "is-excluded";
          const forbiddenMark = root.kind === "denominator"
            ? '<path class="lesson-rational-forbidden-mark" d="M' + (rootXs[index] - 5) + ' 91l10 10m-10 0l10-10"></path>'
            : "";
          return '<circle class="' + pointClass + '" cx="' + rootXs[index] + '" cy="96" r="7"></circle>' + forbiddenMark;
        }).join("");
        const rootLabels = roots.map(function (root, index) {
          const kindLabel = root.kind === "denominator" ? "分母·禁值" : "分子·零点";
          return '<text class="lesson-threading-root-value" x="' + rootXs[index] + '" y="124">' + esc(root.label) + '</text>' +
            '<text class="lesson-rational-root-kind ' + (root.kind === "denominator" ? 'is-forbidden' : 'is-zero') + '" x="' + rootXs[index] + '" y="141">（' + kindLabel + '）</text>';
        }).join("");
        const signXs = intervalBounds.slice(0, -1).map(function (left, index) { return (left + intervalBounds[index + 1]) / 2; });
        const signLabels = signs.map(function (sign, index) {
          return '<text x="' + signXs[index] + '" y="' + (sign === "+" ? 31 : 174) + '">' + (sign === "+" ? "+" : "−") + '</text>';
        }).join("");
        const denominatorEvidence = visual.denominatorEvidence
          ? '<aside class="lesson-rational-denominator-evidence">' +
            '<div><span>辅助判断</span><strong>' + renderFormulaText(visual.denominatorEvidence.expression) + '</strong><p>' + renderFormulaText(visual.denominatorEvidence.conclusion) + '</p></div>' +
            '<svg viewBox="0 0 180 105" role="img" aria-label="分母对应的二次函数恒在 x 轴上方">' +
            '<line x1="12" y1="76" x2="168" y2="76"></line><path class="lesson-rational-mini-axis-arrow" d="M168 76l-8-5m8 5l-8 5"></path>' +
            '<line x1="90" y1="94" x2="90" y2="10"></line><path class="lesson-rational-mini-axis-arrow" d="M90 10l-5 8m5-8l5 8"></path>' +
            '<path class="lesson-rational-mini-curve" d="M24 18 Q90 74 156 18"></path>' +
            '<text x="158" y="69">x</text><text x="100" y="16">y</text><text class="lesson-rational-mini-note" x="90" y="100">a&gt;0，Δ&lt;0</text>' +
            '</svg></aside>'
          : "";
        const facts = Array.isArray(visual.facts) && visual.facts.length
          ? '<ol class="lesson-threading-facts">' + visual.facts.map(function (fact) {
            return '<li>' + renderFormulaText(fact) + '</li>';
          }).join("") + '</ol>'
          : "";
        return (
          '<figure class="lesson-step-visual lesson-step-polynomial-threading lesson-step-rational-threading" role="group" aria-label="' + ariaLabel + '">' +
          (visual.title ? '<h3>' + renderFormulaText(visual.title) + '</h3>' : '') +
          (visual.intro ? '<p class="lesson-threading-intro">' + renderFormulaText(visual.intro) + '</p>' : '') +
          denominatorEvidence +
          '<p class="lesson-threading-standard"><span>移项通分</span>' + renderFormulaText(visual.standardized || "") + '</p>' +
          '<svg viewBox="0 0 560 190" role="img" aria-label="' + ariaLabel + '">' +
          '<g class="lesson-threading-shades">' + shades + '</g>' +
          '<line class="lesson-threading-axis" x1="20" y1="96" x2="542" y2="96"></line>' +
          '<path class="lesson-threading-axis-arrow" d="M542 96l-9-6m9 6l-9 6"></path>' +
          '<g class="lesson-threading-solutions">' + solutionSegments + '</g>' +
          '<path class="lesson-threading-curve" d="' + curvePath + '"></path>' +
          '<g class="lesson-threading-start"><text x="402" y="16">从最右侧开始穿</text><path d="M520 22 C500 27 478 39 458 55"></path><path d="M458 55l4-10m-4 10l10-2"></path></g>' +
          '<g class="lesson-threading-points lesson-rational-points">' + rootPoints + '</g>' +
          '<g class="lesson-threading-labels">' + rootLabels + '</g>' +
          '<g class="lesson-threading-signs">' + signLabels + '</g>' +
          '</svg>' +
          facts +
          '<p class="lesson-threading-result"><span>' + renderFormulaText(visual.target || "") + '</span><strong>解集：' + renderFormulaText(visual.solution || "") + '</strong></p>' +
          (visual.caption ? '<figcaption>' + renderFormulaText(visual.caption) + '</figcaption>' : '') +
          '</figure>'
        );
      }

      if (visual.kind === "absolute-inequality-visual") {
        const transformations = Array.isArray(visual.transformations) && visual.transformations.length
          ? '<div class="lesson-absolute-transformations"><span>转化</span><div>' + visual.transformations.map(function (line) {
            return '<p>' + renderFormulaText(line) + '</p>';
          }).join("") + '</div></div>'
          : "";
        const facts = Array.isArray(visual.facts) && visual.facts.length
          ? '<ol class="lesson-threading-facts lesson-absolute-facts">' + visual.facts.map(function (fact) {
            return '<li>' + renderFormulaText(fact) + '</li>';
          }).join("") + '</ol>'
          : "";
        let graph = "";
        if (visual.mode === "direct-inclusion") {
          const tickLabels = visual.tickLabels;
          graph = (
            '<div class="lesson-absolute-set-legend"><div><span>条件 p</span>' + renderFormulaText(visual.outerCondition) + '</div><div><span>条件 q</span>' + renderFormulaText(visual.innerCondition) + '</div></div>' +
            '<svg class="lesson-absolute-direct-graph" viewBox="0 0 560 190" role="img" aria-label="两个条件解集的数轴包含关系">' +
            '<text class="lesson-absolute-row-label" x="32" y="57">p</text><line class="lesson-threading-axis" x1="72" y1="52" x2="530" y2="52"></line><path class="lesson-threading-axis-arrow" d="M530 52l-8-5m8 5l-8 5"></path>' +
            '<g class="lesson-absolute-set-segments is-outer"><line x1="76" y1="52" x2="190" y2="52"></line><line x1="330" y1="52" x2="526" y2="52"></line></g>' +
            '<g class="lesson-absolute-set-points is-open"><circle cx="190" cy="52" r="6"></circle><circle cx="330" cy="52" r="6"></circle></g>' +
            '<text class="lesson-absolute-row-label" x="32" y="127">q</text><line class="lesson-threading-axis" x1="72" y1="122" x2="530" y2="122"></line><path class="lesson-threading-axis-arrow" d="M530 122l-8-5m8 5l-8 5"></path>' +
            '<g class="lesson-absolute-set-segments is-inner"><line x1="330" y1="122" x2="458" y2="122"></line></g>' +
            '<g class="lesson-absolute-set-points is-open"><circle cx="330" cy="122" r="6"></circle><circle cx="458" cy="122" r="6"></circle></g>' +
            '<g class="lesson-absolute-tick-labels"><text x="190" y="76">' + esc(tickLabels[0]) + '</text><text x="330" y="146">' + esc(tickLabels[1]) + '</text><text x="458" y="146">' + esc(tickLabels[2]) + '</text></g>' +
            '<path class="lesson-absolute-containment-arrow" d="M416 103 C403 88 387 78 365 67"></path><path class="lesson-absolute-containment-arrow" d="M365 67l5 10m-5-10l11 1"></path>' +
            '<text class="lesson-absolute-containment-label" x="426" y="90">q ⊊ p</text>' +
            '<text class="lesson-absolute-set-caption" x="280" y="178">q 的每个取值都属于 p，但 p 还包含更多取值</text>' +
            '</svg>'
          );
        } else if (visual.mode === "rhs-sign-classification") {
          const branches = visual.branches;
          const tickLabels = visual.tickLabels;
          graph = (
            '<div class="lesson-absolute-branch-grid">' + branches.map(function (branch, index) {
              return '<article class="' + (index === 0 ? 'is-automatic' : 'is-split') + '"><span>' + renderFormulaText(branch.condition) + '</span><strong>' + renderFormulaText(branch.result) + '</strong><p>' + renderFormulaText(branch.explanation) + '</p></article>';
            }).join("") + '</div>' +
            '<svg class="lesson-absolute-classification-graph" viewBox="0 0 560 145" role="img" aria-label="分类讨论后合并得到的解集数轴">' +
            '<line class="lesson-threading-axis" x1="28" y1="70" x2="532" y2="70"></line><path class="lesson-threading-axis-arrow" d="M532 70l-8-5m8 5l-8 5"></path>' +
            '<g class="lesson-absolute-solution-band"><line x1="32" y1="70" x2="340" y2="70"></line><line x1="446" y1="70" x2="528" y2="70"></line></g>' +
            '<g class="lesson-absolute-set-points is-open"><circle cx="340" cy="70" r="7"></circle><circle cx="446" cy="70" r="7"></circle></g>' +
            '<line class="lesson-absolute-classification-tick" x1="188" y1="60" x2="188" y2="80"></line>' +
            '<g class="lesson-absolute-tick-labels"><text x="188" y="99">' + esc(tickLabels[0]) + '</text><text x="340" y="99">' + esc(tickLabels[1]) + '</text><text x="446" y="99">' + esc(tickLabels[2]) + '</text></g>' +
            '<text class="lesson-absolute-classification-note" x="188" y="119">分类点，不切断解集</text><text class="lesson-absolute-set-caption" x="280" y="137">合并各分支后读取青色数轴段</text>' +
            '</svg>'
          );
        } else {
          const breakpoints = visual.breakpoints;
          const intersections = visual.intersections;
          graph = (
            '<svg class="lesson-absolute-piecewise-graph" viewBox="0 0 560 230" role="img" aria-label="绝对值和的分段折线与阈值交点图">' +
            '<line class="lesson-absolute-piecewise-x-axis" x1="26" y1="178" x2="536" y2="178"></line><path class="lesson-threading-axis-arrow" d="M536 178l-8-5m8 5l-8 5"></path>' +
            '<line class="lesson-absolute-piecewise-y-axis" x1="280" y1="190" x2="280" y2="12"></line><path class="lesson-threading-axis-arrow" d="M280 12l-5 9m5-9l5 9"></path>' +
            '<line class="lesson-absolute-threshold" x1="38" y1="70" x2="522" y2="70"></line><text class="lesson-absolute-threshold-label" x="506" y="62">y=' + esc(visual.threshold) + '</text>' +
            '<path class="lesson-absolute-piecewise-line" d="M42 18 L210 146 L350 146 L518 18"></path>' +
            '<g class="lesson-absolute-piecewise-intersections"><circle cx="110" cy="70" r="6"></circle><circle cx="460" cy="70" r="6"></circle></g>' +
            '<g class="lesson-absolute-break-lines"><line x1="210" y1="136" x2="210" y2="188"></line><line x1="350" y1="136" x2="350" y2="188"></line></g>' +
            '<g class="lesson-absolute-piecewise-labels"><text x="110" y="204">' + esc(intersections[0]) + '</text><text x="210" y="204">' + esc(breakpoints[0]) + '</text><text x="350" y="204">' + esc(breakpoints[1]) + '</text><text x="460" y="204">' + esc(intersections[1]) + '</text></g>' +
            '<g class="lesson-absolute-piecewise-solution"><line x1="110" y1="178" x2="460" y2="178"></line><circle cx="110" cy="178" r="7"></circle><circle cx="460" cy="178" r="7"></circle></g>' +
            '<text class="lesson-absolute-axis-label" x="528" y="169">x</text><text class="lesson-absolute-axis-label" x="292" y="22">y</text>' +
            '<text class="lesson-absolute-set-caption" x="280" y="224">折线不高于 y=' + esc(visual.threshold) + ' 的部分对应青色闭区间</text>' +
            '</svg>'
          );
        }
        return (
          '<figure class="lesson-step-visual lesson-step-absolute-visual is-' + esc(visual.mode) + '" role="group" aria-label="' + ariaLabel + '">' +
          '<header class="lesson-absolute-header"><span>' + esc(visual.method || "方法") + '</span><h3>' + renderFormulaText(visual.title || "") + '</h3></header>' +
          (visual.intro ? '<p class="lesson-absolute-intro">' + renderFormulaText(visual.intro) + '</p>' : '') +
          transformations + graph + facts +
          '<p class="lesson-threading-result lesson-absolute-result"><span>结论</span><strong>' + renderFormulaText(visual.solution || "") + '</strong></p>' +
          (visual.caption ? '<figcaption>' + renderFormulaText(visual.caption) + '</figcaption>' : '') +
          '</figure>'
        );
      }

      if (visual.kind === "quadratic-function-sign-graphs") {
        const graphs = Array.isArray(visual.graphs) ? visual.graphs : [];
        const curvePaths = {
          up: {
            positive: "M72 40 Q260 416 448 40",
            zero: "M72 40 Q260 320 448 40",
            negative: "M72 40 Q260 250 448 40",
          },
          down: {
            positive: "M72 320 Q260 -56 448 320",
            zero: "M72 320 Q260 40 448 320",
            negative: "M72 320 Q260 110 448 320",
          },
        };
        const rootPositions = {
          positive: [165, 355],
          zero: [260],
          negative: [],
        };
        const renderSolutionSegments = function (mode) {
          const segment = function (x1, x2) {
            return '<line class="lesson-quadratic-solution-segment" x1="' + x1 + '" y1="180" x2="' + x2 + '" y2="180"></line>';
          };
          const endpoint = function (x, closed) {
            return '<circle class="lesson-quadratic-solution-endpoint ' + (closed ? 'is-closed' : 'is-open') + '" cx="' + x + '" cy="180" r="8"></circle>';
          };
          if (mode === "middle-open" || mode === "middle-closed") {
            return segment(165, 355) + endpoint(165, mode === "middle-closed") + endpoint(355, mode === "middle-closed");
          }
          if (mode === "outside-open" || mode === "outside-closed") {
            return segment(45, 165) + segment(355, 475) + endpoint(165, mode === "outside-closed") + endpoint(355, mode === "outside-closed");
          }
          if (mode === "except-root") {
            return segment(45, 252) + segment(268, 475) + endpoint(260, false);
          }
          if (mode === "all") return segment(45, 475);
          return "";
        };
        const cards = graphs.map(function (item, index) {
          const opening = item.opening === "down" ? "down" : "up";
          const discriminant = new Set(["positive", "zero", "negative"]).has(item.discriminant)
            ? item.discriminant
            : "positive";
          const roots = Array.isArray(item.roots) ? item.roots : [];
          const positions = rootPositions[discriminant];
          const rootsIncluded = item.solutionMode === "middle-closed" || item.solutionMode === "outside-closed";
          const rootMarkup = positions.map(function (x, rootIndex) {
            const label = roots[rootIndex] || (discriminant === "zero" ? "x₀" : rootIndex === 0 ? "x₁" : "x₂");
            return '<circle class="lesson-quadratic-root' + (rootsIncluded ? ' is-included' : '') + '" cx="' + x + '" cy="180" r="5"></circle>' +
              '<text class="lesson-quadratic-root-label" x="' + x + '" y="207">' + esc(label) + '</text>';
          }).join("");
          const facts = Array.isArray(item.facts) && item.facts.length
            ? '<ol class="lesson-quadratic-graph-facts">' + item.facts.map(function (fact) {
              return '<li>' + renderFormulaText(fact) + '</li>';
            }).join("") + '</ol>'
            : "";
          const emptyLabel = item.solutionMode === "none"
            ? '<text class="lesson-quadratic-empty-label" x="260" y="268">目标区域不存在</text>'
            : "";
          return (
            '<article class="lesson-quadratic-graph-card">' +
            '<header><span>' + esc(item.label || String(index + 1)) + '</span><strong>' + renderFormulaText(item.expression || "") + '</strong></header>' +
            facts +
            '<svg viewBox="0 0 520 330" role="img" aria-label="' + esc(item.ariaLabel || item.label || "二次函数图像") + '">' +
            '<g class="lesson-quadratic-solution-regions">' + renderSolutionSegments(item.solutionMode) + '</g>' +
            '<g class="lesson-quadratic-axes"><line x1="32" y1="180" x2="492" y2="180"></line><path d="M492 180l-10-6m10 6l-10 6"></path><line x1="260" y1="310" x2="260" y2="20"></line><path d="M260 20l-6 10m6-10l6 10"></path><text x="486" y="169">x</text><text x="270" y="31">y</text></g>' +
            '<path class="lesson-quadratic-curve is-' + opening + '" d="' + curvePaths[opening][discriminant] + '"></path>' +
            '<g class="lesson-quadratic-roots">' + rootMarkup + '</g>' +
            emptyLabel +
            '</svg>' +
            '<footer><span>' + renderFormulaText(item.target || "") + '</span><strong>' + renderFormulaText(item.solution || "") + '</strong></footer>' +
            '</article>'
          );
        }).join("");
        return (
          '<figure class="lesson-step-visual lesson-step-quadratic-graphs" role="group" aria-label="' + ariaLabel + '">' +
          (visual.title ? '<h3>' + renderFormulaText(visual.title) + '</h3>' : '') +
          (visual.intro ? '<p class="lesson-quadratic-graph-intro">' + renderFormulaText(visual.intro) + '</p>' : '') +
          '<div class="lesson-quadratic-graph-grid is-' + Math.min(graphs.length, 4) + '">' + cards + '</div>' +
          (visual.caption ? '<figcaption>' + renderFormulaText(visual.caption) + '</figcaption>' : '') +
          '</figure>'
        );
      }

      if (visual.kind === "implication-condition-pairs") {
        const cases = Array.isArray(visual.cases) ? visual.cases : [];
        const cards = cases.map(function (item, index) {
          const sufficientOk = item.sufficient === true;
          const necessaryOk = item.necessary === true;
          const topColor = sufficientOk ? "#177c66" : "#c5534a";
          const bottomColor = necessaryOk ? "#177c66" : "#c5534a";
          const topMarker = "implication-top-" + index;
          const bottomMarker = "implication-bottom-" + index;
          const setEvidence = item.setEvidence;
          const explanationMarkup = setEvidence && Array.isArray(setEvidence.explanations) ? (
            '<div class="lesson-implication-set-explanations">' + setEvidence.explanations.map(function (line, lineIndex) {
              return '<p><span class="lesson-implication-set-explanation-index">' + (lineIndex + 1) + '</span><span class="lesson-implication-set-explanation-text">' + renderFormulaText(line) + '</span></p>';
            }).join("") + '</div>'
          ) : "";
          const setEvidenceMarkup = setEvidence && setEvidence.kind === "nested-open-intervals" ? (
            '<figure class="lesson-implication-set-evidence">' +
            '<svg viewBox="0 0 520 210" role="img" aria-label="' + esc(
              "解集 " + setEvidence.qSet + " 真包含于 " + setEvidence.pSet,
            ) + '">' +
            '<g class="lesson-implication-set-axis"><line x1="92" y1="62" x2="458" y2="62"/><path d="M458 62l-11-7v14z"/><line x1="92" y1="132" x2="458" y2="132"/><path d="M458 132l-11-7v14z"/></g>' +
            '<g class="lesson-implication-set-row-label"><text x="52" y="69">P</text><text x="52" y="139">Q</text></g>' +
            '<g class="lesson-implication-set-segment is-p"><line x1="142" y1="62" x2="405" y2="62"/><circle cx="142" cy="62" r="8"/><circle cx="405" cy="62" r="8"/></g>' +
            '<g class="lesson-implication-set-segment is-q"><line x1="142" y1="132" x2="230" y2="132"/><circle cx="142" cy="132" r="8"/><circle cx="230" cy="132" r="8"/></g>' +
            '<g class="lesson-implication-set-ticks"><text x="142" y="91">' + esc(setEvidence.sharedLeft) + '</text><text x="230" y="161">' + esc(setEvidence.qRight) + '</text><text x="405" y="91">' + esc(setEvidence.pRight) + '</text></g>' +
            '<text class="lesson-implication-set-relation" x="275" y="196">' + esc(setEvidence.relation) + '</text>' +
            '</svg>' +
            '<figcaption><strong>' + esc(setEvidence.pSet) + '</strong>，<strong>' + esc(setEvidence.qSet) + '</strong></figcaption>' +
            explanationMarkup +
            '</figure>'
          ) : setEvidence && setEvidence.kind === "parameter-interval-containment" ? (
            '<figure class="lesson-implication-set-evidence is-parameter">' +
            '<svg viewBox="0 0 520 220" role="img" aria-label="' + esc(setEvidence.ariaLabel || "含参区间包含关系数轴") + '">' +
            '<g class="lesson-implication-set-axis"><line x1="92" y1="62" x2="458" y2="62"/><path d="M458 62l-11-7v14z"/><line x1="92" y1="132" x2="458" y2="132"/><path d="M458 132l-11-7v14z"/></g>' +
            '<g class="lesson-implication-set-row-label"><text x="52" y="69">P</text><text x="52" y="139">Q</text></g>' +
            (setEvidence.layout === "fixed-inside-right-ray" ? (
              '<g class="lesson-implication-set-segment is-p"><line x1="230" y1="62" x2="375" y2="62"/><circle class="is-closed" cx="230" cy="62" r="8"/><circle class="is-closed" cx="375" cy="62" r="8"/></g>' +
              '<g class="lesson-implication-set-segment is-q"><line x1="135" y1="132" x2="450" y2="132"/><circle cx="135" cy="132" r="8"/><path d="M458 132l-14-9v18z"/></g>' +
              '<g class="lesson-implication-set-ticks"><text x="230" y="91">' + esc(setEvidence.pLeft) + '</text><text x="375" y="91">' + esc(setEvidence.pRight) + '</text><text x="135" y="162">' + esc(setEvidence.qEndpoint) + '</text></g>'
            ) : (
              '<g class="lesson-implication-set-segment is-p"><line x1="100" y1="62" x2="285" y2="62"/><path d="M92 62l14-9v18z"/><circle cx="285" cy="62" r="8"/></g>' +
              '<g class="lesson-implication-set-segment is-q"><line x1="100" y1="132" x2="405" y2="132"/><path d="M92 132l14-9v18z"/><circle cx="405" cy="132" r="8"/></g>' +
              '<g class="lesson-implication-set-ticks"><text x="285" y="91">' + esc(setEvidence.pEndpoint) + '</text><text x="405" y="162">' + esc(setEvidence.qEndpoint) + '</text></g>'
            )) +
            '<text class="lesson-implication-set-relation" x="275" y="207">' + esc(setEvidence.relation) + '</text>' +
            '</svg>' +
            '<figcaption><strong>' + esc(setEvidence.pSet) + '</strong>，<strong>' + esc(setEvidence.qSet) + '</strong></figcaption>' +
            explanationMarkup +
            '</figure>'
          ) : setEvidence && setEvidence.kind === "complement-right-ray-parameter" ? (
            '<figure class="lesson-implication-set-evidence is-parameter is-parameter-result">' +
            '<svg viewBox="0 0 520 292" role="img" aria-label="' + esc(setEvidence.ariaLabel || "补集与含参右开射线的包含关系") + '">' +
            '<g class="lesson-implication-set-axis"><line x1="92" y1="55" x2="458" y2="55"/><path d="M458 55l-11-7v14z"/><line x1="92" y1="130" x2="458" y2="130"/><path d="M458 130l-11-7v14z"/><line x1="92" y1="205" x2="458" y2="205"/><path d="M458 205l-11-7v14z"/></g>' +
            '<g class="lesson-implication-set-row-label"><text x="52" y="62">' + renderSvgSetExpression(setEvidence.pRowLabel) + '</text><text x="52" y="137">' + renderSvgSetExpression(setEvidence.qRowLabel) + '</text><text x="52" y="212">' + renderSvgSetExpression(setEvidence.resultRowLabel) + '</text></g>' +
            '<g class="lesson-implication-set-segment is-p"><line x1="100" y1="55" x2="210" y2="55"/><path d="M92 55l14-9v18z"/><circle cx="210" cy="55" r="8"/><line x1="340" y1="55" x2="450" y2="55"/><circle cx="340" cy="55" r="8"/><path d="M458 55l-14-9v18z"/></g>' +
            '<g class="lesson-implication-set-segment is-q"><line x1="340" y1="130" x2="450" y2="130"/><circle cx="340" cy="130" r="8"/><path d="M458 130l-14-9v18z"/></g>' +
            '<g class="lesson-implication-set-segment is-result"><line x1="340" y1="205" x2="450" y2="205"/><circle class="is-closed" cx="340" cy="205" r="8"/><path d="M458 205l-14-9v18z"/></g>' +
            '<g class="lesson-implication-set-ticks"><text x="210" y="86">' + esc(setEvidence.pLeftEndpoint) + '</text><text x="340" y="86">' + esc(setEvidence.pRightEndpoint) + '</text><text x="340" y="161">' + esc(setEvidence.qEndpoint) + '</text><text x="340" y="236">' + esc(setEvidence.resultEndpoint) + '</text></g>' +
            '<text class="lesson-implication-set-relation" x="275" y="278">' + renderSvgSetExpression(setEvidence.relation) + '</text>' +
            '</svg>' +
            '<figcaption><strong>' + renderFormulaText(setEvidence.pSet) + '</strong>，<strong>' + renderFormulaText(setEvidence.qSet) + '</strong>；参数范围 <strong>' + renderFormulaText(setEvidence.parameterSet) + '</strong></figcaption>' +
            explanationMarkup +
            '</figure>'
          ) : "";
          return (
            '<article class="lesson-implication-card">' +
            '<h3>' + esc(item.label || String(index + 1)) + "　" + esc(item.result || "") + '</h3>' +
            setEvidenceMarkup +
            '<svg viewBox="0 0 420 210" role="img" aria-label="' + esc(
              (item.label || String(index + 1)) + "：充分" + (sufficientOk ? "成立" : "不成立") +
              "，必要" + (necessaryOk ? "成立" : "不成立"),
            ) + '">' +
            '<defs>' +
            '<marker id="' + topMarker + '" markerWidth="10" markerHeight="10" refX="8" refY="5" orient="auto"><path d="M0,0 L10,5 L0,10 Z" fill="' + topColor + '"/></marker>' +
            '<marker id="' + bottomMarker + '" markerWidth="10" markerHeight="10" refX="8" refY="5" orient="auto"><path d="M0,0 L10,5 L0,10 Z" fill="' + bottomColor + '"/></marker>' +
            '</defs>' +
            '<g class="lesson-implication-node"><circle cx="72" cy="105" r="34"/><text x="72" y="114">p</text></g>' +
            '<g class="lesson-implication-node"><circle cx="348" cy="105" r="34"/><text x="348" y="114">q</text></g>' +
            '<path class="lesson-implication-arrow ' + (sufficientOk ? "is-valid" : "is-invalid") + '" d="M104 88 C154 28 266 28 316 88" marker-end="url(#' + topMarker + ')"/>' +
            '<text class="lesson-implication-label" x="210" y="42">充分</text>' +
            '<circle class="lesson-implication-status-backdrop" cx="264" cy="48" r="14"/>' +
            '<text class="lesson-implication-status ' + (sufficientOk ? "is-valid" : "is-invalid") + '" x="264" y="55">' + (sufficientOk ? "✓" : "✕") + '</text>' +
            '<path class="lesson-implication-arrow ' + (necessaryOk ? "is-valid" : "is-invalid") + '" d="M316 122 C266 182 154 182 104 122" marker-end="url(#' + bottomMarker + ')"/>' +
            '<text class="lesson-implication-label" x="210" y="178">必要</text>' +
            '<circle class="lesson-implication-status-backdrop" cx="156" cy="162" r="14"/>' +
            '<text class="lesson-implication-status ' + (necessaryOk ? "is-valid" : "is-invalid") + '" x="156" y="169">' + (necessaryOk ? "✓" : "✕") + '</text>' +
            '</svg>' +
            '<div class="lesson-implication-definitions"><p><strong>p：</strong>' + renderFormulaText(item.pText || "") + '</p><p><strong>q：</strong>' + renderFormulaText(item.qText || "") + '</p></div>' +
            (item.counterexample ? '<p class="lesson-implication-counterexample"><strong>' + esc(item.evidenceLabel || "反例") + '：</strong>' + renderFormulaText(item.counterexample) + '</p>' : "") +
            '</article>'
          );
        }).join("");
        return (
          '<figure class="lesson-step-visual lesson-step-implications">' +
          '<div class="lesson-implication-grid is-' + cases.length + '">' + cards + '</div>' +
          '<figcaption>箭头线上的“充分”和“必要”分别表示 p 对 q 的两种条件关系；勾表示成立，叉表示不成立。</figcaption>' +
          '</figure>'
        );
      }

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
