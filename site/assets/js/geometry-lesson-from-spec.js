/**
 * 从 geometry-spec（声明式）解析动点状态，并提供完整的 SVG 渲染管线。
 * 依赖：GeometryEngine（必须先加载）
 * 可选：GeometryLabelLayout（有则自动启用标注避让）
 * 暴露：window.GeometryLessonFromSpec
 */
(function (global) {
  "use strict";

  /** 解析交叉点与裁剪重叠区域（spec 格式见 geometry-spec.json）。 */
  function resolveClipOverlap(spec, t) {
    var GE = global.GeometryEngine;
    if (!GE) throw new Error("GeometryEngine is required");
    var paramName = spec.movingParam || "t";
    var tv = Number(t);
    var env = { S3: GE.SQRT3, t: tv };
    env[paramName] = tv;
    var pts = {};

    (spec.expressionEnv || []).forEach(function (item) {
      if (!item || !item.name) return;
      env[item.name] = GE.evalExpr(String(item.expr != null ? item.expr : ""), env);
    });

    var fp = spec.fixedPoints || {};
    Object.keys(fp).forEach(function (k) { pts[k] = GE.evalPoint(fp[k], env); });

    var mp = spec.movingPoints || {};
    Object.keys(mp).forEach(function (k) { pts[k] = GE.evalPoint(mp[k], env); });

    var derived = spec.derivedIntersections || [];
    for (var i = 0; i < derived.length; i++) {
      var d = derived[i];
      var p1 = pts[d.a[0]], p2 = pts[d.a[1]];
      var p3 = pts[d.b[0]], p4 = pts[d.b[1]];
      var hit = GE.segmentIntersection(p1, p2, p3, p4);
      if (hit) {
        pts[d.name] = hit;
      } else if (d.fallback) {
        pts[d.name] = { x: GE.evalExpr(d.fallback[0], env), y: GE.evalExpr(d.fallback[1], env) };
      } else {
        pts[d.name] = { x: NaN, y: NaN };
      }
    }

    var curves = {};
    (spec.curves || []).forEach(function (c) {
      if (!c || !c.id) return;
      if (c.type === "parabola") {
        var pa = c.a != null ? c.a : (c.params && c.params.a);
        var pb = c.b != null ? c.b : (c.params && c.params.b);
        var pc = c.c != null ? c.c : (c.params && c.params.c);
        if (pa == null || pb == null || pc == null) {
          throw new Error("parabola curve missing a/b/c: " + c.id);
        }
        curves[c.id] = {
          type: "parabola",
          a: GE.evalExpr(String(pa), env),
          b: GE.evalExpr(String(pb), env),
          c: GE.evalExpr(String(pc), env)
        };
      }
    });

    function verticalFoldPolygon(source, xFold, side) {
      if (!source || source.length < 3) return [];
      var keepLeft = side !== "right";
      var output = [];
      function inside(p) {
        return keepLeft ? p.x <= xFold + 1e-9 : p.x >= xFold - 1e-9;
      }
      function intersect(a, b) {
        var u = (xFold - a.x) / (b.x - a.x);
        return { x: xFold, y: a.y + u * (b.y - a.y) };
      }
      for (var ci = 0; ci < source.length; ci += 1) {
        var a0 = source[(ci + source.length - 1) % source.length];
        var b0 = source[ci];
        var ia = inside(a0);
        var ib = inside(b0);
        if (ib) {
          if (!ia) output.push(intersect(a0, b0));
          output.push(b0);
        } else if (ia) {
          output.push(intersect(a0, b0));
        }
      }
      return output.map(function (p) { return { x: 2 * xFold - p.x, y: p.y }; });
    }

    var base = (spec.basePolygon || []).map(function (n) { return pts[n]; }).filter(Boolean);
    function tInRange(def) {
      if (!def) return false;
      if (def.minT != null && tv < def.minT - 1e-9) return false;
      if (def.maxT != null && tv > def.maxT + 1e-9) return false;
      return true;
    }

    function polygonFromPointNames(names) {
      return (names || []).map(function (n) { return pts[n]; }).filter(Boolean);
    }

    var moving = [];
    if (spec.foldedPolygon && base.length >= 3) {
      moving = verticalFoldPolygon(base, GE.evalExpr(String(spec.foldedPolygon.x || paramName), env), spec.foldedPolygon.side || "left");
    } else if (Array.isArray(spec.movingPolygons) && spec.movingPolygons.length) {
      var activePoly = spec.movingPolygons.find(tInRange) || spec.movingPolygons[0];
      moving = polygonFromPointNames(activePoly.vertices || activePoly.points || []);
    } else {
      moving = polygonFromPointNames(spec.movingPolygon || []);
    }
    var overlap = [];
    if (base.length >= 3 && moving.length >= 3) {
      overlap = GE.clipPolygon(moving, base);
    }

    return {
      points: pts,
      base: base,
      moving: moving,
      overlap: overlap,
      area: GE.polygonArea(overlap),
      t: tv,
      env: env,
      curves: curves
    };
  }

  /** 将 resolveClipOverlap 结果适配成南开页旧字段名（兼容现存代码）。 */
  function asNankaiStateShape(resolved) {
    var p = resolved.points;
    return { P: p.P, M: p.M, N: p.N, E: p.E, F: p.F, H: p.H, G: p.G, K: p.K, R: p.R, moving: resolved.moving, overlap: resolved.overlap, area: resolved.area };
  }

  // ────────────────────────────────────────────────────────────────────────
  // 声明式渲染管线
  // ────────────────────────────────────────────────────────────────────────

  /**
   * 创建一个基于 geometry-spec + step-decorations 的渲染器。
   *
   * @param {object} spec          geometry-spec.json 对象
   * @param {object} decoData      step-decorations.json 对象（含 layers + steps）
   * @param {Array}  STEPS         STEPS 数组（来自题页）
   * @param {object} POLICIES      POLICIES 对象（来自题页）
   * @param {object} opts          可选配置：W, H, PAD（画布和内边距）
   * @returns {{ diagramMarkupFor, drawMini, renderOriginalFigures }}
   */
  function createSpecRenderer(spec, decoData, STEPS, POLICIES, opts) {
    var GE = global.GeometryEngine;
    var GLL = global.GeometryLabelLayout || null;
    opts = opts || {};

    var W = opts.W || 1080;
    var H = opts.H || 760;
    var PAD = opts.PAD || { left: 92, right: 78, top: 48, bottom: 66 };
    var defaultDomain = spec.domain;
    var domain = defaultDomain;
    var toScreen = GE.createToScreen(domain, PAD, W, H);
    var layers = decoData.layers || {};
    var stepDecos = decoData.steps || {};

    var _layout = null; // 当前 label layout（每次 render 开始时创建，结束时清空）
    var _coordinateLabelPoints = null; // 当前步骤中已显示坐标标签的点，避免重复点名
    var _pointLabelKeys = null; // 当前步骤中已显示的点名，避免层叠时重复点名

    function setRenderDomain(nextDomain) {
      domain = nextDomain || defaultDomain;
      toScreen = GE.createToScreen(domain, PAD, W, H);
    }

    // ── 内部 SVG 工具 ────────────────────────────────────────────────────

    function pathD(pts) {
      if (!pts || !pts.length) return "";
      var first = toScreen(pts[0]);
      var d = "M " + first.x + " " + first.y;
      for (var i = 1; i < pts.length; i++) {
        var q = toScreen(pts[i]);
        d += " L " + q.x + " " + q.y;
      }
      return d + " Z";
    }

    function screenRadiusFromMath(center, radius) {
      var c = toScreen(center);
      var e = toScreen({ x: center.x + radius, y: center.y });
      return Math.abs(e.x - c.x);
    }

    function lineSvg(a, b, color, width, dash) {
      var p = toScreen(a), q = toScreen(b);
      var da = dash ? ' stroke-dasharray="' + dash + '"' : "";
      return '<line x1="' + p.x + '" y1="' + p.y + '" x2="' + q.x + '" y2="' + q.y +
        '" stroke="' + (color || "#334155") + '" stroke-width="' + (width || 2) + '"' + da + ' />';
    }

    function textAtSvg(p, text, color, dx, dy, size) {
      var s = toScreen(p);
      return '<text x="' + (s.x + (dx || 8)) + '" y="' + (s.y + (dy || -10)) +
        '" font-size="' + (size || 14) + '" font-weight="900" fill="' + (color || "#334155") + '">' +
        GE.svgEsc(text) + '</text>';
    }

    function pointSvg(p, label, color, dx, dy, popts) {
      popts = popts || {};
      var s = toScreen(p);
      var r = popts.r || 5.2;
      var col = color || "#1f2937";
      var circle = '<circle cx="' + s.x + '" cy="' + s.y + '" r="' + r +
        '" fill="' + col + '" stroke="#fff" stroke-width="1.8" />';
      if (!label) return circle;
      var fs = popts.fontSize || 15, fw = popts.fontWeight || 900;
      if (GLL && _layout) {
        _layout.occupied.push({ left: s.x - 8, top: s.y - 8, right: s.x + 8, bottom: s.y + 8, kind: "self-point" });
        var candidates = [{ dx: dx || 8, dy: dy || -8 }];
        if (popts.altDx != null) candidates.push({ dx: popts.altDx, dy: popts.altDy != null ? popts.altDy : (dy || -8) });
        if (GLL.candidateOffsets) candidates = candidates.concat(GLL.candidateOffsets(dx || 8, dy || -8));
        return circle + GLL.labelSvg(_layout, p, label, { color: col, fontSize: fs, fontWeight: fw, preferredDx: dx || 8, preferredDy: dy || -8, candidates: candidates, allowNearPoint: true });
      }
      return circle + '<text x="' + (s.x + (dx || 8)) + '" y="' + (s.y + (dy || -8)) +
        '" font-size="' + fs + '" font-weight="' + fw + '" fill="' + col + '">' + GE.svgEsc(label) + '</text>';
    }

    function segmentSvg(a, b, text, color, offsetPx, sopts) {
      sopts = sopts || {};
      if (!GLL || !_layout) return "";
      return GLL.segmentMeasureSvg(_layout, toScreen, a, b, text, {
        color: color || "#0f766e",
        style: sopts.style || "dimension",
        showGuide: sopts.showGuide !== false,
        rotateWithLine: sopts.rotateWithLine || false,
        fontSize: 14, fontWeight: 900,
        offsetPx: offsetPx || 20,
        extraNormal: sopts.extraNormal,
        extraAlong: sopts.extraAlong,
        segmentRole: sopts.segmentRole || "derived",
        crowded: sopts.crowded !== false,
        collinearGroup: sopts.collinearGroup !== false,
        reusedInFormula: sopts.reusedInFormula !== false,
        named: sopts.named || false,
        segmentName: sopts.segmentName
      });
    }

    function angleArcSvg(c, a, b, aopts) {
      aopts = aopts || {};
      var cs = toScreen(c), as = toScreen(a), bs = toScreen(b);
      var r = aopts.radius || 24, color = aopts.color || "#b45309", label = aopts.label || "";
      var arc = GE.svgAngleArcPath(cs, as, bs, r);
      var out = '<path d="' + arc.path + '" fill="none" stroke="' + color + '" stroke-width="2" />';
      if (label && GLL && _layout) {
        out += GLL.polarLabelSvg(_layout, cs, label, {
          radius: aopts.labelRadius || (r + 18),
          angle: aopts.labelAngle || arc.midAngle,
          color: color, fontSize: aopts.fontSize || 14, fontWeight: 900,
          candidates: aopts.candidates,
          lockLabel: aopts.lockLabel
        });
      }
      return out;
    }

    function rightAngleSvg(vertex, rayA, rayB, ropts) {
      ropts = ropts || {};
      if (!GLL || !_layout) return "";
      return GLL.rightAngleSvg(_layout, toScreen, vertex, rayA, rayB, { size: ropts.size || 12, color: ropts.color || "#0f766e" });
    }

    function gridSvg(gopts) {
      gopts = gopts || {};
      var axesColor = gopts.axesColor || "#93a0ad";
      var axesWidth = gopts.axesWidth || 2;
      var axesLabelColor = gopts.axesLabelColor || "#334155";
      var axesLabelFontSize = gopts.axesLabelFontSize || 18;
      var axesArrow = gopts.axesArrow === true;
      var lines = [];
      var defs = "";
      if (axesArrow) {
        var arrowId = "axisArrow" + Math.floor(Math.random() * 1e9).toString(36);
        defs = '<defs><marker id="' + arrowId + '" viewBox="0 0 10 10" refX="9" refY="5" markerUnits="strokeWidth" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 Z" fill="' + axesColor + '" /></marker></defs>';
      }
      for (var x = Math.ceil(domain.minX); x <= domain.maxX; x++) {
        var p1 = toScreen({ x: x, y: domain.minY }), p2 = toScreen({ x: x, y: domain.maxY });
        lines.push('<line x1="' + p1.x + '" y1="' + p1.y + '" x2="' + p2.x + '" y2="' + p2.y + '" stroke="rgba(15,23,42,.06)" stroke-width="1" />');
      }
      for (var y = Math.ceil(domain.minY); y <= domain.maxY; y++) {
        var q1 = toScreen({ x: domain.minX, y: y }), q2 = toScreen({ x: domain.maxX, y: y });
        lines.push('<line x1="' + q1.x + '" y1="' + q1.y + '" x2="' + q2.x + '" y2="' + q2.y + '" stroke="rgba(15,23,42,.06)" stroke-width="1" />');
      }
      var ax1 = toScreen({ x: domain.minX, y: 0 }), ax2 = toScreen({ x: domain.maxX, y: 0 });
      var ay1 = toScreen({ x: 0, y: domain.minY }), ay2 = toScreen({ x: 0, y: domain.maxY });
      var arrowAttr = axesArrow ? ' marker-end="url(#' + arrowId + ')"' : '';
      lines.push('<line x1="' + ax1.x + '" y1="' + ax1.y + '" x2="' + ax2.x + '" y2="' + ax2.y + '" stroke="' + axesColor + '" stroke-width="' + axesWidth + '"' + arrowAttr + ' />');
      lines.push('<line x1="' + ay1.x + '" y1="' + ay1.y + '" x2="' + ay2.x + '" y2="' + ay2.y + '" stroke="' + axesColor + '" stroke-width="' + axesWidth + '"' + arrowAttr + ' />');
      lines.push(textAtSvg({ x: domain.maxX - 0.25, y: 0 }, "x", axesLabelColor, 0, -10, axesLabelFontSize));
      lines.push(textAtSvg({ x: 0, y: domain.maxY - 0.18 }, "y", axesLabelColor, 10, 0, axesLabelFontSize));
      if (gopts.showOriginLabel !== false) {
        lines.push(textAtSvg(
          { x: 0, y: 0 },
          gopts.originLabel || "O",
          gopts.originColor || axesLabelColor,
          gopts.originDx != null ? gopts.originDx : -26,
          gopts.originDy != null ? gopts.originDy : 24,
          gopts.originFontSize || 18
        ));
      }
      return defs + lines.join("");
    }

    /** 添加多边形段落到 label layout 的障碍物列表 */
    function addObstacles(state) {
      if (!GLL || !_layout) return;
      var pts = state.points;
      var segs = [];
      // base polygon edges
      var base = state.base || [];
      for (var i = 0; i < base.length; i++) segs.push([base[i], base[(i + 1) % base.length]]);
      // moving polygon edges
      var mov = state.moving || [];
      for (var j = 0; j < mov.length; j++) segs.push([mov[j], mov[(j + 1) % mov.length]]);
      // key derived segments (if they exist)
      [["P", "G"], ["P", "H"], ["C", "G"]].forEach(function (pair) {
        var a = pts[pair[0]], b = pts[pair[1]];
        if (a && b) segs.push([a, b]);
      });
      segs.forEach(function (seg) {
        GLL.addSegmentObstacle(_layout, toScreen, seg[0], seg[1], { radius: 6, step: 18 });
      });
    }

    /** 检查派生点是否在可见区域内（使用当前 domain） */
    function inBounds(p) {
      var pad = 0.35;
      return (
        p &&
        !isNaN(p.x) &&
        !isNaN(p.y) &&
        p.x > domain.minX - pad &&
        p.x < domain.maxX + pad &&
        p.y > domain.minY - pad &&
        p.y < domain.maxY + pad
      );
    }

    // ── 单个装饰元素渲染 ────────────────────────────────────────────────

    function renderElem(elem, pts, state) {
      if (!elem || !elem.type) return "";
      if (elem.minT != null && state.t < elem.minT) return "";
      if (elem.maxT != null && state.t > elem.maxT) return "";
      if (elem.when != null && Math.abs(state.t - elem.when) >= (elem.eps || 0.04)) return "";
      var a, b, v;
      switch (elem.type) {
        case "grid":
          return gridSvg(elem);
        case "basePoly": {
          if (!state.base.length) return "";
          // 支持 elem.style === "outline" 时去掉填充（只保留描边）；用于"重点是折痕、不是面积"的题
          var bpFill = elem.style === "outline" ? "none" : "var(--paper)";
          return '<path d="' + pathD(state.base) + '" fill="' + bpFill + '" stroke="var(--paper-stroke)" stroke-width="3" />';
        }
        case "movingPoly":
          return state.moving.length
            ? '<path d="' + pathD(state.moving) + '" fill="var(--fold)" stroke="var(--fold-stroke)" stroke-width="3" />'
            : "";
        case "overlap":
          return state.overlap.length
            ? '<path d="' + pathD(state.overlap) + '" fill="var(--overlap)" stroke="var(--overlap-stroke)" stroke-width="3" />'
            : "";
        case "point": {
          var at = pts[elem.at];
          if (!at) return "";
          var lbl = elem.showLabel === false || (_coordinateLabelPoints && _coordinateLabelPoints[elem.at])
            ? null
            : (elem.labelText != null ? elem.labelText : (elem.label != null ? elem.label : elem.at));
          if (lbl && _pointLabelKeys) {
            var pointKey = elem.at + "\u0000" + lbl;
            if (_pointLabelKeys[pointKey]) lbl = null;
            else _pointLabelKeys[pointKey] = true;
          }
          return pointSvg(at, lbl, elem.color || "#1f2937", elem.dx || 8, elem.dy || -8,
            { r: elem.r, fontSize: elem.fontSize, altDx: elem.altDx, altDy: elem.altDy });
        }
        case "derivedPoint": {
          var dp = pts[elem.at];
          if (!inBounds(dp)) return "";
          var dLabel = (_coordinateLabelPoints && _coordinateLabelPoints[elem.at])
            ? null
            : (elem.labelText != null ? elem.labelText : (elem.label != null ? elem.label : elem.at));
          if (dLabel && _pointLabelKeys) {
            var derivedKey = elem.at + "\u0000" + dLabel;
            if (_pointLabelKeys[derivedKey]) dLabel = null;
            else _pointLabelKeys[derivedKey] = true;
          }
          return pointSvg(dp, dLabel, elem.color || "#dc2626", elem.dx || 8, elem.dy || -8, { r: elem.r || 4.6 });
        }
        case "segment": {
          a = pts[elem.from]; b = pts[elem.to];
          if (!a || !b) return "";
          return segmentSvg(a, b, elem.label || "", elem.color || "#0f766e", elem.offsetPx || 20, elem);
        }
        case "coloredLine": {
          a = pts[elem.from]; b = pts[elem.to];
          if (!a || !b) return "";
          return lineSvg(a, b, elem.color || "#dc2626", elem.width || 2, "");
        }
        case "dashedLine":
        case "dottedLine": {
          a = pts[elem.from]; b = pts[elem.to];
          if (!a || !b) return "";
          return lineSvg(a, b, elem.color || "#0f766e", elem.width || 2, elem.dash || "6 5");
        }
        case "rightAngle": {
          v = pts[elem.vertex]; a = pts[elem.rayA]; b = pts[elem.rayB];
          if (!v || !a || !b) return "";
          return rightAngleSvg(v, a, b, { size: elem.size, color: elem.color });
        }
        case "circle": {
          var circleCenter = pts[elem.center];
          if (!circleCenter) return "";
          var envCircle = state.env || {};
          var circleRadius = GE.evalExpr(elem.radiusExpr || elem.radius || "0", envCircle);
          if (!Number.isFinite(circleRadius) || circleRadius <= 0) return "";
          var circleScreen = toScreen(circleCenter);
          var circleR = screenRadiusFromMath(circleCenter, circleRadius);
          return '<circle cx="' + circleScreen.x + '" cy="' + circleScreen.y + '" r="' + circleR +
            '" fill="' + (elem.fill || "none") + '" stroke="' + (elem.color || "#94a3b8") +
            '" stroke-width="' + (elem.width || 2) + '"' + (elem.dash ? ' stroke-dasharray="' + elem.dash + '"' : "") + ' />';
        }
        case "circleArc": {
          var center = pts[elem.center];
          if (!center) return "";
          var envArc = state.env || {};
          var radius = GE.evalExpr(elem.radiusExpr || elem.radius || "0", envArc);
          var startAngle = GE.evalExpr(elem.startAngleExpr || "0", envArc);
          var endAngle = GE.evalExpr(elem.endAngleExpr || "2*pi", envArc);
          var arcSamples = Math.max(8, Math.floor(elem.samples || 64));
          if (!Number.isFinite(radius) || radius <= 0) return "";
          var arcPts = [];
          for (var ai = 0; ai <= arcSamples; ai++) {
            var theta = startAngle + (endAngle - startAngle) * (ai / arcSamples);
            arcPts.push({ x: center.x + radius * Math.cos(theta), y: center.y + radius * Math.sin(theta) });
          }
          var dArcPath = GE.svgOpenPathFromMathPoints(arcPts, toScreen);
          return '<path d="' + dArcPath + '" fill="none" stroke="' + (elem.color || "#94a3b8") +
            '" stroke-width="' + (elem.width || 2) + '"' + (elem.dash ? ' stroke-dasharray="' + elem.dash + '"' : "") + ' />';
        }
        case "angleArc": {
          v = pts[elem.vertex]; a = pts[elem.rayA]; b = pts[elem.rayB];
          if (!v || !a || !b) return "";
          return angleArcSvg(v, a, b, elem);
        }
        case "coordinateLabel": {
          var cp = pts[elem.at];
          if (!cp) return "";
          return textAtSvg(cp, elem.text != null ? elem.text : (elem.label || ""), elem.color || "#334155", elem.dx || 8, elem.dy || -10, elem.fontSize || 14);
        }
        case "areaLabel": {
          var region = (elem.region === "moving") ? state.moving : state.overlap;
          if (!region || !region.length) return "";
          var cen = GE.centroid(region);
          return textAtSvg(cen, elem.text || "S", elem.color || "#dc2626", elem.dx || -5, elem.dy || 5, elem.size || 16);
        }
        case "cutRegion": {
          var verts = (elem.vertices || []).map(function (n) { return pts[n]; }).filter(Boolean);
          if (verts.length < 3) return "";
          var fill = elem.style === "subtracted" ? "rgba(245,158,11,.28)" : "none";
          var out2 = '<path d="' + pathD(verts) + '" fill="' + fill + '" stroke="#b45309" stroke-width="2.2" stroke-dasharray="6 5" />';
          if (elem.centroidLabel) {
            var cen2 = GE.centroid(verts);
            var cs = toScreen(cen2);
            out2 += '<text x="' + cs.x + '" y="' + cs.y + '" dx="-5" dy="5" font-size="16" font-weight="900" fill="#b45309">' + GE.svgEsc(elem.centroidLabel) + '</text>';
          }
          return out2;
        }
        case "outlineRegion": {
          var verts2 = (elem.vertices || []).map(function (n) { return pts[n]; }).filter(Boolean);
          if (verts2.length < 3) return "";
          var isHorseTriangle = elem.style === "horseTriangle";
          var fill2 = elem.fill || (isHorseTriangle ? "rgba(37,99,235,.12)" : "none");
          var stroke2 = elem.color || (isHorseTriangle ? "#2563eb" : "#b45309");
          var width2 = elem.width || (isHorseTriangle ? 2.2 : 2.2);
          var dash2 = elem.dash == null ? (isHorseTriangle ? "" : "6 5") : elem.dash;
          return '<path d="' + pathD(verts2) + '" fill="' + fill2 + '" stroke="' + stroke2 + '" stroke-width="' + width2 + '"' + (dash2 ? ' stroke-dasharray="' + dash2 + '"' : "") + ' />';
        }
        case "areaFormulaCard": {
          var pos = elem.pos;
          if (!pos) return "";
          var sp = toScreen({ x: pos[0], y: pos[1] });
          return GE.svgAreaFormulaCard(sp.x, sp.y, elem.terms || []);
        }
        case "coincidentLabel": {
          var eps = elem.eps || 0.04;
          if (Math.abs(state.t - (elem.when || 0)) >= eps) return "";
          var anchor = pts[elem.anchor];
          if (!anchor) return "";
          return textAtSvg(anchor, elem.text || "", elem.color || "#dc2626", elem.dx || 10, elem.dy || -18, elem.size || 14);
        }
        case "parabola": {
          var cid = elem.curveId || elem.curve;
          var cv = state.curves && cid ? state.curves[cid] : null;
          if (!cv || cv.type !== "parabola") return "";
          var samples = elem.samples || 96;
          var band = elem.yBand != null ? elem.yBand : 14;
          var curvePts = GE.sampleParabola(cv.a, cv.b, cv.c, domain.minX, domain.maxX, samples);
          curvePts = curvePts.filter(function (pt) {
            return Number.isFinite(pt.x) && Number.isFinite(pt.y) && pt.y >= domain.minY - band && pt.y <= domain.maxY + band;
          });
          if (curvePts.length < 2) return "";
          var dPar = GE.svgOpenPathFromMathPoints(curvePts, toScreen);
          return (
            '<path d="' +
            dPar +
            '" fill="none" stroke="' +
            (elem.color || "#2563eb") +
            '" stroke-width="' +
            (elem.width != null ? elem.width : 2.8) +
            '" />'
          );
        }
        case "axisOfSymmetry": {
          var cidAx = elem.curveId || elem.curve;
          var cvAx = state.curves && cidAx ? state.curves[cidAx] : null;
          if (!cvAx || cvAx.type !== "parabola" || Math.abs(cvAx.a) < 1e-12) return "";
          var xSym = -cvAx.b / (2 * cvAx.a);
          var pLo = { x: xSym, y: domain.minY };
          var pHi = { x: xSym, y: domain.maxY };
          return lineSvg(pLo, pHi, elem.color || "#64748b", elem.width != null ? elem.width : 1.6, elem.dash || "10 7");
        }
        case "vertex": {
          var cidV = elem.curveId || elem.curve;
          var cvV = state.curves && cidV ? state.curves[cidV] : null;
          if (!cvV || cvV.type !== "parabola" || Math.abs(cvV.a) < 1e-12) return "";
          var xv = -cvV.b / (2 * cvV.a);
          var yv = cvV.a * xv * xv + cvV.b * xv + cvV.c;
          var vPt = { x: xv, y: yv };
          var vLbl = elem.showLabel === false ? null : (elem.labelText != null ? elem.labelText : elem.label || "顶点");
          return pointSvg(vPt, vLbl, elem.color || "#7c3aed", elem.dx || 10, elem.dy || -12, {
            r: elem.r || 5.5,
            fontSize: elem.fontSize
          });
        }
        case "curvePoint": {
          var cidCp = elem.curveId || elem.curve;
          var cvCp = state.curves && cidCp ? state.curves[cidCp] : null;
          if (!cvCp || cvCp.type !== "parabola") return "";
          var envCurve = state.env || {};
          var x0 = GE.evalExpr(String(elem.xExpr != null ? elem.xExpr : "0"), envCurve);
          var y0 = cvCp.a * x0 * x0 + cvCp.b * x0 + cvCp.c;
          var cPt = { x: x0, y: y0 };
          var cLbl = elem.showLabel === false ? null : (elem.labelText != null ? elem.labelText : elem.label || "");
          return pointSvg(cPt, cLbl || null, elem.color || "#0f766e", elem.dx || 8, elem.dy || 8, {
            r: elem.r || 5.2,
            fontSize: elem.fontSize
          });
        }
        default:
          return "";
      }
    }

    // ── 图层可见性判断 ────────────────────────────────────────────────────

    function isLayerActive(layerDef, stepId, section) {
      if (layerDef.section && section !== layerDef.section) return false;
      if (layerDef.sectionNot) return section !== layerDef.sectionNot;
      if (layerDef.stepStartsWith) {
        return layerDef.stepStartsWith.some(function (prefix) { return stepId.indexOf(prefix) === 0; });
      }
      return true;
    }

    function curveIdFromElem(elem) {
      if (!elem || !elem.type) return null;
      if (elem.type !== "parabola" && elem.type !== "axisOfSymmetry" && elem.type !== "vertex" && elem.type !== "curvePoint") return null;
      return elem.curveId || elem.curve || null;
    }

    function curveIdsForStep(step) {
      if (!step) return [];
      var ids = [];
      function addId(id) {
        if (id && ids.indexOf(id) < 0) ids.push(id);
      }
      Object.keys(layers).forEach(function (layerName) {
        var layerDef = layers[layerName];
        var active = (layerName === "global") ? true : isLayerActive(layerDef, step.id, step.section);
        if (!active) return;
        (layerDef.elements || []).forEach(function (elem) { addId(curveIdFromElem(elem)); });
      });
      var deco = stepDecos[step.id] || {};
      (deco.add || []).forEach(function (elem) { addId(curveIdFromElem(elem)); });
      return ids;
    }

    function renderLayers(stepId, section, pts, state) {
      var out = "";
      Object.keys(layers).forEach(function (layerName) {
        var layerDef = layers[layerName];
        var active = (layerName === "global") ? true : isLayerActive(layerDef, stepId, section);
        if (!active) return;
        var elems = Array.isArray(layerDef.elements) ? layerDef.elements : [];
        elems.forEach(function (elem) {
          if (typeof elem === "string" && elem === "grid") { out += gridSvg(); return; }
          out += renderElem(elem, pts, state);
        });
      });
      return out;
    }

    function coordinateLabelPointsForStep(stepId, section) {
      var points = {};
      function collect(elem) {
        if (elem && elem.type === "coordinateLabel" && elem.at) points[elem.at] = true;
      }
      Object.keys(layers).forEach(function (layerName) {
        var layerDef = layers[layerName];
        var active = (layerName === "global") ? true : isLayerActive(layerDef, stepId, section);
        if (!active) return;
        (layerDef.elements || []).forEach(collect);
      });
      var deco = stepDecos[stepId] || {};
      (deco.add || []).forEach(collect);
      return points;
    }

    // ── 完整步骤 SVG ─────────────────────────────────────────────────────

    function applyPointOverrides(state, overrides, localVars) {
      if (!overrides) return state;
      var env = Object.assign({}, state.env || {}, localVars || {});
      var nextPoints = Object.assign({}, state.points || {});
      Object.keys(overrides).forEach(function (name) {
        var pair = overrides[name];
        if (!Array.isArray(pair) || pair.length < 2) return;
        var x = GE.evalExpr(String(pair[0]), env);
        var y = GE.evalExpr(String(pair[1]), env);
        if (Number.isFinite(x) && Number.isFinite(y)) nextPoints[name] = { x: x, y: y };
      });
      var nextState = Object.assign({}, state);
      nextState.points = nextPoints;
      nextState.env = env;
      return nextState;
    }

    function diagramMarkupFor(index, overrideT, localVars) {
      var step = STEPS[index];
      var policy = POLICIES[step.id];
      var rng = policy.range || [0, 10];
      var localT = Math.max(rng[0], Math.min(rng[1], overrideT != null ? overrideT : step.t));
      var deco = stepDecos[step.id] || {};
      setRenderDomain(deco.domain);
      var state = applyPointOverrides(resolveClipOverlap(spec, localT), deco.pointOverrides, localVars);
      var pts = state.points;

      if (GLL) {
        _layout = GLL.createLabelLayout({ toScreen: toScreen, padding: 4, pointRadius: 8 });
        addObstacles(state);
      }
      _coordinateLabelPoints = coordinateLabelPointsForStep(step.id, step.section);
      _pointLabelKeys = {};

      var out = renderLayers(step.id, step.section, pts, state);

      (deco.add || []).forEach(function (elem) { out += renderElem(elem, pts, state); });

      var liveBox = policy.movable
        ? (step.box || []).concat(["示例 t=" + Number(localT).toFixed(3).replace(/\.?0+$/, "")])
        : (step.box || []);
      if (liveBox.length) out += GE.svgConclusionBox(liveBox, deco.conclusionBox);

      _layout = null;
      _coordinateLabelPoints = null;
      _pointLabelKeys = null;
      setRenderDomain(defaultDomain);
      return out;
    }

    // ── 缩略图 SVG ───────────────────────────────────────────────────────

    function drawMini(t, miniItem, step) {
      var s = resolveClipOverlap(spec, t);
      var curveKeys = Object.keys(s.curves || {});
      if (!curveKeys.length) {
        return GE.svgMini(s.base, s.moving, s.overlap, domain);
      }
      var preferred = [];
      if (miniItem && (miniItem.curveId || miniItem.curve)) preferred.push(miniItem.curveId || miniItem.curve);
      preferred = preferred.concat(curveIdsForStep(step));
      var cid = preferred.find(function (id) { return curveKeys.indexOf(id) >= 0; }) || curveKeys[0];
      var cv = s.curves[cid];
      if (!cv || cv.type !== "parabola") {
        return GE.svgMini(s.base, s.moving, s.overlap, domain);
      }
      var w = 220,
        h = 150;
      var padM = { left: 20, right: 12, top: 12, bottom: 22 };
      var innerW = w - padM.left - padM.right;
      var innerH = h - padM.top - padM.bottom;
      var scale = Math.min(
        innerW / (domain.maxX - domain.minX),
        innerH / (domain.maxY - domain.minY)
      );
      var ox = padM.left + (innerW - (domain.maxX - domain.minX) * scale) / 2;
      var oy = padM.top + (innerH - (domain.maxY - domain.minY) * scale) / 2;
      function tsMini(p) {
        return { x: ox + (p.x - domain.minX) * scale, y: h - oy - (p.y - domain.minY) * scale };
      }
      var miniPts = GE.sampleParabola(cv.a, cv.b, cv.c, domain.minX, domain.maxX, 52);
      miniPts = miniPts.filter(function (pt) {
        return Number.isFinite(pt.x) && Number.isFinite(pt.y) && pt.y >= domain.minY - 18 && pt.y <= domain.maxY + 18;
      });
      var dMini = GE.svgOpenPathFromMathPoints(miniPts, tsMini);
      var svgM = '<svg viewBox="0 0 ' + w + " " + h + '" aria-hidden="true">';
      var ax1m = tsMini({ x: domain.minX, y: 0 }),
        ax2m = tsMini({ x: domain.maxX, y: 0 });
      var ay1m = tsMini({ x: 0, y: domain.minY }),
        ay2m = tsMini({ x: 0, y: domain.maxY });
      svgM +=
        '<line x1="' +
        ax1m.x +
        '" y1="' +
        ax1m.y +
        '" x2="' +
        ax2m.x +
        '" y2="' +
        ax2m.y +
        '" stroke="#94a3b8" stroke-width="1.2" />';
      svgM +=
        '<line x1="' +
        ay1m.x +
        '" y1="' +
        ay1m.y +
        '" x2="' +
        ay2m.x +
        '" y2="' +
        ay2m.y +
        '" stroke="#94a3b8" stroke-width="1.2" />';
      svgM += '<path d="' + dMini + '" fill="none" stroke="#2563eb" stroke-width="2.2" />';
      svgM += "</svg>";
      return svgM;
    }

    // ── 原题图形渲染 ─────────────────────────────────────────────────────

    function renderOriginalFigureSvg(t, figConfig) {
      figConfig = figConfig || {};
      var FIG_PAD = { left: 92, right: 78, top: 48, bottom: 66 };
      var FIG_W = W, FIG_H = H;
      // 使用同一 toScreen（原题图和步骤图共用同一画布尺寸）
      var state = resolveClipOverlap(spec, t);
      var pts = state.points;

      if (GLL) {
        _layout = GLL.createLabelLayout({ toScreen: toScreen, padding: 4, pointRadius: 8 });
      }

      var showGrid = figConfig.showGrid !== false && figConfig.grid !== false;
      var out = showGrid ? gridSvg(figConfig.grid) : "";
      var curveAllow = Array.isArray(figConfig.curveIds) ? figConfig.curveIds : null;
      (spec.curves || []).forEach(function (cr) {
        if (!cr || cr.type !== "parabola" || !cr.id) return;
        if (curveAllow && curveAllow.indexOf(cr.id) < 0) return;
        var cvFig = state.curves && state.curves[cr.id];
        if (!cvFig) return;
        var samp = GE.sampleParabola(cvFig.a, cvFig.b, cvFig.c, domain.minX, domain.maxX, 72);
        samp = samp.filter(function (pt) {
          return Number.isFinite(pt.x) && Number.isFinite(pt.y) && pt.y >= domain.minY - 14 && pt.y <= domain.maxY + 14;
        });
        if (samp.length < 2) return;
        var dFig = GE.svgOpenPathFromMathPoints(samp, toScreen);
        out +=
          '<path d="' +
          dFig +
          '" fill="none" stroke="' +
          (figConfig.parabolaStroke || "#2563eb") +
          '" stroke-width="' +
          (figConfig.parabolaStrokeWidth != null ? figConfig.parabolaStrokeWidth : 3) +
          '" />';
      });
      function renderLabelList(list, defaults) {
        var labels = Array.isArray(list) ? list : defaults;
        labels.forEach(function (item) {
          var key = item.at || item.k;
          var p = pts[key];
          if (!p || !Number.isFinite(p.x) || !Number.isFinite(p.y)) return;
          out += pointSvg(p, item.label || key, item.color || "#1f2937", item.dx, item.dy, {
            r: item.r || 6.6,
            fontSize: item.fontSize || 20
          });
        });
      }

      // base poly（支持 figConfig.basePolyDash 自定义虚线样式，例如 "10 6"；未指定时为实线）
      if (state.base.length) {
        var basePolyDash = figConfig.basePolyDash ? ' stroke-dasharray="' + figConfig.basePolyDash + '"' : '';
        var basePolyFill = figConfig.basePolyFill === false ? 'none' : 'var(--paper)';
        out += '<path d="' + pathD(state.base) + '" fill="' + basePolyFill + '" stroke="var(--paper-stroke)" stroke-width="3"' + basePolyDash + ' />';
      }
      (figConfig.segments || []).forEach(function (seg) {
        var a = pts[seg.from], b = pts[seg.to];
        if (!a || !b) return;
        out += lineSvg(a, b, seg.color || "#0f766e", seg.width || 2.4, seg.dash || "");
      });
      // fixed points with larger size
      renderLabelList(figConfig.fixedLabels, [
        { at: "A", dx: -28, dy: -10 }, { at: "B", dx: -28, dy: 22 },
        { at: "C", dx: 10, dy: 4 }, { at: "D", dx: 8, dy: 22 }
      ]);
      if (figConfig.showMoving !== false && state.moving.length) {
        out += '<path d="' + pathD(state.moving) + '" fill="var(--fold)" stroke="var(--fold-stroke)" stroke-width="3" />';
        if (figConfig.showOverlap && state.overlap.length) {
          out += '<path d="' + pathD(state.overlap) + '" fill="var(--overlap)" stroke="var(--overlap-stroke)" stroke-width="3" />';
        }
        renderLabelList(figConfig.movingLabels, [
          { at: "P", dx: 8, dy: 26, color: "#0f766e", r: 7 },
          { at: "M", dx: -40, dy: -12, color: "#0f766e" },
          { at: "N", dx: 12, dy: -12, color: "#0f766e" }
        ]);
      } else if (Array.isArray(figConfig.movingLabels)) {
        renderLabelList(figConfig.movingLabels, []);
      }
      if (figConfig.showIntersections) {
        renderLabelList(figConfig.intersectionLabels, [
          { at: "E", dx: 10, dy: -12, color: "#dc2626", r: 6, fontSize: 19 },
          { at: "F", dx: 10, dy: 20, color: "#dc2626", r: 6, fontSize: 19 },
          { at: "H", dx: -24, dy: 18, color: "#dc2626", r: 6, fontSize: 19 },
          { at: "G", dx: 10, dy: 20, color: "#dc2626", r: 6, fontSize: 19 }
        ]);
      }
      (figConfig.rightAngles || []).forEach(function (ra) {
        var v = pts[ra.vertex], a = pts[ra.rayA], b = pts[ra.rayB];
        if (!v || !a || !b) return;
        out += rightAngleSvg(v, a, b, {
          size: ra.size || 12,
          color: ra.color || "#1f2937"
        });
      });

      _layout = null;
      return out;
    }

    function renderOriginalFigures() {
      var figs = spec.originalFigures || [];
      figs.forEach(function (fig) {
        var el = document.getElementById(fig.id);
        if (!el) return;
        el.innerHTML = renderOriginalFigureSvg(fig.t, fig);
      });
    }

    return { diagramMarkupFor: diagramMarkupFor, drawMini: drawMini, renderOriginalFigures: renderOriginalFigures };
  }

  global.GeometryLessonFromSpec = {
    resolveClipOverlap: resolveClipOverlap,
    asNankaiStateShape: asNankaiStateShape,
    createSpecRenderer: createSpecRenderer
  };
})(window);
