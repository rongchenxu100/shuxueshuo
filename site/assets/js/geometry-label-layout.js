/**
 * 几何题 SVG 标签与尺寸线布局（数学说公共库）
 * 题页引入：<script src="../../../assets/js/geometry-label-layout.js"></script>
 * 全局：window.GeometryLabelLayout
 */
(function(global){
  function estimateTextWidth(text, fontSize){
    let units = 0;
    for(const ch of String(text)){
      units += /[\u0000-\u00ff]/.test(ch) ? 0.62 : 1;
    }
    return Math.max(fontSize, units * fontSize);
  }

  function rectsOverlap(a, b){
    return !(a.right <= b.left || a.left >= b.right || a.bottom <= b.top || a.top >= b.bottom);
  }

  function overlapArea(a, b){
    if(!rectsOverlap(a, b)) return 0;
    const w = Math.min(a.right, b.right) - Math.max(a.left, b.left);
    const h = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
    return Math.max(0, w) * Math.max(0, h);
  }

  function makeRect(left, top, width, height, padding){
    return {
      left: left - padding,
      top: top - padding,
      right: left + width + padding,
      bottom: top + height + padding
    };
  }

  function createLabelLayout(config){
    return {
      toScreen: config.toScreen,
      occupied: [],
      pointRadius: config.pointRadius ?? 7,
      padding: config.padding ?? 4
    };
  }

  function addPointObstacle(layout, p, radius){
    const s = layout.toScreen(p);
    const r = radius ?? layout.pointRadius;
    layout.occupied.push({
      left: s.x - r,
      top: s.y - r,
      right: s.x + r,
      bottom: s.y + r
    });
  }

  function escapeHtml(text){
    return String(text).replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;");
  }

  function addRectObstacle(layout, rect){
    layout.occupied.push(rect);
  }

  function addSegmentObstacle(layout, toScreen, a, b, options){
    const p = toScreen(a);
    const q = toScreen(b);
    const dx = q.x - p.x;
    const dy = q.y - p.y;
    const len = Math.hypot(dx, dy);
    if(len < 1e-6) return;
    const step = options?.step ?? 22;
    const radius = options?.radius ?? 6;
    const count = Math.max(2, Math.ceil(len / step));
    for(let i = 0; i <= count; i += 1){
      const ratio = i / count;
      const x = p.x + dx * ratio;
      const y = p.y + dy * ratio;
      layout.occupied.push({
        left: x - radius,
        top: y - radius,
        right: x + radius,
        bottom: y + radius,
        kind: options?.kind ?? "segment"
      });
    }
  }

  function pointsCoincident(a, b, tolerance){
    const tol = tolerance ?? 1e-6;
    return Math.hypot(a.x - b.x, a.y - b.y) <= tol;
  }

  function mergeCoincidentLabel(primary, peers, options){
    const tolerance = options?.tolerance ?? 1e-6;
    const separator = options?.separator ?? "、";
    const coincident = [];
    const hidden = [];
    (peers || []).forEach(peer => {
      if(pointsCoincident(primary.point, peer.point, tolerance)){
        coincident.push(peer.label);
        hidden.push(peer.label);
      }
    });
    return {
      label: coincident.length ? `${primary.label}(${coincident.join(separator)})` : primary.label,
      hidden
    };
  }

  function candidateOffsets(preferredDx, preferredDy){
    const dx = preferredDx ?? 8;
    const dy = preferredDy ?? -8;
    const sx = dx === 0 ? 1 : Math.sign(dx);
    const sy = dy === 0 ? -1 : Math.sign(dy);
    const ax = Math.max(Math.abs(dx), 8);
    const ay = Math.max(Math.abs(dy), 8);
    return [
      {dx, dy},
      {dx, dy: -dy || 14 * -sy},
      {dx: -dx || 14 * -sx, dy},
      {dx: -dx || 14 * -sx, dy: -dy || 14 * -sy},
      {dx: 0, dy},
      {dx: 0, dy: -dy || 14 * -sy},
      {dx: ax * sx, dy: 0},
      {dx: -ax * sx, dy: 0},
      {dx: (ax + 10) * sx, dy: (ay + 6) * sy},
      {dx: -(ax + 10) * sx, dy: (ay + 6) * sy},
      {dx: (ax + 10) * sx, dy: -(ay + 6) * sy},
      {dx: -(ax + 10) * sx, dy: -(ay + 6) * sy}
    ];
  }

  function placeLabel(layout, p, text, options){
    const fontSize = options.fontSize ?? 15;
    const width = estimateTextWidth(text, fontSize);
    const height = fontSize + 4;
    const preferredDx = options.preferredDx ?? 8;
    const preferredDy = options.preferredDy ?? -8;
    const candidates = options.candidates ?? candidateOffsets(preferredDx, preferredDy);
    const anchor = layout.toScreen(p);
    const pointRect = {
      left: anchor.x - layout.pointRadius,
      top: anchor.y - layout.pointRadius,
      right: anchor.x + layout.pointRadius,
      bottom: anchor.y + layout.pointRadius
    };

    let best = null;
    candidates.forEach((candidate, index)=>{
      const x = anchor.x + candidate.dx;
      const y = anchor.y + candidate.dy;
      const bbox = makeRect(x, y - fontSize, width, height, layout.padding);
      let score = index * 0.01 + Math.abs(candidate.dx - preferredDx) * 0.4 + Math.abs(candidate.dy - preferredDy) * 0.4;
      if(!options.allowNearPoint){
        score += overlapArea(bbox, pointRect) * 50;
      }
      layout.occupied.forEach(rect => {
        if(options.allowNearPoint && rect.kind === "self-point"){
          return;
        }
        score += overlapArea(bbox, rect) * 100;
      });
      if(!best || score < best.score){
        best = {x, y, bbox, score};
      }
    });

    layout.occupied.push(best.bbox);
    return best;
  }

  function placeScreenLabel(layout, anchorScreen, text, options){
    const fontSize = options.fontSize ?? 15;
    const width = estimateTextWidth(text, fontSize);
    const height = fontSize + 4;
    const preferredDx = options.preferredDx ?? 0;
    const preferredDy = options.preferredDy ?? 0;
    const candidates = options.candidates ?? candidateOffsets(preferredDx, preferredDy);
    let best = null;
    candidates.forEach((candidate, index)=>{
      const x = anchorScreen.x + candidate.dx;
      const y = anchorScreen.y + candidate.dy;
      const bbox = makeRect(x - width / 2, y - fontSize / 2, width, height, 4);
      let score = index * 0.01 + Math.abs(candidate.dx - preferredDx) * 0.4 + Math.abs(candidate.dy - preferredDy) * 0.4;
      layout.occupied.forEach(rect => {
        score += overlapArea(bbox, rect) * 100;
      });
      if(!best || score < best.score){
        best = {x, y, bbox, score};
      }
    });
    layout.occupied.push(best.bbox);
    return best;
  }

  function labelSvg(layout, p, text, options){
    const placed = placeLabel(layout, p, text, options || {});
    const fontSize = options.fontSize ?? 15;
    const fontWeight = options.fontWeight ?? 900;
    const color = options.color ?? "#1f2937";
    return `<text x="${placed.x}" y="${placed.y}" font-size="${fontSize}" font-weight="${fontWeight}" fill="${color}">${escapeHtml(text)}</text>`;
  }

  function polarLabelSvg(layout, centerScreen, text, options){
    const fontSize = options.fontSize ?? 15;
    const radius = options.radius ?? 24;
    const angle = options.angle ?? 0;
    const color = options.color ?? "#1f2937";
    const fontWeight = options.fontWeight ?? 900;
    const preferredDx = Math.cos(angle) * radius;
    const preferredDy = Math.sin(angle) * radius;
    const placed = placeScreenLabel(layout, centerScreen, text, {
      fontSize,
      preferredDx,
      preferredDy,
      candidates: options.candidates
    });
    const x = placed.x;
    const y = placed.y;
    return `<text x="${x}" y="${y}" text-anchor="middle" dominant-baseline="middle" font-size="${fontSize}" font-weight="${fontWeight}" fill="${color}">${escapeHtml(text)}</text>`;
  }

  function lineMidLabelSvg(layout, p1, p2, text, options){
    const fontSize = options.fontSize ?? 14;
    const color = options.color ?? "#1f2937";
    const fontWeight = options.fontWeight ?? 800;
    const dx = p2.x - p1.x;
    const dy = p2.y - p1.y;
    const len = Math.hypot(dx, dy) || 1;
    const tx = dx / len;
    const ty = dy / len;
    const nx = options.nx ?? (-ty);
    const ny = options.ny ?? tx;
    const extraX = options.extraX ?? 0;
    const extraY = options.extraY ?? 0;
    const extraNormal = options.extraNormal ?? 10;
    const extraAlong = options.extraAlong ?? 0;
    const midX = (p1.x + p2.x) / 2 + nx * extraNormal + tx * extraAlong + extraX;
    const midY = (p1.y + p2.y) / 2 + ny * extraNormal + ty * extraAlong + extraY;
    const width = estimateTextWidth(text, fontSize);
    const height = fontSize + 4;
    const bbox = makeRect(midX - width / 2, midY - fontSize / 2, width, height, 4);
    layout.occupied.push(bbox);
    const angle = options.rotateWithLine ? Math.atan2(dy, dx) * 180 / Math.PI : 0;
    const transform = options.rotateWithLine ? ` transform="rotate(${angle} ${midX} ${midY})"` : "";
    return `<text x="${midX}" y="${midY}" font-size="${fontSize}" font-weight="${fontWeight}" text-anchor="middle" dominant-baseline="middle" fill="${color}"${transform}>${escapeHtml(text)}</text>`;
  }

  function rightAngleGeometry(toScreen, vertex, rayA, rayB, size){
    const v = toScreen(vertex);
    const a = toScreen(rayA);
    const b = toScreen(rayB);
    const u = {x:a.x - v.x, y:a.y - v.y};
    const w = {x:b.x - v.x, y:b.y - v.y};
    const lu = Math.hypot(u.x, u.y);
    const lw = Math.hypot(w.x, w.y);
    if(lu < 1e-6 || lw < 1e-6) return null;
    const u1 = {x:u.x / lu, y:u.y / lu};
    const w1 = {x:w.x / lw, y:w.y / lw};
    const p1 = {x:v.x + u1.x * size, y:v.y + u1.y * size};
    const p2 = {x:v.x + w1.x * size, y:v.y + w1.y * size};
    const p3 = {x:p1.x + w1.x * size, y:p1.y + w1.y * size};
    return {v, p1, p2, p3};
  }

  function addRightAngleObstacle(layout, toScreen, vertex, rayA, rayB, options){
    if(!layout) return;
    const size = options?.size ?? 11;
    const padding = options?.padding ?? 6;
    const geometry = rightAngleGeometry(toScreen, vertex, rayA, rayB, size);
    if(!geometry) return;
    const corners = [geometry.v, geometry.p1, geometry.p2, geometry.p3];
    addRectObstacle(layout, {
      left: Math.min(...corners.map(p => p.x)) - padding,
      top: Math.min(...corners.map(p => p.y)) - padding,
      right: Math.max(...corners.map(p => p.x)) + padding,
      bottom: Math.max(...corners.map(p => p.y)) + padding,
      kind: "right-angle"
    });
  }

  function rightAngleSvg(layout, toScreen, vertex, rayA, rayB, options){
    const size = options?.size ?? 11;
    const color = options?.color ?? "#334155";
    const strokeWidth = options?.strokeWidth ?? 1.8;
    const geometry = rightAngleGeometry(toScreen, vertex, rayA, rayB, size);
    if(!geometry) return "";
    if(options?.registerObstacle !== false){
      addRightAngleObstacle(layout, toScreen, vertex, rayA, rayB, options);
    }
    return `<path d="M ${geometry.p1.x} ${geometry.p1.y} L ${geometry.p3.x} ${geometry.p3.y} L ${geometry.p2.x} ${geometry.p2.y}" fill="none" stroke="${color}" stroke-width="${strokeWidth}" />`;
  }

  function dimensionMidLabelSvg(layout, p1, p2, text, options){
    const fontSize = options.fontSize ?? 14;
    const color = options.color ?? "#1f2937";
    const fontWeight = options.fontWeight ?? 800;
    const dx = p2.x - p1.x;
    const dy = p2.y - p1.y;
    const len = Math.hypot(dx, dy) || 1;
    const tx = dx / len;
    const ty = dy / len;
    const nx = -ty;
    const ny = tx;
    const preferredNormal = options.extraNormal ?? 10;
    const preferredAlong = options.extraAlong ?? 0;
    const base = {
      x: (p1.x + p2.x) / 2 + (options.extraX ?? 0),
      y: (p1.y + p2.y) / 2 + (options.extraY ?? 0)
    };
    const candidates = options.candidates ?? [
      {dx: nx * preferredNormal + tx * preferredAlong, dy: ny * preferredNormal + ty * preferredAlong},
      {dx: nx * (preferredNormal + 16) + tx * preferredAlong, dy: ny * (preferredNormal + 16) + ty * preferredAlong},
      {dx: nx * (preferredNormal - 16) + tx * preferredAlong, dy: ny * (preferredNormal - 16) + ty * preferredAlong},
      {dx: -nx * preferredNormal + tx * preferredAlong, dy: -ny * preferredNormal + ty * preferredAlong},
      {dx: nx * preferredNormal + tx * (preferredAlong + 18), dy: ny * preferredNormal + ty * (preferredAlong + 18)},
      {dx: nx * preferredNormal + tx * (preferredAlong - 18), dy: ny * preferredNormal + ty * (preferredAlong - 18)}
    ];
    const placed = placeScreenLabel(layout, base, text, {
      fontSize,
      preferredDx: candidates[0].dx,
      preferredDy: candidates[0].dy,
      candidates
    });
    const angle = options.rotateWithLine ? Math.atan2(dy, dx) * 180 / Math.PI : 0;
    const transform = options.rotateWithLine ? ` transform="rotate(${angle} ${placed.x} ${placed.y})"` : "";
    return `<text x="${placed.x}" y="${placed.y}" font-size="${fontSize}" font-weight="${fontWeight}" text-anchor="middle" dominant-baseline="middle" fill="${color}"${transform}>${escapeHtml(text)}</text>`;
  }

  function chooseSegmentMeasureStrategy(meta){
    const role = meta?.segmentRole ?? "derived";
    const crowded = Boolean(meta?.crowded);
    const collinearGroup = Boolean(meta?.collinearGroup);
    const reusedInFormula = Boolean(meta?.reusedInFormula);
    const visuallyUnique = Boolean(meta?.visuallyUnique);
    const preferNamed = meta?.preferNamed ?? (reusedInFormula || collinearGroup || role === "derived");
    const showGuide = meta?.showGuide ?? (collinearGroup || crowded || role === "boundary");
    const rotateWithLine = meta?.rotateWithLine ?? !showGuide;

    let style = "inline";
    if(showGuide){
      style = "dimension";
    }else if(crowded || role === "helper"){
      style = "parallel";
    }else if(visuallyUnique){
      style = "inline";
    }else{
      style = "parallel";
    }

    return {
      style,
      showGuide,
      rotateWithLine,
      named: preferNamed
    };
  }

  function composeSegmentMeasureText(textOrValue, options){
    if(options?.text) return options.text;
    if(options?.named && options?.segmentName){
      return `${options.segmentName}=${textOrValue}`;
    }
    return textOrValue;
  }

  function segmentMeasureSvg(layout, toScreen, a, b, textOrValue, options){
    const strategy = {
      ...chooseSegmentMeasureStrategy(options),
      ...(options || {})
    };
    const text = composeSegmentMeasureText(textOrValue, strategy);
    const color = strategy.color ?? "#0f766e";
    const width = strategy.strokeWidth ?? 1.8;
    const dash = strategy.dash ?? "5 4";
    const tick = strategy.tickSize ?? 7;
    const p = toScreen(a);
    const q = toScreen(b);
    const dx = q.x - p.x;
    const dy = q.y - p.y;
    const len = Math.hypot(dx, dy);
    if(len < 1e-6) return "";
    const tx = dx / len;
    const ty = dy / len;
    const nx = -ty;
    const ny = tx;

    if(strategy.style === "dimension"){
      const offsetPx = strategy.offsetPx ?? 18;
      const p1 = {x:p.x + nx * offsetPx, y:p.y + ny * offsetPx};
      const p2 = {x:q.x + nx * offsetPx, y:q.y + ny * offsetPx};
      const label = dimensionMidLabelSvg(layout, p1, p2, text, {
        color,
        fontSize: strategy.fontSize ?? 14,
        fontWeight: strategy.fontWeight ?? 800,
        rotateWithLine: Boolean(strategy.rotateWithLine),
        extraNormal: strategy.extraNormal ?? 10,
        extraAlong: strategy.extraAlong ?? 0,
        extraX: strategy.extraX ?? 0,
        extraY: strategy.extraY ?? 0,
        candidates: strategy.candidates
      });
      return `<line x1="${p1.x}" y1="${p1.y}" x2="${p2.x}" y2="${p2.y}" stroke="${color}" stroke-width="${width}" stroke-dasharray="${dash}" />` +
        `<line x1="${p1.x-nx*tick}" y1="${p1.y-ny*tick}" x2="${p1.x+nx*tick}" y2="${p1.y+ny*tick}" stroke="${color}" stroke-width="${width}" />` +
        `<line x1="${p2.x-nx*tick}" y1="${p2.y-ny*tick}" x2="${p2.x+nx*tick}" y2="${p2.y+ny*tick}" stroke="${color}" stroke-width="${width}" />` +
        label;
    }

    const guide = strategy.showGuide
      ? `<line x1="${p.x}" y1="${p.y}" x2="${q.x}" y2="${q.y}" stroke="${color}" stroke-width="${strategy.guideWidth ?? 1.8}" stroke-dasharray="${dash}" />`
      : "";
    const label = lineMidLabelSvg(layout, p, q, text, {
      color,
      fontSize: strategy.fontSize ?? 14,
      fontWeight: strategy.fontWeight ?? 800,
      nx,
      ny,
      rotateWithLine: strategy.style !== "inline" || Boolean(strategy.rotateWithLine),
      extraNormal: strategy.extraNormal ?? (strategy.style === "inline" ? 10 : -12),
      extraAlong: strategy.extraAlong ?? 0,
      extraX: strategy.extraX ?? 0,
      extraY: strategy.extraY ?? 0
    });
    return guide + label;
  }

  function guideLineWithLabelSvg(layout, toScreen, a, b, text, options){
    const color = options?.color ?? "#64748b";
    const width = options?.width ?? 1.8;
    const dash = options?.dash ?? "6 5";
    const p = toScreen(a);
    const q = toScreen(b);
    addSegmentObstacle(layout, toScreen, a, b, {
      step: options?.obstacleStep ?? 22,
      radius: options?.obstacleRadius ?? 4,
      kind: "guide-line"
    });
    const anchor = options?.anchor ? toScreen(options.anchor) : {x:(p.x + q.x) / 2, y:(p.y + q.y) / 2};
    const fontSize = options?.fontSize ?? 14;
    const fontWeight = options?.fontWeight ?? 900;
    const placed = placeScreenLabel(layout, anchor, text, {
      fontSize,
      preferredDx: options?.preferredDx ?? 0,
      preferredDy: options?.preferredDy ?? -18,
      candidates: options?.candidates ?? [
        {dx:0, dy:-18},
        {dx:0, dy:18},
        {dx:46, dy:-18},
        {dx:46, dy:18},
        {dx:-46, dy:-18},
        {dx:-46, dy:18},
        {dx:84, dy:-22},
        {dx:-84, dy:-22}
      ]
    });
    return `<line x1="${p.x}" y1="${p.y}" x2="${q.x}" y2="${q.y}" stroke="${color}" stroke-width="${width}" stroke-dasharray="${dash}" />` +
      `<text x="${placed.x}" y="${placed.y}" font-size="${fontSize}" font-weight="${fontWeight}" text-anchor="middle" dominant-baseline="middle" fill="${color}">${escapeHtml(text)}</text>`;
  }

  global.GeometryLabelLayout = {
    createLabelLayout,
    addPointObstacle,
    addRectObstacle,
    addSegmentObstacle,
    pointsCoincident,
    mergeCoincidentLabel,
    candidateOffsets,
    labelSvg,
    placeScreenLabel,
    polarLabelSvg,
    lineMidLabelSvg,
    addRightAngleObstacle,
    rightAngleSvg,
    chooseSegmentMeasureStrategy,
    segmentMeasureSvg,
    guideLineWithLabelSvg,
    escapeHtml
  };
})(window);
