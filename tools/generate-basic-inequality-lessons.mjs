import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const specsRoot = path.join(repoRoot, "internal/senior-high/lesson-specs");

const source = "高一暑假目标班 · 第4讲";

function meta(id, title, breadcrumbTitle, moduleId) {
  return {
    id,
    outputPath: `site/problems/senior-high/inequalities/inequality-relations/${id}.html`,
    pageTitle: title,
    pageDescription: `${title}的逐步解析。`,
    breadcrumbTitle,
    breadcrumbLabel: "解不等式与基本不等式",
    breadcrumbPath: "site/senior-high/index.html",
    breadcrumbSearch: `?chapter=inequalities&section=inequality-relations&module=${moduleId}`,
  };
}

function problem(lines, lead, items) {
  return {
    source,
    keyPoints: { title: "解题要点", lead, items },
    lines: lines.map((text) => ({ text })),
  };
}

function step(id, section, title, reasoning, derive, options = {}) {
  return {
    id,
    section,
    title,
    t: 0,
    showDiagram: false,
    ...options,
    reasoning: reasoning.map(([kind, text]) => ({ kind, text })),
    derive,
  };
}

function signChart(title, columns, values, selectedIndices, solution, notes, label = "标准式") {
  return {
    kind: "inequality-sign-chart",
    title,
    columns,
    rows: [{ label, values, selectedIndices }],
    solution,
    notes,
    caption: "零点与禁值点把数轴分段，各段符号直接决定最终解集。",
  };
}

function rationalThreading({ title, intro, standardized, roots, signs, selectSign, target, solution, facts, caption }) {
  return {
    kind: "rational-threading-graph",
    title,
    intro,
    standardized,
    roots,
    signs,
    selectSign,
    target,
    solution,
    facts,
    caption: caption || "实心点表示可取的分子零点；带叉空心点表示永远排除的分母禁值。",
  };
}

function lesson(id, title, breadcrumbTitle, moduleId, lines, lead, items, steps) {
  return {
    meta: meta(id, title, breadcrumbTitle, moduleId),
    problem: problem(lines, lead, items),
    steps,
    policies: Object.fromEntries(steps.map(({ id: stepId }) => [stepId, { movable: false, range: [0, 0] }])),
    stepLabels: Object.fromEntries(steps.map(({ id: stepId }, index) => [stepId, `${index + 1} ${steps[index].title}`])),
  };
}

const basicLead = "先检查各项为正，再使用基本不等式，并单独核对等号条件。";
const basicItems = ["一正：参与基本不等式的各项必须为正。", "二定：和或积中必须有一个是定值。", "三相等：只有各项相等时才能取得等号。"];

const lessons = [
  lesson(
    "inequality-basic-q01",
    "定和求积的最大值",
    "基本不等式 · 练习 8-1",
    "basic-inequalities",
    ["1. 设正实数 \\(m，n\\) 满足 \\(m+n=2\\)，则 \\(mn\\) 的最大值为　　　　。"],
    basicLead,
    basicItems,
    [step("s1", "基本不等式", "验证条件并求上界", [
      ["because", "\\(m>0，n>0\\)，所以 \\(\\frac{m+n}{2}\\ge\\sqrt{mn}\\)"],
      ["therefore", "由 \\(m+n=2\\) 得 \\(1\\ge\\sqrt{mn}\\)，即 \\(mn\\le1\\)"],
      ["therefore", "当且仅当 \\(m=n=1\\) 时取等号，所以最大值为 \\(1\\)"],
    ], [["最大值", "1"], ["等号条件", "m=n=1"]], {
      visual: {
        kind: "basic-inequality-mapping",
        title: "把题目中的正数放进基本不等式",
        methodTag: "直接型｜定和求积",
        template: "\\(\\frac{a+b}{2}\\ge\\sqrt{ab}\\)",
        mappings: [
          { slot: "a", value: "m", condition: "\\(m>0\\)" },
          { slot: "b", value: "n", condition: "\\(n>0\\)" },
        ],
        mapped: "\\(\\frac{m+n}{2}\\ge\\sqrt{mn}\\)",
        stageLabel: "代入定和",
        fixedSourceLabel: "已知",
        fixedCondition: "\\(m+n=2\\)",
        replacementText: "把 \\(m+n\\) 换成 \\(2\\)",
        replaced: "\\(\\frac{2}{2}\\ge\\sqrt{mn}\\)",
        simplifyLabel: "化简",
        substituted: "\\(1\\ge\\sqrt{mn}\\)",
        conclusionLabel: "平方后得到上界",
        conclusion: "\\(mn\\le1\\)",
        equalityTemplate: "\\(a=b\\)",
        equalityMapped: "\\(m=n\\)",
        equalityContextLabel: "结合定和",
        equalityResult: "\\(m=n=1\\)",
        caption: "先把题目变量与公式槽位对号入座，再代入定值并核对等号条件。",
      },
    })],
  ),
  lesson(
    "inequality-basic-q02",
    "倒数和定值求积的最小值",
    "基本不等式 · 练习 8-2",
    "basic-inequalities",
    ["2. 已知正实数 \\(x，y\\) 满足 \\(\\frac{1}{x}+\\frac{1}{y}=1\\)，则 \\(xy\\) 最小值为　　　　。"],
    "原条件不能直接代入基本不等式，先把倒数和转成和积关系，再代入并核对等号条件。",
    basicItems,
    [step("s1", "基本不等式", "把倒数条件转成和积关系", [
      ["because", "\\(x>0，y>0\\)，且 \\(\\frac{x+y}{xy}=1\\)，所以 \\(x+y=xy\\)"],
      ["because", "基本不等式给出 \\(x+y\\ge2\\sqrt{xy}\\)，故 \\(xy\\ge2\\sqrt{xy}\\)"],
      ["therefore", "除以正数 \\(\\sqrt{xy}\\) 得 \\(\\sqrt{xy}\\ge2\\)，所以 \\(xy\\ge4\\)"],
      ["therefore", "当 \\(x=y=2\\) 时条件成立并取等号，最小值为 \\(4\\)"],
    ], [["最小值", "4"], ["等号条件", "x=y=2"]], {
      visual: {
        kind: "basic-inequality-mapping",
        title: "把题目中的正数放进基本不等式",
        methodTag: "转化型｜倒数和转和积关系",
        conditionFlowLabel: "先把倒数和转成和积关系",
        conditionFlow: [
          "\\(\\frac{1}{x}+\\frac{1}{y}=1\\)",
          "\\(\\frac{x+y}{xy}=1\\)",
          "\\(x+y=xy\\)",
        ],
        template: "\\(\\frac{a+b}{2}\\ge\\sqrt{ab}\\)",
        mappings: [
          { slot: "a", value: "x", condition: "\\(x>0\\)" },
          { slot: "b", value: "y", condition: "\\(y>0\\)" },
        ],
        mapped: "\\(\\frac{x+y}{2}\\ge\\sqrt{xy}\\)",
        stageLabel: "代入和积关系",
        fixedSourceLabel: "等价条件",
        fixedCondition: "\\(x+y=xy\\)",
        replacementText: "把 \\(x+y\\) 换成 \\(xy\\)",
        replaced: "\\(\\frac{xy}{2}\\ge\\sqrt{xy}\\)",
        simplifyLabel: "同除以正数 \\(\\sqrt{xy}\\)",
        substituted: "\\(\\sqrt{xy}\\ge2\\)",
        conclusionLabel: "平方后得到下界",
        conclusion: "\\(xy\\ge4\\)",
        equalityTemplate: "\\(a=b\\)",
        equalityMapped: "\\(x=y\\)",
        equalityContextLabel: "结合原条件",
        equalityResult: "\\(x=y=2\\)",
        caption: "先把倒数条件化为 \\(x+y=xy\\)，再将题目变量与公式槽位对应，最后核对等号条件。",
      },
    })],
  ),
  lesson(
    "inequality-basic-q03",
    "倒数和定值求线性式的最小值",
    "基本不等式 · 练习 8-3",
    "basic-inequalities",
    ["3. 已知正实数 \\(x，y\\) 满足 \\(\\frac{1}{x}+\\frac{1}{y}=1\\)，则 \\(x+4y\\) 最小值为　　　　。"],
    "求正项和的最小值时，先检查原两项是否定积；若不固定，就从题设中寻找能消去变量的因子构造定积。",
    [
      "看目标：正项和求最小值，先寻找固定乘积。",
      "查定积：x·4y=4xy 不固定，原两项不能直接使用基本不等式。",
      "找线索：条件整体等于 1 且含倒数，可以乘入并消去变量。",
      "验等号：构造出的两个正项相等，并且满足原条件。",
    ],
    [step("s1", "基本不等式", "从目标出发构造固定乘积", [
      ["because", "\\((x+4y)(\\frac{1}{x}+\\frac{1}{y})=5+\\frac{x}{y}+\\frac{4y}{x}\\)"],
      ["because", "\\(\\frac{x}{y}>0，\\frac{4y}{x}>0\\)，且两项乘积为 \\(4\\)，所以它们的和不小于 \\(4\\)"],
      ["therefore", "由 \\(\\frac{1}{x}+\\frac{1}{y}=1\\) 得 \\(x+4y\\ge5+4=9\\)"],
      ["therefore", "当 \\(\\frac{x}{y}=\\frac{4y}{x}\\)，即 \\(x=2y\\) 时取等号；代入条件得 \\(x=3，y=\\frac{3}{2}\\)"],
    ], [["最小值", "9"], ["等号条件", "x=3，y=3/2"]], {
      visual: {
        kind: "fixed-product-construction-flow",
        title: "原两项没有定积，如何构造出定积？",
        methodTag: "构造型｜寻找固定乘积",
        goal: { expression: "\\(x+4y\\)", task: "求正项和的最小值" },
        strategy: "想办法构造定积",
        initialCheck: {
          terms: ["\\(x\\)", "\\(4y\\)"],
          product: "\\(x\\cdot4y=4xy\\)",
          verdict: "乘积不固定，不能直接使用",
        },
        clue: {
          question: "题设中有什么能让变量相消？",
          condition: "\\(\\frac{1}{x}+\\frac{1}{y}=1\\)",
          observation: "条件含有 \\(x、y\\) 的倒数，并且整体等于 \\(1\\)：乘入它不会改变目标式。",
        },
        construction: {
          label: "乘入等于 1 的条件",
          identity: "\\(x+4y=(x+4y)(\\frac{1}{x}+\\frac{1}{y})\\)",
          expanded: "\\(=1+\\frac{x}{y}+\\frac{4y}{x}+4=5+\\frac{x}{y}+\\frac{4y}{x}\\)",
          rows: ["\\(x\\)", "\\(4y\\)"],
          columns: ["\\(\\frac{1}{x}\\)", "\\(\\frac{1}{y}\\)"],
          cells: [
            [{ text: "\\(1\\)", role: "constant" }, { text: "\\(\\frac{x}{y}\\)", role: "constructed" }],
            [{ text: "\\(\\frac{4y}{x}\\)", role: "constructed" }, { text: "\\(4\\)", role: "constant" }],
          ],
          constantSum: "常数项：\\(1+4=5\\)",
        },
        fixedPair: {
          question: "观察展开后的式子，是否可以找到定积？",
          terms: ["\\(\\frac{x}{y}\\)", "\\(\\frac{4y}{x}\\)"],
          product: "\\(\\frac{x}{y}\\cdot\\frac{4y}{x}=4\\cdot\\frac{x}{x}\\cdot\\frac{y}{y}=4\\)",
          verdict: "定积构造成功",
        },
        application: {
          template: "\\(a+b\\ge2\\sqrt{ab}\\)",
          mappings: [
            { slot: "\\(a\\)", value: "\\(\\frac{x}{y}\\)" },
            { slot: "\\(b\\)", value: "\\(\\frac{4y}{x}\\)" },
          ],
          inequality: "\\(\\frac{x}{y}+\\frac{4y}{x}\\ge2\\sqrt4=4\\)",
          combine: "\\(x+4y=5+\\frac{x}{y}+\\frac{4y}{x}\\ge9\\)",
          conclusion: "最小值为 \\(9\\)",
        },
        equality: {
          condition: "\\(\\frac{x}{y}=\\frac{4y}{x}\\)",
          relation: "\\(x=2y\\)",
          result: "\\(x=3，y=\\frac{3}{2}\\)",
        },
        caption: "先以“构造定积”为目标寻找倒数，再通过展开后的交叉项发现固定乘积。",
      },
    })],
  ),
  lesson(
    "inequality-basic-q04",
    "线性约束下求倒数和的最小值",
    "基本不等式 · 练习 8-4",
    "basic-inequalities",
    ["4. 已知 \\(a>0，b>0\\)，且 \\(a+3b=2\\)，则 \\(\\frac{3}{a}+\\frac{4}{b}\\) 的最小值是　　　　。"],
    "求倒数和的最小值时，若原两项乘积不固定，就把定和条件乘入目标式，通过展开寻找乘积固定的交叉项。",
    [
      "看目标：正项和求最小值，先检查两项乘积是否固定。",
      "乘定和：a+3b=2 是定值，乘入目标式会把分母约成比值。",
      "找定积：展开后检查两个交叉项，它们的乘积恒为 36。",
      "验等号：构造出的两个正项相等，并且满足原条件。",
    ],
    [step("s1", "基本不等式", "从定和出发构造固定乘积", [
      ["because", "\\((\\frac{3}{a}+\\frac{4}{b})(a+3b)=15+\\frac{9b}{a}+\\frac{4a}{b}\\)"],
      ["because", "\\(\\frac{9b}{a}>0，\\frac{4a}{b}>0\\)，两项乘积为 \\(36\\)，所以两项和不小于 \\(12\\)"],
      ["therefore", "\\(2(\\frac{3}{a}+\\frac{4}{b})\\ge27\\)，故 \\(\\frac{3}{a}+\\frac{4}{b}\\ge\\frac{27}{2}\\)"],
      ["therefore", "等号要求 \\(\\frac{9b}{a}=\\frac{4a}{b}\\)，结合 \\(a+3b=2\\) 得 \\(a=\\frac{2}{3}，b=\\frac{4}{9}\\)"],
    ], [["最小值", "27/2"], ["等号条件", "a=2/3，b=4/9"]], {
      visual: {
        kind: "fixed-product-construction-flow",
        title: "原两项没有定积，如何借助定和构造？",
        methodTag: "构造型｜乘入定和",
        goal: { expression: "\\(\\frac{3}{a}+\\frac{4}{b}\\)", task: "求正项和的最小值" },
        strategy: "想办法构造定积",
        initialCheck: {
          terms: ["\\(\\frac{3}{a}\\)", "\\(\\frac{4}{b}\\)"],
          product: "\\(\\frac{3}{a}\\cdot\\frac{4}{b}=\\frac{12}{ab}\\)",
          verdict: "乘积不固定，不能直接使用",
        },
        clue: {
          question: "题设中哪个定值能约去分母？",
          condition: "\\(a+3b=2\\)",
          observation: "条件是含有 \\(a、b\\) 的定和。把它乘入目标式，可约出常数项与交叉比值。",
        },
        construction: {
          label: "乘入定和 a+3b=2",
          identity: "\\(2(\\frac{3}{a}+\\frac{4}{b})=(\\frac{3}{a}+\\frac{4}{b})(a+3b)\\)",
          expanded: "\\(=3+\\frac{9b}{a}+\\frac{4a}{b}+12=15+\\frac{9b}{a}+\\frac{4a}{b}\\)",
          rows: ["\\(\\frac{3}{a}\\)", "\\(\\frac{4}{b}\\)"],
          columns: ["\\(a\\)", "\\(3b\\)"],
          cells: [
            [{ text: "\\(3\\)", role: "constant" }, { text: "\\(\\frac{9b}{a}\\)", role: "constructed" }],
            [{ text: "\\(\\frac{4a}{b}\\)", role: "constructed" }, { text: "\\(12\\)", role: "constant" }],
          ],
          constantSum: "常数项：\\(3+12=15\\)",
        },
        fixedPair: {
          question: "观察展开后的式子，是否可以找到定积？",
          terms: ["\\(\\frac{9b}{a}\\)", "\\(\\frac{4a}{b}\\)"],
          product: "\\(\\frac{9b}{a}\\cdot\\frac{4a}{b}=36\\cdot\\frac{a}{a}\\cdot\\frac{b}{b}=36\\)",
          verdict: "定积构造成功",
        },
        application: {
          template: "\\(u+v\\ge2\\sqrt{uv}\\)",
          mappings: [
            { slot: "\\(u\\)", value: "\\(\\frac{9b}{a}\\)" },
            { slot: "\\(v\\)", value: "\\(\\frac{4a}{b}\\)" },
          ],
          inequality: "\\(\\frac{9b}{a}+\\frac{4a}{b}\\ge2\\sqrt{36}=12\\)",
          combine: "\\(2(\\frac{3}{a}+\\frac{4}{b})=15+\\frac{9b}{a}+\\frac{4a}{b}\\ge27\\)",
          conclusion: "最小值为 \\(\\frac{27}{2}\\)",
        },
        equality: {
          condition: "\\(\\frac{9b}{a}=\\frac{4a}{b}\\)",
          relation: "\\(3b=2a\\)",
          result: "\\(a=\\frac{2}{3}，b=\\frac{4}{9}\\)",
        },
        caption: "先把定和乘入目标式，再从展开后的交叉项中发现固定乘积。",
      },
    })],
  ),
  lesson(
    "inequality-basic-q05",
    "补项构造定积求最小值",
    "基本不等式 · 练习 8-5",
    "basic-inequalities",
    ["5. 已知 \\(x>-1\\)，则 \\(x+\\frac{4}{x+1}\\) 的最小值为　　　　，此时 \\(x\\) 的值是　　　　。"],
    "原式中的 x 未必为正，不能直接使用基本不等式；核心是由分母 x+1 反推配对正项，再用补 1、减 1 构造固定乘积，换元只负责简化书写。",
    [
      "看目标：求和的最小值，寻找两个乘积固定的正项。",
      "逆看分母：4/(x+1) 应与正项 x+1 配对，二者乘积恒为 4。",
      "补项构造：把 x 写成 (x+1)-1，补出的 1 在括号外减回。",
      "验等号：先令两个配对正项相等，再求出原变量 x。",
    ],
    [step("s1", "基本不等式", "围绕分母补项构造固定乘积", [
      ["because", "由 \\(x>-1\\) 得 \\(x+1>0\\)，而 \\(x=(x+1)-1\\)"],
      ["because", "原式 \\(=(x+1)+\\frac{4}{x+1}-1\\)，其中 \\((x+1)\\cdot\\frac{4}{x+1}=4\\)"],
      ["therefore", "\\((x+1)+\\frac{4}{x+1}\\ge4\\)，所以原式不小于 \\(3\\)"],
      ["therefore", "当 \\(x+1=\\frac{4}{x+1}\\)，即 \\(x+1=2\\) 时取等号，因此 \\(x=1\\)"],
    ], [["最小值", "3"], ["x", "1"]], {
      visual: {
        kind: "fixed-product-construction-flow",
        title: "分母已经给出线索，如何补出它的配对项？",
        methodTag: "构造型｜补项凑定积",
        goal: { expression: "\\(x+\\frac{4}{x+1}\\)", task: "求含一次项与倒数项的最小值" },
        strategy: "围绕分母凑出定积",
        initialCheck: {
          terms: ["\\(x\\)", "\\(\\frac{4}{x+1}\\)"],
          product: "\\(x\\cdot\\frac{4}{x+1}=\\frac{4x}{x+1}\\)",
          verdict: "乘积不固定，且 x 未必为正",
        },
        clue: {
          question: "分母 x+1 应与哪个正项配对？",
          condition: "\\(x>-1\\Rightarrow x+1>0\\)",
          observation: "\\(x+1\\) 是正项，并且与 \\(\\frac{4}{x+1}\\) 相乘时分母正好约掉，乘积恒为 \\(4\\)。",
        },
        construction: {
          kind: "completion",
          label: "补 1、减 1，补出配对正项",
          givenTerm: "\\(\\frac{4}{x+1}\\)",
          matchingTerm: "\\(x+1\\)",
          identity: "\\(x=(x+1)-1\\)",
          expanded: "\\(x+\\frac{4}{x+1}=\\left[(x+1)+\\frac{4}{x+1}\\right]-1\\)",
          focus: "\\((x+1)+\\frac{4}{x+1}\\)",
          constant: "\\(-1\\)",
          simplification: "令 \\(t=x+1>0\\)，可简写为 \\(t+\\frac{4}{t}-1\\)",
        },
        fixedPair: {
          question: "补出的两个正项，其乘积是否固定？",
          terms: ["\\(x+1\\)", "\\(\\frac{4}{x+1}\\)"],
          product: "\\((x+1)\\cdot\\frac{4}{x+1}=4\\)，且两项均为正",
          verdict: "定积构造成功",
        },
        application: {
          template: "\\(u+v\\ge2\\sqrt{uv}\\)",
          mappings: [
            { slot: "\\(u\\)", value: "\\(x+1\\)" },
            { slot: "\\(v\\)", value: "\\(\\frac{4}{x+1}\\)" },
          ],
          inequality: "\\((x+1)+\\frac{4}{x+1}\\ge2\\sqrt4=4\\)",
          combine: "\\(x+\\frac{4}{x+1}=\\left[(x+1)+\\frac{4}{x+1}\\right]-1\\ge3\\)",
          conclusion: "最小值为 \\(3\\)",
        },
        equality: {
          condition: "\\(x+1=\\frac{4}{x+1}\\)",
          relation: "\\(x+1=2\\)",
          result: "\\(x=1\\)",
        },
        caption: "先由分母反推配对正项，再用补 1、减 1 构造定积；换元只用于简化书写。",
      },
    })],
  ),
  lesson(
    "inequality-basic-q06",
    "换元求含一次项和倒数项的最小值",
    "基本不等式 · 练习 8-6",
    "basic-inequalities",
    ["6. 若 \\(x>-3\\)，则 \\(2x+\\frac{1}{x+3}\\) 的最小值是（　　）", "A. \\(2\\sqrt2+6\\)　　B. \\(2\\sqrt2-6\\)　　C. \\(2\\sqrt2\\)　　D. \\(2\\sqrt2+2\\)"],
    basicLead,
    ["令 t=x+3>0。", "把原式写成 2t+1/t-6。"],
    [step("s1", "基本不等式", "换元后应用基本不等式", [
      ["because", "令 \\(t=x+3>0\\)，则原式 \\(=2t+\\frac{1}{t}-6\\)"],
      ["because", "\\(2t+\\frac{1}{t}\\ge2\\sqrt{2t\\cdot\\frac{1}{t}}=2\\sqrt2\\)"],
      ["therefore", "最小值为 \\(2\\sqrt2-6\\)，选择 B"],
    ], [["答案", "B"], ["最小值", "2√2−6"]])],
  ),
  lesson(
    "inequality-practice-q01", "辨析不等式结论", "实战演练 · 第 1 题", "inequality-practice",
    ["1. 若 \\(a，b，c\\) 为实数，下列结论正确的是（　　）", "A. 若 \\(|a|>b\\)，则 \\(a^2>b^2\\)　　B. 若 \\(a<b<0\\)，则 \\(\\frac{b}{a}>\\frac{a}{b}\\)　　C. 若 \\(a>b\\)，则 \\(ac^2>bc^2\\)　　D. 若 \\(a>b>0\\)，则 \\(a^2>ab>b^2\\)"],
    "逐项检查符号、非零条件与等号退化情形。", ["给错误选项构造反例。", "乘法或除法前先确定乘数、除数的符号。"],
    [step("s1", "性质辨析", "把反例数值真正代入计算", [["because", "错误的恒成立结论，只需一个满足前提、却不满足结论的反例即可推翻"], ["because", "D 中 a>b>0，同乘正数 a 与 b 分别得到 a²>ab 与 ab>b²"], ["therefore", "A、B、C 均被反例推翻，选择 D"]], [["答案", "D"]], { visual: {
      kind: "option-counterexample-review",
      title: "反例要同时满足前提，并算出矛盾",
      intro: "不要只说“条件不足”，把具体数值代入前提与结论，错误会一眼显现。",
      rows: [
        { option: "A", correct: false, judgment: "\\(|a|>b\\nRightarrow a^2>b^2\\)", example: "\\(a=0，b=-1\\)", calculation: "\\(|0|=0>-1\\)，但 \\(0^2=0<1=(-1)^2\\)" },
        { option: "B", correct: false, judgment: "负数取倒数不能照搬正数结论", example: "\\(a=-2，b=-1\\)", calculation: "\\(-2<-1<0\\)，但 \\(\\frac{b}{a}=\\frac{1}{2}<2=\\frac{a}{b}\\)，与题设结论相反" },
        { option: "C", correct: false, judgment: "乘以 \\(c^2\\) 可能退化为 0", example: "\\(a=2，b=1，c=0\\)", calculation: "\\(2>1\\)，但 \\(ac^2=bc^2=0\\)，并非严格大于" },
        { option: "D", correct: true, judgment: "引用基本性质·可乘性", example: "\\(a>b>0\\)", calculation: "同乘 \\(a>0\\) 得 \\(a^2>ab\\)；同乘 \\(b>0\\) 得 \\(ab>b^2\\)" },
      ],
      caption: "反例负责否定，性质负责证明；两种证据不要混在一句话里。",
    } })],
  ),
  lesson(
    "inequality-practice-q02", "判断恒成立的不等式推论", "实战演练 · 第 2 题", "inequality-practice",
    ["2. 如果 \\(a，b，c，d\\in\\mathbb R\\)，则正确的是（　　）", "A. 若 \\(a>b\\)，则 \\(\\frac{1}{a}<\\frac{1}{b}\\)　　B. 若 \\(a>b，c>d\\)，则 \\(a-c>b-d\\)　　C. 若 \\(ac^2>bc^2\\)，则 \\(a>b\\)　　D. 若 \\(a>b，c>d\\)，则 \\(ac>bd\\)"],
    "先找出前提中暗含的非零和正数条件。", ["不等式严格成立可排除 c=0。", "没有符号约束时不能直接取倒数或相乘。"],
    [step("s1", "性质辨析", "正确项证明，错误项用反例击破", [["because", "由 ac²>bc² 可知 c≠0，所以 c²>0；同除以 c²，方向不变，得到 a>b"], ["because", "A、B、D 分别缺少同号、同向相加与乘数符号条件，可用具体数值反驳"], ["therefore", "选择 C"]], [["答案", "C"]], { visual: {
      kind: "option-counterexample-review",
      title: "先检查条件，再决定能否使用不等式性质",
      intro: "每个错误选项都给出一组满足前提的数值，并完整算出结论为何失败。",
      rows: [
        { option: "A", correct: false, judgment: "未保证 \\(a、b\\) 非零同号", example: "\\(a=1，b=-1\\)", calculation: "\\(1>-1\\)，但 \\(\\frac{1}{a}=1>-1=\\frac{1}{b}\\)，不是 \\(\\frac{1}{a}<\\frac{1}{b}\\)" },
        { option: "B", correct: false, judgment: "\\(a>b、c>d\\) 不能直接相减", example: "\\(a=4，b=3，c=5，d=1\\)", calculation: "\\(a-c=-1<2=b-d\\)，题设结论不成立" },
        { option: "C", correct: true, judgment: "严格不等式自动给出 \\(c^2>0\\)", example: "\\(ac^2>bc^2\\)", calculation: "\\((a-b)c^2>0\\Rightarrow c\\ne0\\Rightarrow c^2>0\\Rightarrow a>b\\)" },
        { option: "D", correct: false, judgment: "两组大小关系不能直接相乘", example: "\\(a=1，b=0，c=0，d=-1\\)", calculation: "\\(1>0，0>-1\\)，但 \\(ac=0=bd\\)，不是 \\(ac>bd\\)" },
      ],
      caption: "先由前提读出正负和非零信息，再选择可加性、可乘性或反例。",
    } })],
  ),
  lesson(
    "inequality-practice-q03", "比较两个条件的充分必要性", "实战演练 · 第 3 题", "inequality-practice",
    ["3. 设 \\(x\\in\\mathbb R\\)，则“\\(x^2+x-2>0\\)”是“\\(|x-2|<1\\)”的（　　）", "A. 充分而不必要条件　　B. 必要而不充分条件　　C. 充要条件　　D. 既不充分也不必要条件"],
    "分别求出两个条件的解集，再比较集合包含关系。", ["二次式先因式分解。", "绝对值不等式化为区间。"],
    [step("s1", "充分必要条件", "把两个条件画成解集再看包含", [["because", "P：x²+x-2>0 的解集为 (-∞,-2)∪(1,+∞)"], ["because", "Q：|x-2|<1 的解集为 (1,3)，且 Q 真包含于 P"], ["therefore", "Q⇒P，而 P⇏Q，所以 P 是 Q 的必要而不充分条件，选择 B"]], [["答案", "B"]], { visual: {
      kind: "number-line-reasoning", method: "集合包含", title: "箭头关系由解集包含方向决定",
      intro: "先忘掉“充分、必要”四个字，只判断哪个解集装在另一个里面。",
      ticks: [{ position: 0.24, label: "−2" }, { position: 0.53, label: "1" }, { position: 0.82, label: "3" }],
      rows: [
        { label: "条件 P", condition: "\\(x^2+x-2>0\\)", set: "\\(P=(-\\infty,-2)\\cup(1,+\\infty)\\)", segments: [{ start: 0.02, end: 0.24, left: "ray", right: "open" }, { start: 0.53, end: 0.98, left: "open", right: "ray" }] },
        { label: "条件 Q", condition: "\\(|x-2|<1\\)", set: "\\(Q=(1,3)\\)", segments: [{ start: 0.53, end: 0.82, left: "open", right: "open" }] },
      ],
      implicationCheck: {
        title: "双向检验：两个方向要分别判断",
        directions: [
          { from: "P", to: "Q", holds: false, question: "P 是 Q 的充分条件吗？", setRelation: "\\(P\\nsubseteq Q\\)", reasoning: "不成立。例如 x=4 时 P 成立，但 Q 不成立。" },
          { from: "Q", to: "P", holds: true, question: "P 是 Q 的必要条件吗？", setRelation: "\\(Q\\subsetneq P\\)", reasoning: "成立。Q 中的每个 x 都属于 P。" },
        ],
        conclusion: "只成立 \\(Q\\Rightarrow P\\)，所以 P 是 Q 的必要而不充分条件。",
      },
      caption: "必要条件的解集更大；充分条件的解集更小。",
    } })],
  ),
  lesson(
    "inequality-practice-q04", "由整数解个数确定参数", "实战演练 · 第 4 题", "inequality-practice",
    ["4. 若关于 \\(x\\) 的一元二次不等式 \\(x^2-6x+a\\le0\\ (a\\in\\mathbb Z)\\) 的解集中有且仅有 3 个整数，则 \\(a\\) 的取值可以是（　　）", "A. 4　　　B. 5　　　C. 8　　　D. 9"],
    "先利用对称轴锁定三个整数解，再检查最内侧解点与相邻排除点。", ["参数 a 只让抛物线上下平移，对称轴始终是 x=3。", "恰有三个整数解时，关于 3 对称的整数只能是 2、3、4。", "含等号的内侧点要保留，相邻外侧点必须排除。"],
    [step("s1", "参数不等式", "由对称轴锁定整数解，再检查边界", [["because", "令 f(x)=x²-6x+a，抛物线开口向上且对称轴恒为 x=3；解集关于 3 对称"], ["because", "解集中恰有 3 个整数，所以只能是 2、3、4；因此 f(2)≤0，而相邻的 1 必须排除，即 f(1)>0"], ["because", "f(2)≤0 得 a≤8，f(1)>0 得 a>5，所以 5<a≤8"], ["therefore", "a∈Z，所以 a∈{6,7,8}；选项中可以取 8，选择 C"]], [["答案", "C"]], { visual: {
      kind: "quadratic-symmetric-integer-window", title: "对称轴先锁定整数解，边界点再确定参数",
      function: "\\(f(x)=x^2-6x+a\\)", axis: "\\(x=3\\)", movement: "参数 \\(a\\) 只使图像上下平移",
      included: ["2", "3", "4"], excluded: ["1", "5"],
      lockStatement: "恰有 3 个整数解，只能取关于对称轴成对的 2、3、4", innerPairLabel: "f(2)=f(4)", outerPairLabel: "f(1)=f(5)",
      checks: [
        { role: "最外侧解点", point: "2", symmetry: "\\(f(4)=f(2)\\)", condition: "\\(f(2)\\le0\\)", calculation: "\\(4-12+a\\le0\\)", result: "\\(a\\le8\\)" },
        { role: "相邻排除点", point: "1", symmetry: "\\(f(5)=f(1)\\)", condition: "\\(f(1)>0\\)", calculation: "\\(1-6+a>0\\)", result: "\\(a>5\\)" },
      ],
      range: "\\(5<a\\le8\\)", integerValues: "\\(a\\in\\{6,7,8\\}\\)", conclusion: "选项中可以取 \\(a=8\\)，选择 C",
      caption: "关于整数对称轴，奇数个整数解由中心点和若干对称点对组成。",
    } })],
  ),
  lesson(
    "inequality-practice-q05", "比较两个对称多项式", "实战演练 · 第 5 题", "inequality-practice",
    ["5. 已知 \\(a，b\\) 均为正实数，若 \\(M=a^3+b^3，N=a^2b+ab^2\\)，则（　　）", "A. \\(M<N\\)　　B. \\(M\\le N\\)　　C. \\(M>N\\)　　D. \\(M\\ge N\\)"],
    "作差并把结果分解成符号可控的因式。", ["计算 M-N。", "注意 a=b 时是否能取等号。"],
    [step("s1", "作差比较", "把差拆成两个符号可控的因式", [["because", "作差并因式分解：M-N=(a+b)(a-b)²"], ["because", "a、b 为正数，所以 a+b>0；平方项 (a-b)²≥0"], ["therefore", "M-N≥0，即 M≥N；a=b 时取等号，选择 D"]], [["答案", "D"]], { visual: {
      kind: "difference-factor-sign", title: "比较大小先作差，再只看每个因式的符号",
      difference: "\\(M-N=a^3+b^3-a^2b-ab^2\\)", factorization: "\\((a+b)(a-b)^2\\)",
      factors: [{ label: "正数条件", expression: "\\(a+b\\)", sign: "\\(a+b>0\\)" }, { label: "平方非负", expression: "\\((a-b)^2\\)", sign: "\\((a-b)^2\\ge0\\)" }],
      conclusion: "\\(M-N\\ge0\\Rightarrow M\\ge N\\)", equality: "当且仅当 \\(a=b\\) 时取等号",
    } })],
  ),
  lesson(
    "inequality-practice-q06", "求两个区间变量乘积的范围", "实战演练 · 第 6 题", "inequality-practice",
    ["6. 已知实数 \\(a，b\\) 满足 \\(-2<a<-1，1<b<3\\)，则 \\(a\\cdot b\\) 的取值范围是　　　　。"],
    "先把负数区间正化，再用同向正不等式的可乘法则，最后还原乘积符号。", ["同乘负数时，不等号方向改变。", "两组同向不等式对应相乘前，必须确认各项均为正数。", "开区间的端点不能取到。"],
    [step("s1", "范围计算", "正化后相乘，再还原符号", [["because", "由 -2<a<-1 各部分同乘 -1 并改变方向，整理得 1<-a<2"], ["because", "-a 与 b 都是正数；将 1<-a<2 和 1<b<3 的下界、上界分别相乘，得 1<(-a)b<6，即 1<-ab<6"], ["because", "各部分同乘 -1，不等号再次改变方向，整理得 -6<ab<-1"], ["therefore", "a、b 独立连续变化且原区间均为开区间，所以取值范围为 (-6,-1)"]], [["取值范围", "(-6,-1)"]], { visual: {
      kind: "positive-interval-product-chain", title: "先把负区间正化，再使用同向正不等式相乘",
      normalize: {
        source: "\\(-2<a<-1\\)", factor: "\\(×(-1)\\)", rule: "同乘负数，方向改变", result: "\\(1<-a<2\\)",
      },
      multiply: {
        rows: ["\\(1<-a<2\\)", "\\(1<b<3\\)"], positivity: "\\(-a>0，b>0\\)", rule: "同向正不等式对应相乘", expanded: "\\(1×1<(-a)b<2×3\\)", result: "\\(1<-ab<6\\)",
      },
      restore: {
        source: "\\(1<-ab<6\\)", factor: "\\(×(-1)\\)", rule: "同乘负数，方向改变并按从小到大重排", result: "\\(-6<ab<-1\\)",
      },
      conclusion: "\\(ab\\in(-6,-1)\\)", caption: "两个变量在开区间内独立连续变化，中间值均可取得，两个端点不能取到。",
    } })],
  ),
  lesson(
    "inequality-practice-q07", "解基础分式不等式", "实战演练 · 第 7 题", "inequality-practice",
    ["7. 不等式 \\(\\frac{3}{x-2}\\ge1\\) 的解集为　　　　（用区间表示）。"],
    "移项通分后，把分子零点和分母禁值点放入同一符号表。", ["x=2 是禁值点。", "不等号含等号，可取分子零点 x=5。"],
    [step("s1", "分式不等式", "移项通分后在数轴上穿线", [["because", "\\(\\frac{3}{x-2}-1=\\frac{5-x}{x-2}\\ge0\\iff(x-5)(x-2)\\le0，x\\ne2\\)"], ["because", "从最右侧正号开始穿，负号区域位于 2 与 5 之间"], ["therefore", "2 是分母禁值排除，5 是分子零点可取，解集为 (2,5]"]], [["解集", "(2,5]"]], { visual: rationalThreading({
      title: "分子零点可取，分母禁值必须排除", intro: "把零点和禁值点放在同一条穿针图上，阴影直接对应目标负号区域。",
      standardized: "\\(\\frac{3}{x-2}\\ge1\\iff(x-5)(x-2)\\le0，x\\ne2\\)",
      roots: [{ label: "2", kind: "denominator", included: false }, { label: "5", kind: "numerator", included: true }], signs: ["+", "-", "+"], selectSign: "-", target: "取负号区域，并保留允许的等号点", solution: "\\((2,5]\\)",
      facts: ["x=2 使原分母为 0，用带叉空心点排除。", "x=5 使分子为 0，题目含等号，用实心点并入。"],
    }) })],
  ),
  lesson(
    "inequality-practice-q08", "解含等号的分式不等式", "实战演练 · 第 8 题", "inequality-practice",
    ["8. 不等式 \\(\\frac{x+3}{2-x}\\ge0\\) 的解集为　　　　。"],
    "分别标出分子零点与分母禁值点。", ["x=-3 可以取。", "x=2 不能取。"],
    [step("s1", "分式不等式", "转化为乘积后穿针判号", [["because", "\\(\\frac{x+3}{2-x}\\ge0\\iff(x+3)(x-2)\\le0，x\\ne2\\)"], ["because", "从最右侧正号开始，两个单根之间为负"], ["therefore", "−3 可取，2 是禁值，解集为 [-3,2)"]], [["解集", "[-3,2)"]], { visual: rationalThreading({
      title: "同一条数轴区分零点与禁值点", intro: "先转成整式乘积判号，再单独保留分母不为 0 的条件。",
      standardized: "\\(\\frac{x+3}{2-x}\\ge0\\iff(x+3)(x-2)\\le0，x\\ne2\\)", roots: [{ label: "−3", kind: "numerator", included: true }, { label: "2", kind: "denominator", included: false }], signs: ["+", "-", "+"], selectSign: "-", target: "取负号区间", solution: "\\([-3,2)\\)", facts: ["−3 是分子零点，题目含等号，所以并入解集。", "2 是分母禁值，永远排除。"],
    }) })],
  ),
  lesson(
    "inequality-practice-q09", "移项通分解分式不等式", "实战演练 · 第 9 题", "inequality-practice",
    ["9. 不等式 \\(\\frac{3x+1}{2x-1}\\le1\\) 的解集为　　　　。"],
    "先移项通分，再判断分式的非正区间。", ["x=1/2 是禁值点。", "x=-2 是允许取到的零点。"],
    [step("s1", "分式不等式", "移到一侧，再用穿针图读取非正区域", [["because", "\\(\\frac{3x+1}{2x-1}-1=\\frac{x+2}{2x-1}\\le0\\iff(x+2)(2x-1)\\le0，x\\ne\\frac{1}{2}\\)"], ["because", "两个一次分界点之间乘积为负"], ["therefore", "−2 可取，1/2 是禁值，解集为 [-2,1/2)"]], [["解集", "[-2,1/2)"]], { visual: rationalThreading({
      title: "右边不是 0：先移项，不能直接交叉相乘", intro: "通分后再把分子零点和分母禁值点一起放入穿针图。",
      standardized: "\\(\\frac{3x+1}{2x-1}\\le1\\iff(x+2)(2x-1)\\le0，x\\ne\\frac{1}{2}\\)", roots: [{ label: "−2", kind: "numerator", included: true }, { label: "1/2", kind: "denominator", included: false }], signs: ["+", "-", "+"], selectSign: "-", target: "取非正区域", solution: "\\([-2,\\frac{1}{2})\\)", facts: ["−2 使通分后的分子为 0，可以取。", "1/2 使原分母为 0，必须排除。"],
    }) })],
  ),
  lesson(
    "inequality-practice-q10", "解因式型分式不等式", "实战演练 · 第 10 题", "inequality-practice",
    ["10. 不等式 \\(\\frac{(x+1)(2-x)}{x+4}\\ge0\\) 的解集为　　　　。"],
    "按顺序排列两个零点和一个禁值点。", ["x=-4 是禁值点。", "x=-1、2 是分子零点。"],
    [step("s1", "分式不等式", "三个分界点按顺序穿线", [["because", "\\(\\frac{(x+1)(2-x)}{x+4}\\ge0\\iff(x+4)(x+1)(x-2)\\le0，x\\ne-4\\)"], ["because", "−4、−1、2 都是单根，穿过每个点符号交替"], ["therefore", "取负号区域，排除禁值 −4，保留分子零点 −1、2，得到 (-∞,-4)∪[-1,2]"]], [["解集", "(-∞,-4)∪[-1,2]"]], { visual: rationalThreading({
      title: "三个分界点：禁值也参与穿线，但绝不进入解集", intro: "把最高次项系数化正后，从最右侧正号开始依次穿过 2、−1、−4。",
      standardized: "\\(\\frac{(x+1)(2-x)}{x+4}\\ge0\\iff(x+4)(x+1)(x-2)\\le0，x\\ne-4\\)", roots: [{ label: "−4", kind: "denominator", included: false }, { label: "−1", kind: "numerator", included: true }, { label: "2", kind: "numerator", included: true }], signs: ["-", "+", "-", "+"], selectSign: "-", target: "取负号区域", solution: "\\(( -\\infty,-4)\\cup[-1,2]\\)", facts: ["−4 是分母禁值，用带叉空心点排除。", "−1、2 是分子零点，题目含等号，所以并入解集。"],
    }) })],
  ),
  lesson(
    "inequality-practice-q11", "解右侧含常数的分式不等式", "实战演练 · 第 11 题", "inequality-practice",
    ["11. 不等式 \\(\\frac{x-3}{5-x}\\ge4\\) 的解集是　　　　。"],
    "移项通分时保留分母符号，不直接交叉相乘。", ["把 4 移到左侧。", "x=5 是禁值点。"],
    [step("s1", "分式不等式", "移项通分后穿线读取正号区域", [["because", "\\(\\frac{x-3}{5-x}-4=\\frac{5x-23}{5-x}\\ge0\\iff(5x-23)(x-5)\\le0，x\\ne5\\)"], ["because", "两个分界点 23/5、5 之间乘积为负"], ["therefore", "23/5 可取，5 是禁值，解集为 [23/5,5)"]], [["解集", "[23/5,5)"]], { visual: rationalThreading({
      title: "先统一到一侧为 0，再区分零点和禁值", intro: "不要在不知道分母正负时直接乘以 5−x。",
      standardized: "\\(\\frac{x-3}{5-x}\\ge4\\iff(5x-23)(x-5)\\le0，x\\ne5\\)", roots: [{ label: "23/5", kind: "numerator", included: true }, { label: "5", kind: "denominator", included: false }], signs: ["+", "-", "+"], selectSign: "-", target: "取负号区域", solution: "\\([\\frac{23}{5},5)\\)", facts: ["23/5 是分子零点，题目含等号，可以取。", "5 使原分母为 0，必须排除。"],
    }) })],
  ),
  lesson(
    "inequality-practice-q12", "解两个基础绝对值不等式", "实战演练 · 第 12 题", "inequality-practice",
    ["12. 解下列不等式：", "（1）\\(|5x-2|\\ge8\\)；", "（2）\\(2\\le|x-2|\\le4\\)。"],
    "先认出单个绝对值与正常数的比较，再直接套用对应规则。", ["大于取两边：|u|≥a⇔u≤−a 或 u≥a。", "小于取中间：|u|≤a⇔−a≤u≤a；双边限制分别求解后取交集。"],
    [
      step("s1", "绝对值不等式", "（1）直接套用“大于取两边”", [["because", "令 u=5x−2，a=8，由 |u|≥a⇔u≤−a 或 u≥a"], ["because", "代入得 5x−2≤−8 或 5x−2≥8"], ["therefore", "解得 x≤−6/5 或 x≥2"]], [["（1）", "(-∞,-6/5]∪[2,+∞)"]], { visual: {
        kind: "absolute-direct-rule-map", mode: "single", method: "直接法", title: "认准结构，大于取两边",
        intro: "把题目中的绝对值内部整体放进公式槽位，不需要先改写成距离。",
        original: "\\(|5x-2|\\ge8\\)",
        rules: [{
          index: "01", name: "大于取两边", template: "\\(|u|\\ge a\\iff u\\le-a\\text{ 或 }u\\ge a\\)",
          mappings: ["\\(u←5x-2\\)", "\\(a←8\\)"],
          substituted: "\\(5x-2\\le-8\\text{ 或 }5x-2\\ge8\\)",
          solved: "\\(x\\le-\\frac{6}{5}\\text{ 或 }x\\ge2\\)",
          solution: "\\(( -\\infty,-\\frac{6}{5}]\\cup[2,+\\infty)\\)",
        }],
        caption: "公式中的 u 是一个整体；先对号入座，再分别解两边的一元一次不等式。",
      } }),
      step("s2", "绝对值不等式", "（2）分别直接求解，再取交集", [["because", "2≤|x−2|≤4 等价于 |x−2|≥2 且 |x−2|≤4"], ["because", "大于取两边得 x≤0 或 x≥4；小于取中间得 −2≤x≤6"], ["therefore", "两个解集取交集，得到 [-2,0]∪[4,6]"]], [["（2）", "[-2,0]∪[4,6]"]], { visual: {
        kind: "absolute-direct-rule-map", mode: "intersection", method: "直接法", title: "双边限制：拆成两条，再取交集",
        intro: "一个 x 要同时满足左右两侧限制，所以先把连写不等式拆成“且”。",
        original: "\\(2\\le|x-2|\\le4\\)",
        rules: [
          {
            index: "01", name: "大于取两边", template: "\\(|u|\\ge a\\iff u\\le-a\\text{ 或 }u\\ge a\\)",
            mappings: ["\\(u←x-2\\)", "\\(a←2\\)"],
            substituted: "\\(x-2\\le-2\\text{ 或 }x-2\\ge2\\)",
            solved: "\\(x\\le0\\text{ 或 }x\\ge4\\)",
            solution: "\\(( -\\infty,0]\\cup[4,+\\infty)\\)",
          },
          {
            index: "02", name: "小于取中间", template: "\\(|u|\\le a\\iff-a\\le u\\le a\\)",
            mappings: ["\\(u←x-2\\)", "\\(a←4\\)"],
            substituted: "\\(-4\\le x-2\\le4\\)",
            solved: "\\(-2\\le x\\le6\\)",
            solution: "\\([-2,6]\\)",
          },
        ],
        intersection: {
          label: "同时成立＝取交集",
          expression: "\\((( -\\infty,0]\\cup[4,+\\infty))\\cap[-2,6]\\)",
          result: "\\([-2,0]\\cup[4,6]\\)",
        },
        caption: "双边绝对值不等式的关键不是分类讨论，而是把两条直接法结果取交集。",
      } }),
    ],
  ),
  lesson(
    "inequality-practice-q13", "分段解绝对值不等式", "实战演练 · 第 13 题", "inequality-practice",
    ["13. 解下列不等式：", "（1）\\(|x+1|+|x-1|\\ge3\\)；", "（2）\\(|x-3|-|x+1|<1\\)。"],
    "多个绝对值先找零点分区，再在每个区间内去绝对值。", ["零点只负责划分区间。", "每段结果要与本段范围取交集，最后合并。"],
    [
      step("s1", "绝对值不等式", "（1）找零点分区，逐段去绝对值", [["because", "绝对值内部在 x=-1、1 处为零，因此分成三个区间讨论"], ["because", "各段根据内部符号去绝对值，并把求得结果与本段范围取交集"], ["therefore", "合并三个区间的结果，得 (-∞,-3/2]∪[3/2,+∞)"]], [["（1）", "(-∞,-3/2]∪[3/2,+∞)"]], { visual: {
        kind: "absolute-case-analysis", method: "分类讨论法", title: "找零点分区，逐段去绝对值",
        intro: "零点只负责切分区间；每一段都要重新判断绝对值内部的符号。",
        original: "\\(|x+1|+|x-1|\\ge3\\)",
        breakpoints: [
          { equation: "\\(x+1=0\\)", value: "\\(x=-1\\)", numeric: -1 },
          { equation: "\\(x-1=0\\)", value: "\\(x=1\\)", numeric: 1 },
        ],
        cases: [
          { index: "01", interval: "\\(x\\le-1\\)", signs: "\\(x+1\\le0，x-1<0\\)", rewrite: "\\(-(x+1)-(x-1)=-2x\\)", inequality: "\\(-2x\\ge3\\)", result: "\\(x\\le-\\frac{3}{2}\\)" },
          { index: "02", interval: "\\(-1<x<1\\)", signs: "\\(x+1>0，x-1<0\\)", rewrite: "\\((x+1)-(x-1)=2\\)", inequality: "\\(2\\ge3\\)", result: "\\(\\varnothing\\)" },
          { index: "03", interval: "\\(x\\ge1\\)", signs: "\\(x+1>0，x-1\\ge0\\)", rewrite: "\\((x+1)+(x-1)=2x\\)", inequality: "\\(2x\\ge3\\)", result: "\\(x\\ge\\frac{3}{2}\\)" },
        ],
        graph: {
          xRange: [-3, 3], yRange: [0, 6],
          pieces: [{ from: -3, to: -1, slope: -2, intercept: 0 }, { from: -1, to: 1, slope: 0, intercept: 2 }, { from: 1, to: 3, slope: 2, intercept: 0 }],
          threshold: { value: 3, label: "y=3", relation: "ge" },
          ticks: [{ value: -1.5, label: "−3/2" }, { value: -1, label: "−1" }, { value: 1, label: "1" }, { value: 1.5, label: "3/2" }],
          solutionSegments: [{ start: null, end: -1.5, left: "ray", right: "closed" }, { start: 1.5, end: null, left: "closed", right: "ray" }],
        },
        merge: { label: "合并各段", result: "\\(( -\\infty,-\\frac{3}{2}]\\cup[\\frac{3}{2},+\\infty)\\)" },
        caption: "函数图像只用于核对：阈值交点由分段函数自动计算，必须落在对应线段上。",
      } }),
      step("s2", "绝对值不等式", "（2）逐段求解，再合并解集", [["because", "绝对值内部在 x=-1、3 处为零，分成三个区间"], ["because", "前一段不成立，中间段得到 x>1/2，后一段恒成立"], ["therefore", "分别与各自区间取交集后合并，解集为 (1/2,+∞)"]], [["（2）", "(1/2,+∞)"]], { visual: {
        kind: "absolute-case-analysis", method: "分类讨论法", title: "分段判断符号，段内求解",
        intro: "先按零点分区，再逐段去绝对值；不要从最终图像反猜代数过程。",
        original: "\\(|x-3|-|x+1|<1\\)",
        breakpoints: [
          { equation: "\\(x+1=0\\)", value: "\\(x=-1\\)", numeric: -1 },
          { equation: "\\(x-3=0\\)", value: "\\(x=3\\)", numeric: 3 },
        ],
        cases: [
          { index: "01", interval: "\\(x<-1\\)", signs: "\\(x-3<0，x+1<0\\)", rewrite: "\\(-(x-3)+ (x+1)=4\\)", inequality: "\\(4<1\\)", result: "\\(\\varnothing\\)" },
          { index: "02", interval: "\\(-1\\le x<3\\)", signs: "\\(x-3<0，x+1\\ge0\\)", rewrite: "\\(-(x-3)-(x+1)=2-2x\\)", inequality: "\\(2-2x<1\\)", result: "\\(\\frac{1}{2}<x<3\\)" },
          { index: "03", interval: "\\(x\\ge3\\)", signs: "\\(x-3\\ge0，x+1>0\\)", rewrite: "\\((x-3)-(x+1)=-4\\)", inequality: "\\(-4<1\\)", result: "\\([3,+\\infty)\\)" },
        ],
        graph: {
          xRange: [-3, 5], yRange: [-5, 5],
          pieces: [{ from: -3, to: -1, slope: 0, intercept: 4 }, { from: -1, to: 3, slope: -2, intercept: 2 }, { from: 3, to: 5, slope: 0, intercept: -4 }],
          threshold: { value: 1, label: "y=1", relation: "lt" },
          ticks: [{ value: -1, label: "−1" }, { value: 0.5, label: "1/2" }, { value: 3, label: "3" }],
          solutionSegments: [{ start: 0.5, end: null, left: "open", right: "ray" }],
        },
        merge: { label: "合并各段", result: "\\((\\frac{1}{2},+\\infty)\\)" },
        caption: "图像核对中，x=1/2 是中间线段与 y=1 的真实交点。",
      } }),
    ],
  ),
];

for (const item of lessons) {
  const dir = path.join(specsRoot, item.meta.id);
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(dir, "lesson-data.json"), `${JSON.stringify(item, null, 2)}\n`);
}

console.log(`Generated ${lessons.length} basic-inequality and practice lessons.`);
