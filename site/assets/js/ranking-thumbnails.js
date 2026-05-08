(function () {
  "use strict";

  var GE = window.GeometryEngine;
  var GL = window.GeometryLessonFromSpec;
  if (!GE || !GL) return;

  var S3 = GE.SQRT3 || Math.sqrt(3);
  var W = 210;
  var H = 140;
  var PAD = { left: 18, right: 16, top: 14, bottom: 18 };

  function spec(config) {
    return config;
  }

  var DATA = {
    "tj-2026-nankai-yimo-24": spec({
      t: 3.75,
      domain: { minX: -0.9, maxX: 7.3, minY: -1.65, maxY: 6.05 },
      fixedPoints: { O: ["0", "0"], A: ["0", "3*S3"], B: ["0", "-S3"], C: ["6", "S3"], D: ["3", "0"] },
      movingParam: "t",
      movingPoints: { P: ["t", "0"], M: ["t/2", "S3*t/2"], N: ["3*t/2", "S3*t/2"] },
      basePolygon: ["A", "B", "C"],
      movingPolygon: ["M", "P", "N"],
      derivedIntersections: [
        { name: "E", a: ["A", "C"], b: ["M", "N"], fallback: ["9-3*t/2", "S3*t/2"] },
        { name: "F", a: ["A", "C"], b: ["P", "N"], fallback: ["3*(t+3)/4", "S3*(9-t)/4"] },
        { name: "H", a: ["B", "C"], b: ["P", "M"], fallback: ["3*(t+1)/4", "S3*(t-3)/4"] },
        { name: "G", a: ["B", "C"], b: ["P", "N"], fallback: ["3*(t-1)/2", "S3*(t-3)/2"] }
      ],
      labels: ["A", "B", "C", "P", "E", "F", "H", "G"]
    }),

    "tj-2026-nankai-ermo-24": spec({
      t: 5,
      domain: { minX: -0.9, maxX: 12.9, minY: -0.9, maxY: 4.8 },
      fixedPoints: { O: ["0", "0"], A: ["12", "0"], C: ["2", "2*S3"], B: ["6", "2*S3"] },
      movingParam: "t",
      movingPoints: { P: ["t", "0"], Q: ["t", "2*S3"], Op: ["2*t", "0"], Cp: ["2*t-2", "2*S3"] },
      basePolygon: ["O", "A", "B", "C"],
      movingPolygon: ["P", "Q", "Cp", "Op"],
      foldedPolygon: { x: "t", side: "left" },
      derivedIntersections: [
        { name: "D", a: ["Cp", "Op"], b: ["A", "B"], fallback: ["3*t-6", "S3*(6-t)"] }
      ],
      labels: ["O", "A", "B", "C", "P", "Q", "Op", "Cp", "D"]
    }),

    "tj-2026-hebei-yimo-24": spec({
      t: 2.5 * S3,
      domain: { minX: -2.4, maxX: 5.8, minY: -0.55, maxY: 3.85 },
      fixedPoints: { O: ["0", "0"], A: ["3*S3", "3"], B: ["-S3", "3"], C: ["0", "3"] },
      movingParam: "t",
      movingPoints: {
        M: ["3*S3-t", "3-t/S3"],
        N: ["3*S3-t", "3"],
        Ap: ["3*S3-2*t", "3"]
      },
      basePolygon: ["O", "A", "B"],
      movingPolygon: ["Ap", "M", "N"],
      derivedIntersections: [
        { name: "P", a: ["Ap", "M"], b: ["O", "B"], fallback: ["S3*(6-2*t/S3)/5", "3*(6-2*t/S3)/5"] }
      ],
      labels: ["O", "A", "B", "M", "N", "Ap", "P"]
    }),

    "tj-2026-hedong-yimo-24": spec({
      t: 3,
      domain: { minX: -2.6, maxX: 6.5, minY: -0.6, maxY: 4.7 },
      fixedPoints: { O: ["0", "0"], A: ["4", "0"], B: ["4", "4"], C: ["2", "2"], D: ["0", "4"] },
      movingParam: "t",
      movingPoints: { Op: ["t", "0"], Cp: ["t+2", "2"], Dp: ["t", "4"], Ep: ["t-2", "2"] },
      basePolygon: ["O", "A", "B"],
      movingPolygon: ["Op", "Cp", "Dp", "Ep"],
      derivedIntersections: [
        { name: "G", a: ["Op", "Cp"], b: ["A", "B"], fallback: ["4", "4-t"] },
        { name: "H", a: ["Cp", "Dp"], b: ["O", "B"], fallback: ["t", "t"] },
        { name: "M", a: ["Ep", "Op"], b: ["O", "B"], fallback: ["t/2", "t/2"] },
        { name: "N", a: ["Ep", "Op"], b: ["O", "B"], fallback: ["t/2", "t/2"] }
      ],
      labels: ["O", "A", "B", "Op", "Cp", "Dp", "Ep", "G", "H"]
    }),

    "tj-2026-xiqing-yimo-24": spec({
      t: 7 * S3,
      domain: { minX: -1.2, maxX: 11.4, minY: -0.8, maxY: 9.8 },
      fixedPoints: { O: ["0", "0"], B: ["6*S3", "0"], A: ["3*S3", "9"] },
      movingParam: "t",
      movingPoints: { Dp: ["t-6*S3", "0"], Op: ["t", "0"], Cp: ["t-6*S3", "6"] },
      basePolygon: ["O", "B", "A"],
      movingPolygon: ["Dp", "Op", "Cp"],
      derivedIntersections: [
        { name: "M", a: ["Cp", "Op"], b: ["O", "A"], fallback: ["t/2", "S3*t/2"] },
        { name: "N", a: ["Cp", "Op"], b: ["A", "B"], fallback: ["(t+6*S3)/2", "S3*(6*S3-t)/2"] },
        { name: "P", a: ["Cp", "Dp"], b: ["O", "A"], fallback: ["t-6*S3", "S3*(t-6*S3)"] }
      ],
      labels: ["O", "A", "B", "Dp", "Cp", "Op", "M", "N", "P"]
    }),

    "tj-2026-binhai-yimo-24": spec({
      t: 4.5,
      domain: { minX: -6.8, maxX: 9.6, minY: -0.8, maxY: 6.8 },
      fixedPoints: { O: ["0", "0"], E0: ["0", "3"], A: ["8", "0"], B: ["8", "6"], C: ["0", "6"] },
      movingParam: "t",
      movingPoints: { Ep: ["t", "3"], Fp: ["t-3", "3-S3"], Gp: ["t-6", "3"], Hp: ["t-3", "3+S3"] },
      basePolygon: ["O", "A", "B", "C"],
      movingPolygon: ["Ep", "Hp", "Gp", "Fp"],
      derivedIntersections: [
        { name: "M", a: ["O", "C"], b: ["Gp", "Fp"], fallback: ["0", "3-S3*(6-t)/3"] },
        { name: "N", a: ["O", "C"], b: ["Gp", "Hp"], fallback: ["0", "3+S3*(6-t)/3"] }
      ],
      labels: ["O", "A", "B", "C", "Ep", "Fp", "Gp", "Hp", "M", "N"]
    }),

    "tj-2026-heping-yimo-24": spec({
      t: 1.5 * S3,
      domain: { minX: -0.8, maxX: 9.2, minY: -0.7, maxY: 5.7 },
      fixedPoints: { O: ["0", "0"], A: ["0", "5"], B: ["5*S3", "0"] },
      movingParam: "t",
      movingPoints: { Dp: ["t-2*S3", "3"], Ep: ["t", "3"], Fp: ["t-S3", "0"] },
      basePolygon: ["O", "B", "A"],
      movingPolygon: ["Fp", "Ep", "Dp"],
      derivedIntersections: [
        { name: "G", a: ["Dp", "Fp"], b: ["O", "A"], fallback: ["0", "3-S3*t/3"] }
      ],
      labels: ["O", "A", "B", "Dp", "Ep", "Fp", "G"]
    }),

    "tj-2026-hexi-yimo-24": spec({
      t: 1.6,
      domain: { minX: -0.7, maxX: 5.1, minY: -0.6, maxY: 4 },
      fixedPoints: { O: ["0", "0"], A: ["4", "0"], B: ["2", "2*S3"], C: ["0", "S3"], D: ["3", "S3"] },
      movingParam: "t",
      movingPoints: { Op: ["t", "0"], Cp: ["t", "S3"], Dp: ["t+3", "S3"] },
      basePolygon: ["O", "A", "B"],
      movingPolygon: ["Op", "Dp", "Cp"],
      derivedIntersections: [
        { name: "E", a: ["Cp", "Dp"], b: ["A", "B"], fallback: ["3", "S3"] },
        { name: "F", a: ["Op", "Dp"], b: ["A", "B"], fallback: ["3+t/4", "S3*(1-t/4)"] }
      ],
      labels: ["O", "A", "B", "Cp", "Op", "Dp", "E", "F"]
    }),

    "tj-2026-beichen-yimo-24": spec({
      t: 1,
      domain: { minX: -0.4, maxX: 5.8, minY: -0.4, maxY: 4.1 },
      fixedPoints: { C: ["0", "2*S3"], D: ["2", "0"], E: ["2+2*S3", "2"], B: ["2+2*S3", "2*S3"] },
      movingParam: "t",
      movingPoints: { Cp: ["t", "2*S3"], Op: ["t", "0"], Dp: ["t+2", "0"] },
      basePolygon: ["B", "C", "D", "E"],
      movingPolygon: ["Cp", "Op", "Dp"],
      derivedIntersections: [
        { name: "M", a: ["Cp", "Op"], b: ["C", "D"], fallback: ["t", "2*S3-S3*t"] },
        { name: "N", a: ["Cp", "Dp"], b: ["D", "E"], fallback: ["2+3*t/4", "S3*t/4"] }
      ],
      labels: ["B", "C", "D", "E", "Cp", "Op", "Dp", "M", "N"]
    }),

    "tj-2026-hedong-ermo-24": spec({
      t: 1,
      domain: { minX: -4.2, maxX: 4.8, minY: -0.6, maxY: 6.6 },
      fixedPoints: { O: ["0", "0"], A: ["4", "0"], B: ["4", "4"], C: ["0", "4"] },
      movingParam: "t",
      movingPoints: { D: ["0", "t"], E: ["4", "t+4/S3"], Op: ["-S3*t/2", "3*t/2"], Ap: ["2-S3*t/2", "2*S3+3*t/2"] },
      basePolygon: ["O", "A", "B", "C"],
      movingPolygon: ["D", "Op", "Ap", "E"],
      derivedIntersections: [
        { name: "F", a: ["O", "C"], b: ["Op", "Ap"], fallback: ["0", "3"] },
        { name: "G", a: ["C", "B"], b: ["Op", "Ap"], fallback: ["0.7", "4"] },
        { name: "H", a: ["C", "B"], b: ["Ap", "E"], fallback: ["2.0", "4"] }
      ],
      labels: ["O", "A", "B", "C", "D", "E", "Op", "Ap", "F", "G", "H"]
    }),

    "tj-2026-heping-ermo-24": spec({
      t: 3.6,
      domain: { minX: -0.8, maxX: 7.7, minY: -0.6, maxY: 4.4 },
      fixedPoints: { O: ["0", "0"], A: ["1", "S3"], B: ["4", "S3"], C: ["5", "0"] },
      movingParam: "t",
      movingPoints: { P: ["t", "0"], Q: ["t-1", "S3"], Op: ["3*t/2", "S3*t/2"], Ap: ["(3*t-4)/2", "S3*t/2"] },
      basePolygon: ["O", "C", "B", "A"],
      movingPolygon: ["P", "Op", "Ap", "Q"],
      derivedIntersections: [
        { name: "E", a: ["Op", "P"], b: ["B", "C"], fallback: ["(t+5)/2", "S3*(5-t)/2"] }
      ],
      labels: ["O", "A", "B", "C", "P", "Q", "Op", "Ap", "E"]
    }),

    "tj-2026-dongli-yimo-24": spec({
      t: 1,
      domain: { minX: -2.8, maxX: 2.8, minY: -0.9, maxY: 3.9 },
      fixedPoints: { O: ["0", "0"], A: ["1.5", "1"], B: ["1.5", "3"], C: ["0", "1.5"], D: ["0", "-0.5"], M0: ["0.5", "0"] },
      movingParam: "t",
      movingPoints: { Op: ["t", "0"], Ep: ["t-2", "0"], Fp: ["t-2", "2"] },
      basePolygon: ["D", "A", "B", "C"],
      movingPolygon: ["Op", "Fp", "Ep"],
      derivedIntersections: [
        { name: "G", a: ["Op", "Fp"], b: ["C", "D"], fallback: ["0", "t"] },
        { name: "N", a: ["Op", "Fp"], b: ["A", "D"], fallback: ["(t+0.5)/2", "(t-0.5)/2"] }
      ],
      labels: ["O", "A", "B", "C", "D", "Op", "Ep", "Fp", "G", "N"]
    }),

    "tj-2026-hongqiao-yimo-24": spec({
      t: 2.5,
      domain: { minX: -0.6, maxX: 6.4, minY: -0.6, maxY: 4.3 },
      fixedPoints: { O: ["0", "0"], A: ["2", "0"], C: ["2", "2*S3"], B: ["4", "2*S3"] },
      movingParam: "t",
      movingPoints: { P: ["t", "0"], Op: ["2*t", "0"], Cp: ["2*t-2", "2*S3"] },
      basePolygon: ["O", "A", "B", "C"],
      foldedPolygon: { x: "t", side: "left" },
      derivedIntersections: [
        { name: "F", a: ["Op", "Cp"], b: ["A", "B"], fallback: ["4", "2*S3*(3-t)"] }
      ],
      labels: ["O", "A", "B", "C", "P", "Op", "Cp", "F"]
    }),

    "tj-2026-hexi-jieke-24": spec({
      t: 2.4,
      domain: { minX: -5.4, maxX: 5.4, minY: -0.55, maxY: 5.6 },
      fixedPoints: { O: ["0", "0"], A: ["24/5", "7/5"], B: ["0", "5"], C: ["-24/5", "18/5"] },
      movingParam: "t",
      movingPoints: {
        P: ["-24/5+24*t/25", "18/5+7*t/25"],
        Q: ["-24/5+24*t/25", "18/5-18*t/25"],
        D: ["-24/5+48*t/25", "18/5"]
      },
      basePolygon: ["O", "A", "B", "C"],
      movingPolygon: ["D", "P", "Q"],
      labels: ["O", "A", "B", "C", "P", "Q", "D"]
    })
  };

  function esc(value) {
    return String(value).replace(/[&<>"']/g, function (ch) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch];
    });
  }

  function toScreenFor(domain) {
    return GE.createToScreen(domain, PAD, W, H);
  }

  function autoDomain(config, resolved) {
    var points = [];
    [resolved.base, resolved.moving, resolved.overlap].forEach(function (poly) {
      (poly || []).forEach(function (p) {
        if (p && Number.isFinite(p.x) && Number.isFinite(p.y)) points.push(p);
      });
    });
    (config.labels || []).forEach(function (name) {
      var p = resolved.points[name];
      if (p && Number.isFinite(p.x) && Number.isFinite(p.y)) points.push(p);
    });
    if (!points.length) return config.domain;
    var minX = Math.min.apply(null, points.map(function (p) { return p.x; }));
    var maxX = Math.max.apply(null, points.map(function (p) { return p.x; }));
    var minY = Math.min.apply(null, points.map(function (p) { return p.y; }));
    var maxY = Math.max.apply(null, points.map(function (p) { return p.y; }));
    var width = Math.max(1, maxX - minX);
    var height = Math.max(1, maxY - minY);
    var padX = width * 0.18;
    var padY = height * 0.2;
    return {
      minX: minX - padX,
      maxX: maxX + padX,
      minY: minY - padY,
      maxY: maxY + padY
    };
  }

  function pathD(points, toScreen) {
    if (!points || !points.length) return "";
    var first = toScreen(points[0]);
    var d = "M " + first.x.toFixed(2) + " " + first.y.toFixed(2);
    for (var i = 1; i < points.length; i += 1) {
      var p = toScreen(points[i]);
      d += " L " + p.x.toFixed(2) + " " + p.y.toFixed(2);
    }
    return d + " Z";
  }

  function lineSvg(a, b, toScreen, color, width, dash) {
    var p = toScreen(a);
    var q = toScreen(b);
    return '<line x1="' + p.x.toFixed(2) + '" y1="' + p.y.toFixed(2) + '" x2="' + q.x.toFixed(2) + '" y2="' + q.y.toFixed(2) + '" stroke="' + color + '" stroke-width="' + width + '"' + (dash ? ' stroke-dasharray="' + dash + '"' : "") + ' />';
  }

  function pointSvg(point, label, toScreen, color) {
    if (!point || !Number.isFinite(point.x) || !Number.isFinite(point.y)) return "";
    var p = toScreen(point);
    var text = label ? '<text x="' + (p.x + 4).toFixed(2) + '" y="' + (p.y - 5).toFixed(2) + '" font-size="8.5" font-weight="800" fill="' + color + '">' + esc(label.replace("Op", "O′").replace("Cp", "C′").replace("Dp", "D′").replace("Ep", "E′").replace("Fp", "F′").replace("Gp", "G′").replace("Hp", "H′").replace("Ap", "A′")) + '</text>' : "";
    return '<circle cx="' + p.x.toFixed(2) + '" cy="' + p.y.toFixed(2) + '" r="2.6" fill="' + color + '" stroke="#fffdf8" stroke-width="1" />' + text;
  }

  function render(svg, config) {
    var resolved = GL.resolveClipOverlap(config, config.t);
    var points = resolved.points;
    var domain = autoDomain(config, resolved);
    var toScreen = toScreenFor(domain);
    var markup = "";

    markup += '<g class="ranking-thumbnail-grid">';
    for (var gx = Math.ceil(domain.minX); gx <= Math.floor(domain.maxX); gx += 1) {
      markup += lineSvg({ x: gx, y: domain.minY }, { x: gx, y: domain.maxY }, toScreen, "rgba(15,54,58,.08)", 0.8, "");
    }
    for (var gy = Math.ceil(domain.minY); gy <= Math.floor(domain.maxY); gy += 1) {
      markup += lineSvg({ x: domain.minX, y: gy }, { x: domain.maxX, y: gy }, toScreen, "rgba(15,54,58,.08)", 0.8, "");
    }
    markup += "</g>";

    if (domain.minX < 0 && domain.maxX > 0) {
      markup += lineSvg({ x: 0, y: domain.minY }, { x: 0, y: domain.maxY }, toScreen, "rgba(15,54,58,.24)", 1.1, "");
    }
    if (domain.minY < 0 && domain.maxY > 0) {
      markup += lineSvg({ x: domain.minX, y: 0 }, { x: domain.maxX, y: 0 }, toScreen, "rgba(15,54,58,.24)", 1.1, "");
    }

    if (resolved.base.length) {
      markup += '<path d="' + pathD(resolved.base, toScreen) + '" fill="rgba(201,120,40,.10)" stroke="#c97828" stroke-width="1.9" />';
    }
    if (resolved.moving.length) {
      markup += '<path d="' + pathD(resolved.moving, toScreen) + '" fill="rgba(15,107,104,.12)" stroke="#0f6b68" stroke-width="1.9" />';
    }
    if (resolved.overlap.length) {
      markup += '<path d="' + pathD(resolved.overlap, toScreen) + '" fill="rgba(220,38,38,.20)" stroke="#dc2626" stroke-width="2.1" />';
    }

    (config.labels || []).forEach(function (name) {
      var color = /p$|^E$|^F$|^G$|^H$|^M$|^N$|^P$|^Q$|^D$/.test(name) && !/^[OABC]$/.test(name) ? "#dc2626" : "#0b2f34";
      if (/p$/.test(name)) color = "#0f6b68";
      markup += pointSvg(points[name], name, toScreen, color);
    });

    svg.innerHTML = markup;
  }

  document.querySelectorAll("svg[data-ranking-figure]").forEach(function (svg) {
    var key = svg.getAttribute("data-ranking-figure");
    var config = DATA[key];
    if (!config) return;
    try {
      render(svg, config);
    } catch (error) {
      svg.innerHTML = '<text x="105" y="72" text-anchor="middle" font-size="12" font-weight="800" fill="#9a3412">图 2 加载失败</text>';
      // Keep the page usable even if one thumbnail has bad geometry data.
      console.warn("ranking thumbnail failed:", key, error);
    }
  });
})();
