import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const specsRoot = path.join(repoRoot, "internal/senior-high/lesson-specs");

const meta = (id, title, breadcrumb) => ({
  id,
  outputPath: `site/problems/senior-high/inequalities/inequality-relations/${id}.html`,
  pageTitle: title,
  pageDescription: `${title}的逐步解析。`,
  breadcrumbTitle: `解不等式 · ${breadcrumb}`,
  breadcrumbLabel: "解不等式与基本不等式",
  breadcrumbPath: "site/senior-high/index.html",
  breadcrumbSearch: "?chapter=inequalities&section=inequality-relations&module=solving-inequalities",
});

const problem = (lines, items) => ({
  source: "高一暑假目标班 · 第4讲",
  keyPoints: {
    title: "解题要点",
    lead: "先化为标准形式，再用根、禁值点或分类断点划分区间。",
    items,
  },
  lines: lines.map((text) => ({ text })),
});

const chart = (title, columns, rows, solution, notes, caption = "符号表把每个区间上的符号变化与最终解集对应起来。") => ({
  kind: "inequality-sign-chart",
  title,
  columns,
  rows,
  solution,
  notes,
  caption,
});

const step = (id, section, title, visual, reasoning, derive, table) => {
  const completeReasoning = reasoning.length >= 2
    ? reasoning
    : [["because", "先依据等价变形、分界点与各区间符号完成判断"], ...reasoning];
  return {
    id, section, title, t: 0, showDiagram: false,
    ...(table ? { table } : {}),
    ...(visual ? { visual } : {}),
    reasoning: completeReasoning.map(([kind, text]) => ({ kind, text })),
    derive,
  };
};

const single = (id, title, breadcrumb, lines, keyItems, answer, lessonStep) => ({
  meta: meta(id, title, breadcrumb),
  problem: problem(lines, keyItems),
  steps: [lessonStep],
  policies: { s1: { movable: false, range: [0, 0] } },
  stepLabels: { s1: "1 化标准式并判断符号" },
});

const lessons = [
  single(
    "inequality-solving-quadratic-q01", "由必要条件反查二次不等式解集", "练习 4-1",
    ["不等式 \\(2x^2-5x-3<0\\) 的一个必要不充分条件是（　　）", "A. \\(-3<x<\\frac12\\)　B. \\(-1<x<6\\)　C. \\(-\\frac12<x<0\\)　D. \\(-\\frac12<x<3\\)"],
    ["先求原不等式的完整解集。", "必要条件对应原解集的真超集。"], "D",
    step("s1", "一元二次不等式", "因式分解并比较集合包含",
      chart("二次不等式符号表", ["区间", "(-∞,-1/2)", "-1/2", "(-1/2,3)", "3", "(3,+∞)"], [{ label: "(2x+1)(x-3)", values: ["+", "0", "−", "0", "+"], selectedIndices: [2] }], "原解集：(-1/2,3)", ["开口向上，两个根之间为负。", "选项 D 的区间真包含原解集，因此是必要不充分条件。"]),
      [["because", "\\(2x^2-5x-3=(2x+1)(x-3)\\)"], ["therefore", "原解集为 \\((-\\frac12,3)\\)，选择 D"]], [["答案", "D"]]),
  ),
  single(
    "inequality-solving-quadratic-q02", "判断恒无解的二次不等式", "练习 4-2",
    ["一元二次不等式 \\(-x^2+2x-3>0\\) 的解集是（　　）", "A. \\(\\varnothing\\)　B. \\((-3,1)\\)　C. \\((-1,3)\\)　D. \\((-3,-1)\\)"],
    ["先配方判断二次式的最大值。", "整个二次式恒小于 0。"], "A",
    step("s1", "一元二次不等式", "配方判断整段符号", null,
      [["because", "\\(-x^2+2x-3=-(x-1)^2-2<0\\) 对任意实数 x 成立"], ["therefore", "不可能大于 0，解集为空集"]], [["答案", "A（空集）"]], { headers: ["二次式", "最大值", "与 0 的关系"], rows: [["−(x−1)²−2", "−2", "恒小于 0"]] }),
  ),
  {
    meta: meta("inequality-solving-quadratic-q03", "求四个一元二次不等式的解集", "练习 4-3"),
    problem: problem(["求下列不等式的解集：", "（1）\\(x^2-5x+6\\le 0\\)；（2）\\(-2x^2+5x-3\\le0\\)；", "（3）\\(x^2-6x+9>0\\)；（4）\\(x^2+x+1>0\\)。"], ["优先因式分解；不能分解时看判别式。", "严格不等式不取等号点。"]),
    steps: [step("s1", "一元二次不等式", "分别判断根与开口方向",
      chart("四个二次不等式的结论", ["题号", "标准形式", "根或判别式", "解集"], [
        { label: "（1）", values: ["(x−2)(x−3)≤0", "2，3", "[2,3]"], selectedIndices: [2] },
        { label: "（2）", values: ["−(2x−3)(x−1)≤0", "1，3/2", "(−∞,1]∪[3/2,+∞)"], selectedIndices: [2] },
        { label: "（3）", values: ["(x−3)²>0", "重根 3", "ℝ∖{3}"], selectedIndices: [2] },
        { label: "（4）", values: ["x²+x+1>0", "Δ=−3<0", "ℝ"], selectedIndices: [2] },
      ], "答案见各行", ["重根处两侧不变号。", "开口向上且 Δ<0 时二次式恒正。"]),
      [["because", "根把数轴分区间，开口方向决定正负区域"], ["therefore", "逐题按端点是否取等号写出解集"]], [["（1）", "[2,3]"], ["（2）", "(−∞,1]∪[3/2,+∞)"], ["（3）", "ℝ∖{3}"], ["（4）", "ℝ"]])],
    policies: { s1: { movable: false, range: [0, 0] } }, stepLabels: { s1: "1 分解并判断各区间符号" },
  },
  {
    meta: meta("inequality-solving-polynomial-q01", "用穿针引线法解三个高次不等式", "练习 5-1"),
    problem: problem(["求下列不等式：", "（1）\\((x-1)(x-2)(x-3)>0\\)；", "（2）\\((x-1)(x+2)(3-x)>0\\)；", "（3）\\((x-2)(x+3)(x^2-2x+1)>0\\)。"], ["先把各因式最高次项系数化为正。", "奇数重根变号，偶数重根不变号。"]),
    steps: [
      step("s1", "高次不等式", "（1）三个单根逐个变号", chart("（1）符号表", ["区间", "(-∞,1)", "1", "(1,2)", "2", "(2,3)", "3", "(3,+∞)"], [{ label: "乘积", values: ["−", "0", "+", "0", "−", "0", "+"], selectedIndices: [2, 6] }], "(1,2)∪(3,+∞)", ["三个根均为单根，每经过一个根就变号。"]), [["therefore", "（1）的解集为 \\((1,2)\\cup(3,+\\infty)\\)"]], [["（1）", "(1,2)∪(3,+∞)"]]),
      step("s2", "高次不等式", "（2）先处理负的最高次项", chart("（2）符号表", ["区间", "(-∞,-2)", "-2", "(-2,1)", "1", "(1,3)", "3", "(3,+∞)"], [{ label: "(x−1)(x+2)(3−x)", values: ["+", "0", "−", "0", "+", "0", "−"], selectedIndices: [0, 4] }], "(-∞,-2)∪(1,3)", ["3−x=−(x−3)，整体多一个负号。"]), [["therefore", "（2）的解集为 \\(( -\\infty,-2)\\cup(1,3)\\)"]], [["（2）", "(−∞,-2)∪(1,3)"]]),
      step("s3", "高次不等式", "（3）偶次根不改变符号", chart("（3）符号表", ["区间", "(-∞,-3)", "-3", "(-3,1)", "1（二重根）", "(1,2)", "2", "(2,+∞)"], [{ label: "(x−2)(x+3)(x−1)²", values: ["+", "0", "−", "0", "−", "0", "+"], selectedIndices: [0, 6] }], "(-∞,-3)∪(2,+∞)", ["x=1 是二重根，穿过它时符号不变。"]), [["therefore", "（3）的解集为 \\(( -\\infty,-3)\\cup(2,+\\infty)\\)"]], [["（3）", "(−∞,-3)∪(2,+∞)"]]),
    ],
    policies: { s1:{movable:false,range:[0,0]}, s2:{movable:false,range:[0,0]}, s3:{movable:false,range:[0,0]} },
    stepLabels: { s1:"1 三个单根", s2:"2 处理负号", s3:"3 识别偶次根" },
  },
  single(
    "inequality-solving-polynomial-q02", "穿针引线法判断三次不等式", "练习 5-2",
    ["\\((x+1)(x-1)(x-2)>0\\) 的解集是（　　）", "A. \\(-1<x<2\\)　B. \\(x<-1\\) 或 \\(1<x<2\\)　C. \\(-1<x<1\\) 或 \\(1<x<2\\)　D. \\(-1<x<1\\) 或 \\(x>2\\)"],
    ["按 −1、1、2 排列根。", "从右向左逐根变号。"], "D",
    step("s1", "高次不等式", "按根划分区间",
      chart("三次不等式符号表", ["区间", "(-∞,-1)", "-1", "(-1,1)", "1", "(1,2)", "2", "(2,+∞)"], [{ label:"乘积", values:["−","0","+","0","−","0","+"], selectedIndices:[2,6] }], "(-1,1)∪(2,+∞)", ["所有根都是单根，符号交替。"]),
      [["therefore", "选择 D"]], [["答案", "D"]]),
  ),
  single(
    "inequality-solving-polynomial-q03", "识别偶次根的高次不等式", "练习 5-3",
    ["不等式 \\((x^2-2x-3)(x^2-4x+4)<0\\) 的解集是（　　）", "A. \\(x<-1\\) 或 \\(x>3\\)　B. \\(-1<x<3\\)　C. \\(x<-3\\) 或 \\(x>1\\)　D. \\(-1<x<2\\) 或 \\(2<x<3\\)"],
    ["因式分解为 \\((x+1)(x-3)(x-2)^2\\)。", "x=2 是偶次根，不变号但严格不等式仍要排除。"], "D",
    step("s1", "高次不等式", "偶次根处不变号",
      chart("含二重根的符号表", ["区间", "(-∞,-1)", "-1", "(-1,2)", "2（二重根）", "(2,3)", "3", "(3,+∞)"], [{ label:"乘积", values:["+","0","−","0","−","0","+"], selectedIndices:[2,4] }], "(-1,2)∪(2,3)", ["x=2 两侧同为负，但 x=2 使乘积等于 0，不能取。"]),
      [["therefore", "选择 D"]], [["答案", "D"]]),
  ),
  ...[
    ["inequality-solving-rational-q01", "解分式不等式（含等号）", "练习 6-1", "\\frac{x+3}{2-x}\\ge0", ["-3","2"], ["−","0","+","禁值","−"], [1,2], "[-3,2)", "分母 x=2 必须排除。"],
    ["inequality-solving-rational-q02", "移项通分解分式不等式", "练习 6-2", "\\frac{3x+1}{2x-1}\\le1", ["-2","1/2"], ["+","0","−","禁值","+"], [1,2], "[-2,1/2)", "先化为 (x+2)/(2x−1)≤0。"],
    ["inequality-solving-rational-q03", "判断恒正分母的分式不等式", "练习 6-3", "\\frac{2x^2-x-2}{x^2+x+1}>1", ["-1","3"], ["+","0","−","0","+"], [0,4], "(-∞,-1)∪(3,+∞)", "x²+x+1>0，分母恒正。"],
    ["inequality-solving-rational-q04", "通分后判断分子分母符号", "练习 6-4", "\\frac{x}{3x-2}>2", ["2/3","4/5"], ["−","禁值","+","0","−"], [2], "(2/3,4/5)", "x=2/3 是分母禁值。"],
  ].map(([id,title,breadcrumb,expr,points,values,selected,solution,note]) => single(
    id, title, breadcrumb, [`解不等式 \\(${expr}\\)。`], ["移项并通分成一侧为 0。", "分母为 0 的点只作分界点，永远不能写进解集。"], solution,
    step("s1", "分式不等式", "移项通分并标出禁值点",
      chart("分式不等式符号表", ["区间", `(-∞,${points[0]})`, points[0], `(${points[0]},${points[1]})`, points[1], `(${points[1]},+∞)`], [{ label:"通分后的式子", values, selectedIndices:selected }], solution, [note, "按题目要求选取正区间、负区间和允许取等号的零点。"]),
      [["therefore", `解集为 \\(${solution}\\)`]], [["解集", solution]]),
  )),
  single(
    "inequality-solving-absolute-q01", "比较绝对值条件的充分必要性", "练习 7-1",
    ["设 \\(x\\in\\mathbb R\\)，则“\\(x<-2\\) 或 \\(x>1\\)”是“\\(|x-2|<1\\)”的（　　）", "A. 充分而不必要条件　B. 必要而不充分条件　C. 充要条件　D. 既不充分也不必要条件"],
    ["先把绝对值不等式化为区间。", "比较两个条件解集的包含方向。"], "B",
    step("s1", "绝对值不等式", "化成区间并比较包含", null,
      [["because", "\\(|x-2|<1\\iff1<x<3\\)，其解集包含在 \\(( -\\infty,-2)\\cup(1,+\\infty)\\) 中"], ["therefore", "前者是后者的必要而不充分条件，选择 B"]], [["答案", "B"]], { headers:["条件","解集"], rows:[["p：x<−2 或 x>1","(−∞,−2)∪(1,+∞)"],["q：|x−2|<1","(1,3)"]] }),
  ),
  single(
    "inequality-solving-absolute-q02", "分类解含二次式的绝对值不等式", "练习 7-2",
    ["解不等式 \\(|x^2-3|>2x\\)。"], ["先利用右侧 2x 的正负分类。", "当 x≥0 时再去绝对值。"], "(-∞,1)∪(3,+∞)",
    step("s1", "绝对值不等式", "按右侧符号分类", null,
      [["because", "x<0 时右侧为负，绝对值恒非负，所以全部成立"], ["because", "x≥0 时，\\(|x^2-3|>2x\\iff x^2-3>2x\\) 或 \\(x^2-3<-2x\\)"], ["therefore", "合并得到 \\(( -\\infty,1)\\cup(3,+\\infty)\\)"]], [["解集", "(−∞,1)∪(3,+∞)"]], { headers:["分类","化简","所得范围"], rows:[["x<0","自动成立","(−∞,0)"],["x≥0 且 x²−3>2x","(x−3)(x+1)>0","(3,+∞)"],["x≥0 且 x²−3<−2x","(x−1)(x+3)<0","[0,1)"]] }),
  ),
  single(
    "inequality-solving-absolute-q03", "按零点分类解绝对值和不等式", "练习 7-3",
    ["关于 x 的不等式 \\(|x-2|+|x+1|\\le10\\) 的解集为　　　　。"], ["以 −1、2 为分类断点。", "三段分别去绝对值，再取并集。"], "[-9/2,11/2]",
    step("s1", "绝对值不等式", "按两个零点分三段", null,
      [["because", "x≤−1 时化为 1−2x≤10；−1≤x≤2 时恒为 3；x≥2 时化为 2x−1≤10"], ["therefore", "三段合并为 \\([ -\\frac92,\\frac{11}{2}]\\)"]], [["解集", "[−9/2,11/2]"]], { headers:["区间","去绝对值后","本段解"], rows:[["x≤−1","1−2x≤10","[−9/2,−1]"],["−1≤x≤2","3≤10","[−1,2]"],["x≥2","2x−1≤10","[2,11/2]"]] }),
  ),
];

for (const lesson of lessons) {
  const dir = path.join(specsRoot, lesson.meta.id);
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(dir, "lesson-data.json"), `${JSON.stringify(lesson, null, 2)}\n`);
}

console.log(`Generated ${lessons.length} inequality-solving lessons.`);
