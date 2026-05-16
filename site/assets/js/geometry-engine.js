/**
 * 初中几何题公共数学与坐标工具（数学说）
 * 无 DOM 依赖，可在校验脚本中复用。
 * 暴露：window.GeometryEngine
 */
(function (global) {
  "use strict";

  var SQRT3 = Math.sqrt(3);

  function clamp(v, min, max) {
    return Math.max(min, Math.min(max, v));
  }

  function polygonArea(poly) {
    if (!poly || poly.length < 3) return 0;
    var area = 0;
    for (var i = 0; i < poly.length; i += 1) {
      var p = poly[i];
      var q = poly[(i + 1) % poly.length];
      area += p.x * q.y - q.x * p.y;
    }
    return Math.abs(area) / 2;
  }

  function centroid(poly) {
    if (!poly || !poly.length) return { x: 0, y: 0 };
    var sx = 0;
    var sy = 0;
    for (var i = 0; i < poly.length; i += 1) {
      sx += poly[i].x;
      sy += poly[i].y;
    }
    return { x: sx / poly.length, y: sy / poly.length };
  }

  /** 线段 a-b 与 c-d 的交点（含延长线）；若无则 null */
  function lineLineIntersection(a, b, c, d) {
    var x1 = a.x;
    var y1 = a.y;
    var x2 = b.x;
    var y2 = b.y;
    var x3 = c.x;
    var y3 = c.y;
    var x4 = d.x;
    var y4 = d.y;
    var den = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4);
    if (Math.abs(den) < 1e-12) return null;
    var px =
      ((x1 * y2 - y1 * x2) * (x3 - x4) - (x1 - x2) * (x3 * y4 - y3 * x4)) / den;
    var py =
      ((x1 * y2 - y1 * x2) * (y3 - y4) - (y1 - y2) * (x3 * y4 - y3 * x4)) / den;
    return { x: px, y: py };
  }

  function onSegment(p, a, b, eps) {
    var e = eps || 1e-9;
    var minx = Math.min(a.x, b.x) - e;
    var maxx = Math.max(a.x, b.x) + e;
    var miny = Math.min(a.y, b.y) - e;
    var maxy = Math.max(a.y, b.y) + e;
    return p.x >= minx && p.x <= maxx && p.y >= miny && p.y <= maxy;
  }

  /** 线段 ab 与 cd 的交点（限制在线段上） */
  function segmentIntersection(a, b, c, d) {
    var hit = lineLineIntersection(a, b, c, d);
    if (!hit) return null;
    if (onSegment(hit, a, b, 1e-8) && onSegment(hit, c, d, 1e-8)) return hit;
    return null;
  }

  function insidePoly(p, poly) {
    var wn = 0;
    for (var i = 0; i < poly.length; i += 1) {
      var a = poly[i];
      var b = poly[(i + 1) % poly.length];
      if (a.y <= p.y) {
        if (b.y > p.y && cross(a, b, p) > 0) wn += 1;
      } else {
        if (b.y <= p.y && cross(a, b, p) < 0) wn -= 1;
      }
    }
    return wn !== 0;
  }

  function cross(o, a, b) {
    return (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x);
  }

  function clipPolygon(subject, clipper) {
    if (!subject.length) return [];
    var output = subject.slice();
    for (var i = 0; i < clipper.length; i += 1) {
      var a = clipper[i];
      var b = clipper[(i + 1) % clipper.length];
      var input = output.slice();
      output = [];
      var inside = function (p) {
        return (b.x - a.x) * (p.y - a.y) - (b.y - a.y) * (p.x - a.x) >= -1e-9;
      };
      var intersect = function (p, q) {
        var dx = q.x - p.x;
        var dy = q.y - p.y;
        var ex = b.x - a.x;
        var ey = b.y - a.y;
        var u = ((a.x - p.x) * ey - (a.y - p.y) * ex) / (dx * ey - dy * ex);
        return { x: p.x + u * dx, y: p.y + u * dy };
      };
      input.forEach(function (p, index) {
        var q = input[(index + 1) % input.length];
        var ip = inside(p);
        var iq = inside(q);
        if (ip && iq) output.push(q);
        else if (ip && !iq) output.push(intersect(p, q));
        else if (!ip && iq) {
          output.push(intersect(p, q));
          output.push(q);
        }
      });
    }
    return output;
  }

  /**
   * 极简表达式：数字、括号、+ - * /、一元负号、变量 t、常量 S3（√3）
   */
  function evalExpr(expr, env) {
    if (expr == null || expr === "") return 0;
    var s = String(expr).trim().replace(/\s+/g, "");
    var i = 0;
    var T = env.t;
    var S3 = env.S3 != null ? env.S3 : SQRT3;

    function peek() {
      return s[i] || "";
    }
    function eat(ch) {
      if (peek() === ch) {
        i += 1;
        return true;
      }
      return false;
    }
    function parseNumber() {
      var start = i;
      while (/[0-9.]/.test(peek())) i += 1;
      if (start === i) throw new Error("expected number at " + i);
      return parseFloat(s.slice(start, i));
    }
    function parseIdent() {
      var start = i;
      while (/[a-zA-Z0-9_]/.test(peek())) i += 1;
      return s.slice(start, i);
    }
    function primary() {
      if (eat("(")) {
        var v = addSub();
        eat(")");
        return v;
      }
      if (eat("-")) return -primary();
      if (eat("+")) return primary();
      if (/[0-9]/.test(peek())) return parseNumber();
      var id = parseIdent();
      if (eat("(")) {
        var arg = addSub();
        eat(")");
        if (id === "sin") return Math.sin(arg);
        if (id === "cos") return Math.cos(arg);
        if (id === "tan") return Math.tan(arg);
        if (id === "sqrt") return Math.sqrt(arg);
        if (id === "abs") return Math.abs(arg);
        throw new Error("unknown function: " + id);
      }
      if (id === "t") return T;
      if (id === "S3" || id === "sqrt3") return S3;
      if (id === "pi") return Math.PI;
      if (Object.prototype.hasOwnProperty.call(env, id)) {
        var vv = env[id];
        if (typeof vv === "number") return vv;
      }
      throw new Error("unknown ident: " + id);
    }
    function mulDiv() {
      var v = primary();
      for (;;) {
        if (eat("*")) v *= primary();
        else if (eat("/")) v /= primary();
        else break;
      }
      return v;
    }
    function addSub() {
      var v = mulDiv();
      for (;;) {
        if (eat("+")) v += mulDiv();
        else if (eat("-")) v -= mulDiv();
        else break;
      }
      return v;
    }
    var result = addSub();
    if (i !== s.length) throw new Error("trailing: " + s.slice(i));
    return result;
  }

  function evalPoint(pair, env) {
    return { x: evalExpr(pair[0], env), y: evalExpr(pair[1], env) };
  }

  function createToScreen(domain, pad, w, h) {
    return function toScreen(p) {
      var innerW = w - pad.left - pad.right;
      var innerH = h - pad.top - pad.bottom;
      var scale = Math.min(
        innerW / (domain.maxX - domain.minX),
        innerH / (domain.maxY - domain.minY)
      );
      var ox = pad.left + (innerW - (domain.maxX - domain.minX) * scale) / 2;
      var oy = pad.top + (innerH - (domain.maxY - domain.minY) * scale) / 2;
      return {
        x: ox + (p.x - domain.minX) * scale,
        y: h - oy - (p.y - domain.minY) * scale
      };
    };
  }

  function createFmtFromLandmarks(landmarks, epsilon, precision) {
    var eps = epsilon ?? 0.004;
    var prec = precision ?? 3;
    if (!landmarks || !landmarks.length) {
      return function (v) {
        return Number(v)
          .toFixed(prec)
          .replace(/\.?0+$/, "")
          .replace(/\.$/, "");
      };
    }
    return function (v) {
      var n = Number(v);
      for (var i = 0; i < landmarks.length; i += 1) {
        var item = landmarks[i];
        if (Math.abs(n - Number(item.value)) < eps) return String(item.display);
      }
      return Number(n)
        .toFixed(prec)
        .replace(/\.?0+$/, "")
        .replace(/\.$/, "");
    };
  }

  /**
   * 验证：点 p 到线段 ab 的距离是否 <= tol（用于交点落在线段上）
   */
  function pointNearSegment(p, a, b, tol) {
    var t = tol || 1e-6;
    var hit = lineLineIntersection(a, b, p, {
      x: p.x + (b.y - a.y),
      y: p.y - (b.x - a.x)
    });
    if (!hit) return false;
    return onSegment(hit, a, b, t);
  }

  // ── SVG 辅助函数（无 DOM 依赖，仅返回字符串）──────────────────────────

  function svgEsc(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  /** 结论框（右上角白色圆角矩形 + 文字行） */
  function svgConclusionBox(lines, opts) {
    var o = opts || {};
    var x = o.x != null ? o.x : 720;
    var y = o.y != null ? o.y : 54;
    var w = o.w != null ? o.w : 318;
    var lineH = o.lineH != null ? o.lineH : 24;
    var h = 16 + lines.length * lineH;
    var out =
      '<rect x="' + x + '" y="' + y + '" width="' + w + '" height="' + h +
      '" rx="10" fill="rgba(255,255,255,.95)" stroke="#475569" stroke-width="1.4" />';
    for (var i = 0; i < lines.length; i++) {
      out +=
        '<text x="' + (x + 14) + '" y="' + (y + 23 + i * lineH) +
        '" font-size="14" font-weight="900" fill="#111827">' + svgEsc(lines[i]) + '</text>';
    }
    return out;
  }

  /**
   * 缩略图 SVG（完整 <svg> 元素字符串）
   * basePoly/movPoly/overlapPoly 为 {x,y} 数组
   */
  function svgMini(basePoly, movPoly, overlapPoly, domain, w, h, pad) {
    w = w || 220;
    h = h || 150;
    pad = pad || { left: 20, right: 12, top: 12, bottom: 22 };
    var innerW = w - pad.left - pad.right;
    var innerH = h - pad.top - pad.bottom;
    var scale = Math.min(
      innerW / (domain.maxX - domain.minX),
      innerH / (domain.maxY - domain.minY)
    );
    var ox = pad.left + (innerW - (domain.maxX - domain.minX) * scale) / 2;
    var oy = pad.top + (innerH - (domain.maxY - domain.minY) * scale) / 2;
    function ts(p) {
      return { x: ox + (p.x - domain.minX) * scale, y: h - oy - (p.y - domain.minY) * scale };
    }
    function pathD(poly) {
      if (!poly || !poly.length) return "";
      var first = ts(poly[0]);
      var d = "M " + first.x + " " + first.y;
      for (var i = 1; i < poly.length; i++) {
        var q = ts(poly[i]);
        d += " L " + q.x + " " + q.y;
      }
      return d + " Z";
    }
    var ax1 = ts({ x: domain.minX, y: 0 }), ax2 = ts({ x: domain.maxX, y: 0 });
    var ay1 = ts({ x: 0, y: domain.minY }), ay2 = ts({ x: 0, y: domain.maxY });
    var svg = '<svg viewBox="0 0 ' + w + ' ' + h + '" aria-hidden="true">';
    svg += '<line x1="' + ax1.x + '" y1="' + ax1.y + '" x2="' + ax2.x + '" y2="' + ax2.y + '" stroke="#94a3b8" stroke-width="1.2" />';
    svg += '<line x1="' + ay1.x + '" y1="' + ay1.y + '" x2="' + ay2.x + '" y2="' + ay2.y + '" stroke="#94a3b8" stroke-width="1.2" />';
    if (basePoly && basePoly.length) {
      svg += '<path d="' + pathD(basePoly) + '" fill="rgba(245,158,11,.12)" stroke="#d97706" stroke-width="2" />';
    }
    if (movPoly && movPoly.length) {
      svg += '<path d="' + pathD(movPoly) + '" fill="rgba(14,116,144,.14)" stroke="#0f766e" stroke-width="2" />';
    }
    if (overlapPoly && overlapPoly.length) {
      svg += '<path d="' + pathD(overlapPoly) + '" fill="rgba(220,38,38,.22)" stroke="#dc2626" stroke-width="2" />';
    }
    svg += '</svg>';
    return svg;
  }

  /**
   * 角弧路径辅助（不含文字标注）
   * 返回 { path: "M...A...", midAngle }
   */
  function svgAngleArcPath(cs, as, bs, r) {
    var a1 = Math.atan2(as.y - cs.y, as.x - cs.x);
    var a2 = Math.atan2(bs.y - cs.y, bs.x - cs.x);
    var d = a2 - a1;
    while (d <= -Math.PI) d += Math.PI * 2;
    while (d > Math.PI) d -= Math.PI * 2;
    var sweep = d > 0 ? 1 : 0;
    var end = a1 + d;
    var p1 = { x: cs.x + r * Math.cos(a1), y: cs.y + r * Math.sin(a1) };
    var p2 = { x: cs.x + r * Math.cos(end), y: cs.y + r * Math.sin(end) };
    return {
      path: "M " + p1.x + " " + p1.y + " A " + r + " " + r + " 0 0 " + sweep + " " + p2.x + " " + p2.y,
      midAngle: a1 + d / 2
    };
  }

  /**
   * 抛物线 y = ax² + bx + c 在 [xMin,xMax] 上均匀采样（数学坐标）
   */
  function sampleParabola(a, b, c, xMin, xMax, numPoints) {
    var n = Math.max(2, numPoints || 80);
    var pts = [];
    var dx = (xMax - xMin) / (n - 1);
    for (var i = 0; i < n; i++) {
      var x = xMin + i * dx;
      var y = a * x * x + b * x + c;
      pts.push({ x: x, y: y });
    }
    return pts;
  }

  /**
   * 将数学坐标点列转为开放折线路径 d（不含 Z），用于抛物线等曲线。
   * toScreen: {x,y} -> {x,y} 像素坐标
   */
  function svgOpenPathFromMathPoints(points, toScreen) {
    if (!points || !points.length || typeof toScreen !== "function") return "";
    var first = toScreen(points[0]);
    var d = "M " + first.x + " " + first.y;
    for (var i = 1; i < points.length; i++) {
      var q = toScreen(points[i]);
      d += " L " + q.x + " " + q.y;
    }
    return d;
  }

  /**
   * 线段 AB 与抛物线 y = ax²+bx+c 的交点（仅保留在线段上的点）
   */
  function segmentParabolaIntersections(a, b, c, p1, p2) {
    var out = [];
    var x1 = p1.x,
      y1 = p1.y,
      x2 = p2.x,
      y2 = p2.y;
    var tol = 1e-9;
    if (Math.abs(x2 - x1) < tol) {
      var xv = (x1 + x2) / 2;
      var yp = a * xv * xv + b * xv + c;
      var hitV = { x: xv, y: yp };
      if (onSegment(hitV, p1, p2, 1e-5)) out.push(hitV);
      return out;
    }
    var m = (y2 - y1) / (x2 - x1);
    var k = y1 - m * x1;
    var A = a,
      B = b - m,
      Ccoef = c - k;
    if (Math.abs(A) < tol) {
      if (Math.abs(B) < tol) return out;
      var xs = -Ccoef / B;
      var pt = { x: xs, y: m * xs + k };
      if (onSegment(pt, p1, p2, 1e-5)) out.push(pt);
      return out;
    }
    var disc = B * B - 4 * A * Ccoef;
    if (disc < -1e-12) return out;
    var sd = Math.sqrt(Math.max(0, disc));
    var xa = (-B - sd) / (2 * A),
      xb = (-B + sd) / (2 * A);
    [xa, xb].forEach(function (xv) {
      var pt = { x: xv, y: m * xv + k };
      if (onSegment(pt, p1, p2, 1e-5)) out.push(pt);
    });
    return out;
  }

  /** 面积拆分公式卡片（CSS class area-formula-* 由页面 CSS 定义） */
  function svgAreaFormulaCard(sx, sy, terms) {
    function charW(ch) { return /[\u0000-\u00ff]/.test(ch) ? 8.5 : 17; }
    function textW(s) {
      return Array.from(String(s)).reduce(function (sum, ch) { return sum + charW(ch); }, 0);
    }
    var totalW = terms.reduce(function (sum, t) { return sum + textW(t.text) + 8; }, 0) + 28;
    var width = Math.max(360, totalW);
    var height = 38;
    var cursor = sx + 14;
    var spans = terms.map(function (term) {
      var cls = term.kind ? "area-formula-" + term.kind : "area-formula-op";
      var out = '<tspan class="' + cls + '" x="' + cursor + '" dy="0">' + svgEsc(term.text) + "</tspan>";
      cursor += textW(term.text) + 8;
      return out;
    }).join("");
    return (
      '<g class="area-formula">' +
      '<rect class="area-formula-bg" x="' + sx + '" y="' + (sy - height + 8) + '" width="' + width + '" height="' + height + '" rx="9" />' +
      '<text class="area-formula-text" x="' + (sx + 14) + '" y="' + sy + '" dominant-baseline="middle">' + spans + "</text>" +
      "</g>"
    );
  }

  global.GeometryEngine = {
    SQRT3,
    clamp,
    polygonArea,
    centroid,
    lineLineIntersection,
    segmentIntersection,
    insidePoly,
    clipPolygon,
    evalExpr,
    evalPoint,
    createToScreen,
    createFmtFromLandmarks,
    pointNearSegment,
    onSegment,
    // SVG helpers
    svgEsc,
    svgConclusionBox,
    svgMini,
    svgAngleArcPath,
    svgAreaFormulaCard,
    sampleParabola,
    svgOpenPathFromMathPoints,
    segmentParabolaIntersections
  };
})(window);
