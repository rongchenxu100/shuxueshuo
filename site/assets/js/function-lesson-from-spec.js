/**
 * Declarative renderer for non-calculus high-school function lessons.
 * Depends on MathExpressionEngine and exposes window.FunctionLessonFromSpec.
 */
(function (global) {
  "use strict";

  var MEE = global.MathExpressionEngine;
  if (!MEE) throw new Error("MathExpressionEngine is required");

  function esc(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function evaluate(expr, env) {
    return MEE.evaluate(String(expr == null ? "0" : expr), env || {});
  }

  function resolveState(spec, parameterValue, localVars) {
    var parameter = spec.parameter || { name: "state", initial: 0 };
    var value = Number(parameterValue);
    if (!Number.isFinite(value)) value = Number(parameter.initial) || 0;
    var env = Object.assign({}, localVars || {});
    env[parameter.name] = value;
    (spec.bindings || []).forEach(function (binding) {
      env[binding.name] = evaluate(binding.expr, env);
    });
    return { parameterValue: value, env: env };
  }

  function formatNumber(value) {
    if (!Number.isFinite(value)) return "—";
    if (Math.abs(value) < 1e-9) return "0";
    return Number(value).toFixed(3).replace(/\.0+$/, "").replace(/(\.\d*?)0+$/, "$1");
  }

  function indexById(items) {
    var result = {};
    (items || []).forEach(function (item) { if (item && item.id) result[item.id] = item; });
    return result;
  }

  function elementVisible(id, decoration) {
    var visible = decoration.visibleElementIds;
    return !Array.isArray(visible) || visible.indexOf(id) >= 0;
  }

  function elementHighlighted(id, decoration) {
    return (decoration.highlightElementIds || []).indexOf(id) >= 0;
  }

  function panelBox(panel, width, height) {
    var viewport = panel.viewport;
    return {
      x: viewport.x * width,
      y: viewport.y * height,
      width: viewport.width * width,
      height: viewport.height * height
    };
  }

  function panelFrame(panel, box, options) {
    var hideTitle = options && options.hideTitle;
    var title = hideTitle ? "" : (panel.title || panel.id);
    return '<rect x="' + box.x + '" y="' + box.y + '" width="' + box.width + '" height="' + box.height + '" rx="14" fill="#fff" stroke="#d9e2df" />' +
      (title ? '<text x="' + (box.x + 20) + '" y="' + (box.y + 30) + '" font-size="17" font-weight="700" fill="#164e4a">' + esc(title) + '</text>' : "");
  }

  function setDescription(set) {
    if (!set) return "";
    if (Array.isArray(set.values)) return "{" + set.values.join(", ") + "}";
    if (Array.isArray(set.intervals) && set.intervals[0]) {
      var interval = set.intervals[0];
      return (interval.openMin ? "(" : "[") + formatNumber(interval.min) + ", " + formatNumber(interval.max) + (interval.openMax ? ")" : "]");
    }
    return "";
  }

  function sampleSet(set, count) {
    if (!set) return [];
    if (Array.isArray(set.values)) return set.values.slice();
    var interval = set.intervals && set.intervals[0];
    if (!interval) return [];
    var size = Math.max(2, count || 5);
    return Array.from({ length: size }, function (_, index) {
      return interval.min + ((interval.max - interval.min) * index) / (size - 1);
    });
  }

  function renderMapping(panel, box, decoration, state, candidateOverride) {
    var candidateId = candidateOverride || decoration.activeCandidateId;
    if (!candidateId && panel.candidates && panel.candidates.length) {
      candidateId = panel.candidates[Math.max(0, Math.min(panel.candidates.length - 1, Math.round(state.parameterValue)))].id;
    }
    var candidate = (panel.candidates || []).find(function (item) { return item.id === candidateId; }) || panel.candidates[0];
    var sourceX = box.x + box.width * 0.26;
    var targetX = box.x + box.width * 0.74;
    var centerY = box.y + box.height * 0.55;
    var radiusX = Math.min(110, box.width * 0.17);
    var radiusY = Math.min(210, box.height * 0.34);
    var out = panelFrame(panel, box);
    out += '<ellipse cx="' + sourceX + '" cy="' + centerY + '" rx="' + radiusX + '" ry="' + radiusY + '" fill="#eff8f5" stroke="#0f766e" stroke-width="2" />';
    out += '<ellipse cx="' + targetX + '" cy="' + centerY + '" rx="' + radiusX + '" ry="' + radiusY + '" fill="#f6f4ff" stroke="#7c3aed" stroke-width="2" />';
    out += '<text x="' + sourceX + '" y="' + (box.y + 68) + '" text-anchor="middle" font-size="18" font-weight="700" fill="#0f766e">' + esc(panel.sourceSet.label) + '</text>';
    out += '<text x="' + sourceX + '" y="' + (box.y + 92) + '" text-anchor="middle" font-size="13" fill="#52706c">' + esc(setDescription(panel.sourceSet)) + '</text>';
    out += '<text x="' + targetX + '" y="' + (box.y + 68) + '" text-anchor="middle" font-size="18" font-weight="700" fill="#6d28d9">' + esc(panel.targetSet.label) + '</text>';
    out += '<text x="' + targetX + '" y="' + (box.y + 92) + '" text-anchor="middle" font-size="13" fill="#6b6477">' + esc(setDescription(panel.targetSet)) + '</text>';
    out += '<defs><marker id="fnArrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#64748b" /></marker></defs>';
    var values = sampleSet(panel.sourceSet, 5);
    var targetInterval = panel.targetSet.intervals && panel.targetSet.intervals[0];
    values.forEach(function (x, index) {
      var ratio = values.length === 1 ? 0.5 : index / (values.length - 1);
      var sy = centerY - radiusY * 0.66 + ratio * radiusY * 1.32;
      var y = candidate ? evaluate(candidate.expr, Object.assign({}, state.env, { x: x })) : NaN;
      var valid = Number.isFinite(y) && (!targetInterval || (y >= targetInterval.min && y <= targetInterval.max));
      var tyRatio = targetInterval ? (y - targetInterval.min) / (targetInterval.max - targetInterval.min) : ratio;
      var ty = centerY - radiusY * 0.66 + Math.max(0, Math.min(1, tyRatio)) * radiusY * 1.32;
      if (!valid && targetInterval) {
        ty = y > targetInterval.max ? centerY + radiusY + 26 : centerY - radiusY - 26;
      }
      var color = valid ? "#64748b" : "#dc2626";
      out += '<circle cx="' + sourceX + '" cy="' + sy + '" r="5" fill="#0f766e" />';
      out += '<text x="' + (sourceX - 15) + '" y="' + (sy + 5) + '" text-anchor="end" font-size="13" fill="#334155">' + esc(formatNumber(x)) + '</text>';
      out += '<path d="M' + (sourceX + 8) + ',' + sy + ' C' + (sourceX + 85) + ',' + sy + ' ' + (targetX - 85) + ',' + ty + ' ' + (targetX - 8) + ',' + ty + '" fill="none" stroke="' + color + '" stroke-width="' + (valid ? 1.5 : 3) + '" marker-end="url(#fnArrow)" />';
      out += '<circle cx="' + targetX + '" cy="' + ty + '" r="' + (valid ? 5 : 7) + '" fill="' + (valid ? "#7c3aed" : "#fff") + '" stroke="' + color + '" stroke-width="2" />';
      out += '<text x="' + (targetX + 15) + '" y="' + (ty + 5) + '" font-size="13" fill="' + color + '">' + esc(formatNumber(y)) + '</text>';
    });
    out += '<rect x="' + (box.x + box.width * 0.34) + '" y="' + (box.y + box.height - 82) + '" width="' + (box.width * 0.32) + '" height="48" rx="24" fill="' + (candidate && candidate.valid === false ? "#fef2f2" : "#f0fdfa") + '" stroke="' + (candidate && candidate.valid === false ? "#fecaca" : "#99f6e4") + '" />';
    out += '<text x="' + (box.x + box.width * 0.5) + '" y="' + (box.y + box.height - 52) + '" text-anchor="middle" font-size="17" font-weight="700" fill="' + (candidate && candidate.valid === false ? "#b91c1c" : "#0f766e") + '">' + esc(candidate ? candidate.label : "") + '</text>';
    if (candidate && candidate.note) out += '<text x="' + (box.x + box.width * 0.5) + '" y="' + (box.y + box.height - 14) + '" text-anchor="middle" font-size="13" fill="#52525b">' + esc(candidate.note) + '</text>';
    return out;
  }

  function renderNumberLine(panel, box, decoration) {
    var out = panelFrame(panel, box);
    var axis = panel.axis;
    var left = box.x + 70;
    var right = box.x + box.width - 45;
    var y = box.y + box.height * 0.58;
    function sx(value) { return left + ((value - axis.min) / (axis.max - axis.min)) * (right - left); }
    out += '<line x1="' + left + '" y1="' + y + '" x2="' + right + '" y2="' + y + '" stroke="#52525b" stroke-width="2" />';
    for (var tick = Math.ceil(axis.min); tick <= Math.floor(axis.max); tick += 1) {
      out += '<line x1="' + sx(tick) + '" y1="' + (y - 6) + '" x2="' + sx(tick) + '" y2="' + (y + 6) + '" stroke="#71717a" />';
      out += '<text x="' + sx(tick) + '" y="' + (y + 25) + '" text-anchor="middle" font-size="12" fill="#71717a">' + tick + '</text>';
    }
    var renderedIntervalIndex = 0;
    (panel.intervals || []).forEach(function (interval) {
      if (!elementVisible(interval.id, decoration)) return;
      var index = renderedIntervalIndex;
      renderedIntervalIndex += 1;
      var x1 = sx(Math.max(axis.min, interval.min));
      var x2 = sx(Math.min(axis.max, interval.max));
      var iy = y - 22 - index * 18;
      var color = interval.color || (elementHighlighted(interval.id, decoration) ? "#0f766e" : "#7c3aed");
      out += '<line x1="' + x1 + '" y1="' + iy + '" x2="' + x2 + '" y2="' + iy + '" stroke="' + color + '" stroke-width="6" stroke-linecap="round" />';
      if (interval.extendsMin) {
        out += '<path d="M' + x1 + ',' + iy + ' l14,-9 v18 z" fill="' + color + '" />';
      } else if (interval.min >= axis.min) {
        out += '<circle cx="' + x1 + '" cy="' + iy + '" r="7" fill="' + (interval.openMin ? "#fff" : color) + '" stroke="' + color + '" stroke-width="3" />';
      }
      if (interval.extendsMax) {
        out += '<path d="M' + x2 + ',' + iy + ' l-14,-9 v18 z" fill="' + color + '" />';
      } else if (interval.max <= axis.max) {
        out += '<circle cx="' + x2 + '" cy="' + iy + '" r="7" fill="' + (interval.openMax ? "#fff" : color) + '" stroke="' + color + '" stroke-width="3" />';
      }
      if (interval.label) out += '<text x="' + ((x1 + x2) / 2) + '" y="' + (iy - 12) + '" text-anchor="middle" font-size="14" fill="' + color + '">' + renderSvgMathLabel(interval.label) + '</text>';
    });
    (panel.excludedPoints || []).forEach(function (point) {
      if (!elementVisible(point.id, decoration)) return;
      out += '<circle cx="' + sx(point.value) + '" cy="' + y + '" r="8" fill="#fff" stroke="#dc2626" stroke-width="3" />';
      out += '<text x="' + sx(point.value) + '" y="' + (y + 48) + '" text-anchor="middle" font-size="13" fill="#b91c1c">' + renderSvgMathLabel(point.label || formatNumber(point.value)) + '</text>';
    });
    return out;
  }

  function renderConstraintList(panel, box, decoration) {
    var out = panelFrame(panel, box);
    var y = box.y + 72;
    (panel.constraints || []).forEach(function (item) {
      if (!elementVisible(item.id, decoration)) return;
      var active = elementHighlighted(item.id, decoration);
      out += '<rect x="' + (box.x + 28) + '" y="' + y + '" width="' + (box.width - 56) + '" height="76" rx="10" fill="' + (active ? "#ecfdf5" : "#fafafa") + '" stroke="' + (active ? "#5eead4" : "#e4e4e7") + '" />';
      out += '<text x="' + (box.x + 48) + '" y="' + (y + 28) + '" font-size="14" font-weight="700" fill="#0f766e">' + esc(item.label) + '</text>';
      out += '<text x="' + (box.x + 48) + '" y="' + (y + 55) + '" font-size="17" fill="#18181b">' + esc(item.expression + "　⇒　" + item.result) + '</text>';
      y += 88;
    });
    return out;
  }

  function graphLayout(panel, box) {
    var domain = panel.domain;
    var inner = { x: box.x + 62, y: box.y + 58, width: box.width - 90, height: box.height - 100 };
    function point(x, y) {
      return {
        x: inner.x + ((x - domain.minX) / (domain.maxX - domain.minX)) * inner.width,
        y: inner.y + inner.height - ((y - domain.minY) / (domain.maxY - domain.minY)) * inner.height
      };
    }
    return { domain: domain, inner: inner, point: point };
  }

  function functionValue(definition, x, env) {
    var next = Object.assign({}, env || {});
    next[definition.variable] = x;
    return evaluate(definition.expr, next);
  }

  function renderSvgMathLabel(value) {
    var source = String(value == null ? "" : value);
    var pattern = /\\frac\{([^{}]+)\}\{\\sqrt\{([^{}]+)\}\}|\\frac\{([^{}]+)\}\{([^{}]+)\}|\\sqrt\{([^{}]+)\}|√\(([^()]*)\)|√([A-Za-z0-9]+)|\^\{([^{}]+)\}|\^\(([^()]*)\)|\^([+-]?(?:\d+(?:\.\d+)?|[A-Za-z]))/g;
    var cursor = 0;
    var markup = "";
    var match;
    while ((match = pattern.exec(source)) !== null) {
      markup += esc(source.slice(cursor, match.index));
      if (match[1] != null) {
        var nestedNumerator = match[1];
        var nestedRadicand = match[2];
        var nestedShift = Math.max(0.7, nestedNumerator.length * 0.5);
        markup += '<tspan font-size="0.78em" dy="-0.48em" text-decoration="underline">' + renderSvgMathLabel(nestedNumerator) + '</tspan>';
        markup += '<tspan font-size="0.78em" dx="-' + nestedShift + 'em" dy="1em">√</tspan><tspan font-size="0.78em" text-decoration="overline">' + esc(nestedRadicand) + '</tspan>';
      } else if (match[3] != null) {
        var numerator = match[3];
        var denominator = match[4];
        var numeratorShift = Math.max(0.7, numerator.length * 0.5);
        markup += '<tspan font-size="0.78em" dy="-0.48em" text-decoration="underline">' + renderSvgMathLabel(numerator) + '</tspan>';
        markup += '<tspan font-size="0.78em" dx="-' + numeratorShift + 'em" dy="1em">' + renderSvgMathLabel(denominator) + '</tspan>';
      } else if (match[5] != null || match[6] != null || match[7] != null) {
        var radicand = match[5] || match[6] || match[7] || "";
        markup += '√<tspan text-decoration="overline">' + esc(radicand) + "</tspan>";
      } else {
        var exponent = match[8] || match[9] || match[10] || "";
        markup += '<tspan baseline-shift="super" font-size="0.72em">' + esc(exponent) + "</tspan>";
      }
      cursor = match.index + match[0].length;
    }
    return markup + esc(source.slice(cursor));
  }

  function renderFunctionPaths(definition, intervals, layout, env, style) {
    var out = "";
    (intervals || []).forEach(function (interval) {
      var commands = [];
      var penDown = false;
      for (var index = 0; index <= 220; index += 1) {
        var x = interval.min + ((interval.max - interval.min) * index) / 220;
        var y;
        try { y = functionValue(definition, x, env); } catch (_error) { y = NaN; }
        if (
          !Number.isFinite(y)
          || y < layout.domain.minY
          || y > layout.domain.maxY
        ) {
          penDown = false;
          continue;
        }
        var point = layout.point(x, y);
        commands.push((penDown ? "L" : "M") + point.x.toFixed(2) + "," + point.y.toFixed(2));
        penDown = true;
      }
      if (commands.length) {
        out += '<path d="' + commands.join(" ") + '" fill="none" stroke="' + style.stroke + '" stroke-width="' + style.strokeWidth + '" stroke-linecap="round" opacity="' + (style.opacity || 1) + '" />';
      }
    });
    return out;
  }

  function intersectIntervals(leftIntervals, rightIntervals) {
    var intersections = [];
    (leftIntervals || []).forEach(function (left) {
      (rightIntervals || []).forEach(function (right) {
        var min = Math.max(left.min, right.min);
        var max = Math.min(left.max, right.max);
        if (min <= max) intersections.push({ min: min, max: max });
      });
    });
    return intersections;
  }

  function renderFunctionGraph(panel, box, decoration, state, candidateOverride, options) {
    var originalFigure = options && options.originalFigure;
    var originalFigureScale = options && options.originalFigureScale;
    var detailOriginalFigure = originalFigure && originalFigureScale === "detail";
    var tickFontSize = detailOriginalFigure ? 36 : (originalFigure ? 22 : 13);
    var axisLabelFontSize = detailOriginalFigure ? 42 : (originalFigure ? 28 : 14);
    var originFontSize = detailOriginalFigure ? 32 : (originalFigure ? 21 : 13);
    var pointLabelFontSize = detailOriginalFigure
      ? 28
      : (originalFigure ? 18 : Number(panel.pointLabelFontSize || 13));
    var axisStrokeWidth = detailOriginalFigure ? 3 : (originalFigure ? 2 : 1.4);
    var curveStrokeWidth = detailOriginalFigure ? 8 : (originalFigure ? 5 : 4);
    var axisColor = originalFigure ? "#64748b" : "#94a3b8";
    var axisLabelColor = originalFigure ? "#475569" : "#64748b";
    var out = panelFrame(panel, box, options);
    var functionDefinitions = panel.functions && panel.functions.length ? panel.functions : [panel.function];
    var activeFunctionId = candidateOverride || decoration.activeCandidateId;
    var activeFunction = functionDefinitions.find(function (definition) { return definition && definition.id === activeFunctionId; }) || functionDefinitions[0];
    if (!activeFunction) return out;
    var renderedFunctions = panel.renderAllFunctions
      ? functionDefinitions.filter(function (definition) {
          return definition && elementVisible(definition.id, decoration);
        })
      : [activeFunction];
    if (!renderedFunctions.length) renderedFunctions = [activeFunction];
    var layout = graphLayout(panel, box);
    var domain = layout.domain;
    var inner = layout.inner;
    var toPoint = layout.point;
    var gridStepX = panel.gridStepX || 1;
    var gridStepY = panel.gridStepY || 1;
    for (var gx = Math.ceil(domain.minX / gridStepX) * gridStepX; gx <= domain.maxX + 1e-9; gx += gridStepX) {
      var spx = toPoint(gx, 0).x;
      out += '<line x1="' + spx + '" y1="' + inner.y + '" x2="' + spx + '" y2="' + (inner.y + inner.height) + '" stroke="#f1f5f9" />';
    }
    for (var gy = Math.ceil(domain.minY / gridStepY) * gridStepY; gy <= domain.maxY + 1e-9; gy += gridStepY) {
      var spy = toPoint(0, gy).y;
      out += '<line x1="' + inner.x + '" y1="' + spy + '" x2="' + (inner.x + inner.width) + '" y2="' + spy + '" stroke="#f1f5f9" />';
    }
    var axisY = toPoint(0, 0).y;
    var axisX = toPoint(0, 0).x;
    out += '<line x1="' + inner.x + '" y1="' + axisY + '" x2="' + (inner.x + inner.width) + '" y2="' + axisY + '" stroke="' + axisColor + '" stroke-width="' + axisStrokeWidth + '" />';
    out += '<line x1="' + axisX + '" y1="' + inner.y + '" x2="' + axisX + '" y2="' + (inner.y + inner.height) + '" stroke="' + axisColor + '" stroke-width="' + axisStrokeWidth + '" />';
    if (panel.showAxisTicks) {
      for (var xTick = Math.ceil(domain.minX); xTick <= Math.floor(domain.maxX); xTick += gridStepX) {
        if (Math.abs(xTick) < 1e-9) continue;
        var xTickPoint = toPoint(xTick, 0);
        out += '<line x1="' + xTickPoint.x + '" y1="' + (axisY - 5) + '" x2="' + xTickPoint.x + '" y2="' + (axisY + 5) + '" stroke="#64748b" />';
        out += '<text data-axis-tick="x" x="' + xTickPoint.x + '" y="' + (axisY + tickFontSize * 1.55) + '" text-anchor="middle" font-size="' + tickFontSize + '" fill="#334155">' + formatNumber(xTick) + '</text>';
      }
      for (var yTick = Math.ceil(domain.minY); yTick <= Math.floor(domain.maxY); yTick += gridStepY) {
        if (Math.abs(yTick) < 1e-9) continue;
        var yTickPoint = toPoint(0, yTick);
        out += '<line x1="' + (axisX - 5) + '" y1="' + yTickPoint.y + '" x2="' + (axisX + 5) + '" y2="' + yTickPoint.y + '" stroke="#64748b" />';
        out += '<text data-axis-tick="y" x="' + (axisX - 10) + '" y="' + (yTickPoint.y + tickFontSize * 0.34) + '" text-anchor="end" font-size="' + tickFontSize + '" fill="#334155">' + formatNumber(yTick) + '</text>';
      }
      out += '<text data-axis-origin x="' + (axisX - 10) + '" y="' + (axisY + originFontSize * 1.25) + '" text-anchor="end" font-size="' + originFontSize + '" fill="#475569">O</text>';
    }
    (panel.referenceLines || []).forEach(function (referenceLine) {
      var color = referenceLine.color || "#f59e0b";
      if (referenceLine.orientation === "vertical") {
        var referenceX = toPoint(referenceLine.value, 0).x;
        if (referenceX < inner.x || referenceX > inner.x + inner.width) return;
        var verticalStart = referenceLine.max == null ? inner.y : toPoint(0, referenceLine.max).y;
        var verticalEnd = referenceLine.min == null ? inner.y + inner.height : toPoint(0, referenceLine.min).y;
        out += '<line data-reference-line="' + esc(referenceLine.id) + '" x1="' + referenceX + '" y1="' + verticalStart + '" x2="' + referenceX + '" y2="' + verticalEnd + '" stroke="' + esc(color) + '" stroke-width="2" stroke-dasharray="7 6" />';
        if (referenceLine.label) {
          out += '<text x="' + (referenceX + 8) + '" y="' + (verticalStart + 18) + '" font-size="14" font-weight="700" fill="' + esc(color) + '">' + renderSvgMathLabel(referenceLine.label) + '</text>';
        }
        return;
      }
      var referenceY = toPoint(0, referenceLine.value).y;
      if (referenceY < inner.y || referenceY > inner.y + inner.height) return;
      var horizontalStart = referenceLine.min == null ? inner.x : toPoint(referenceLine.min, 0).x;
      var horizontalEnd = referenceLine.max == null ? inner.x + inner.width : toPoint(referenceLine.max, 0).x;
      out += '<line data-reference-line="' + esc(referenceLine.id) + '" x1="' + horizontalStart + '" y1="' + referenceY + '" x2="' + horizontalEnd + '" y2="' + referenceY + '" stroke="' + esc(color) + '" stroke-width="2" stroke-dasharray="7 6" />';
      if (referenceLine.label) {
        out += '<text x="' + (horizontalStart + 8) + '" y="' + (referenceY - 8) + '" font-size="14" font-weight="700" fill="' + esc(color) + '">' + renderSvgMathLabel(referenceLine.label) + '</text>';
      }
    });
    if (decoration.showDomain && panel.studyIntervals && panel.studyIntervals[0]) {
      var di = panel.studyIntervals[0];
      var dl = toPoint(di.min, 0).x;
      var dr = toPoint(di.max, 0).x;
      out += '<rect x="' + dl + '" y="' + inner.y + '" width="' + (dr - dl) + '" height="' + inner.height + '" fill="#ccfbf1" opacity="0.35" />';
      var domainBoundaries = [];
      if (!di.extendsMin) domainBoundaries.push({ x: dl, label: di.minLabel || formatNumber(di.min), open: di.openMin });
      if (!di.extendsMax) domainBoundaries.push({ x: dr, label: di.maxLabel || formatNumber(di.max), open: di.openMax });
      domainBoundaries.forEach(function (boundary) {
        out += '<line x1="' + boundary.x + '" y1="' + inner.y + '" x2="' + boundary.x + '" y2="' + (inner.y + inner.height) + '" stroke="#0f766e" stroke-width="1.5" stroke-dasharray="6 5" opacity="0.55" />';
        out += '<circle cx="' + boundary.x + '" cy="' + axisY + '" r="6" fill="' + (boundary.open ? "#fff" : "#0f766e") + '" stroke="#0f766e" stroke-width="2.5" />';
        out += '<text x="' + boundary.x + '" y="' + (axisY + 30) + '" text-anchor="middle" font-size="14" font-weight="700" fill="#0f766e">' + renderSvgMathLabel(boundary.label) + '</text>';
      });
      if (di.extendsMin) {
        out += '<path d="M' + dl + ',' + axisY + ' l14,-9 v18 z" fill="#0f766e" />';
        out += '<text x="' + (dl + 18) + '" y="' + (axisY + 30) + '" font-size="14" font-weight="700" fill="#0f766e">' + esc(di.minLabel || "-∞") + '</text>';
      }
      if (di.extendsMax) {
        out += '<path d="M' + dr + ',' + axisY + ' l-14,-9 v18 z" fill="#0f766e" />';
        out += '<text x="' + (dr - 18) + '" y="' + (axisY + 30) + '" text-anchor="end" font-size="14" font-weight="700" fill="#0f766e">' + esc(di.maxLabel || "+∞") + '</text>';
      }
    }
    var activeRange = panel.renderAllFunctions ? panel.range : (activeFunction.range || panel.range);
    if (decoration.showRange && activeRange && activeRange[0]) {
      var ri = activeRange[0];
      var rt = toPoint(0, ri.max).y;
      var rb = toPoint(0, ri.min).y;
      out += '<rect x="' + inner.x + '" y="' + rt + '" width="' + inner.width + '" height="' + (rb - rt) + '" fill="#ede9fe" opacity="0.35" />';
    }
    renderedFunctions.forEach(function (definition) {
      var intervals = definition.intervals || [{ min: domain.minX, max: domain.maxX }];
      if (decoration.highlightStudyInterval && panel.studyIntervals && panel.studyIntervals.length) {
        out += renderFunctionPaths(definition, intervals, layout, state.env, {
          stroke: "#a1a1aa",
          strokeWidth: 2.5,
          opacity: 0.8
        });
        out += renderFunctionPaths(
          definition,
          intersectIntervals(intervals, panel.studyIntervals),
          layout,
          state.env,
          { stroke: "#0f766e", strokeWidth: Math.max(5, curveStrokeWidth), opacity: 1 }
        );
      } else {
        out += renderFunctionPaths(definition, intervals, layout, state.env, {
          stroke: "#2563eb",
          strokeWidth: curveStrokeWidth,
          opacity: 1
        });
      }
    });
    var visiblePoints = (panel.points || []).filter(function (point) {
      return elementVisible(point.id, decoration);
    });
    visiblePoints.forEach(function (point) {
      var pointPosition = toPoint(point.x, point.y);
      var pointColor = elementHighlighted(point.id, decoration) ? "#f59e0b" : "#0f766e";
      out += '<circle cx="' + pointPosition.x + '" cy="' + pointPosition.y + '" r="7" fill="' + (point.open ? "#fff" : pointColor) + '" stroke="' + pointColor + '" stroke-width="3" />';
      if (point.label) {
        out += '<text x="' + (pointPosition.x + Number(point.labelDx || 10)) + '" y="' + (pointPosition.y + Number(point.labelDy || -10)) + '" font-size="' + pointLabelFontSize + '" font-weight="700" fill="' + pointColor + '">' + renderSvgMathLabel(point.label) + '</text>';
      }
    });
    var xValue = state.parameterValue;
    var movingFunction = activeFunction;
    var movingPointInDomain = true;
    if (panel.renderAllFunctions) {
      movingFunction = renderedFunctions.find(function (definition) {
        return (definition.intervals || [{ min: domain.minX, max: domain.maxX }]).some(function (interval) {
          var aboveMin = interval.openMin ? xValue > interval.min : xValue >= interval.min;
          var belowMax = interval.openMax ? xValue < interval.max : xValue <= interval.max;
          return aboveMin && belowMax;
        });
      }) || null;
      movingPointInDomain = Boolean(movingFunction);
      if (!movingFunction) {
        movingFunction = activeFunction;
      }
    }
    var yValue = functionValue(movingFunction, xValue, state.env);
    if (
      !originalFigure
      && decoration.showMovingPoint !== false
      && movingPointInDomain
      && Number.isFinite(yValue)
    ) {
      var moving = toPoint(xValue, yValue);
      var matchingPoint = visiblePoints.find(function (point) {
        return Math.abs(point.x - xValue) < 1e-9
          && Math.abs(point.y - yValue) < 1e-9;
      });
      if (decoration.showVerticalTest) {
        out += '<line x1="' + moving.x + '" y1="' + inner.y + '" x2="' + moving.x + '" y2="' + (inner.y + inner.height) + '" stroke="#f59e0b" stroke-width="2.5" stroke-dasharray="8 6" />';
        out += '<text x="' + (moving.x + 8) + '" y="' + (inner.y + 18) + '" font-size="13" font-weight="700" fill="#b45309">唯一交点</text>';
      }
      if (decoration.showProjection) {
        out += '<line x1="' + moving.x + '" y1="' + moving.y + '" x2="' + moving.x + '" y2="' + axisY + '" stroke="#0f766e" stroke-width="2" stroke-dasharray="6 5" />';
        out += '<line x1="' + moving.x + '" y1="' + moving.y + '" x2="' + axisX + '" y2="' + moving.y + '" stroke="#7c3aed" stroke-width="2" stroke-dasharray="6 5" />';
      }
      if (!matchingPoint) {
        out += '<circle cx="' + moving.x + '" cy="' + moving.y + '" r="' + (decoration.fillMovingPoint ? 7 : 8) + '" fill="' + (decoration.fillMovingPoint ? "#0f766e" : "#fff") + '" stroke="#0f766e" stroke-width="' + (decoration.fillMovingPoint ? 3 : 4) + '" />';
        out += '<text x="' + (moving.x + 12) + '" y="' + (moving.y - 12) + '" font-size="' + Math.max(15, pointLabelFontSize) + '" font-weight="700" fill="#0f766e">(' + esc(formatNumber(xValue)) + ', ' + esc(formatNumber(yValue)) + ')</text>';
      }
    }
    out += '<text data-axis-label="x" x="' + (inner.x + inner.width - 4) + '" y="' + (axisY - 10) + '" text-anchor="end" font-size="' + axisLabelFontSize + '" font-style="italic" fill="' + axisLabelColor + '">' + esc(movingFunction.variable || "x") + '</text>';
    out += '<text data-axis-label="y" x="' + (axisX + 10) + '" y="' + (inner.y + axisLabelFontSize * 0.9) + '" font-size="' + axisLabelFontSize + '" font-style="italic" fill="' + axisLabelColor + '">y</text>';
    if (!originalFigure && !panel.renderAllFunctions) {
      out += '<text x="' + (box.x + box.width - 28) + '" y="' + (box.y + 31) + '" text-anchor="end" font-size="15" fill="#2563eb">' + renderSvgMathLabel(activeFunction.label) + '</text>';
    }
    return out;
  }

  function renderValueTable(panel, box, decoration, options) {
    var originalFigure = options && options.originalFigure;
    var out = panelFrame(panel, box, options);
    var columns = panel.columns || [];
    var rows = (panel.rows || []).filter(function (row) { return elementVisible(row.id, decoration); });
    var left = box.x + (originalFigure ? 32 : 28);
    var width = box.width - (originalFigure ? 64 : 56);
    var rowCount = Math.max(1, rows.length + 1);
    var rowHeight = originalFigure
      ? Math.min(128, (box.height - 64) / rowCount)
      : 48;
    var top = originalFigure
      ? box.y + (box.height - rowHeight * rowCount) / 2
      : box.y + 62;
    var columnWidth = width / Math.max(1, columns.length);
    function visualTextLength(cell) {
      return Array.from(String(cell)).reduce(function (total, character) {
        return total + (character.charCodeAt(0) > 255 ? 1 : 0.58);
      }, 0);
    }
    var maxTextLength = Math.max.apply(null, columns.concat(
      rows.flatMap(function (row) { return row.cells || []; })
    ).map(visualTextLength));
    var fittedFontSize = Math.floor(
      (columnWidth - 16) / Math.max(1, maxTextLength * 0.92)
    );
    var originalFontSize = Math.max(14, Math.min(42, fittedFontSize));
    var headerFontSize = originalFigure ? originalFontSize : 17;
    var bodyFontSize = originalFigure ? originalFontSize : 18;
    columns.forEach(function (column, index) {
      out += '<rect data-table-role="header" x="' + (left + index * columnWidth) + '" y="' + top + '" width="' + columnWidth + '" height="' + rowHeight + '" fill="#ecfdf5" stroke="#94a3b8" stroke-width="' + (originalFigure ? 2 : 1) + '" />';
      out += '<text data-table-role="header" x="' + (left + (index + 0.5) * columnWidth) + '" y="' + (top + rowHeight * 0.62) + '" text-anchor="middle" font-size="' + headerFontSize + '" font-weight="700" fill="#0f766e">' + esc(column) + '</text>';
    });
    rows.forEach(function (row, rowIndex) {
      row.cells.forEach(function (cell, columnIndex) {
        var active = elementHighlighted(row.id, decoration);
        var rowTop = top + rowHeight * (rowIndex + 1);
        out += '<rect data-table-role="body" x="' + (left + columnIndex * columnWidth) + '" y="' + rowTop + '" width="' + columnWidth + '" height="' + rowHeight + '" fill="' + (active ? "#fef3c7" : "#fff") + '" stroke="#94a3b8" stroke-width="' + (originalFigure ? 2 : 1) + '" />';
        out += '<text data-table-role="body" x="' + (left + (columnIndex + 0.5) * columnWidth) + '" y="' + (rowTop + rowHeight * 0.62) + '" text-anchor="middle" font-size="' + bodyFontSize + '" font-weight="' + (originalFigure ? 650 : 400) + '" fill="#27272a">' + esc(cell) + '</text>';
      });
    });
    return out;
  }

  function renderRelationPlot(panel, box, decoration, state, options) {
    var axisPadding = panel.axisPadding || {};
    var displayDomain = {
      minX: panel.domain.minX - Number(axisPadding.minX || 0),
      maxX: panel.domain.maxX + Number(axisPadding.maxX || 0),
      minY: panel.domain.minY - Number(axisPadding.minY || 0),
      maxY: panel.domain.maxY + Number(axisPadding.maxY || 0)
    };
    var graphPanel = Object.assign({}, panel, {
      kind: "functionGraph",
      domain: displayDomain,
      function: { variable: "x", expr: "0", label: "" },
      range: []
    });
    var out = panelFrame(panel, box, options);
    var layout = graphLayout(graphPanel, box);
    var inner = layout.inner;
    var axisY = layout.point(0, 0).y;
    var axisX = layout.point(0, 0).x;
    var axisColor = "#475569";
    var originalFigure = options && options.originalFigure;
    var tickFontSize = originalFigure ? 34 : 18;
    var axisLabelFontSize = originalFigure ? 38 : 22;
    var originFontSize = originalFigure ? 30 : 18;
    var arrowId = "relation-axis-arrow-" + String(panel.id).replace(/[^A-Za-z0-9_-]/g, "-");
    out += '<defs><marker id="' + arrowId + '" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="' + axisColor + '" /></marker></defs>';
    out += '<line x1="' + inner.x + '" y1="' + axisY + '" x2="' + (inner.x + inner.width) + '" y2="' + axisY + '" stroke="' + axisColor + '" stroke-width="1.8" marker-end="url(#' + arrowId + ')" />';
    out += '<line x1="' + axisX + '" y1="' + (inner.y + inner.height) + '" x2="' + axisX + '" y2="' + inner.y + '" stroke="' + axisColor + '" stroke-width="1.8" marker-end="url(#' + arrowId + ')" />';
    out += '<text data-axis-label="x" x="' + (inner.x + inner.width + 12) + '" y="' + (axisY - 10) + '" text-anchor="start" font-size="' + axisLabelFontSize + '" font-style="italic" fill="' + axisColor + '">x</text>';
    out += '<text data-axis-label="y" x="' + (axisX + 12) + '" y="' + (inner.y + axisLabelFontSize * 0.84) + '" text-anchor="start" font-size="' + axisLabelFontSize + '" font-style="italic" fill="' + axisColor + '">y</text>';
    out += '<text x="' + (axisX - 12) + '" y="' + (axisY + 34) + '" text-anchor="end" font-size="' + originFontSize + '" fill="#64748b">O</text>';
    for (var xTick = Math.ceil(panel.domain.minX); xTick <= Math.floor(panel.domain.maxX); xTick += 1) {
      if (Math.abs(xTick) < 1e-9) continue;
      var xTickPosition = layout.point(xTick, 0).x;
      out += '<line x1="' + xTickPosition + '" y1="' + (axisY - 6) + '" x2="' + xTickPosition + '" y2="' + (axisY + 6) + '" stroke="' + axisColor + '" />';
      out += '<text data-axis-tick="x" data-axis-value="' + formatNumber(xTick) + '" x="' + xTickPosition + '" y="' + (axisY + 39) + '" text-anchor="middle" font-size="' + tickFontSize + '" fill="#475569">' + formatNumber(xTick) + '</text>';
    }
    for (var yTick = Math.ceil(panel.domain.minY); yTick <= Math.floor(panel.domain.maxY); yTick += 1) {
      if (Math.abs(yTick) < 1e-9) continue;
      var yTickPosition = layout.point(0, yTick).y;
      out += '<line x1="' + (axisX - 6) + '" y1="' + yTickPosition + '" x2="' + (axisX + 6) + '" y2="' + yTickPosition + '" stroke="' + axisColor + '" />';
      out += '<text data-axis-tick="y" data-axis-value="' + formatNumber(yTick) + '" x="' + (axisX - 14) + '" y="' + (yTickPosition + tickFontSize * 0.32) + '" text-anchor="end" font-size="' + tickFontSize + '" fill="#475569">' + formatNumber(yTick) + '</text>';
    }
    (panel.guidePoints || []).forEach(function (guidePoint) {
      var guide = layout.point(guidePoint.x, guidePoint.y);
      if (guidePoint.showX !== false) {
        out += '<line x1="' + guide.x + '" y1="' + axisY + '" x2="' + guide.x + '" y2="' + guide.y + '" stroke="#64748b" stroke-width="1.6" stroke-dasharray="8 7" />';
      }
      if (guidePoint.showY !== false) {
        out += '<line x1="' + axisX + '" y1="' + guide.y + '" x2="' + guide.x + '" y2="' + guide.y + '" stroke="#64748b" stroke-width="1.6" stroke-dasharray="8 7" />';
      }
    });
    (panel.segments || []).forEach(function (segment) {
      if (!elementVisible(segment.id, decoration)) return;
      var a = layout.point(segment.x1, segment.y1);
      var b = layout.point(segment.x2, segment.y2);
      out += '<line x1="' + a.x + '" y1="' + a.y + '" x2="' + b.x + '" y2="' + b.y + '" stroke="#334155" stroke-width="4" stroke-linecap="round" />';
    });
    (panel.points || []).forEach(function (point) {
      if (!elementVisible(point.id, decoration)) return;
      var p = layout.point(point.x, point.y);
      out += '<circle cx="' + p.x + '" cy="' + p.y + '" r="7" fill="#0f766e" />';
    });
    if (decoration.showVerticalTest) {
      var testX = state.parameterValue;
      var testScreenX = layout.point(testX, 0).x;
      var intersections = [];
      (panel.segments || []).forEach(function (segment) {
        if (!elementVisible(segment.id, decoration)) return;
        var minX = Math.min(segment.x1, segment.x2);
        var maxX = Math.max(segment.x1, segment.x2);
        if (testX < minX - 1e-9 || testX > maxX + 1e-9) return;
        if (Math.abs(segment.x2 - segment.x1) < 1e-9) {
          intersections.push(segment.y1, segment.y2);
          return;
        }
        var ratio = (testX - segment.x1) / (segment.x2 - segment.x1);
        intersections.push(segment.y1 + ratio * (segment.y2 - segment.y1));
      });
      var uniqueIntersections = intersections.filter(function (value, index, values) {
        return values.findIndex(function (candidate) { return Math.abs(candidate - value) < 1e-7; }) === index;
      });
      out += '<line x1="' + testScreenX + '" y1="' + inner.y + '" x2="' + testScreenX + '" y2="' + (inner.y + inner.height) + '" stroke="#f59e0b" stroke-width="3" stroke-dasharray="8 6" />';
      uniqueIntersections.forEach(function (value) {
        var intersection = layout.point(testX, value);
        out += '<circle cx="' + intersection.x + '" cy="' + intersection.y + '" r="8" fill="#fff" stroke="#f59e0b" stroke-width="4" />';
      });
      out += '<text x="' + Math.min(testScreenX + 10, inner.x + inner.width - 95) + '" y="' + (inner.y + 20) + '" font-size="14" font-weight="700" fill="#b45309">' + uniqueIntersections.length + ' 个交点</text>';
    }
    return out;
  }

  function renderContextGeometry(panel, box, state, options) {
    var out = panelFrame(panel, box, options);
    var originalFigure = options && options.originalFigure;
    var dimensionFontSize = originalFigure ? 44 : 16;
    var pointFontSize = originalFigure ? 34 : 14;
    var dimensionStrokeWidth = originalFigure ? 4 : 2.5;
    var dimensionTickWidth = originalFigure ? 3 : 2;
    var points = indexById((panel.geometry && panel.geometry.points || []).map(function (point) {
      return Object.assign({}, point, {
        x: point.xExpr == null ? point.x : evaluate(point.xExpr, state.env),
        y: point.yExpr == null ? point.y : evaluate(point.yExpr, state.env)
      });
    }));
    (panel.geometry && panel.geometry.polygons || []).forEach(function (polygon, index) {
      var values = polygon.pointIds.map(function (id) { return points[id]; }).filter(Boolean);
      var fill = polygon.fill || (index ? "#ccfbf1" : "#f8fafc");
      var stroke = polygon.stroke || "#0f766e";
      var strokeWidth = Number.isFinite(polygon.strokeWidth) ? polygon.strokeWidth : 3;
      var fillOpacity = Number.isFinite(polygon.fillOpacity)
        ? ' fill-opacity="' + polygon.fillOpacity + '"'
        : "";
      out += '<polygon data-geometry-polygon="' + esc(polygon.id) + '" points="' + values.map(function (point) { return (box.x + 35 + point.x * (box.width - 70)) + ',' + (box.y + 55 + point.y * (box.height - 90)); }).join(" ") + '" fill="' + esc(fill) + '"' + fillOpacity + ' stroke="' + esc(stroke) + '" stroke-width="' + strokeWidth + '" />';
      if (polygon.label && values.length) {
        var centerX = values.reduce(function (sum, point) { return sum + point.x; }, 0) / values.length;
        var centerY = values.reduce(function (sum, point) { return sum + point.y; }, 0) / values.length;
        out += '<text x="' + (box.x + 35 + centerX * (box.width - 70)) + '" y="' + (box.y + 55 + centerY * (box.height - 90)) + '" text-anchor="middle" font-size="17" font-weight="700" fill="#0f766e">' + esc(polygon.label) + '</text>';
      }
    });
    (panel.geometry && panel.geometry.ellipses || []).forEach(function (ellipse) {
      var center = points[ellipse.centerPointId];
      if (!center) return;
      var cx = box.x + 35 + center.x * (box.width - 70);
      var cy = box.y + 55 + center.y * (box.height - 90);
      var rx = ellipse.rx * (box.width - 70);
      var ry = ellipse.ry * (box.height - 90);
      var stroke = ellipse.stroke || "#0f766e";
      var fill = ellipse.fill || "none";
      out += '<g data-geometry-ellipse="' + esc(ellipse.id) + '">';
      out += '<ellipse cx="' + cx + '" cy="' + cy + '" rx="' + rx + '" ry="' + ry + '" fill="' + esc(fill) + '" stroke="none" />';
      if (ellipse.backHalfDashed) {
        // SVG y-down: sweep=0 goes through the upper (far/back) half; sweep=1 through the lower (near/front) half.
        out += '<path d="M ' + (cx - rx) + " " + cy + " A " + rx + " " + ry + ' 0 0 0 ' + (cx + rx) + " " + cy + '" fill="none" stroke="' + esc(stroke) + '" stroke-width="3" stroke-dasharray="8 6" />';
        out += '<path d="M ' + (cx - rx) + " " + cy + " A " + rx + " " + ry + ' 0 0 1 ' + (cx + rx) + " " + cy + '" fill="none" stroke="' + esc(stroke) + '" stroke-width="3" />';
      } else {
        out += '<ellipse cx="' + cx + '" cy="' + cy + '" rx="' + rx + '" ry="' + ry + '" fill="none" stroke="' + esc(stroke) + '" stroke-width="3" />';
      }
      out += "</g>";
    });
    (panel.geometry && panel.geometry.dimensions || []).forEach(function (dimension) {
      var start = points[dimension.startPointId];
      var end = points[dimension.endPointId];
      if (!start || !end) return;
      var x1 = box.x + 35 + start.x * (box.width - 70);
      var y1 = box.y + 55 + start.y * (box.height - 90);
      var x2 = box.x + 35 + end.x * (box.width - 70);
      var y2 = box.y + 55 + end.y * (box.height - 90);
      var color = dimension.color || "#f59e0b";
      var dash = dimension.dashed ? ' stroke-dasharray="7 6"' : "";
      var dx = x2 - x1;
      var dy = y2 - y1;
      var length = Math.sqrt(dx * dx + dy * dy) || 1;
      var tickX = (-dy / length) * 6;
      var tickY = (dx / length) * 6;
      out += '<g data-geometry-dimension="' + esc(dimension.id) + '">';
      out += '<line x1="' + x1 + '" y1="' + y1 + '" x2="' + x2 + '" y2="' + y2 + '" stroke="' + esc(color) + '" stroke-width="' + dimensionStrokeWidth + '"' + dash + ' />';
      out += '<line x1="' + (x1 - tickX) + '" y1="' + (y1 - tickY) + '" x2="' + (x1 + tickX) + '" y2="' + (y1 + tickY) + '" stroke="' + esc(color) + '" stroke-width="' + dimensionTickWidth + '" />';
      out += '<line x1="' + (x2 - tickX) + '" y1="' + (y2 - tickY) + '" x2="' + (x2 + tickX) + '" y2="' + (y2 + tickY) + '" stroke="' + esc(color) + '" stroke-width="' + dimensionTickWidth + '" />';
      out += '<text x="' + ((x1 + x2) / 2 + (dimension.labelDx || 0)) + '" y="' + ((y1 + y2) / 2 + (dimension.labelDy || 0)) + '" text-anchor="middle" font-size="' + dimensionFontSize + '" font-weight="700" fill="' + esc(color) + '">' + renderSvgMathLabel(dimension.label) + '</text>';
      out += "</g>";
    });
    Object.values(points).forEach(function (point) {
      if (!point.label) return;
      out += '<text x="' + (box.x + 35 + point.x * (box.width - 70) + (point.labelDx == null ? 8 : point.labelDx)) + '" y="' + (box.y + 55 + point.y * (box.height - 90) + (point.labelDy == null ? -8 : point.labelDy)) + '" font-size="' + pointFontSize + '" font-weight="700" fill="#334155">' + esc(point.label) + '</text>';
    });
    return out;
  }

  function createSpecRenderer(spec, decorations, steps, _policies, options) {
    var width = options && options.W || 1080;
    var height = options && options.H || 760;
    function renderPanel(panel, box, decoration, state, candidateOverride, renderOptions) {
      if (panel.kind === "mapping") return renderMapping(panel, box, decoration, state, candidateOverride);
      if (panel.kind === "numberLine") return renderNumberLine(panel, box, decoration);
      if (panel.kind === "constraintList") return renderConstraintList(panel, box, decoration);
      if (panel.kind === "functionGraph") return renderFunctionGraph(panel, box, decoration, state, candidateOverride, renderOptions);
      if (panel.kind === "valueTable") return renderValueTable(panel, box, decoration, renderOptions);
      if (panel.kind === "relationPlot") return renderRelationPlot(panel, box, decoration, state, renderOptions);
      if (panel.kind === "contextGeometry") return renderContextGeometry(panel, box, state, renderOptions);
      return "";
    }
    function render(index, parameterValue, localVars, candidateOverride) {
      var step = steps[index] || steps[0];
      var decoration = decorations.steps[step.id] || {};
      var state = resolveState(spec, parameterValue, localVars);
      var visible = decoration.visiblePanels || spec.panels.map(function (panel) { return panel.id; });
      // Return inner SVG markup only; LessonPageRuntime wraps the outer <svg>.
      var out = "";
      spec.panels.forEach(function (panel) {
        if (visible.indexOf(panel.id) < 0) return;
        var box = panelBox(panel, width, height);
        out += renderPanel(panel, box, decoration, state, candidateOverride);
      });
      return out;
    }
    function originalFigureMarkupFor(panelId) {
      var panel = spec.panels.find(function (candidate) { return candidate.id === panelId; });
      if (!panel) return "";
      var state = resolveState(spec, spec.parameter && spec.parameter.initial, {});
      var detailFunctionGraph = panel.kind === "functionGraph" && width > 900;
      var figureWidth = detailFunctionGraph ? 720 : width;
      var figureHeight = detailFunctionGraph
        ? 660
        : (panel.kind === "valueTable" && height / width > 0.6
          ? Math.round(width / 2)
          : height);
      return renderPanel(
        panel,
        { x: 24, y: 18, width: figureWidth - 48, height: figureHeight - 36 },
        { showVerticalTest: false },
        state,
        undefined,
        {
          hideTitle: true,
          originalFigure: true,
          originalFigureScale: detailFunctionGraph ? "detail" : "aggregate"
        }
      );
    }
    function renderOriginalFigures() {
      if (typeof document === "undefined") return;
      spec.panels.forEach(function (panel) {
        var element = document.getElementById(panel.id);
        if (!element) return;
        if (panel.kind === "valueTable" && height / width > 0.6) {
          element.setAttribute("viewBox", "0 0 " + width + " " + Math.round(width / 2));
        } else if (panel.kind === "functionGraph" && width > 900) {
          element.setAttribute("viewBox", "0 0 720 660");
        }
        element.innerHTML = originalFigureMarkupFor(panel.id);
      });
    }
    return {
      resolveStateFor: function (parameterValue, localVars) { return resolveState(spec, parameterValue, localVars); },
      diagramMarkupFor: function (index, parameterValue, localVars) { return render(index, parameterValue, localVars); },
      diagramMarkupForFrame: function (index, _frame, parameterValue, localVars) { return render(index, parameterValue, localVars); },
      originalFigureMarkupFor: originalFigureMarkupFor,
      renderOriginalFigures: renderOriginalFigures,
      drawMini: function (parameterValue, miniItem, step) {
        var index = Math.max(0, steps.indexOf(step));
        return '<svg viewBox="0 0 ' + width + ' ' + height + '" aria-hidden="true">' + render(index, parameterValue, {}, miniItem && miniItem.candidateId) + '</svg>';
      }
    };
  }

  global.FunctionLessonFromSpec = {
    createSpecRenderer: createSpecRenderer,
    evaluate: evaluate,
    functionValue: functionValue,
    resolveState: resolveState
  };
})(typeof window !== "undefined" ? window : globalThis);
