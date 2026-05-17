(function () {
  "use strict";

  var W = 210;
  var H = 140;
  var PAD = { left: 16, right: 14, top: 12, bottom: 18 };

  var COLORS = {
    ink: "#0b2f34",
    muted: "rgba(15,54,58,.5)",
    teal: "#0f6b68",
    amber: "#c97828",
    red: "#dc2626",
    blue: "#2563eb",
    green: "#16a34a"
  };

  function esc(value) {
    return String(value).replace(/[&<>"']/g, function (ch) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch];
    });
  }

  function map(domain) {
    var sx = (W - PAD.left - PAD.right) / (domain.maxX - domain.minX);
    var sy = (H - PAD.top - PAD.bottom) / (domain.maxY - domain.minY);
    var s = Math.min(sx, sy);
    var usedW = (domain.maxX - domain.minX) * s;
    var usedH = (domain.maxY - domain.minY) * s;
    var ox = PAD.left + (W - PAD.left - PAD.right - usedW) / 2;
    var oy = PAD.top + (H - PAD.top - PAD.bottom - usedH) / 2;
    return function (p) {
      return {
        x: ox + (p.x - domain.minX) * s,
        y: oy + (domain.maxY - p.y) * s
      };
    };
  }

  function pt(x, y) {
    return { x: x, y: y };
  }

  function addLine(out, to, a, b, color, width, dash) {
    var p = to(a);
    var q = to(b);
    out.push('<line x1="' + p.x.toFixed(2) + '" y1="' + p.y.toFixed(2) + '" x2="' + q.x.toFixed(2) + '" y2="' + q.y.toFixed(2) + '" stroke="' + color + '" stroke-width="' + (width || 2) + '" stroke-linecap="round"' + (dash ? ' stroke-dasharray="' + dash + '"' : "") + ' />');
  }

  function addPath(out, to, points, color, width, fill, dash) {
    if (!points.length) return;
    var first = to(points[0]);
    var d = "M " + first.x.toFixed(2) + " " + first.y.toFixed(2);
    points.slice(1).forEach(function (point) {
      var p = to(point);
      d += " L " + p.x.toFixed(2) + " " + p.y.toFixed(2);
    });
    out.push('<path d="' + d + '" fill="' + (fill || "none") + '" stroke="' + color + '" stroke-width="' + (width || 2) + '" stroke-linejoin="round" stroke-linecap="round"' + (dash ? ' stroke-dasharray="' + dash + '"' : "") + ' />');
  }

  function addPolygon(out, to, points, color, fill) {
    if (!points.length) return;
    var d = points.map(function (point) {
      var p = to(point);
      return p.x.toFixed(2) + "," + p.y.toFixed(2);
    }).join(" ");
    out.push('<polygon points="' + d + '" fill="' + fill + '" stroke="' + color + '" stroke-width="1.8" stroke-linejoin="round" />');
  }

  function addPoint(out, to, p, label, color, dx, dy) {
    var q = to(p);
    out.push('<circle cx="' + q.x.toFixed(2) + '" cy="' + q.y.toFixed(2) + '" r="3.1" fill="' + color + '" stroke="#fffdf8" stroke-width="1.1" />');
    if (label) {
      out.push('<text x="' + (q.x + (dx == null ? 5 : dx)).toFixed(2) + '" y="' + (q.y + (dy == null ? -6 : dy)).toFixed(2) + '" font-size="9" font-weight="800" fill="' + color + '">' + esc(label) + '</text>');
    }
  }

  function addLabel(out, to, p, text, color, size) {
    var q = to(p);
    out.push('<text x="' + q.x.toFixed(2) + '" y="' + q.y.toFixed(2) + '" text-anchor="middle" font-size="' + (size || 9.5) + '" font-weight="800" fill="' + color + '">' + esc(text) + '</text>');
  }

  function addCircle(out, to, c, r, color, fill, dash) {
    var pc = to(c);
    var pr = to(pt(c.x + r, c.y));
    out.push('<circle cx="' + pc.x.toFixed(2) + '" cy="' + pc.y.toFixed(2) + '" r="' + Math.abs(pr.x - pc.x).toFixed(2) + '" fill="' + (fill || "none") + '" stroke="' + color + '" stroke-width="1.8"' + (dash ? ' stroke-dasharray="' + dash + '"' : "") + ' />');
  }

  function addParabola(out, to, f, x0, x1, color) {
    var points = [];
    for (var i = 0; i <= 44; i += 1) {
      var x = x0 + (x1 - x0) * i / 44;
      points.push(pt(x, f(x)));
    }
    addPath(out, to, points, color || COLORS.muted, 1.5, "none", "3 4");
  }

  function addGrid(out, to, domain) {
    for (var x = Math.ceil(domain.minX); x <= Math.floor(domain.maxX); x += 1) {
      addLine(out, to, pt(x, domain.minY), pt(x, domain.maxY), "rgba(15,54,58,.08)", 0.8);
    }
    for (var y = Math.ceil(domain.minY); y <= Math.floor(domain.maxY); y += 1) {
      addLine(out, to, pt(domain.minX, y), pt(domain.maxX, y), "rgba(15,54,58,.08)", 0.8);
    }
    if (domain.minX < 0 && domain.maxX > 0) addLine(out, to, pt(0, domain.minY), pt(0, domain.maxY), "rgba(15,54,58,.26)", 1);
    if (domain.minY < 0 && domain.maxY > 0) addLine(out, to, pt(domain.minX, 0), pt(domain.maxX, 0), "rgba(15,54,58,.26)", 1);
  }

  function common(svg, domain, draw) {
    var to = map(domain);
    var out = [];
    addGrid(out, to, domain);
    draw(out, to);
    svg.innerHTML = out.join("");
  }

  function interpolate(a, b, t) {
    return pt(a.x + (b.x - a.x) * t, a.y + (b.y - a.y) * t);
  }

  var SCENES = {
    "tj-2026-nankai-yimo-25": function (svg, t) {
      common(svg, { minX: -0.5, maxX: 6.5, minY: -5.6, maxY: 2.3 }, function (out, to) {
        var D = pt(1, 0);
        var F = pt(1.5, -1.5);
        var M = interpolate(pt(2.7, 1), pt(5, 1), t);
        var N = pt(2, 1 - M.x);
        var Dp = pt(M.x + 1, 2 - M.x);
        var G = interpolate(N, M, 0.46);
        addPolygon(out, to, [D, M, Dp, N], COLORS.teal, "rgba(15,107,104,.10)");
        addLine(out, to, D, G, COLORS.red, 3);
        addLine(out, to, G, F, COLORS.red, 3);
        addLine(out, to, Dp, G, COLORS.blue, 2.2, "5 4");
        addLine(out, to, Dp, F, COLORS.blue, 2.5);
        addPoint(out, to, D, "D", COLORS.ink);
        addPoint(out, to, M, "M", COLORS.teal);
        addPoint(out, to, N, "N", COLORS.teal);
        addPoint(out, to, Dp, "D'", COLORS.blue);
        addPoint(out, to, G, "G", COLORS.red);
        addPoint(out, to, F, "F", COLORS.red);
        addLabel(out, to, pt(4.25, 1.65), "EG+FG -> DG+FG -> D'G+FG", COLORS.red, 8.6);
      });
    },

    "tj-2026-heping-ermo-25": function (svg, t) {
      common(svg, { minX: -4.5, maxX: 2.2, minY: -4.8, maxY: 1.6 }, function (out, to) {
        var A = pt(-3, 0);
        var E = pt(-1, -0.8 - 2.2 * t);
        var K = pt(E.x + (A.y - E.y), E.y - (A.x - E.x));
        var G = pt(A.x + (A.y - E.y), A.y - (A.x - E.x));
        var H = pt((E.x + G.x) / 2, (E.y + G.y) / 2);
        var M = pt(-1, 0);
        var Gr = pt(G.x, -G.y - 1.3);
        addPolygon(out, to, [A, E, K, G], COLORS.teal, "rgba(15,107,104,.10)");
        addLine(out, to, pt(-4.3, G.y), pt(2, G.y), COLORS.amber, 1.7, "5 4");
        addLine(out, to, H, M, COLORS.red, 2.4);
        addLine(out, to, M, G, COLORS.red, 2.4);
        addLine(out, to, G, Gr, COLORS.blue, 1.8, "4 4");
        addLine(out, to, A, Gr, COLORS.blue, 2.4);
        addPoint(out, to, A, "A", COLORS.ink);
        addPoint(out, to, E, "E", COLORS.teal);
        addPoint(out, to, G, "G", COLORS.teal);
        addPoint(out, to, H, "H", COLORS.red);
        addPoint(out, to, M, "M", COLORS.red);
        addPoint(out, to, Gr, "G'", COLORS.blue);
        addLabel(out, to, pt(-1.1, 1.15), "HF+FM+MG -> AG+MG", COLORS.red, 9);
      });
    },

    "tj-2026-heping-yimo-25": function (svg, t) {
      common(svg, { minX: -0.9, maxX: 5.3, minY: -2.7, maxY: 3.1 }, function (out, to) {
        var O = pt(0, 0);
        var B = pt(3, 0);
        var C = pt(0, -3);
        var M = interpolate(B, C, t);
        var N = pt(C.x + (C.x - M.x), C.y + (C.y - M.y));
        var G = pt(M.x + 1.15, M.y - 0.25);
        addLine(out, to, B, C, COLORS.teal, 2.3);
        addLine(out, to, C, pt(4.8, -1.8), COLORS.teal, 1.8, "5 4");
        addLine(out, to, O, M, COLORS.red, 2.6);
        addLine(out, to, B, N, COLORS.amber, 2.2);
        addLine(out, to, M, G, COLORS.blue, 2.6);
        addLine(out, to, O, G, COLORS.red, 1.8, "4 4");
        addPoint(out, to, O, "O", COLORS.ink);
        addPoint(out, to, B, "B", COLORS.ink);
        addPoint(out, to, C, "C", COLORS.ink);
        addPoint(out, to, M, "M", COLORS.red);
        addPoint(out, to, N, "N", COLORS.amber);
        addPoint(out, to, G, "G", COLORS.blue);
        addLabel(out, to, pt(2.8, 2.55), "OM+BN -> OM+MG", COLORS.red, 9);
      });
    },

    "tj-2026-hedong-ermo-25": function (svg, t) {
      common(svg, { minX: -3.3, maxX: 4.8, minY: -3.6, maxY: 3.6 }, function (out, to) {
        var upper = t > 0.5;
        var O = pt(0, 0);
        var B = pt(3, 0);
        var C = upper ? pt(0, 2.4) : pt(0, -2.4);
        var F = upper ? pt(2.9, 1.5) : pt(2.9, -1.5);
        var H = upper ? pt(0.8, 1.05) : pt(0.8, -1.05);
        addCircle(out, to, pt(1.5, 0), 1.5, COLORS.amber, "rgba(201,120,40,.08)", "5 4");
        addLine(out, to, O, B, COLORS.ink, 2);
        addLine(out, to, O, C, COLORS.teal, 2);
        addLine(out, to, H, F, COLORS.red, 2.8);
        addLine(out, to, H, B, COLORS.muted, 1.7, "4 4");
        addPoint(out, to, O, "O", COLORS.ink);
        addPoint(out, to, B, "B", COLORS.ink);
        addPoint(out, to, C, upper ? "C上" : "C下", COLORS.teal);
        addPoint(out, to, H, "H", COLORS.red);
        addPoint(out, to, F, "F", COLORS.red);
        addLabel(out, to, pt(1.2, 3.1), upper ? "上半轴情形" : "下半轴情形", COLORS.red, 9);
      });
    },

    "tj-2026-nankai-ermo-25": function (svg, t) {
      common(svg, { minX: -1.1, maxX: 4.7, minY: -0.8, maxY: 4.6 }, function (out, to) {
        var A = pt(0, 0);
        var M = pt(4, 0);
        var P = pt(0.7 + 2.4 * t, 1.2 + 1.2 * t);
        var B = pt(3.2, 3.2);
        var D = pt(1.2, 3.2);
        var F = pt((M.x + D.x) / 2, (M.y + D.y) / 2);
        addPolygon(out, to, [M, F, D, B], COLORS.teal, "rgba(15,107,104,.10)");
        addLine(out, to, M, B, COLORS.teal, 2);
        addLine(out, to, F, D, COLORS.teal, 2);
        addLine(out, to, P, B, COLORS.red, 2.5);
        addLine(out, to, P, M, COLORS.amber, 2.5);
        addLine(out, to, A, M, COLORS.blue, 2, "4 4");
        addPoint(out, to, A, "A", COLORS.ink);
        addPoint(out, to, M, "M", COLORS.ink);
        addPoint(out, to, P, "P", COLORS.red);
        addPoint(out, to, B, "B", COLORS.teal);
        addPoint(out, to, F, "F", COLORS.teal);
        addPoint(out, to, D, "D", COLORS.teal);
        addLabel(out, to, pt(2.25, 4.15), "平行四边形交点 -> B", COLORS.red, 9);
      });
    },

    "tj-2026-hedong-yimo-25": function (svg, t) {
      common(svg, { minX: -2.4, maxX: 5.2, minY: -4.2, maxY: 1.6 }, function (out, to) {
        var A = pt(-1.4, 0);
        var G = interpolate(pt(0.1, -0.8), pt(3.4, -2.8), t);
        var H = pt(G.x, -1.8);
        var F = pt(4.4, -1.8);
        var Ap = pt(1.2, -1.8);
        addLine(out, to, pt(-2.2, -1.8), pt(5, -1.8), COLORS.muted, 1.6, "5 4");
        addLine(out, to, A, G, COLORS.red, 2.2);
        addLine(out, to, G, H, COLORS.red, 2.2);
        addLine(out, to, H, F, COLORS.red, 2.2);
        addLine(out, to, Ap, F, COLORS.blue, 2.7);
        addLine(out, to, A, Ap, COLORS.blue, 1.8, "4 4");
        addPoint(out, to, A, "A", COLORS.ink);
        addPoint(out, to, Ap, "A'", COLORS.blue);
        addPoint(out, to, G, "G", COLORS.red);
        addPoint(out, to, H, "H", COLORS.red);
        addPoint(out, to, F, "F", COLORS.red);
        addLabel(out, to, pt(2.2, 1.15), "两次对称拉直", COLORS.red, 9);
      });
    },

    "tj-2026-beichen-yimo-25": function (svg, t) {
      common(svg, { minX: -0.8, maxX: 6.3, minY: -0.8, maxY: 4.6 }, function (out, to) {
        var A = pt(0, 0);
        var B = pt(5, 0);
        var C = pt(5, 3.6);
        var H = interpolate(B, C, t);
        var R = pt(H.x - (H.y - B.y), H.y + (H.x - B.x));
        addLine(out, to, B, C, COLORS.teal, 2.2);
        addPolygon(out, to, [B, H, R], COLORS.blue, "rgba(37,99,235,.10)");
        addLine(out, to, A, H, COLORS.red, 2.4);
        addLine(out, to, B, R, COLORS.blue, 2.6);
        addLine(out, to, H, R, COLORS.blue, 1.8, "4 4");
        addLine(out, to, A, R, COLORS.red, 1.8, "4 4");
        addPoint(out, to, A, "A", COLORS.ink);
        addPoint(out, to, B, "B", COLORS.ink);
        addPoint(out, to, C, "C", COLORS.ink);
        addPoint(out, to, H, "H", COLORS.red);
        addPoint(out, to, R, "R", COLORS.blue);
        addLabel(out, to, pt(3, 4.15), "√2BH -> BR", COLORS.red, 9);
      });
    },

    "tj-2026-hexi-yimo-25": function (svg, t) {
      common(svg, { minX: -1.2, maxX: 5.2, minY: -1, maxY: 4.6 }, function (out, to) {
        var A = pt(0, 0);
        var M = pt(4.4, 0);
        var N = interpolate(pt(1.2, 0.5), pt(3.4, 2.8), t);
        var mid = pt((A.x + N.x) / 2, (A.y + N.y) / 2);
        var Q = pt(mid.x - (N.y - A.y) / 2, mid.y + (N.x - A.x) / 2);
        addPolygon(out, to, [A, Q, N], COLORS.blue, "rgba(37,99,235,.10)");
        addLine(out, to, M, N, COLORS.red, 2.5);
        addLine(out, to, N, Q, COLORS.red, 2.5);
        addLine(out, to, A, N, COLORS.amber, 2.2);
        addPoint(out, to, A, "A", COLORS.ink);
        addPoint(out, to, M, "M", COLORS.ink);
        addPoint(out, to, N, "N", COLORS.red);
        addPoint(out, to, Q, "Q", COLORS.blue);
        addLabel(out, to, pt(2.25, 4.05), "√2MN+AN -> √2(MN+QN)", COLORS.red, 8.5);
      });
    },

    "tj-2026-xiqing-yimo-25": function (svg, t) {
      common(svg, { minX: -0.8, maxX: 5.7, minY: -3.5, maxY: 2.8 }, function (out, to) {
        var A = pt(0, 0);
        var D = pt(4, -2.5);
        var M = pt(0.9 + 3.4 * t, 0);
        var N = pt(M.x + 0.85 * (M.x - A.x), 0.49 * (M.x - A.x));
        addLine(out, to, A, pt(5.4, 3.1), COLORS.blue, 1.7, "5 4");
        addLine(out, to, D, M, COLORS.red, 2.5);
        addLine(out, to, M, N, COLORS.red, 2.5);
        addLine(out, to, A, M, COLORS.amber, 2);
        addPoint(out, to, A, "A", COLORS.ink);
        addPoint(out, to, D, "D", COLORS.ink);
        addPoint(out, to, M, "M", COLORS.red);
        addPoint(out, to, N, "N", COLORS.blue);
        addLabel(out, to, pt(2.7, 2.35), "30°辅助线转化", COLORS.red, 9);
      });
    },

    "tj-2026-binhai-yimo-25": function (svg, t) {
      common(svg, { minX: -3.8, maxX: 5.3, minY: -0.8, maxY: 4.7 }, function (out, to) {
        var B = pt(-2.8, 0);
        var D = pt(3.7, 3.5);
        var E = pt(0, 0.5 + 3 * t);
        var Dp = pt(D.x - 2.2, D.y);
        addLine(out, to, B, E, COLORS.red, 2.5);
        addLine(out, to, D, pt(E.x + 2.2, E.y), COLORS.amber, 2.3);
        addLine(out, to, Dp, E, COLORS.amber, 2.3);
        addLine(out, to, B, Dp, COLORS.blue, 2.4, "5 4");
        addLine(out, to, D, Dp, COLORS.blue, 1.7, "4 4");
        addPoint(out, to, B, "B", COLORS.ink);
        addPoint(out, to, D, "D", COLORS.ink);
        addPoint(out, to, Dp, "D'", COLORS.blue);
        addPoint(out, to, E, "E", COLORS.red);
        addLabel(out, to, pt(0.7, 4.15), "DF平移 -> BE+ED'", COLORS.red, 9);
      });
    },

    "tj-2026-hongqiao-ermo-25": function (svg) {
      common(svg, { minX: -2.8, maxX: 5.2, minY: -1, maxY: 4.3 }, function (out, to) {
        var A = pt(-2, 0);
        var G = pt(1.6, 1.8);
        var D = pt(4, 3);
        var E = pt(0.8, 0);
        var F = pt(2.3, 0.9);
        addPolygon(out, to, [E, F, D, G], COLORS.teal, "rgba(15,107,104,.10)");
        addLine(out, to, A, G, COLORS.red, 2.5);
        addLine(out, to, G, D, COLORS.red, 2.5);
        addLine(out, to, A, D, COLORS.blue, 2.1, "5 4");
        addPoint(out, to, A, "A", COLORS.ink);
        addPoint(out, to, G, "G", COLORS.red);
        addPoint(out, to, D, "D", COLORS.ink);
        addPoint(out, to, E, "E", COLORS.teal);
        addPoint(out, to, F, "F", COLORS.teal);
        addLabel(out, to, pt(1.5, 3.85), "平行四边形 -> 三点共线", COLORS.red, 9);
      });
    },

    "tj-2026-hongqiao-yimo-25": function (svg) {
      common(svg, { minX: -2.8, maxX: 4.5, minY: -2.4, maxY: 3.2 }, function (out, to) {
        var C = pt(0, 0);
        var A = pt(-1.8, 0);
        var Ap = pt(0.5, 1.8);
        var B = pt(3.3, 0.4);
        var M = pt(1.5, -1.5);
        addPolygon(out, to, [C, Ap, B], COLORS.blue, "rgba(37,99,235,.10)");
        addLine(out, to, C, A, COLORS.teal, 2.3);
        addLine(out, to, C, Ap, COLORS.teal, 2.3);
        addLine(out, to, B, M, COLORS.red, 2.2);
        addLine(out, to, M, pt(1.5, 0), COLORS.red, 1.7, "4 4");
        addPoint(out, to, C, "C", COLORS.ink);
        addPoint(out, to, A, "A", COLORS.teal);
        addPoint(out, to, Ap, "A'", COLORS.teal);
        addPoint(out, to, B, "B", COLORS.blue);
        addPoint(out, to, M, "M", COLORS.red);
        addLabel(out, to, pt(1.2, 2.65), "等角/等腰 + 铅垂面积", COLORS.red, 9);
      });
    },

    "tj-2026-hexi-jieke-25": function (svg) {
      common(svg, { minX: -2.2, maxX: 4.1, minY: -3.2, maxY: 1.4 }, function (out, to) {
        var A = pt(-1, 0);
        var B = pt(3.2, 0);
        var N = pt(0.8, -2.2);
        var E = pt(0.8, 0);
        addPolygon(out, to, [A, E, N], COLORS.blue, "rgba(37,99,235,.10)");
        addLine(out, to, A, B, COLORS.ink, 2);
        addLine(out, to, A, N, COLORS.red, 2.5);
        addLine(out, to, N, E, COLORS.red, 2.5);
        addLine(out, to, N, B, COLORS.amber, 2.2);
        addPoint(out, to, A, "A", COLORS.ink);
        addPoint(out, to, B, "B", COLORS.ink);
        addPoint(out, to, N, "N", COLORS.red);
        addPoint(out, to, E, "E", COLORS.blue);
        addLabel(out, to, pt(1.2, 1.05), "等腰三角形得半角", COLORS.red, 9);
      });
    },

    "tj-2026-hebei-yimo-25": function (svg) {
      common(svg, { minX: -1.5, maxX: 5.4, minY: -1.4, maxY: 4.2 }, function (out, to) {
        addParabola(out, to, function (x) { return 0.25 * (x - 2) * (x - 2) - 0.5; }, -0.8, 5, COLORS.muted);
        var M = pt(0.8, 2.7);
        var H = pt(4.2, 2.7);
        var N = pt(2.6, 0.2);
        var I = pt(2.6, 2.7);
        addLine(out, to, M, H, COLORS.red, 2.6);
        addLine(out, to, N, I, COLORS.blue, 2.6);
        addLine(out, to, pt(-1.2, 2.7), pt(5.1, 2.7), COLORS.muted, 1.3, "4 4");
        addPoint(out, to, M, "M", COLORS.red);
        addPoint(out, to, H, "H", COLORS.red);
        addPoint(out, to, N, "N", COLORS.blue);
        addPoint(out, to, I, "I", COLORS.blue);
        addLabel(out, to, pt(2.2, 3.75), "MP=2NI，纯计算", COLORS.red, 9);
      });
    }
  };

  var items = [];
  document.querySelectorAll("svg[data-ranking-keystep]").forEach(function (svg, index) {
    var key = svg.getAttribute("data-ranking-keystep");
    var scene = SCENES[key];
    if (!scene) return;
    try {
      scene(svg, 0.5);
      items.push({ svg: svg, key: key, scene: scene, phase: index * 0.19 });
    } catch (error) {
      svg.innerHTML = '<text x="105" y="72" text-anchor="middle" font-size="12" font-weight="800" fill="#9a3412">关键图加载失败</text>';
      console.warn("ranking keystep thumbnail failed:", key, error);
    }
  });

  if (!window.requestAnimationFrame || (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches)) return;

  var startedAt = performance.now();
  var duration = 5200;
  var lastFrame = 0;

  function animate(now) {
    if (document.hidden) {
      window.requestAnimationFrame(animate);
      return;
    }
    if (now - lastFrame < 90) {
      window.requestAnimationFrame(animate);
      return;
    }
    lastFrame = now;
    items.forEach(function (item) {
      var progress = ((now - startedAt) / duration + item.phase) % 1;
      var wave = 0.5 - 0.5 * Math.cos(progress * Math.PI * 2);
      try {
        item.scene(item.svg, wave);
      } catch (error) {
        item.scene(item.svg, 0.5);
      }
    });
    window.requestAnimationFrame(animate);
  }

  window.requestAnimationFrame(animate);
})();
