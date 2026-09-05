import fs from "node:fs";
import path from "node:path";

const OUT = path.resolve("site/assets/xiaohongshu/high-school-basic-inequality-methods-carousel");
const SRC = path.join(OUT, "source");
fs.mkdirSync(SRC, { recursive: true });

const C = {
  ink: "#083f46",
  teal: "#087d78",
  cyan: "#12a8c5",
  cyanSoft: "#e8f7f8",
  orange: "#ee8a00",
  orangeSoft: "#fff4df",
  coral: "#ee604d",
  mint: "#e8f4ee",
  green: "#14966f",
  ivory: "#fffdf7",
  paper: "#fbf8ef",
  line: "#bddad8",
  muted: "#547276",
  white: "#ffffff",
};

const esc = (s) => String(s)
  .replaceAll("&", "&amp;")
  .replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;");

const text = (x, y, value, size = 34, opts = {}) => {
  const { fill = C.ink, weight = 600, anchor = "start", family = "sans", opacity = 1, letter = 0 } = opts;
  const ff = family === "math" ? "'STIX Two Math','Times New Roman','Songti SC',serif" : "'PingFang SC','Noto Sans CJK SC','Microsoft YaHei',sans-serif";
  return `<text x="${x}" y="${y}" text-anchor="${anchor}" fill="${fill}" font-size="${size}" font-weight="${weight}" font-family="${ff}" opacity="${opacity}" letter-spacing="${letter}">${esc(value)}</text>`;
};

const lines = (x, y, arr, size = 34, gap = 1.42, opts = {}) => arr.map((v, i) => text(x, y + i * size * gap, v, size, opts)).join("");
const rect = (x, y, w, h, opts = {}) => `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${opts.r ?? 28}" fill="${opts.fill ?? C.white}" stroke="${opts.stroke ?? C.line}" stroke-width="${opts.sw ?? 2}"${opts.dash ? ` stroke-dasharray="${opts.dash}"` : ""}${opts.opacity != null ? ` opacity="${opts.opacity}"` : ""}/>`;
const pill = (x, y, w, h, label, opts = {}) => rect(x, y, w, h, { r: h / 2, fill: opts.fill ?? C.mint, stroke: opts.stroke ?? "none", sw: 0 }) + text(x + w / 2, y + h * 0.68, label, opts.size ?? 28, { anchor: "middle", fill: opts.color ?? C.ink, weight: 700 });
const arrowR = (x1, y, x2, color = C.coral, width = 5) => `<path d="M${x1} ${y} H${x2 - 18}" fill="none" stroke="${color}" stroke-width="${width}" stroke-linecap="round"/><path d="M${x2 - 24} ${y - 12} L${x2} ${y} L${x2 - 24} ${y + 12}" fill="none" stroke="${color}" stroke-width="${width}" stroke-linecap="round" stroke-linejoin="round"/>`;
const arrowD = (x, y1, y2, color = C.coral, width = 5) => `<path d="M${x} ${y1} V${y2 - 18}" fill="none" stroke="${color}" stroke-width="${width}" stroke-linecap="round"/><path d="M${x - 12} ${y2 - 24} L${x} ${y2} L${x + 12} ${y2 - 24}" fill="none" stroke="${color}" stroke-width="${width}" stroke-linecap="round" stroke-linejoin="round"/>`;
const slotSquare = (x, y, s = 92, color = C.cyan) => `<rect x="${x}" y="${y}" width="${s}" height="${s}" rx="16" fill="${C.ivory}" stroke="${color}" stroke-width="8"/>`;
const slotCircle = (cx, cy, r = 48, color = C.orange) => `<circle cx="${cx}" cy="${cy}" r="${r}" fill="${C.ivory}" stroke="${color}" stroke-width="8"/>`;
const check = (x, y, label, color = C.green) => `<path d="M${x} ${y} l18 18 34 -40" fill="none" stroke="${color}" stroke-width="9" stroke-linecap="round" stroke-linejoin="round"/>${text(x + 70, y + 12, label, 28, { fill: color, weight: 700 })}`;

function chrome(n, kicker, title, subtitle = "") {
  return `
    <g>
      ${pill(72, 64, 250, 58, kicker, { fill: C.mint, size: 26 })}
      ${pill(910, 70, 96, 48, String(n).padStart(2, "0"), { fill: "#ffd163", size: 24 })}
      ${text(72, 190, title, 66, { weight: 800 })}
      ${subtitle ? text(74, 248, subtitle, 30, { fill: C.muted, weight: 500 }) : ""}
    </g>`;
}

function footer(n, domain = false) {
  return `
    <g opacity="0.78">
      <line x1="72" y1="1360" x2="1008" y2="1360" stroke="${C.line}" stroke-width="2"/>
      ${text(76, 1402, domain ? "数学说 · shuxueshuo.com" : "数学说", 23, { fill: C.muted, weight: 600 })}
      ${text(1004, 1402, `${String(n).padStart(2, "0")} / 16`, 22, { fill: C.muted, anchor: "end", weight: 600 })}
    </g>`;
}

function svg(n, kicker, title, subtitle, body, opts = {}) {
  return `<svg xmlns="http://www.w3.org/2000/svg" width="1080" height="1440" viewBox="0 0 1080 1440">
  <defs>
    <pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse"><path d="M40 0H0V40" fill="none" stroke="#dce9e6" stroke-width="1" opacity="0.7"/></pattern>
    <filter id="shadow" x="-20%" y="-20%" width="140%" height="140%"><feDropShadow dx="0" dy="10" stdDeviation="14" flood-color="#174a4e" flood-opacity="0.10"/></filter>
    <linearGradient id="softMint" x1="0" x2="1"><stop offset="0" stop-color="#e8f6f4"/><stop offset="1" stop-color="#fff5e6"/></linearGradient>
  </defs>
  <rect width="1080" height="1440" fill="${C.paper}"/>
  <rect width="1080" height="1440" fill="url(#grid)" opacity="0.65"/>
  ${chrome(n, kicker, title, subtitle)}
  ${body}
  ${footer(n, opts.domain ?? false)}
</svg>`;
}

function problemBox(label, arr, y = 304, h = 190) {
  return `${rect(72, y, 936, h, { fill: "url(#softMint)", stroke: C.line, sw: 2, r: 30 })}
    ${pill(96, y + 24, 132, 48, label, { fill: C.ink, color: C.white, size: 24 })}
    ${lines(112, y + 104, arr, 36, 1.42, { weight: 650 })}`;
}

function stepCard(y, num, titleValue, formulaArr, accent = C.cyan) {
  const h = 190;
  return `${rect(92, y, 896, h, { fill: C.white, stroke: accent, sw: 3, r: 26 })}
    ${pill(112, y + 22, 70, 42, num, { fill: accent, color: C.white, size: 22 })}
    ${text(202, y + 55, titleValue, 30, { weight: 750 })}
    ${lines(132, y + 120, formulaArr, 34, 1.35, { family: "math", weight: 600 })}`;
}

const slides = [];

slides.push({ name: "01-cover", svg: svg(1, "高中数学 · 基本不等式", "高中应用基本不等式", "收藏这一篇就够了", `
  ${pill(72, 306, 418, 62, "6 种解法 · 先看结构再选方法", { fill: C.ivory, stroke: C.ink, size: 27 })}
  ${slotSquare(154, 444, 92)}${text(322, 520, "＋", 66, { anchor: "middle" })}${slotCircle(398, 490, 50)}
  ${text(510, 520, "≥", 66, { anchor: "middle", family: "math" })}${text(588, 520, "2", 62, { anchor: "middle", family: "math" })}${text(654, 536, "√", 94, { anchor: "middle", family: "math", weight: 500 })}
  <line x1="690" y1="454" x2="944" y2="454" stroke="${C.ink}" stroke-width="5"/>
  ${slotSquare(716, 470, 58)}${text(818, 518, "·", 48, { anchor: "middle", family: "math" })}${slotCircle(888, 500, 31)}
  ${rect(92, 666, 896, 430, { fill: C.white, stroke: C.line, sw: 2, r: 34 })}
  ${text(540, 740, "难点从来不是背公式", 43, { anchor: "middle", weight: 800 })}
  ${text(540, 804, "而是看见题目属于哪种结构", 43, { anchor: "middle", weight: 800, fill: C.coral })}
  ${pill(142, 884, 242, 64, "定和 / 定积", { fill: C.cyanSoft, size: 28 })}
  ${pill(419, 884, 242, 64, "对称 / 齐次", { fill: C.orangeSoft, size: 28 })}
  ${pill(696, 884, 242, 64, "多轮 / 改写", { fill: C.mint, size: 28 })}
  ${text(540, 1036, "从识别信号，到取等验证", 32, { anchor: "middle", fill: C.muted, weight: 600 })}
  ${pill(310, 1160, 460, 78, "一套可以反复套用的解题路径", { fill: C.ink, color: C.white, size: 29 })}
`) });

slides.push({ name: "02-three-conditions", svg: svg(2, "先过三关", "基本不等式为什么会失分？", "漏掉任何一关，得到的都可能不是真正最值", `
  ${rect(72, 306, 936, 222, { fill: C.white, stroke: C.line, sw: 2, r: 32 })}
  ${slotSquare(154, 329, 74)}${text(281, 386, "＋", 56, { anchor: "middle" })}${slotCircle(354, 367, 40)}
  ${text(448, 386, "≥", 58, { anchor: "middle", family: "math" })}${text(518, 386, "2", 54, { anchor: "middle", family: "math" })}${text(578, 400, "√", 82, { anchor: "middle", family: "math", weight: 500 })}
  <line x1="610" y1="332" x2="900" y2="332" stroke="${C.ink}" stroke-width="5"/>
  ${slotSquare(646, 346, 50)}${text(756, 382, "·", 44, { anchor: "middle", family: "math" })}${slotCircle(836, 367, 27)}
  ${text(540, 478, "它给出一个边界，但边界不一定取得到", 28, { anchor: "middle", fill: C.muted })}
  ${rect(72, 574, 286, 500, { fill: C.cyanSoft, stroke: C.cyan, sw: 3, r: 30 })}
  ${pill(103, 604, 76, 50, "一", { fill: C.cyan, color: C.white, size: 25 })}
  ${text(215, 650, "正", 54, { anchor: "middle", weight: 800 })}
  ${text(215, 715, "两个完整项", 30, { anchor: "middle", weight: 700 })}
  ${text(215, 760, "都必须大于 0", 30, { anchor: "middle", weight: 700 })}
  ${pill(112, 828, 206, 58, "✓ 定义域要先看", { fill: C.white, stroke: C.green, size: 23, color: C.green })}
  ${rect(397, 574, 286, 500, { fill: C.orangeSoft, stroke: C.orange, sw: 3, r: 30 })}
  ${pill(428, 604, 76, 50, "二", { fill: C.orange, color: C.white, size: 25 })}
  ${text(540, 650, "定", 54, { anchor: "middle", weight: 800 })}
  ${text(540, 715, "和或积中", 30, { anchor: "middle", weight: 700 })}
  ${text(540, 760, "必须有一个定值", 30, { anchor: "middle", weight: 700 })}
  ${pill(437, 828, 206, 58, "✓ 方向才确定", { fill: C.white, stroke: C.green, size: 23, color: C.green })}
  ${rect(722, 574, 286, 500, { fill: C.mint, stroke: C.green, sw: 3, r: 30 })}
  ${pill(753, 604, 76, 50, "三", { fill: C.green, color: C.white, size: 25 })}
  ${text(865, 650, "相等", 54, { anchor: "middle", weight: 800 })}
  ${text(865, 715, "取等条件", 30, { anchor: "middle", weight: 700 })}
  ${text(865, 760, "必须能同时成立", 30, { anchor: "middle", weight: 700 })}
  ${pill(762, 828, 206, 58, "✓ 回到原条件", { fill: C.white, stroke: C.green, size: 23, color: C.green })}
  ${pill(180, 1148, 720, 78, "一正 · 二定 · 三相等", { fill: C.ink, color: C.white, size: 36 })}
`) });

slides.push({ name: "03-method-map", svg: svg(3, "先选入口", "看到什么结构，就选什么方法", "四个直接入口 + 两个改写入口", `
  ${rect(72, 306, 936, 760, { fill: C.white, stroke: C.line, sw: 2, r: 34 })}
  ${pill(105, 336, 212, 52, "四个直接入口", { fill: C.ink, color: C.white, size: 24 })}
  ${rect(105, 420, 398, 132, { fill: C.cyanSoft, stroke: C.cyan, sw: 3, r: 24 })}
  ${text(136, 466, "定和 / 定积", 29, { weight: 800 })}${text(136, 516, "直接应用基本不等式", 33, { weight: 750 })}
  ${rect(577, 420, 398, 132, { fill: C.orangeSoft, stroke: C.orange, sw: 3, r: 24 })}
  ${text(608, 466, "整式 × 分式 → 0 次", 29, { weight: 800 })}${text(608, 516, "配齐次式", 33, { weight: 750 })}
  ${rect(105, 588, 398, 132, { fill: C.cyanSoft, stroke: C.cyan, sw: 3, r: 24 })}
  ${text(136, 634, "交换变量后不变", 29, { weight: 800 })}${text(136, 684, "找对称结构", 33, { weight: 750 })}
  ${rect(577, 588, 398, 132, { fill: C.orangeSoft, stroke: C.orange, sw: 3, r: 24 })}
  ${text(608, 634, "变量多、需要逐轮消去", 29, { weight: 800 })}${text(608, 684, "多次应用基本不等式", 33, { weight: 750 })}
  ${pill(105, 772, 212, 52, "结构被挡住", { fill: C.coral, color: C.white, size: 24 })}
  ${rect(105, 854, 398, 132, { fill: C.ivory, stroke: C.coral, sw: 3, r: 24 })}
  ${text(136, 900, "完整分母 / 根号整体", 29, { weight: 800 })}${text(136, 950, "换元法", 33, { weight: 750 })}
  ${rect(577, 854, 398, 132, { fill: C.ivory, stroke: C.muted, sw: 3, r: 24 })}
  ${text(608, 900, "条件能表示一个变量", 29, { weight: 800 })}${text(608, 950, "条件消元法", 33, { weight: 750 })}
  ${pill(178, 1142, 724, 80, "先观察结构，再决定第一步", { fill: C.ink, color: C.white, size: 34 })}
`) });

slides.push({ name: "04-direct-core", svg: svg(4, "方法 1 · 核心意义", "直接应用基本不等式", "比较的不是两个字母，而是两个完整的正项", `
  ${rect(72, 314, 936, 746, { fill: C.white, stroke: C.cyan, sw: 3, r: 34 })}
  ${text(540, 402, "任意两个完整正项", 36, { anchor: "middle", weight: 800, fill: C.coral })}
  ${rect(122, 458, 380, 82, { fill: C.cyanSoft, stroke: C.cyan, sw: 2, r: 20 })}${text(312, 510, "正变量 · 正常数", 29, { anchor: "middle" })}
  ${rect(578, 458, 380, 82, { fill: C.orangeSoft, stroke: C.orange, sw: 2, r: 20 })}${text(768, 510, "完整表达式 · 函数值", 29, { anchor: "middle" })}
  ${arrowD(312, 548, 652, C.cyan)}${arrowD(768, 548, 652, C.orange)}
  ${slotSquare(230, 662, 126)}${text(401, 756, "＋", 66, { anchor: "middle" })}${slotCircle(540, 725, 68)}
  ${text(670, 756, "≥  2√", 68, { family: "math", weight: 700 })}<line x1="810" y1="681" x2="997" y2="681" stroke="${C.ink}" stroke-width="5"/>${slotSquare(820, 704, 62)}${text(900, 756, "·", 52, { anchor: "middle" })}${slotCircle(955, 735, 33)}
  ${rect(198, 882, 684, 112, { fill: C.ivory, stroke: C.orange, sw: 2, r: 28 })}
  ${text(446, 952, "取等  ⇔", 42, { anchor: "middle", weight: 800 })}${slotSquare(548, 914, 42)}${text(636, 950, "＝", 38, { anchor: "middle" })}${slotCircle(706, 935, 23)}
  ${pill(194, 1130, 692, 76, "识别正项 → 代入图形 → 验证取等", { fill: C.ink, color: C.white, size: 31 })}
`) });

slides.push({ name: "05-direct-example", svg: svg(5, "方法 1 · HOW + 示例", "目标已露出两个正项，直接代入", "例：已知 m,n＞0，m+n=2，求 mn 的最大值", `
  ${problemBox("定和", ["m＞0，n＞0，m+n=2", "目标：mn 的最大值"], 304, 184)}
  ${stepCard(534, "01", "识别两个完整正项", ["□ ← m        ○ ← n"], C.cyan)}
  ${stepCard(758, "02", "代入基本不等式", ["(m+n)/2 ≥ √(mn)", "m+n=2  ⇒  1 ≥ √(mn)  ⇒  mn ≤ 1"], C.orange)}
  ${stepCard(982, "03", "验证取等", ["m=n 且 m+n=2", "所以 m=n=1，最大值为 1"], C.green)}
`) });

slides.push({ name: "06-homogeneous-core", svg: svg(6, "方法 2 · 核心意义", "配齐次式", "把目标整式总次数配成 0", `
  ${rect(72, 314, 936, 754, { fill: C.white, stroke: C.orange, sw: 3, r: 34 })}
  ${text(250, 420, "原有整式", 27, { anchor: "middle", fill: C.muted })}${text(250, 468, "x+y", 42, { anchor: "middle", family: "math" })}
  ${text(540, 420, "乘入定值", 27, { anchor: "middle", fill: C.muted })}${text(540, 468, "1/x + 1/y = 1", 37, { anchor: "middle", family: "math" })}
  ${arrowD(250, 492, 574, C.cyan)}${arrowD(540, 492, 574, C.orange)}
  ${rect(132, 590, 238, 146, { fill: C.cyanSoft, stroke: C.cyan, sw: 6, r: 24 })}${text(368, 596, "m", 42, { anchor: "end", family: "math", weight: 700 })}
  ${text(420, 682, "×", 50, { anchor: "middle" })}
  ${rect(470, 590, 238, 146, { fill: C.orangeSoft, stroke: C.orange, sw: 6, r: 24 })}${text(706, 596, "n", 42, { anchor: "end", family: "math", weight: 700 })}
  ${text(754, 682, "＝", 48, { anchor: "middle" })}
  ${rect(800, 590, 150, 146, { fill: C.mint, stroke: C.teal, sw: 6, r: 24 })}${text(948, 596, "0", 42, { anchor: "end", family: "math", weight: 700 })}
  ${text(420, 790, "m + n = 0", 38, { anchor: "middle", family: "math", weight: 700 })}
  ${arrowD(540, 820, 912, C.teal)}
  ${pill(204, 932, 672, 76, "只研究变量比值 · 比值乘积是定值", { fill: C.ink, color: C.white, size: 30 })}
  ${pill(188, 1146, 704, 76, "先配次数 → 展开圈出正项 → 找定积", { fill: C.orangeSoft, stroke: C.orange, size: 31 })}
`) });

slides.push({ name: "07-homogeneous-example", svg: svg(7, "方法 2 · HOW + 示例", "整式 × 分式，配成 0 次", "例：x,y＞0，1/x+1/y=1，求 x+4y 的最小值", `
  ${problemBox("结构", ["目标 x+4y：1 次", "条件 1/x+1/y=1：−1 次"], 304, 184)}
  ${stepCard(534, "01", "配次数：1+(−1)=0", ["(x+4y)(1/x+1/y) = x+4y"], C.cyan)}
  ${stepCard(758, "02", "展开，圈出定积", ["x+4y = 5 + x/y + 4y/x", "(x/y)·(4y/x)=4"], C.orange)}
  ${stepCard(982, "03", "应用基本不等式并验等", ["x/y + 4y/x ≥ 4  ⇒  x+4y ≥ 9", "取等 x=2y；代入条件得 x=3，y=3/2"], C.green)}
`) });

slides.push({ name: "08-symmetric-core", svg: svg(8, "方法 3 · 核心意义", "找对称结构", "交换 x、y 后原式不变", `
  ${rect(72, 314, 936, 754, { fill: C.white, stroke: C.cyan, sw: 3, r: 34 })}
  ${pill(374, 360, 332, 86, "交换变量  x ↔ y", { fill: C.ivory, stroke: C.ink, size: 36 })}
  ${arrowD(540, 456, 538, C.coral)}
  ${rect(118, 566, 346, 142, { fill: C.cyanSoft, stroke: C.cyan, sw: 4, r: 24 })}${text(291, 651, "原式", 40, { anchor: "middle", weight: 800 })}
  ${text(540, 652, "＝", 50, { anchor: "middle" })}
  ${rect(616, 566, 346, 142, { fill: C.orangeSoft, stroke: C.orange, sw: 4, r: 24 })}${text(789, 651, "交换后的式子", 34, { anchor: "middle", weight: 800 })}
  ${arrowD(540, 730, 810, C.coral)}
  ${pill(350, 828, 380, 76, "对称结构", { fill: C.teal, color: C.white, size: 38 })}
  ${text(540, 982, "最基本的对称结构", 28, { anchor: "middle", fill: C.muted })}
  ${pill(174, 1012, 326, 80, "和  s=x+y", { fill: C.cyanSoft, stroke: C.cyan, size: 33 })}
  ${pill(580, 1012, 326, 80, "积  p=xy", { fill: C.orangeSoft, stroke: C.orange, size: 33 })}
  ${pill(192, 1160, 696, 76, "和积换元 → 用 s²≥4p 消元", { fill: C.ink, color: C.white, size: 31 })}
`) });

slides.push({ name: "09-symmetric-example", svg: svg(9, "方法 3 · HOW + 示例", "先交换检验，再用和与积改写", "例：x²+y²−xy=1，求 x+y 的取值范围", `
  ${problemBox("检验", ["目标 x+y：交换 x、y 后不变", "条件 x²+y²−xy=1：交换后也不变"], 304, 190)}
  ${stepCard(540, "01", "和与积换元", ["令 s=x+y，p=xy", "x²+y²−xy = s²−3p = 1"], C.cyan)}
  ${stepCard(764, "02", "用基本不等式消去 p", ["p=(s²−1)/3，且 s²≥4p", "s² ≥ 4(s²−1)/3  ⇒  s²≤4"], C.orange)}
  ${stepCard(988, "03", "求边界并验证取等", ["−2≤s≤2", "s=±2 时 x=y=±1，两个边界均能取到"], C.green)}
`) });

slides.push({ name: "10-repeated-core", svg: svg(10, "方法 4 · 核心意义", "多次应用基本不等式", "先判断大约需要应用几次", `
  ${rect(72, 314, 936, 754, { fill: C.white, stroke: C.orange, sw: 3, r: 34 })}
  ${text(540, 390, "先判断还缺几条取等关系", 36, { anchor: "middle", weight: 800 })}
  ${rect(120, 456, 250, 170, { fill: C.cyanSoft, stroke: C.cyan, sw: 3, r: 26 })}${text(245, 510, "变量数", 28, { anchor: "middle" })}${text(245, 582, "n", 58, { anchor: "middle", family: "math" })}
  ${text(416, 552, "−", 54, { anchor: "middle" })}
  ${rect(460, 456, 250, 170, { fill: C.orangeSoft, stroke: C.orange, sw: 3, r: 26 })}${text(585, 510, "已有取等条件数", 25, { anchor: "middle" })}${text(585, 582, "k", 58, { anchor: "middle", family: "math" })}
  ${text(756, 552, "＝", 50, { anchor: "middle" })}
  ${rect(800, 456, 160, 170, { fill: C.mint, stroke: C.green, sw: 3, r: 26 })}${text(880, 510, "预计次数", 25, { anchor: "middle" })}${text(880, 582, "n−k", 48, { anchor: "middle", family: "math" })}
  ${arrowD(540, 660, 766, C.coral)}
  ${rect(126, 794, 210, 120, { fill: C.cyanSoft, stroke: C.cyan, sw: 2, r: 22 })}${text(231, 842, "选一组正项", 26, { anchor: "middle" })}${text(231, 884, "消去一个变量", 26, { anchor: "middle", weight: 800 })}
  ${arrowR(350, 854, 430)}
  ${rect(435, 794, 210, 120, { fill: C.orangeSoft, stroke: C.orange, sw: 2, r: 22 })}${text(540, 842, "整理新式", 26, { anchor: "middle" })}${text(540, 884, "继续配对", 26, { anchor: "middle", weight: 800 })}
  ${arrowR(659, 854, 739)}
  ${rect(744, 794, 210, 120, { fill: C.mint, stroke: C.green, sw: 2, r: 22 })}${text(849, 842, "最后联立", 26, { anchor: "middle" })}${text(849, 884, "全部取等条件", 26, { anchor: "middle", weight: 800 })}
  ${pill(196, 1150, 688, 76, "判断次数 → 逐轮消元 → 联立取等", { fill: C.ink, color: C.white, size: 31 })}
`) });

slides.push({ name: "11-repeated-example", svg: svg(11, "方法 4 · HOW + 示例", "两轮基本不等式，逐次消元", "例：a,b＞0，求 1/a+a/b²+b 的最小值", `
  ${problemBox("判断", ["2 个变量，0 个已有取等条件", "预计应用 2 次基本不等式"], 304, 184)}
  ${stepCard(534, "第 1 轮", "先配前两项，消去 a", ["1/a + a/b² ≥ 2/b", "取等：1/a = a/b²  ⇒  a=b"], C.cyan)}
  ${stepCard(758, "第 2 轮", "再处理只含 b 的式子", ["2/b + b ≥ 2√2", "取等：2/b=b  ⇒  b=√2"], C.orange)}
  ${stepCard(982, "联立", "两轮取等必须同时成立", ["a=b=√2", "所以原式最小值为 2√2"], C.green)}
`) });

slides.push({ name: "12-substitution-core", svg: svg(12, "方法 5 · 核心意义", "换元法", "完整结构整体换元，并同步改写条件整式与目标整式", `
  ${rect(72, 314, 936, 754, { fill: C.white, stroke: C.cyan, sw: 3, r: 34 })}
  ${text(316, 412, "完整分母", 28, { anchor: "middle", weight: 800 })}
  ${text(316, 492, "1", 42, { anchor: "middle", family: "math" })}<line x1="250" y1="512" x2="382" y2="512" stroke="${C.ink}" stroke-width="4"/>${rect(250, 526, 132, 76, { fill: C.cyanSoft, stroke: C.cyan, sw: 4, r: 16 })}
  ${text(764, 412, "根号整体", 28, { anchor: "middle", weight: 800 })}
  ${text(686, 566, "√", 92, { family: "math", weight: 500 })}<line x1="744" y1="492" x2="876" y2="492" stroke="${C.ink}" stroke-width="4"/>${rect(744, 504, 132, 76, { fill: C.orangeSoft, stroke: C.orange, sw: 4, r: 16 })}
  ${arrowD(316, 626, 720, C.cyan)}${arrowD(764, 606, 720, C.orange)}
  ${text(312, 796, "令  u ＝", 52, { anchor: "end", family: "math", weight: 700 })}${rect(336, 718, 408, 120, { fill: C.ivory, stroke: C.cyan, sw: 5, r: 24 })}
  ${text(540, 894, "把题目中的完整结构放入方框", 28, { anchor: "middle", fill: C.muted })}
  <line x1="130" y1="948" x2="950" y2="948" stroke="${C.line}" stroke-width="2"/>
  ${text(156, 1008, "条件整式： … □ …", 30, { weight: 700 })}${text(156, 1060, "目标整式： … □ …", 30, { weight: 700 })}
  ${arrowR(444, 1030, 614, C.teal)}
  ${text(642, 1008, "条件整式： … u …", 30, { weight: 700 })}${text(642, 1060, "目标整式： … u …", 30, { weight: 700 })}
  ${pill(202, 1160, 676, 76, "整体换元 → 全部替换 → 再观察结构", { fill: C.ink, color: C.white, size: 30 })}
`) });

slides.push({ name: "13-substitution-example", svg: svg(13, "方法 5 · HOW + 示例", "分母整体换元后，齐次结构显形", "例：x+y=2，求 1/(x+1)+1/(y+2) 的最小值", `
  ${problemBox("定义域", ["x＞−1，y＞−2", "令 u=x+1＞0，v=y+2＞0"], 304, 184)}
  ${stepCard(534, "01", "同步改写条件与目标", ["x+y=2  ⇒  u+v=5", "目标：1/u + 1/v"], C.cyan)}
  ${stepCard(758, "02", "发现齐次结构，乘入定和", ["5(1/u+1/v)=(u+v)(1/u+1/v)", "=2+u/v+v/u ≥ 4"], C.orange)}
  ${stepCard(982, "03", "还原等号", ["u=v=5/2", "x=3/2，y=1/2；最小值为 4/5"], C.green)}
`) });

slides.push({ name: "14-elimination-core", svg: svg(14, "方法 6 · 核心意义", "条件消元法", "条件能表示一个变量，就代入目标消去它", `
  ${rect(72, 314, 936, 754, { fill: C.white, stroke: C.cyan, sw: 3, r: 34 })}
  ${text(540, 396, "由条件整式表示变量", 32, { anchor: "middle", weight: 800 })}
  ${text(326, 520, "y ＝", 62, { anchor: "end", family: "math", weight: 700 })}${rect(350, 438, 404, 124, { fill: C.cyanSoft, stroke: C.cyan, sw: 5, r: 24 })}
  ${text(552, 610, "只含 x 的式子", 28, { anchor: "middle", fill: C.muted })}
  ${arrowD(540, 638, 742, C.coral)}
  ${rect(112, 770, 330, 128, { fill: C.ivory, stroke: C.orange, sw: 3, r: 24 })}${text(277, 818, "目标整式", 27, { anchor: "middle", fill: C.muted })}${text(277, 864, "… x … y …", 40, { anchor: "middle", family: "math" })}
  ${arrowR(464, 834, 616, C.coral)}${text(540, 804, "代入", 25, { anchor: "middle", fill: C.coral })}
  ${rect(638, 770, 330, 128, { fill: C.mint, stroke: C.green, sw: 3, r: 24 })}${text(803, 818, "一元式", 27, { anchor: "middle", fill: C.muted })}${text(803, 864, "… x …", 40, { anchor: "middle", family: "math" })}
  ${pill(208, 984, 664, 76, "目标整式降成只含一个变量", { fill: C.ink, color: C.white, size: 32 })}
  ${pill(214, 1160, 652, 76, "整理条件 → 表示代入 → 回代验等", { fill: C.cyanSoft, stroke: C.cyan, size: 31 })}
`) });

slides.push({ name: "15-elimination-example", svg: svg(15, "方法 6 · HOW + 示例", "先由条件表示 y，再代入目标", "例：x,y＞0，1/(x+1)+1/(x+2y)=1", `
  ${problemBox("目标", ["求 2x+y 的最小值", "条件经通分可表示 y"], 304, 184)}
  ${stepCard(534, "01", "整理条件并表示 y", ["x(x+2y−1)=1", "y=(1+1/x−x)/2"], C.cyan)}
  ${stepCard(758, "02", "代入目标，降成一元式", ["2x+y = (3x+1/x+1)/2", "3x+1/x ≥ 2√3"], C.orange)}
  ${stepCard(982, "03", "回代验证取等", ["3x=1/x  ⇒  x=1/√3", "y=1/2+1/√3；最小值为 √3+1/2"], C.green)}
`) });

slides.push({ name: "16-transfer", svg: svg(16, "最后一题 · 不揭晓答案", "先判断方法，再选出最小值", "把方法真正变成自己的判断", `
  ${problemBox("挑战", ["已知 a,b＞0，a+b=1", "求 a²/(a+1)+b²/(b+1) 的最小值"], 304, 214)}
  ${rect(92, 570, 420, 112, { fill: C.white, stroke: C.line, sw: 2, r: 24 })}${text(302, 640, "A   1/4", 38, { anchor: "middle", family: "math" })}
  ${rect(568, 570, 420, 112, { fill: C.white, stroke: C.line, sw: 2, r: 24 })}${text(778, 640, "B   1/3", 38, { anchor: "middle", family: "math" })}
  ${rect(92, 718, 420, 112, { fill: C.white, stroke: C.line, sw: 2, r: 24 })}${text(302, 788, "C   1/2", 38, { anchor: "middle", family: "math" })}
  ${rect(568, 718, 420, 112, { fill: C.white, stroke: C.line, sw: 2, r: 24 })}${text(778, 788, "D   2/3", 38, { anchor: "middle", family: "math" })}
  ${text(540, 924, "先写下你的答案，再看完整解析", 34, { anchor: "middle", weight: 750 })}
  ${rect(72, 1000, 936, 210, { fill: C.teal, stroke: C.ink, sw: 3, r: 34 })}
  ${text(540, 1084, "访问 shuxueshuo.com", 48, { anchor: "middle", fill: C.white, weight: 800 })}
  ${text(540, 1140, "查看结构识别、完整推导与互动讲解", 29, { anchor: "middle", fill: C.white, weight: 600 })}
  ${pill(314, 1262, 452, 62, "数学说 · 更懂你的学习路径", { fill: C.orangeSoft, stroke: C.orange, size: 27 })}
`, { domain: true }) });

for (const slide of slides) {
  fs.writeFileSync(path.join(SRC, `${slide.name}.svg`), slide.svg);
}

const manifest = {
  postType: "解题方法型",
  title: "高中应用基本不等式｜收藏这一篇就够了",
  slides: slides.map((slide) => ({ png: `${slide.name}.png`, mode: "svg", source: `${slide.name}.svg` })),
  unansweredSlides: ["16-transfer.png"],
  branding: {
    everySlide: "数学说",
    domainOnly: ["16-transfer.png"],
  },
};
fs.writeFileSync(path.join(SRC, "slide-manifest.json"), `${JSON.stringify(manifest, null, 2)}\n`);

const postCopy = `# 小红书发布文案

## 推荐标题

高中应用基本不等式｜收藏这一篇就够了

## 备选标题

1. 基本不等式会背却不会用？先看懂这 6 种结构
2. 高中数学｜基本不等式最值题，先选方法再计算
3. 一正二定三相等之后，基本不等式到底怎么选方法？

## 正文

基本不等式难的往往不是公式，而是看到题目后，不知道第一步该做什么。
这组图把常见题目按“结构入口”拆成 6 种方法：看见什么结构，就知道下一步往哪里走。

1. 定和或定积已经显露：直接应用基本不等式。
2. 对称、齐次或多变量：分别用和积换元、配 0 次与逐轮消元。
3. 结构被复杂分母或条件挡住：先换元，或用条件消去一个变量。

最后一张先别急着看答案，先判断它属于哪种结构，再写下最小值。

访问 shuxueshuo.com，查看结构识别、完整推导与互动讲解。

## 话题

#高中数学 #高一数学 #基本不等式 #最值问题 #数学解题方法 #数学可视化 #数学学习

## 图片清单

1. \`01-cover.png\` — 总标题与“先看结构”的承诺
2. \`02-three-conditions.png\` — 一正、二定、三相等
3. \`03-method-map.png\` — 六种方法入口图
4. \`04-direct-core.png\` — 直接应用：核心意义
5. \`05-direct-example.png\` — 直接应用：HOW + 示例
6. \`06-homogeneous-core.png\` — 配齐次式：核心意义
7. \`07-homogeneous-example.png\` — 配齐次式：HOW + 示例
8. \`08-symmetric-core.png\` — 找对称结构：核心意义
9. \`09-symmetric-example.png\` — 找对称结构：HOW + 示例
10. \`10-repeated-core.png\` — 多次应用：核心意义
11. \`11-repeated-example.png\` — 多次应用：HOW + 示例
12. \`12-substitution-core.png\` — 换元法：核心意义
13. \`13-substitution-example.png\` — 换元法：HOW + 示例
14. \`14-elimination-core.png\` — 条件消元法：核心意义
15. \`15-elimination-example.png\` — 条件消元法：HOW + 示例
16. \`16-transfer.png\` — 未揭晓迁移题与网站承接

## 生成说明

- 内容类型：解题方法型长图合集
- 渲染模式：16 页均为 SVG
- 画布：1080×1440 PNG
- 品牌策略：每页仅保留“数学说”；只在最后一页出现 shuxueshuo.com
- SVG 源文件：\`source/slide-manifest.json\`
- 最后一页故意不揭晓答案
`;
fs.writeFileSync(path.join(OUT, "post-copy.md"), postCopy);

console.log(`Generated ${slides.length} SVG slides in ${OUT}`);
