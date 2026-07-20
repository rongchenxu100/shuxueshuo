/**
 * Declarative renderer for high-school calculus lesson specs.
 * Depends on MathExpressionEngine and exposes window.CalculusLessonFromSpec.
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

  function clamp(value, min, max) {
    return Math.max(min, Math.min(max, value));
  }

  function evaluate(expr, env) {
    return MEE.evaluate(String(expr == null ? "0" : expr), env || {});
  }

  function evaluateFunction(definition, x, env) {
    var nextEnv = Object.assign({}, env || {});
    nextEnv[definition.variable] = Number(x);
    return evaluate(definition.expr, nextEnv);
  }

  function evaluateDerivative(definition, x, env) {
    if (!definition.derivativeExpr) return NaN;
    var nextEnv = Object.assign({}, env || {});
    nextEnv[definition.variable] = Number(x);
    return evaluate(definition.derivativeExpr, nextEnv);
  }

  function indexById(items) {
    var result = {};
    (items || []).forEach(function (item) {
      if (item && item.id) result[item.id] = item;
    });
    return result;
  }

  function resolveState(spec, parameterValue, localVars) {
    var parameter = spec.parameter || { name: "t", initial: 0 };
    var value = Number(parameterValue);
    if (!Number.isFinite(value)) value = Number(parameter.initial) || 0;
    var env = Object.assign({}, localVars || {});
    env[parameter.name] = value;

    (spec.bindings || []).forEach(function (binding) {
      env[binding.name] = evaluate(binding.expr, env);
    });

    var functions = indexById(spec.functions);
    var panels = indexById(spec.panels);
    var points = {};
    (spec.functionPoints || []).forEach(function (definition) {
      var fn = functions[definition.functionId];
      if (!fn) return;
      var x = evaluate(definition.xExpr, env);
      points[definition.id] = {
        id: definition.id,
        panelId: definition.panelId || fn.panelId,
        functionId: fn.id,
        x: x,
        y: evaluateFunction(fn, x, env)
      };
    });

    var tangents = {};
    (spec.tangentLines || []).forEach(function (definition) {
      var fn = functions[definition.functionId];
      if (!fn) return;
      var x = evaluate(definition.atExpr, env);
      var y = evaluateFunction(fn, x, env);
      var slope = evaluateDerivative(fn, x, env);
      tangents[definition.id] = {
        id: definition.id,
        panelId: definition.panelId || fn.panelId,
        functionId: fn.id,
        x: x,
        y: y,
        slope: slope,
        intercept: y - slope * x
      };
    });

    var lines = {};
    (spec.lines || []).forEach(function (definition) {
      lines[definition.id] = {
        id: definition.id,
        panelId: definition.panelId,
        slope: evaluate(definition.slopeExpr, env),
        intercept: evaluate(definition.interceptExpr, env)
      };
    });

    return {
      parameterValue: value,
      env: env,
      functions: functions,
      panels: panels,
      points: points,
      tangents: tangents,
      lines: lines
    };
  }

  function intervalContains(interval, x) {
    if (x < interval.min || x > interval.max) return false;
    if (interval.openMin && x === interval.min) return false;
    if (interval.openMax && x === interval.max) return false;
    return true;
  }

  function functionIntervals(definition, panelDomain) {
    var declared = definition.domain && definition.domain.length
      ? definition.domain
      : [{ min: panelDomain.minX, max: panelDomain.maxX }];
    return declared
      .map(function (interval) {
        return {
          min: Math.max(panelDomain.minX, Number(interval.min)),
          max: Math.min(panelDomain.maxX, Number(interval.max)),
          openMin: Boolean(interval.openMin),
          openMax: Boolean(interval.openMax)
        };
      })
      .filter(function (interval) { return interval.max > interval.min; });
  }

  function sampleFunction(definition, env, panelDomain, samples) {
    var count = Math.max(16, Number(samples) || 180);
    var segments = [];
    functionIntervals(definition, panelDomain).forEach(function (interval) {
      var current = [];
      var previous = null;
      for (var index = 0; index <= count; index += 1) {
        var ratio = index / count;
        var x = interval.min + (interval.max - interval.min) * ratio;
        if ((index === 0 && interval.openMin) || (index === count && interval.openMax)) {
          x += index === 0 ? 1e-7 : -1e-7;
        }
        if (!intervalContains(interval, x)) continue;
        var y;
        try {
          y = evaluateFunction(definition, x, env);
        } catch (_error) {
          y = NaN;
        }
        var point = { x: x, y: y };
        var finite = Number.isFinite(y);
        var jump = previous && finite && Number.isFinite(previous.y)
          ? Math.abs(y - previous.y) > Math.max(20, (panelDomain.maxY - panelDomain.minY) * 2.5)
          : false;
        if (!finite || jump) {
          if (current.length > 1) segments.push(current);
          current = [];
        }
        if (finite) current.push(point);
        previous = point;
      }
      if (current.length > 1) segments.push(current);
    });
    return segments;
  }

  function niceStep(span) {
    var rough = span / 6;
    var magnitude = Math.pow(10, Math.floor(Math.log(rough) / Math.LN10));
    var normalized = rough / magnitude;
    var multiple = normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10;
    return multiple * magnitude;
  }

  function formatNumber(value) {
    if (Math.abs(value) < 1e-9) return "0";
    return Number(value).toFixed(2).replace(/\.00$/, "").replace(/(\.\d)0$/, "$1");
  }

  function panelLayout(panel, domain, width, height) {
    var viewport = panel.viewport;
    var outer = {
      x: viewport.x * width,
      y: viewport.y * height,
      width: viewport.width * width,
      height: viewport.height * height
    };
    var inner = {
      x: outer.x + 50,
      y: outer.y + 30,
      width: Math.max(40, outer.width - 70),
      height: Math.max(40, outer.height - 72)
    };
    function toScreen(point) {
      return {
        x: inner.x + ((point.x - domain.minX) / (domain.maxX - domain.minX)) * inner.width,
        y: inner.y + inner.height - ((point.y - domain.minY) / (domain.maxY - domain.minY)) * inner.height
      };
    }
    return { outer: outer, inner: inner, toScreen: toScreen, domain: domain };
  }

  function activeLayer(layer, step) {
    if (layer.section && layer.section !== step.section) return false;
    if (layer.sectionNot && layer.sectionNot === step.section) return false;
    if (Array.isArray(layer.stepIds) && layer.stepIds.indexOf(step.id) < 0) return false;
    if (Array.isArray(layer.stepStartsWith)) {
      return layer.stepStartsWith.some(function (prefix) { return step.id.indexOf(prefix) === 0; });
    }
    return true;
  }

  function createSpecRenderer(spec, decorations, steps, policies, options) {
    var opts = options || {};
    var W = opts.W || 1080;
    var H = opts.H || 760;
    var layers = decorations.layers || {};
    var stepDecorations = decorations.steps || {};
    var renderSequence = 0;

    function renderGrid(panel, layout) {
      var domain = layout.domain;
      var inner = layout.inner;
      var toScreen = layout.toScreen;
      var out = '<rect x="' + layout.outer.x + '" y="' + layout.outer.y + '" width="' + layout.outer.width + '" height="' + layout.outer.height + '" rx="12" fill="#ffffff" stroke="#e4e4e7" />';
      out += '<text x="' + (layout.outer.x + 18) + '" y="' + (layout.outer.y + 21) + '" font-size="15" font-weight="700" fill="#3f3f46">' + esc(panel.title || panel.id) + '</text>';
      var xStep = niceStep(domain.maxX - domain.minX);
      var yStep = niceStep(domain.maxY - domain.minY);
      var xStart = Math.ceil(domain.minX / xStep) * xStep;
      var yStart = Math.ceil(domain.minY / yStep) * yStep;
      for (var x = xStart; x <= domain.maxX + 1e-9; x += xStep) {
        var sx = toScreen({ x: x, y: 0 }).x;
        out += '<line x1="' + sx + '" y1="' + inner.y + '" x2="' + sx + '" y2="' + (inner.y + inner.height) + '" stroke="#f1f5f9" stroke-width="1" />';
        out += '<text x="' + sx + '" y="' + (inner.y + inner.height + 19) + '" text-anchor="middle" font-size="11" fill="#71717a">' + formatNumber(x) + '</text>';
      }
      for (var y = yStart; y <= domain.maxY + 1e-9; y += yStep) {
        var sy = toScreen({ x: 0, y: y }).y;
        out += '<line x1="' + inner.x + '" y1="' + sy + '" x2="' + (inner.x + inner.width) + '" y2="' + sy + '" stroke="#f1f5f9" stroke-width="1" />';
        out += '<text x="' + (inner.x - 8) + '" y="' + (sy + 4) + '" text-anchor="end" font-size="11" fill="#71717a">' + formatNumber(y) + '</text>';
      }
      if (domain.minY <= 0 && domain.maxY >= 0) {
        var axisY = toScreen({ x: 0, y: 0 }).y;
        out += '<line x1="' + inner.x + '" y1="' + axisY + '" x2="' + (inner.x + inner.width) + '" y2="' + axisY + '" stroke="#94a3b8" stroke-width="1.4" />';
      }
      if (domain.minX <= 0 && domain.maxX >= 0) {
        var axisX = toScreen({ x: 0, y: 0 }).x;
        out += '<line x1="' + axisX + '" y1="' + inner.y + '" x2="' + axisX + '" y2="' + (inner.y + inner.height) + '" stroke="#94a3b8" stroke-width="1.4" />';
      }
      out += '<text x="' + (inner.x + inner.width - 2) + '" y="' + (inner.y + inner.height + 31) + '" text-anchor="end" font-size="13" font-style="italic" fill="#52525b">' + esc(panel.xLabel || "x") + '</text>';
      out += '<text x="' + (inner.x - 32) + '" y="' + (inner.y + 12) + '" text-anchor="middle" font-size="13" font-style="italic" fill="#52525b">' + esc(panel.yLabel || "y") + '</text>';
      return out;
    }

    function pathFromPoints(points, toScreen) {
      return points.map(function (point, index) {
        var screen = toScreen(point);
        return (index === 0 ? "M" : "L") + screen.x.toFixed(2) + " " + screen.y.toFixed(2);
      }).join(" ");
    }

    function renderPoint(point, layout, element) {
      if (!point || !Number.isFinite(point.x) || !Number.isFinite(point.y)) return "";
      var screen = layout.toScreen(point);
      var color = element.color || "#0f766e";
      var out = '<circle cx="' + screen.x + '" cy="' + screen.y + '" r="' + (element.r || 5.2) + '" fill="#fff" stroke="' + color + '" stroke-width="2.6" />';
      if (element.showLabel !== false && (element.label || point.id)) {
        out += '<text x="' + (screen.x + (element.dx == null ? 9 : element.dx)) + '" y="' + (screen.y + (element.dy == null ? -10 : element.dy)) + '" font-size="13" font-weight="700" fill="' + color + '">' + esc(element.label || point.id) + '</text>';
      }
      return out;
    }

    function renderElement(element, state, panelLayouts, clipIds) {
      var fn = element.functionId ? state.functions[element.functionId] : null;
      var point = element.pointId ? state.points[element.pointId] : null;
      var tangent = element.tangentId ? state.tangents[element.tangentId] : null;
      var line = element.lineId ? state.lines[element.lineId] : null;
      var panelId = element.panelId || (fn && fn.panelId) || (point && point.panelId) || (tangent && tangent.panelId) || (line && line.panelId);
      var layout = panelLayouts[panelId];
      if (element.type === "grid") return layout ? renderGrid(state.panels[panelId], layout) : "";
      if (!layout) return "";
      var domain = layout.domain;
      var clip = ' clip-path="url(#' + clipIds[panelId] + ')"';

      if (element.type === "functionCurve" && fn) {
        return sampleFunction(fn, state.env, domain, element.samples).map(function (segment) {
          return '<path d="' + pathFromPoints(segment, layout.toScreen) + '" fill="none" stroke="' + (element.color || "#2563eb") + '" stroke-width="' + (element.width || 2.8) + '" stroke-linecap="round" stroke-linejoin="round"' + clip + ' />';
        }).join("");
      }
      if (element.type === "functionPoint") return renderPoint(point, layout, element);
      if (element.type === "criticalPoint" && fn) {
        var criticalX = evaluate(element.xExpr, state.env);
        return renderPoint({ id: element.label || "", x: criticalX, y: evaluateFunction(fn, criticalX, state.env) }, layout, element);
      }
      if ((element.type === "tangentLine" && tangent) || (element.type === "line" && line)) {
        var source = tangent || line;
        var p1 = { x: domain.minX, y: source.slope * domain.minX + source.intercept };
        var p2 = { x: domain.maxX, y: source.slope * domain.maxX + source.intercept };
        var s1 = layout.toScreen(p1);
        var s2 = layout.toScreen(p2);
        return '<line x1="' + s1.x + '" y1="' + s1.y + '" x2="' + s2.x + '" y2="' + s2.y + '" stroke="' + (element.color || "#dc2626") + '" stroke-width="' + (element.width || 2.4) + '"' + (element.dash ? ' stroke-dasharray="' + esc(element.dash) + '"' : "") + clip + ' />';
      }
      if (element.type === "guideLine") {
        var guideValue = evaluate(element.valueExpr, state.env);
        var ga = element.orientation === "horizontal"
          ? layout.toScreen({ x: domain.minX, y: guideValue })
          : layout.toScreen({ x: guideValue, y: domain.minY });
        var gb = element.orientation === "horizontal"
          ? layout.toScreen({ x: domain.maxX, y: guideValue })
          : layout.toScreen({ x: guideValue, y: domain.maxY });
        return '<line x1="' + ga.x + '" y1="' + ga.y + '" x2="' + gb.x + '" y2="' + gb.y + '" stroke="' + (element.color || "#64748b") + '" stroke-width="' + (element.width || 1.5) + '" stroke-dasharray="' + (element.dash || "6 5") + '"' + clip + ' />';
      }
      if (element.type === "intervalHighlight") {
        var from = clamp(evaluate(element.fromExpr, state.env), domain.minX, domain.maxX);
        var to = clamp(evaluate(element.toExpr, state.env), domain.minX, domain.maxX);
        var left = layout.toScreen({ x: Math.min(from, to), y: 0 }).x;
        var right = layout.toScreen({ x: Math.max(from, to), y: 0 }).x;
        return '<rect x="' + left + '" y="' + layout.inner.y + '" width="' + Math.max(0, right - left) + '" height="' + layout.inner.height + '" fill="' + (element.fill || "rgba(14,165,233,.08)") + '"' + clip + ' />';
      }
      if (element.type === "rangeBand") {
        var minY = clamp(evaluate(element.minExpr, state.env), domain.minY, domain.maxY);
        var maxY = element.maxExpr ? clamp(evaluate(element.maxExpr, state.env), domain.minY, domain.maxY) : domain.maxY;
        var top = layout.toScreen({ x: 0, y: Math.max(minY, maxY) }).y;
        var bottom = layout.toScreen({ x: 0, y: Math.min(minY, maxY) }).y;
        return '<rect x="' + layout.inner.x + '" y="' + top + '" width="' + layout.inner.width + '" height="' + Math.max(0, bottom - top) + '" fill="' + (element.fill || "rgba(16,185,129,.09)") + '"' + clip + ' />';
      }
      if (element.type === "signBand" && fn) {
        var roots = (element.roots || []).map(function (expr) { return evaluate(expr, state.env); })
          .filter(function (value) { return Number.isFinite(value) && value > domain.minX && value < domain.maxX; })
          .sort(function (a, b) { return a - b; });
        var boundaries = [domain.minX].concat(roots, [domain.maxX]);
        var bandY = layout.inner.y + layout.inner.height - 18;
        var out = "";
        for (var boundaryIndex = 0; boundaryIndex < boundaries.length - 1; boundaryIndex += 1) {
          var lo = boundaries[boundaryIndex];
          var hi = boundaries[boundaryIndex + 1];
          var mid = (lo + hi) / 2;
          var signValue = fn.derivativeExpr ? evaluateDerivative(fn, mid, state.env) : evaluateFunction(fn, mid, state.env);
          var leftX = layout.toScreen({ x: lo, y: 0 }).x;
          var rightX = layout.toScreen({ x: hi, y: 0 }).x;
          var positive = signValue >= 0;
          out += '<rect x="' + leftX + '" y="' + bandY + '" width="' + (rightX - leftX) + '" height="16" fill="' + (positive ? "rgba(16,185,129,.18)" : "rgba(244,63,94,.14)") + '" />';
          out += '<text x="' + ((leftX + rightX) / 2) + '" y="' + (bandY + 12) + '" text-anchor="middle" font-size="12" font-weight="800" fill="' + (positive ? "#047857" : "#be123c") + '">' + (positive ? "+" : "−") + '</text>';
        }
        return out;
      }
      if (element.type === "functionLabel" && fn) {
        var labelX = evaluate(element.xExpr, state.env);
        var labelY = evaluateFunction(fn, labelX, state.env);
        if (!Number.isFinite(labelY)) return "";
        var labelScreen = layout.toScreen({ x: labelX, y: labelY });
        return '<text x="' + (labelScreen.x + (element.dx || 8)) + '" y="' + (labelScreen.y + (element.dy || -8)) + '" font-size="13" font-weight="700" fill="' + (element.color || "#2563eb") + '">' + esc(element.text || fn.id) + '</text>';
      }
      return "";
    }

    function diagramMarkupFor(index, overrideParameter, localVars) {
      var step = steps[index];
      if (!step) return "";
      var state = resolveState(spec, overrideParameter == null ? step.t : overrideParameter, localVars);
      var deco = stepDecorations[step.id] || {};
      var panelLayouts = {};
      var visiblePanels = Array.isArray(deco.visiblePanels) ? deco.visiblePanels : null;
      (spec.panels || []).forEach(function (panel) {
        if (visiblePanels && visiblePanels.indexOf(panel.id) < 0) return;
        var domain = deco.panelDomains && deco.panelDomains[panel.id]
          ? deco.panelDomains[panel.id]
          : panel.domain;
        var viewport = deco.panelViewports && deco.panelViewports[panel.id]
          ? deco.panelViewports[panel.id]
          : panel.viewport;
        panelLayouts[panel.id] = panelLayout(
          Object.assign({}, panel, { viewport: viewport }),
          domain,
          W,
          H,
        );
      });

      renderSequence += 1;
      var clipIds = {};
      var defs = "<defs>";
      Object.keys(panelLayouts).forEach(function (panelId) {
        var layout = panelLayouts[panelId];
        var clipId = "calc-clip-" + renderSequence + "-" + panelId.replace(/[^A-Za-z0-9_-]/g, "-");
        clipIds[panelId] = clipId;
        defs += '<clipPath id="' + clipId + '"><rect x="' + layout.inner.x + '" y="' + layout.inner.y + '" width="' + layout.inner.width + '" height="' + layout.inner.height + '" /></clipPath>';
      });
      defs += "</defs>";

      var elements = [];
      var hidden = deco.hideLayers || [];
      Object.keys(layers).forEach(function (name) {
        if (hidden.indexOf(name) >= 0 || !activeLayer(layers[name], step)) return;
        elements = elements.concat(layers[name].elements || []);
      });
      elements = elements.concat(deco.add || []);
      return defs + elements.map(function (element) {
        return renderElement(element, state, panelLayouts, clipIds);
      }).join("");
    }

    function diagramMarkupForFrame(index, _frame, overrideParameter, localVars) {
      return diagramMarkupFor(index, overrideParameter, localVars);
    }

    function drawMini(parameterValue, _miniItem, step) {
      var index = Math.max(0, steps.indexOf(step));
      return '<svg viewBox="0 0 ' + W + ' ' + H + '" aria-hidden="true">' + diagramMarkupFor(index, parameterValue, {}) + '</svg>';
    }

    function renderOriginalFigures() {}

    return {
      diagramMarkupFor: diagramMarkupFor,
      diagramMarkupForFrame: diagramMarkupForFrame,
      drawMini: drawMini,
      renderOriginalFigures: renderOriginalFigures,
      resolveStateFor: function (parameterValue, localVars) {
        return resolveState(spec, parameterValue, localVars);
      }
    };
  }

  global.CalculusLessonFromSpec = {
    createSpecRenderer: createSpecRenderer,
    evaluateFunction: evaluateFunction,
    evaluateDerivative: evaluateDerivative,
    resolveState: resolveState,
    sampleFunction: sampleFunction
  };
})(typeof window !== "undefined" ? window : this);
