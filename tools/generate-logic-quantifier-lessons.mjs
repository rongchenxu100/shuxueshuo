import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const lessonRoot = path.join(repoRoot, "internal/senior-high/lesson-specs");

function meta(id, title, moduleId, breadcrumb) {
  return {
    id,
    outputPath: `site/problems/senior-high/sets/common-logical-language/${id}.html`,
    pageTitle: title,
    pageDescription: `${title}的逐步解析。`,
    breadcrumbTitle: breadcrumb,
    breadcrumbLabel: "常用逻辑用语",
    breadcrumbPath: "site/senior-high/index.html",
    breadcrumbSearch: `?chapter=sets&section=common-logical-language&module=${moduleId}`,
  };
}

function lesson({ id, title, moduleId, breadcrumb, lead, keyItems, lines, section, stepTitle, table, reasoning, derive, visual }) {
  const step = { id: "s1", section, title: stepTitle, t: 0, showDiagram: false };
  if (visual) step.visual = visual;
  if (table) step.table = table;
  const completeReasoning = reasoning.length === 1
    ? [["because", "逐项完成结构转换，并核对量词、研究范围与关系符号"], ...reasoning]
    : reasoning;
  step.reasoning = completeReasoning.map(([kind, text]) => ({ kind, text }));
  step.derive = derive;
  return {
    meta: meta(id, title, moduleId, breadcrumb),
    problem: { source: "培训教材 · 常用逻辑用语", keyPoints: { title: "解题要点", lead, items: keyItems }, lines: lines.map((text) => ({ text })) },
    steps: [step],
    policies: { s1: { movable: false, range: [0, 0] } },
    stepLabels: { s1: `1 ${stepTitle}` },
  };
}

const conditionChoices = "A. 充分不必要条件　　B. 必要不充分条件　　C. 充要条件　　D. 既不充分也不必要条件";
const specs = [
  lesson({
    id: "logic-quantifier-q01", title: "判断三个量词命题的真假", moduleId: "quantifiers", breadcrumb: "全称量词与存在量词 · 练习 5-1",
    lead: "存在命题举例验证，全称命题寻找反例。", keyItems: ["一个实例可以说明存在命题为真；", "一个反例可以说明全称命题为假。"],
    lines: ["判断下列命题的真假：", "（1）存在一对实数 \\((a,b)\\)，使 \\(a^2+b<0\\) 成立；", "（2）有理数 \\(x\\) 的平方仍为有理数；（3）实数的平方大于 0。"], section: "命题与量词", stepTitle: "逐项选择验证方式",
    table: { headers: ["命题", "验证", "结论"], rows: [["（1）", "取 \\(a=0,b=-1\\)，则 \\(a^2+b=-1<0\\)", "真"], ["（2）", "若 \\(x=m/n\\)，则 \\(x^2=m^2/n^2\\) 仍是有理数", "真"], ["（3）", "反例 \\(x=0\\)，此时 \\(x^2=0\\)", "假"]] },
    reasoning: [["because", "（1）找到了满足条件的实数对；（2）对任意有理数都成立；（3）被 \\(x=0\\) 否定"], ["therefore", "依次为真命题、真命题、假命题"]], derive: [["答案", "真，真，假"]],
  }),
  lesson({
    id: "logic-quantifier-q02", title: "选择一个真命题", moduleId: "quantifiers", breadcrumb: "全称量词与存在量词 · 练习 5-2",
    lead: "存在命题看方程或不等式是否有解，全称命题检查最小值与等号。", keyItems: ["严格大于 0 时，取到 0 也算反例；", "存在命题无解即为假。"],
    lines: ["下列命题中为真命题的是（　　）", "A. \\(∃x_0∈\\mathbb R，x_0^2+2x_0+2<0\\)　　B. \\(∃x_0∈\\mathbb R，x_0^2+x_0=-1\\)　　C. \\(∀x∈\\mathbb R，x^2-x+\\frac{1}{4}>0\\)　　D. \\(∀x∈\\mathbb R，-x^2-1<0\\)"], section: "命题与量词", stepTitle: "逐项检验真值",
    table: { headers: ["选项", "化简", "真值"], rows: [["A", "\\((x+1)^2+1<0\\) 无解", "假"], ["B", "\\(x^2+x+1=0\\)，\\(\\Delta=-3<0\\)", "假"], ["C", "\\(x=\\frac{1}{2}\\) 时等于 0", "假"], ["D", "\\(-x^2-1≤-1<0\\)", "真"]] },
    reasoning: [["because", "A、B 的存在对象不存在；C 在 \\(x=\\frac{1}{2}\\) 处不满足严格大于 0"], ["therefore", "只有 D 对任意实数成立"]], derive: [["答案", "D"]],
  }),
  lesson({
    id: "logic-quantifier-q03", title: "由全称命题为真求参数", moduleId: "quantifiers", breadcrumb: "全称量词与存在量词 · 练习 5-3",
    lead: "恒正二次函数必须开口向上且与横轴没有交点。", keyItems: ["先单独排除 \\(a=0\\)；", "严格恒正对应 \\(\\Delta<0\\)，不能取等号。"],
    lines: ["已知命题 \\(p:∀x∈\\mathbb R，ax^2+2x+3>0\\) 为真命题，则实数 \\(a\\) 的取值范围是（　　）", "A. \\(0<a≤\\frac{1}{2}\\)　B. \\(0<a<\\frac{1}{3}\\)　C. \\(a≥\\frac{1}{3}\\)　D. \\(a>\\frac{1}{3}\\)"], section: "命题与量词", stepTitle: "按函数类型分类",
    table: { headers: ["情形", "结果"], rows: [["\\(a=0\\)", "\\(2x+3\\) 不恒正"], ["\\(a<0\\)", "开口向下，不可能恒正"], ["\\(a>0\\)", "需 \\(\\Delta=4-12a<0\\)，即 \\(a>\\frac{1}{3}\\)"]] },
    reasoning: [["because", "当 \\(a>0\\) 时二次函数开口向上；要对所有实数严格为正，必须没有实根"], ["therefore", "\\(a>\\frac{1}{3}\\)，选择 D"]], derive: [["答案", "D"]],
  }),
  lesson({
    id: "logic-negation-q01", title: "否定一个全称不等式命题", moduleId: "quantifier-negations", breadcrumb: "量词命题的否定 · 练习 6-1",
    lead: "量词互换，谓词取否，研究范围保持不变。", keyItems: ["\\(∀\\) 的否定是 \\(∃\\)；", "\\(≥\\) 的否定是 \\(<\\)。"],
    lines: ["命题“\\(∀x∈\\mathbb R，4x^2+5x+2≥0\\)”的否定是（　　）", "A. \\(∃x∈\\mathbb R，4x^2+5x+2<0\\)　　B. \\(∀x\\notin\\mathbb R，4x^2+5x+2≥0\\)　　C. \\(∃x\\notin\\mathbb R，4x^2+5x+2<0\\)　　D. \\(∀x∈\\mathbb R，4x^2+5x+2<0\\)"], section: "量词命题的否定", stepTitle: "逐层完成否定",
    table: { headers: ["原结构", "否定后"], rows: [["对任意 \\(x∈\\mathbb R\\)", "存在 \\(x∈\\mathbb R\\)"], ["\\(4x^2+5x+2≥0\\)", "\\(4x^2+5x+2<0\\)"]] },
    reasoning: [["because", "变量范围 \\(x∈\\mathbb R\\) 不变，只把全称量词改为存在量词，并否定不等式"], ["therefore", "选择 A"]], derive: [["答案", "A"]],
  }),
  lesson({
    id: "logic-negation-q02", title: "否定一个自然数命题", moduleId: "quantifier-negations", breadcrumb: "量词命题的否定 · 练习 6-2",
    lead: "否定属于关系时，变量的原定义域不能改变。", keyItems: ["\\(∀\\) 改为 \\(∃\\)；", "\\(∈\\) 改为 \\(∉\\)。"],
    lines: ["命题“\\(∀x∈\\mathbb Z，|x-1|∈\\mathbb N^*\\)”的否定为（　　）", "A. \\(∀x\\notin\\mathbb Z，|x-1|∈\\mathbb N^*\\)　B. \\(∀x∈\\mathbb Z，|x-1|\\notin\\mathbb N^*\\)　C. \\(∃x\\notin\\mathbb Z，|x-1|\\notin\\mathbb N^*\\)　D. \\(∃x∈\\mathbb Z，|x-1|\\notin\\mathbb N^*\\)"], section: "量词命题的否定", stepTitle: "保留范围并否定谓词",
    table: { headers: ["原命题", "否定"], rows: [["\\(∀x∈\\mathbb Z\\)", "\\(∃x∈\\mathbb Z\\)"], ["\\(|x-1|∈\\mathbb N^*\\)", "\\(|x-1|\\notin\\mathbb N^*\\)"]] },
    reasoning: [["therefore", "完整否定为 \\(∃x∈\\mathbb Z，|x-1|\\notin\\mathbb N^*\\)，选择 D"]], derive: [["答案", "D"]],
  }),
  lesson({
    id: "logic-negation-q03", title: "否定带范围的存在命题", moduleId: "quantifier-negations", breadcrumb: "量词命题的否定 · 练习 6-3",
    lead: "写在量词后的限制条件是研究范围，不能随谓词一起取反。", keyItems: ["\\(∃x≤0\\) 改为 \\(∀x≤0\\)；", "\\(≤0\\) 的结论改为 \\(>0\\)。"],
    lines: ["命题 \\(p:∃x≤0，x^2-2x+a≤0\\) 的否定是（　　）", "A. \\(∀x>0，x^2-2x+a≤0\\)　B. \\(∃x>0，x^2-2x+a≤0\\)　C. \\(∀x≤0，x^2-2x+a>0\\)　D. \\(∃x≤0，x^2-2x+a>0\\)"], section: "量词命题的否定", stepTitle: "区分研究范围与结论",
    table: { headers: ["部分", "原命题", "否定后"], rows: [["量词", "存在", "任意"], ["范围", "\\(x≤0\\)", "\\(x≤0\\)"], ["谓词", "\\(x^2-2x+a≤0\\)", "\\(x^2-2x+a>0\\)"]] },
    reasoning: [["therefore", "选择 C"]], derive: [["答案", "C"]],
  }),
  lesson({
    id: "logic-negation-q04", title: "否定“至少一个成立”", moduleId: "quantifier-negations", breadcrumb: "量词命题的否定 · 练习 6-4",
    lead: "“至少有一个成立”的反面不是“至少有一个不成立”，而是“全部不成立”。", keyItems: ["全称量词改为存在量词；", "析取命题取否后变为两个否定同时成立。"],
    lines: ["命题“\\(∀a,b>0\\)，\\(a+\\frac{1}{b}≥2\\) 和 \\(b+\\frac{1}{a}≥2\\) 至少有一个成立”的否定为（　　）", "A. \\(∀a,b>0\\)，\\(a+\\frac{1}{b}<2\\) 和 \\(b+\\frac{1}{a}<2\\) 至少有一个成立　B. \\(∀a,b>0\\)，\\(a+\\frac{1}{b}≥2\\) 和 \\(b+\\frac{1}{a}≥2\\) 都不成立　C. \\(∃a,b>0\\)，\\(a+\\frac{1}{b}<2\\) 和 \\(b+\\frac{1}{a}<2\\) 至少有一个成立　D. \\(∃a,b>0\\)，\\(a+\\frac{1}{b}≥2\\) 和 \\(b+\\frac{1}{a}≥2\\) 都不成立"], section: "量词命题的否定", stepTitle: "否定量词与“至少一个”",
    table: { headers: ["原命题结构", "否定后"], rows: [["对任意 \\(a,b>0\\)", "存在 \\(a,b>0\\)"], ["两个不等式至少一个成立", "两个不等式都不成立，即 \\(a+\\frac{1}{b}<2\\) 且 \\(b+\\frac{1}{a}<2\\)"]] },
    reasoning: [["because", "“至少有一个成立”的否定是“两个都不成立”；每个 \\(≥2\\) 分别否定为 \\(<2\\)"], ["therefore", "完整否定为：存在 \\(a,b>0\\)，使 \\(a+\\frac{1}{b}<2\\) 且 \\(b+\\frac{1}{a}<2\\) 同时成立。这与选项 D 的“两个原不等式都不成立”等价"]], derive: [["等价否定", "\\(∃a,b>0\\)，\\(a+\\frac{1}{b}<2\\) 且 \\(b+\\frac{1}{a}<2\\)"], ["答案", "D"]],
  }),
];

const practiceData = [
  ["logic-practice-q01", "判断 x=-1 与 x²=1 的条件关系", ["“\\(x=-1\\)”是“\\(x^2=1\\)”成立的（　　）", conditionChoices], "充分成立：\\(x=-1\\) 能推出 \\(x^2=1\\)；必要不成立：取 \\(x=1\\) 时，\\(x^2=1\\) 成立但 \\(x=-1\\) 不成立", "A", true, false],
  ["logic-practice-q02", "判断分式不等式的条件关系", ["“\\(a>b>0\\)”是“\\(\\frac{b}{a}<1\\)”的（　　）", conditionChoices], "充分成立：\\(a>b>0\\) 能推出 \\(0<\\frac{b}{a}<1\\)；必要不成立：取 \\(a=-1,b=1\\) 时，\\(\\frac{b}{a}=-1<1\\)，但 \\(a>b>0\\) 不成立", "A", true, false],
  ["logic-practice-q03", "判断两个射线条件的关系", ["设 \\(x∈\\mathbb R\\)，则“\\(x>3\\)”是“\\(x>4\\)”的（　　）", conditionChoices], "充分不成立：取 \\(x=3.5\\) 时，\\(x>3\\) 成立但 \\(x>4\\) 不成立；必要成立：\\(x>4\\) 一定能推出 \\(x>3\\)", "B", false, true],
];
for (const [id, title, lines, explanation, answer, sufficient, necessary] of practiceData) {
  specs.push(lesson({ id, title, moduleId: "logic-practice", breadcrumb: `实战演练 · 第 ${id.slice(-2).replace(/^0/, "")} 题`, lead: "分别标记充分与必要是否成立。", keyItems: ["充分看前件能否保证后件；", "必要看后件成立时前件是否必须成立。"], lines, section: "充分必要条件", stepTitle: "判断充分与必要", visual: { kind: "implication-condition-pairs", ariaLabel: `${title}推导图`, cases: [{ label: title, pText: lines[0].match(/“([^”]+)”/)?.[1] ?? "p", qText: lines[0].match(/是“([^”]+)”/)?.[1] ?? "q", sufficient, necessary, result: answer === "A" ? "充分不必要条件" : "必要不充分条件", evidenceLabel: "判断依据", counterexample: explanation }] }, reasoning: [["because", explanation], ["therefore", `选择 ${answer}`]], derive: [["答案", answer]] }));
}

const negPractice = [
  ["logic-practice-q04", "否定一个关于自然数的存在命题", "命题“\\(∃n∈\\mathbb N，n^2>2n+3\\)”的否定是（　　）", "A. \\(∀n\\notin\\mathbb N，n^2<2n+3\\)　B. \\(∀n∈\\mathbb N，n^2<2n+3\\)　C. \\(∀n\\notin\\mathbb N，n^2≤2n+3\\)　D. \\(∀n∈\\mathbb N，n^2≤2n+3\\)", "\\(∀n∈\\mathbb N，n^2≤2n+3\\)", "D"],
  ["logic-practice-q05", "否定带限制范围的全称命题", "命题“\\(∀x>1，x^2-m>1\\)”的否定是（　　）", "A. \\(∃x>1，x^2-m≤1\\)　B. \\(∃x≤1，x^2-m≤1\\)　C. \\(∀x>1，x^2-m≤1\\)　D. \\(∀x≤1，x^2-m≤1\\)", "\\(∃x>1，x^2-m≤1\\)", "A"],
  ["logic-practice-q06", "否定一个二次不等式存在命题", "命题“\\(∃x∈\\mathbb R，x^2-2x-2>0\\)”的否定是（　　）", "A. \\(∀x∈\\mathbb R，x^2-2x-2≤0\\)　B. \\(∃x∈\\mathbb R，x^2-2x-2≤0\\)　C. \\(∀x∈\\mathbb R，x^2-2x-2>0\\)　D. \\(∃x∈\\mathbb R，x^2-2x-2<0\\)", "\\(∀x∈\\mathbb R，x^2-2x-2≤0\\)", "A"],
  ["logic-practice-q07", "否定一个二次不等式全称命题", "命题“\\(∀x∈\\mathbb R，x^2+x+1>0\\)”的否定是（　　）", "A. \\(∀x∈\\mathbb R，x^2+x+1≤0\\)　B. \\(∃x∈\\mathbb R，x^2+x+1≤0\\)　C. \\(∃x∈\\mathbb R，x^2+x+1<0\\)　D. \\(∃x∈\\mathbb R，x^2+x+1>0\\)", "\\(∃x∈\\mathbb R，x^2+x+1≤0\\)", "B"],
];
for (const [id, title, stem, options, result, answer] of negPractice) {
  specs.push(lesson({ id, title, moduleId: "logic-practice", breadcrumb: `实战演练 · 第 ${id.slice(-2).replace(/^0/, "")} 题`, lead: "量词互换，谓词取否，变量范围原样保留。", keyItems: ["\\(∃\\) 与 \\(∀\\) 互换；", "\\(>\\) 的否定是 \\(≤\\)。"], lines: [stem, options], section: "量词命题的否定", stepTitle: "按三部分完成否定", table: { headers: ["检查项", "处理"], rows: [["量词", "\\(∃\\) 与 \\(∀\\) 互换"], ["范围", "保持不变"], ["谓词", "关系符号取否"]] }, reasoning: [["therefore", `完整否定为 ${result}，选择 ${answer}`]], derive: [["答案", answer]] }));
}

specs.push(lesson({
  id: "logic-practice-q08", title: "由必要不充分条件求参数", moduleId: "logic-practice", breadcrumb: "实战演练 · 第 8 题", lead: "先把条件化为集合，再按必要不充分关系确定真包含方向。", keyItems: ["\\(A=[1,3]\\)，所以 \\(C_{\\mathbb R}A=(-∞,1)∪(3,+∞)\\)；", "q 的解集必须是 p 的真子集。"],
  lines: ["集合 \\(A=\\{x\\mid x^2-4x+3≤0\\}\\)，\\(B=\\{x\\mid x>m\\}\\)。若“\\(x∈C_{\\mathbb R}A\\)”是“\\(x∈B\\)”的必要不充分条件，则实数 \\(m\\) 的取值范围是（　　）", "A. \\((-∞,1)\\)　B. \\([1,3]\\)　C. \\([3,+∞)\\)　D. \\([2,3]\\)"], section: "集合与条件关系", stepTitle: "集合化并比较包含", visual: { kind: "implication-condition-pairs", ariaLabel: "原题集合、条件关系与参数范围推导图", cases: [{ label: "先比较原题集合，再判断条件关系", pText: "\\(x∈C_{\\mathbb R}A\\)", qText: "\\(x∈B\\)", sufficient: false, necessary: true, result: "必要不充分条件", evidenceLabel: "判断依据", counterexample: "\\(C_{\\mathbb R}A\\) 还含有左侧射线 \\((-∞,1)\\)，所以 p 成立时 q 不一定成立。", setEvidence: { kind: "complement-right-ray-parameter", ariaLabel: "补集 CℝA、集合 B 与参数范围的三行数轴", pRowLabel: "CℝA", qRowLabel: "B", resultRowLabel: "m", pSet: "\\(C_{\\mathbb R}A=(-∞,1)∪(3,+∞)\\)", qSet: "\\(B=(m,+∞)\\)", pLeftEndpoint: "1", pRightEndpoint: "3", qEndpoint: "m", resultEndpoint: "3", relation: "B⊊CℝA ⇔ m≥3", parameterSet: "\\(m∈[3,+∞)\\)", explanations: ["\\(B\\) 的右开射线必须避开闭区间 \\([1,3]\\)，所以左端点 \\(m≥3\\)。", "\\(C_{\\mathbb R}A\\) 中的元素不一定在 \\(B\\) 中，所以 p 成立时 q 不一定成立——充分不成立。", "\\(B\\) 中的每个元素都在 \\(C_{\\mathbb R}A\\) 中，所以 q 成立时 p 一定成立——必要成立。"] } }] }, table: { headers: ["条件", "对应集合"], rows: [["p：\\(x∈C_{\\mathbb R}A\\)", "\\(C_{\\mathbb R}A=(-∞,1)∪(3,+∞)\\)"], ["q：\\(x∈B\\)", "\\(B=(m,+∞)\\)"]] }, reasoning: [["because", "p 是 q 的必要条件，要求 \\(B⊆C_{\\mathbb R}A\\)。右射线 \\((m,+∞)\\) 要避开闭区间 \\([1,3]\\)，必须有 \\(m≥3\\)"], ["because", "此时 \\(B\\) 始终是 \\(C_{\\mathbb R}A\\) 的真子集，所以 p 不是 q 的充分条件"], ["therefore", "\\(m∈[3,+∞)\\)，选择 C"]], derive: [["答案", "C"]],
}));
specs.push(lesson({
  id: "logic-practice-q09", title: "由任意集合的子集求参数", moduleId: "logic-practice", breadcrumb: "实战演练 · 第 9 题", lead: "能成为任何集合子集的集合只能是空集。", keyItems: ["先把集合条件翻译为方程无实根；", "无实根要求判别式严格小于 0。"],
  lines: ["已知 \\(a\\) 是实数，若集合 \\(\\{x\\mid x^2+x+a=0\\}\\) 是任何集合的子集，则 \\(a\\) 的取值范围是______。"], section: "量词与集合", stepTitle: "转化为空集条件", table: { headers: ["要求", "等价条件"], rows: [["是任何集合的子集", "该集合为 \\(\\varnothing\\)"], ["方程无实根", "\\(\\Delta=1-4a<0\\)"], ["解不等式", "\\(a>\\frac{1}{4}\\)"]] }, reasoning: [["because", "空集是任何集合的子集；若解集含有元素，就不可能是某个不含该元素的集合的子集"], ["therefore", "\\(a>\\frac{1}{4}\\)"]], derive: [["答案", "\\(a>\\frac{1}{4}\\)"]],
}));

for (const spec of specs) {
  const dir = path.join(lessonRoot, spec.meta.id);
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(dir, "lesson-data.json"), `${JSON.stringify(spec, null, 2)}\n`);
}

console.log(`generated ${specs.length} common-logic lessons`);
