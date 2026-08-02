#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const lessonRoot = path.join(repoRoot, "internal/senior-high/lesson-specs");

const commonMeta = {
  breadcrumbLabel: "集合的表示",
  breadcrumbPath: "site/senior-high/index.html",
  breadcrumbSearch: "?chapter=sets&section=set-concepts-and-representation&module=set-representation",
};

function lesson(id, title, group, problemLines, keyPoints, steps, source = "培训教材 · 集合的表示") {
  return {
    meta: {
      id,
      outputPath: `site/problems/senior-high/sets/set-concepts-and-representation/${id}.html`,
      pageTitle: title,
      pageDescription: `${group}专题：${title}。`,
      breadcrumbTitle: `集合的表示 · ${title}`,
      ...commonMeta,
    },
    problem: {
      source,
      keyPoints: {
        title: "解题要点",
        lead: keyPoints[0],
        items: keyPoints.slice(1),
      },
      lines: problemLines.map((line) => typeof line === "string" ? { text: line } : line),
    },
    steps: steps.map((step, index) => ({
      id: `s${index + 1}`,
      section: group,
      title: step.title,
      t: index,
      showDiagram: false,
      ...(step.table ? { table: step.table } : {}),
      ...(step.visual ? { visual: step.visual } : {}),
      ...(step.reasoning ? { reasoning: step.reasoning } : {}),
      derive: step.derive,
    })),
    policies: Object.fromEntries(steps.map((_, index) => [`s${index + 1}`, {
      movable: false,
      range: [index, index],
    }])),
    stepLabels: Object.fromEntries(steps.map((step, index) => [
      `s${index + 1}`,
      `${index + 1} ${step.short || step.title}`,
    ])),
  };
}

const lessons = [
  lesson("set-representation-enumeration-q01", "列举指定范围内的整数", "列举法", [
    "用列举法表示大于 1 且小于 6 的整数所组成的集合。",
  ], [
    "先根据范围确定可能的整数，再用花括号逐一列出。",
    "列举时不遗漏、不重复，元素之间用逗号分隔。",
  ], [{
    title: "筛选并列出全部元素",
    reasoning: [
      { kind: "because", text: "\\(x\\in\\mathbb Z\\)，且 \\(1<x<6\\)" },
      { kind: "therefore", text: "\\(x=2,3,4,5\\)" },
      { kind: "therefore", text: "所求集合为 \\(\\{2,3,4,5\\}\\)" },
    ],
    derive: [["整数范围", "\\(1<x<6\\)"], ["结论", "\\(\\{2,3,4,5\\}\\)"]],
  }]),
  lesson("set-representation-enumeration-q02", "用解集表示方程组的解", "列举法", [
    "方程组 \\(x+y=4，x-y=2\\) 的解集为（　）。",
    "A. \\(\\{3,1\\}\\)　B. \\(\\{(3,1)\\}\\)　C. \\((3,1)\\)　D. \\(\\{(1,3)\\}\\)",
  ], [
    "方程组的一个解是一个有序数对，解集还必须用花括号表示。",
    "区分元素、有序数对和只含一个有序数对的集合。",
  ], [{
    title: "先求解，再辨认集合层级",
    reasoning: [
      { kind: "because", text: "方程组为 \\(x+y=4，x-y=2\\)" },
      { kind: "therefore", text: "\\(x=3,y=1\\)" },
      { kind: "therefore", text: "方程组的解是有序数对 \\((3,1)\\)" },
      { kind: "therefore", text: "解集为 \\(\\{(3,1)\\}\\)，选择 B" },
    ],
    derive: [["解方程组", "\\(x=3,y=1\\)"], ["解集", "\\(\\{(3,1)\\}\\)，选择 B"]],
  }]),
  lesson("set-representation-enumeration-q03", "辨认方程组解集的正确写法", "列举法", [
    "方程组 \\(x+y=3，x-y=1\\) 的解集是：① \\(\\{2,1\\}\\)；② \\(\\{x=2,y=1\\}\\)；③ \\(\\{(2,1)\\}\\)；④ \\(\\{(1,2)\\}\\)。",
  ], [
    "二元方程组的解是有序数对。",
    "解集是以这个有序数对为元素的集合。",
  ], [{
    title: "确定有序数对及其外层集合",
    reasoning: [
      { kind: "because", text: "方程组为 \\(x+y=3，x-y=1\\)" },
      { kind: "therefore", text: "\\(x=2,y=1\\)" },
      { kind: "therefore", text: "方程组的解是有序数对 \\((2,1)\\)" },
      { kind: "therefore", text: "解集为 \\(\\{(2,1)\\}\\)，选择 ③" },
    ],
    derive: [["方程组的解", "\\((2,1)\\)"], ["结论", "解集是 \\(\\{(2,1)\\}\\)，选 ③"]],
  }]),
  lesson("set-representation-enumeration-q04", "由元素属于集合求参数", "列举法", [
    "设集合 \\(A=\\{2,a+2,2a^2+a\\}\\)，若 \\(3\\in A\\)，求 \\(a\\)。",
  ], [
    "元素 3 可能由集合中的任一含参式产生。",
    "得到候选值后必须利用元素互异性排除使元素重复的情况。",
  ], [{
    title: "分类产生候选参数",
    reasoning: [
      { kind: "because", text: "\\(3\\in A\\)，且集合中已有元素 \\(2\\)" },
      { kind: "therefore", text: "\\(a+2=3\\) 或 \\(2a^2+a=3\\)" },
      { kind: "therefore", text: "候选值为 \\(a=1\\) 或 \\(a=-\\frac{3}{2}\\)" },
    ],
    derive: [["\\(a+2=3\\)", "\\(a=1\\)"], ["\\(2a^2+a=3\\)", "\\(a=1\\) 或 \\(a=-\\frac{3}{2}\\)"]],
  }, {
    title: "代回集合检查互异性",
    reasoning: [
      { kind: "because", text: "当 \\(a=1\\) 时，\\(A=\\{2,3,3\\}\\)，元素重复" },
      { kind: "therefore", text: "舍去 \\(a=1\\)" },
      { kind: "therefore", text: "\\(a=-\\frac{3}{2}\\)" },
    ],
    derive: [["\\(a=1\\)", "\\(A=\\{2,3,3\\}\\)，不满足三个元素互异"], ["结论", "\\(a=-\\frac{3}{2}\\)"]],
  }]),
  lesson("set-representation-enumeration-q05", "检查集合中的参数候选值", "列举法", [
    "已知集合 \\(A=\\{0,m,m^2-2m+3\\}\\)，且 \\(3\\in A\\)，则实数 \\(m\\) 为（　）。",
    "A. \\(2\\)　B. \\(3\\)　C. \\(2\\) 或 \\(3\\)　D. \\(0\\) 或 \\(2\\) 或 \\(3\\)",
  ], [
    "3 可以等于 m，也可以等于第三个代数式。",
    "三个列出的代数式表示集合中的三个元素，候选值还必须满足元素互异性。",
  ], [{
    title: "分类得到候选值",
    reasoning: [
      { kind: "because", text: "\\(3\\in A\\)，且集合中已有元素 \\(0\\)" },
      { kind: "therefore", text: "\\(m=3\\) 或 \\(m^2-2m+3=3\\)" },
      { kind: "therefore", text: "候选值为 \\(m=0,2,3\\)" },
    ],
    derive: [["\\(m=3\\)", "得到候选值 \\(m=3\\)"], ["\\(m^2-2m+3=3\\)", "\\(m=0\\) 或 \\(m=2\\)"]],
  }, {
    title: "检查集合中元素的互异性",
    reasoning: [
      { kind: "because", text: "当 \\(m=0\\) 时，\\(A=\\{0,0,3\\}\\)，前两个元素重复" },
      { kind: "therefore", text: "舍去 \\(m=0\\)" },
      { kind: "therefore", text: "\\(m=2\\) 或 \\(m=3\\)，选择 C" },
    ],
    derive: [["\\(m=0\\)", "\\(A=\\{0,0,3\\}\\)，前两个元素重复，舍去"], ["结论", "\\(m=2\\) 或 \\(m=3\\)，选择 C"]],
  }]),
  lesson("set-representation-enumeration-q06", "利用两个列举集合相等求值", "列举法", [
    "含有 3 个实数的集合可表示为 \\(\\{a,\\frac{b}{a},1\\}\\)，又可表示为 \\(\\{a^2,a+b,0\\}\\)，求 \\(a^{2019}+b^{2019}\\)。",
  ], [
    "两个集合相等意味着元素完全相同，但排列顺序可以不同。",
    "先利用 0 必须出现在第一个集合中确定 b，再利用互异性确定 a。",
  ], [{
    title: "由零元素确定参数",
    reasoning: [
      { kind: "because", text: "分式 \\(\\frac{b}{a}\\) 有意义" },
      { kind: "therefore", text: "\\(a\\ne0\\)" },
      { kind: "because", text: "两个集合相等，且右侧集合含有元素 \\(0\\)" },
      { kind: "therefore", text: "\\(\\frac{b}{a}=0\\)，所以 \\(b=0\\)" },
    ],
    derive: [["分式 \\(\\frac{b}{a}\\) 有意义", "\\(a\\ne0\\)"], ["\\(0\\in\\{a,\\frac{b}{a},1\\}\\)", "\\(b=0\\)"]],
  }, {
    title: "比较剩余元素",
    reasoning: [
      { kind: "because", text: "\\(b=0\\)，且两个集合相等" },
      { kind: "therefore", text: "\\(\\{a,0,1\\}=\\{a^2,a,0\\}\\)" },
      { kind: "because", text: "集合含有 3 个互异的实数" },
      { kind: "therefore", text: "\\(a=-1\\)" },
      { kind: "therefore", text: "\\(a^{2019}+b^{2019}=-1\\)" },
    ],
    derive: [["集合相等", "\\(\\{a,0,1\\}=\\{a^2,a,0\\}\\)"], ["互异性", "\\(a=-1\\)"], ["结论", "\\(a^{2019}+b^{2019}=-1\\)"]],
  }]),

  lesson("set-representation-description-q01", "读懂描述法中代表元素的含义", "描述法", [
    "试用自然语言叙述下列集合所包含的元素：",
    "（1）\\(\\{x\\in\\mathbb R\\mid x<4\\}\\)；（2）\\(\\{y\\in\\mathbb R\\mid y<4\\}\\)；（3）\\(\\{y\\in\\mathbb N\\mid y<4\\}\\)；",
    "（4）\\(\\{x\\mid y=x^2+1\\}\\)；（5）\\(\\{y\\mid y=x^2+1\\}\\)；（6）\\(\\{(x,y)\\mid y=x^2+1\\}\\)。",
  ], [
    "先看竖线左侧的代表元素，再读右侧共同特征。",
    "x、y 或 (x,y) 分别表示横坐标、纵坐标或点，不能只看条件式。",
  ], [{
    title: "按代表元素分类解释",
    reasoning: [
      { kind: "because", text: "（1）（2）的代表元素都是实数，且共同满足 \\(x<4\\) 或 \\(y<4\\)" },
      { kind: "therefore", text: "（1）（2）都表示小于 4 的全体实数" },
      { kind: "because", text: "（3）的代表元素 \\(y\\in\\mathbb N\\)，且 \\(y<4\\)" },
      { kind: "therefore", text: "（3）表示 \\(\\{0,1,2,3\\}\\)" },
      { kind: "because", text: "（4）的代表元素是 \\(x\\)，而方程 \\(y=x^2+1\\) 对任意 \\(x\\in\\mathbb R\\) 都有实数 \\(y\\) 与之对应" },
      { kind: "therefore", text: "（4）表示全体实数 \\(\\mathbb R\\)" },
      { kind: "because", text: "（5）的代表元素是 \\(y\\)，且 \\(y=x^2+1\\ge1\\)；反之每个 \\(y\\ge1\\) 都可由 \\(x=\\pm\\sqrt{y-1}\\) 取得" },
      { kind: "therefore", text: "（5）表示 \\([1,+∞)\\)" },
      { kind: "because", text: "（6）的代表元素是有序数对 \\((x,y)\\)，并满足 \\(y=x^2+1\\)" },
      { kind: "therefore", text: "（6）表示抛物线 \\(y=x^2+1\\) 上所有点组成的集合" },
    ],
    table: {
      headers: ["小题", "代表元素", "集合含义"],
      rows: [
        ["（1）（2）", "实数", "小于 4 的全体实数"],
        ["（3）", "自然数", "\\(\\{0,1,2,3\\}\\)"],
        ["（4）", "x", "抛物线横坐标的集合，即 \\(\\mathbb R\\)"],
        ["（5）", "y", "抛物线纵坐标的集合，即 \\([1,+∞)\\)"],
        ["（6）", "(x,y)", "抛物线 \\(y=x^2+1\\) 上所有点的集合"],
      ],
    },
    derive: [["关键", "描述法由“代表元素”和“共同特征”两部分共同决定"]],
  }]),
  lesson("set-representation-description-q02", "把描述法集合改写为列举法", "描述法", [
    "用列举法表示集合 \\(A=\\{x\\mid 3x-1\\le11, x\\in\\mathbb N\\}\\)。",
  ], [
    "先解不等式，再与自然数集取交集。",
  ], [{
    title: "解条件并列举自然数",
    reasoning: [
      { kind: "because", text: "\\(3x-1\\le11\\)" },
      { kind: "therefore", text: "\\(3x\\le12\\)，即 \\(x\\le4\\)" },
      { kind: "because", text: "\\(x\\in\\mathbb N\\)" },
      { kind: "therefore", text: "\\(x\\in\\{0,1,2,3,4\\}\\)，所以 \\(A=\\{0,1,2,3,4\\}\\)" },
    ],
    derive: [["\\(3x-1\\le11\\)", "\\(x\\le4\\)"], ["\\(x\\in\\mathbb N\\)", "\\(A=\\{0,1,2,3,4\\}\\)"]],
  }], "2023 南开中学第一次月考"),
  lesson("set-representation-description-q03", "列举不等式中的整数解", "描述法", [
    "集合 \\(\\{x\\in\\mathbb Z\\mid -3<2x-1<3\\}\\) 用列举法表示。",
  ], [
    "先解双边不等式，再筛选整数。",
    "严格不等号对应的端点不能取。",
  ], [{
    title: "化简范围并筛选整数",
    reasoning: [
      { kind: "because", text: "\\(-3<2x-1<3\\)" },
      { kind: "therefore", text: "\\(-2<2x<4\\)，所以 \\(-1<x<2\\)" },
      { kind: "because", text: "\\(x\\in\\mathbb Z\\)" },
      { kind: "therefore", text: "\\(x=0\\) 或 \\(x=1\\)，所以所求集合为 \\(\\{0,1\\}\\)" },
    ],
    derive: [["\\(-3<2x-1<3\\)", "\\(-1<x<2\\)"], ["结论", "\\(\\{0,1\\}\\)"]],
  }]),
  lesson("set-representation-description-q04", "列举含整除条件的集合", "描述法", [
    "用列举法表示集合 \\(\\{x\\mid \\frac{6}{2-x}\\in\\mathbb Z, x\\in\\mathbb Z\\}\\)。",
  ], [
    "令 d=2-x，则 d 是 6 的非零整数因数。",
    "列出正、负因数后分别还原 x，避免遗漏。",
  ], [{
    title: "把分式整除转化为因数问题",
    reasoning: [
      { kind: "because", text: "令 \\(d=2-x\\)，且 \\(x\\in\\mathbb Z\\)、\\(\\frac{6}{2-x}\\in\\mathbb Z\\)" },
      { kind: "therefore", text: "\\(d\\in\\mathbb Z\\)、\\(d\\ne0\\)，且 \\(d\\mid6\\)" },
      { kind: "therefore", text: "\\(d\\in\\{-6,-3,-2,-1,1,2,3,6\\}\\)" },
      { kind: "because", text: "\\(x=2-d\\)" },
      { kind: "therefore", text: "所求集合为 \\(\\{-4,-1,0,1,3,4,5,8\\}\\)" },
    ],
    derive: [["\\(d=2-x\\)", "\\(d\\in\\{±1,±2,±3,±6\\}\\)"], ["结论", "\\(\\{-4,-1,0,1,3,4,5,8\\}\\)"]],
  }]),
  lesson("set-representation-description-q05", "列举有限范围内的有理数", "描述法", [
    "用列举法表示集合 \\(\\{x\\mid x=\\frac{a}{b}, a\\in\\mathbb Z, |a|<2, b\\in\\mathbb N^*, b<3\\}\\)。",
  ], [
    "分别列出 a、b 的有限取值，再计算所有商。",
    "集合中的相同结果只保留一次。",
  ], [{
    title: "枚举参数并去重",
    reasoning: [
      { kind: "because", text: "\\(a\\in\\mathbb Z\\)，且 \\(|a|<2\\)" },
      { kind: "therefore", text: "\\(a\\in\\{-1,0,1\\}\\)" },
      { kind: "because", text: "\\(b\\in\\mathbb N^*\\)，且 \\(b<3\\)" },
      { kind: "therefore", text: "\\(b\\in\\{1,2\\}\\)" },
      { kind: "therefore", text: "当 \\(b=1\\) 时，\\(\\frac{a}{b}\\in\\{-1,0,1\\}\\)；当 \\(b=2\\) 时，\\(\\frac{a}{b}\\in\\{-\\frac{1}{2},0,\\frac{1}{2}\\}\\)" },
      { kind: "therefore", text: "去掉重复元素后，所求集合为 \\(\\{-1,-\\frac{1}{2},0,\\frac{1}{2},1\\}\\)" },
    ],
    derive: [["\\(a\\in\\{-1,0,1\\},b\\in\\{1,2\\}\\)", "计算所有 \\(\\frac{a}{b}\\)"], ["结论", "\\(\\{-1,-\\frac{1}{2},0,\\frac{1}{2},1\\}\\)"]],
  }]),
  lesson("set-representation-description-q06", "列举满足条件的有序数对", "描述法", [
    "用列举法表示集合 \\(\\{(x,y)\\mid y=2x, x\\in\\mathbb N, 1\\le x<4\\}\\)。",
  ], [
    "代表元素是有序数对 (x,y)，不能只列出 x 或 y。",
    "按 x=1,2,3 依次计算对应的 y。",
  ], [{
    title: "逐个生成有序数对",
    reasoning: [
      { kind: "because", text: "\\(x\\in\\mathbb N\\)，且 \\(1\\le x<4\\)" },
      { kind: "therefore", text: "\\(x=1,2,3\\)" },
      { kind: "because", text: "\\(y=2x\\)" },
      { kind: "therefore", text: "对应的有序数对依次为 \\((1,2),(2,4),(3,6)\\)" },
      { kind: "therefore", text: "所求集合为 \\(\\{(1,2),(2,4),(3,6)\\}\\)" },
    ],
    derive: [["\\(x=1,2,3\\)", "\\(y=2,4,6\\)"], ["结论", "\\(\\{(1,2),(2,4),(3,6)\\}\\)"]],
  }]),
  lesson("set-representation-description-q07", "辨析不同形式表示的集合", "描述法", [
    "下列四组中表示同一集合的为（　）。",
    "A. \\(M=\\{(-1,3)\\},N=\\{(3,-1)\\}\\)　B. \\(M=\\{-1,3\\},N=\\{3,-1\\}\\)　C. \\(M=\\{(x,y)\\mid y=x^2+3x\\},N=\\{x\\mid y=x^2+3x\\}\\)　D. \\(M=\\{0\\},N=0\\)",
  ], [
    "先比较代表元素的类型，再比较元素是否完全相同。",
    "集合无序，但有序数对有顺序；集合与集合中的一个元素也不同。",
  ], [{
    title: "逐项比较元素与类型",
    reasoning: [
      { kind: "because", text: "A 中两个集合的元素分别是有序数对 \\((-1,3)\\) 与 \\((3,-1)\\)，而有序数对的顺序不能交换" },
      { kind: "therefore", text: "A 中 \\(M\\ne N\\)" },
      { kind: "because", text: "B 中 \\(M\\) 与 \\(N\\) 都由数 \\(-1,3\\) 组成，集合中元素的排列顺序不影响集合" },
      { kind: "therefore", text: "B 中 \\(M=N\\)" },
      { kind: "because", text: "C 中 \\(M\\) 的元素是有序数对，\\(N\\) 的元素是数；D 中 \\(M\\) 是集合，\\(N\\) 是数 \\(0\\)" },
      { kind: "therefore", text: "C、D 均不表示同一集合，所以选择 B" },
    ],
    derive: [["B", "两个集合都含有 -1 和 3，顺序不影响集合"], ["结论", "选择 B"]],
  }]),
  lesson("set-representation-description-q08", "由取值范围判断集合相等", "描述法", [
    "下列集合中表示同一集合的是（　）。",
    "A. \\(M=\\{(3,2)\\},N=\\{(2,3)\\}\\)　B. \\(M=\\{(x,y)\\mid x+y=1\\},N=\\{y\\mid x+y=1\\}\\)　C. \\(M=\\{1,2\\},N=\\{(1,2)\\}\\)　D. \\(M=\\{y\\mid y=x^2+3\\},N=\\{x\\mid y=\\sqrt{x-3}\\}\\)",
  ], [
    "描述法集合相等既要代表元素类型相同，也要取值范围相同。",
    "D 中两个集合分别是两个函数的值域和定义域。",
  ], [{
    title: "求出两个描述集合的范围",
    reasoning: [
      { kind: "because", text: "A 中两个集合分别只含 \\((3,2)\\) 与 \\((2,3)\\)，C 中一个集合的元素是数，另一个集合的元素是有序数对" },
      { kind: "therefore", text: "A、C 中的两个集合均不相等" },
      { kind: "because", text: "B 中 \\(M\\) 的元素是有序数对，\\(N\\) 的元素是数" },
      { kind: "therefore", text: "B 中 \\(M\\ne N\\)" },
      { kind: "because", text: "D 中 \\(y=x^2+3\\)，所以 \\(M=\\{y\\mid y\\ge3\\}\\)；又因为 \\(y=\\sqrt{x-3}\\) 要求 \\(x\\ge3\\)，所以 \\(N=\\{x\\mid x\\ge3\\}\\)" },
      { kind: "therefore", text: "D 中 \\(M=N=[3,+∞)\\)，所以选择 D" },
    ],
    derive: [["\\(y=x^2+3\\)", "\\(y\\ge3\\)"], ["\\(y=\\sqrt{x-3}\\)", "\\(x\\ge3\\)"], ["结论", "两者均为 \\([3,+∞)\\)，选择 D"]],
  }]),
  lesson("set-representation-description-q09", "按乘积条件统计有序数对", "描述法", [
    "已知 \\(A=\\{1,2,4,5,6\\}\\)，\\(B=\\{(x,y)\\mid x\\in A,y\\in A,xy\\in A\\}\\)，求集合 B 的元素个数。",
  ], [
    "B 的元素是有序数对，(x,y) 与 (y,x) 通常不同。",
    "集合不大时枚举所有情况；集合较大时先枚举部分情况，从中发现规律后再计数。",
  ], [{
    title: "枚举所有符合条件的有序数对",
    reasoning: [
      { kind: "because", text: "\\(B\\) 的元素是满足 \\(x,y\\in A\\) 且 \\(xy\\in A\\) 的有序数对" },
      { kind: "therefore", text: "固定 \\(x=1,2,4,5,6\\) 时，符合条件的 \\(y\\) 的个数依次为 \\(5,2,1,1,1\\)" },
      { kind: "because", text: "不同的 \\(x\\) 或 \\(y\\) 产生不同的有序数对" },
      { kind: "therefore", text: "\\(|B|=5+2+1+1+1=10\\)" },
    ],
    table: {
      headers: ["x", "可取的 y", "个数"],
      rows: [["1", "1,2,4,5,6", "5"], ["2", "1,2", "2"], ["4", "1", "1"], ["5", "1", "1"], ["6", "1", "1"]],
    },
    derive: [["合计", "\\(5+2+1+1+1=10\\)"]],
  }]),
  lesson("set-representation-description-q10", "按新定义运算列举集合", "描述法", [
    "若 \\(A=\\{1,2,3\\},B=\\{3,5\\}\\)，用列举法表示 \\(A*B=\\{2a-b\\mid a\\in A,b\\in B\\}\\)。",
  ], [
    "把 A、B 中元素的所有搭配代入 2a-b。",
    "结果相同的数在集合中只保留一次。",
  ], [{
    title: "列出全部运算结果并去重",
    reasoning: [
      { kind: "because", text: "当 \\(a=1,2,3\\)，\\(b=3,5\\) 时，需要计算全部六种 \\(2a-b\\)" },
      { kind: "therefore", text: "所得结果依次为 \\(-1,-3,1,-1,3,1\\)" },
      { kind: "because", text: "集合中的相同元素只保留一次" },
      { kind: "therefore", text: "\\(A*B=\\{-3,-1,1,3\\}\\)" },
    ],
    table: {
      headers: ["a", "b=3 时的 2a-b", "b=5 时的 2a-b"],
      rows: [["1", "-1", "-3"], ["2", "1", "-1"], ["3", "3", "1"]],
    },
    derive: [["所有结果", "\\(-1,-3,1,-1,3,1\\)"], ["结论", "\\(A*B=\\{-3,-1,1,3\\}\\)"]],
  }]),
  lesson("set-representation-description-q11", "按差值条件统计有序数对", "描述法", [
    "若 \\(A=\\{0,1,2,3\\}\\)，\\(B=\\{(x,y)\\mid x\\in A,y\\in A,x-y\\in A\\}\\)，求 B 中元素的个数。",
  ], [
    "条件 x-y∈A 等价于 x≥y。",
    "固定 x 时，y 可取 0 到 x，共 x+1 个。",
  ], [{
    title: "逐行列出符合条件的有序数对",
    reasoning: [
      { kind: "because", text: "\\(x,y\\in A=\\{0,1,2,3\\}\\)，且 \\(x-y\\in A\\)" },
      { kind: "therefore", text: "\\(x-y\\ge0\\)，即 \\(x\\ge y\\)" },
      { kind: "because", text: "固定 \\(x=0,1,2,3\\) 时，\\(y\\) 分别有 \\(1,2,3,4\\) 种取值" },
      { kind: "therefore", text: "\\(|B|=1+2+3+4=10\\)" },
    ],
    table: {
      headers: ["x", "可取的 y", "得到的有序数对", "个数"],
      rows: [
        ["0", "0", "(0,0)", "1"],
        ["1", "0,1", "(1,0),(1,1)", "2"],
        ["2", "0,1,2", "(2,0),(2,1),(2,2)", "3"],
        ["3", "0,1,2,3", "(3,0),(3,1),(3,2),(3,3)", "4"],
      ],
    },
    derive: [["各行个数", "\\(1,2,3,4\\)"], ["结论", "\\(|B|=1+2+3+4=10\\)"]],
  }]),
  lesson("set-representation-description-q12", "求差值封闭时有序数对的最大数量", "描述法", [
    "已知集合 \\(A=\\{a_1,a_2,\\ldots,a_{20}\\}\\)，且 \\(a_k>0\\)。集合 \\(B=\\{(a,b)\\mid a\\in A,b\\in A,a-b\\in A\\}\\)，求 B 中元素至多有多少个。",
  ], [
    "由于 A 中元素都为正数，a-b∈A 必有 a>b。",
    "先将 A 中 20 个互异正数从小到大重新编号，再按每个元素前面较小元素的个数计数。",
  ], [{
    title: "从小到大排列并找计数规律",
    reasoning: [
      { kind: "because", text: "集合 \\(A\\) 由 20 个互异的正数组成" },
      { kind: "therefore", text: "可将其元素从小到大重新编号为 \\(0<a_1<a_2<\\cdots<a_{20}\\)" },
      { kind: "because", text: "\\(a-b\\in A\\)，且 \\(A\\) 中所有元素都为正数" },
      { kind: "therefore", text: "必须有 \\(a>b\\)" },
      { kind: "because", text: "当 \\(a=a_i\\) 时，它前面恰有 \\(i-1\\) 个较小元素，所以 \\(b\\) 至多有 \\(i-1\\) 种取值" },
      { kind: "therefore", text: "\\(|B|\\le0+1+2+\\cdots+19=\\frac{20×19}{2}=190\\)" },
      { kind: "because", text: "取 \\(A=\\{1,2,\\ldots,20\\}\\) 时，每一对 \\(a>b\\) 都有 \\(a-b\\in A\\)" },
      { kind: "therefore", text: "上界可以达到，所以 \\(B\\) 中元素至多有 \\(190\\) 个" },
    ],
    table: {
      caption: "将 A 中的元素从小到大重新编号：\\(0<a_1<a_2<\\cdots<a_{20}\\)",
      headers: ["a=aᵢ 的位置", "比 aᵢ 小的元素个数", "可形成的 (a,b) 个数"],
      rows: [
        ["a=a₁（最小）", "0", "0"],
        ["a=a₂", "1", "1"],
        ["a=a₃", "2", "2"],
        ["……", "……", "……"],
        ["a=a₂₀（最大）", "19", "19"],
      ],
    },
    derive: [["上界", "\\(19+18+\\ldots+1=190\\)"], ["可达性", "取 \\(A=\\{1,2,\\ldots,20\\}\\) 时所有正差仍在 A"], ["结论", "至多 190 个"]],
  }]),
  lesson("set-representation-description-q13", "计算新定义集合中元素之和", "描述法", [
    "定义 \\(A*B=\\{z\\mid z=x^2(y-1),x\\in A,y\\in B\\}\\)。若 \\(A=\\{-1,1\\},B=\\{0,2\\}\\)，求集合 A*B 中所有元素之和。",
    "A. \\(0\\)　B. \\(1\\)　C. \\(2\\)　D. \\(3\\)",
  ], [
    "先利用 x² 恒为 1 简化运算。",
    "集合要去重后再求元素之和。",
  ], [{
    title: "列出全部运算结果并去重",
    reasoning: [
      { kind: "because", text: "\\(x\\in\\{-1,1\\}\\)，所以无论 \\(x\\) 取何值都有 \\(x^2=1\\)" },
      { kind: "therefore", text: "\\(z=x^2(y-1)=y-1\\)" },
      { kind: "because", text: "\\(y\\in\\{0,2\\}\\)" },
      { kind: "therefore", text: "\\(z\\in\\{-1,1\\}\\)，所以集合中所有元素之和为 \\(-1+1=0\\)，选择 A" },
    ],
    table: {
      headers: ["x", "x²", "y", "z=x²(y-1)"],
      rows: [
        ["-1", "1", "0", "-1"],
        ["-1", "1", "2", "1"],
        ["1", "1", "0", "-1"],
        ["1", "1", "2", "1"],
      ],
    },
    derive: [["\\(x^2=1\\)", "\\(z=y-1\\in\\{-1,1\\}\\)"], ["元素之和", "\\(-1+1=0\\)，选择 A"]],
  }]),
  lesson("set-representation-description-q14", "研究变换封闭的有限集合", "描述法", [
    "设集合 A 由实数组成，并满足：若 \\(x\\in A\\)（\\(x\\ne0,1\\)），则 \\(\\frac{1}{1-x}\\in A\\)。",
    "（1）若 \\(2\\in A\\)，证明 A 中还有另外两个元素；（2）A 是否可能为双元素集合；（3）若 A 中元素不超过 8 个，元素和为 \\(\\frac{14}3\\)，且某个元素的平方等于所有元素的积，求 A。",
  ], [
    "连续施加变换 f(x)=1/(1-x)，第三次会回到 x。",
    "每 3 个数构成一个循环组；有限集合由若干个这样的三元素循环组组成。",
  ], [{
    title: "列表观察三步循环",
    reasoning: [
      { kind: "because", text: "令 \\(f(x)=\\frac{1}{1-x}\\)，集合 \\(A\\) 对变换 \\(f\\) 封闭" },
      { kind: "therefore", text: "若 \\(x\\in A\\)，则 \\(f(x)=\\frac{1}{1-x}\\in A\\)，且 \\(f^2(x)=\\frac{x-1}{x}\\in A\\)" },
      { kind: "because", text: "\\(f^3(x)=x\\)，且方程 \\(f(x)=x\\) 在实数范围内无解" },
      { kind: "therefore", text: "\\(x,f(x),f^2(x)\\) 是 3 个不同的数，并且每 3 个数构成一个循环组" },
      { kind: "because", text: "取 \\(x=2\\)" },
      { kind: "therefore", text: "\\(f(2)=-1\\)，\\(f(-1)=\\frac{1}{2}\\)，所以 \\(A\\) 中还有 \\(-1,\\frac{1}{2}\\)" },
      { kind: "because", text: "有限集合中的元素按每 3 个数一个循环组出现" },
      { kind: "therefore", text: "\\(|A|\\) 是 3 的倍数，因此 \\(A\\) 不可能是双元素集合" },
    ],
    table: {
      headers: ["施加变换的次数", "得到的数"],
      rows: [
        ["0", "\\(x\\)"],
        ["1", "\\(f(x)=\\frac{1}{1-x}\\)"],
        ["2", "\\(f^2(x)=\\frac{x-1}{x}\\)"],
        ["3", "\\(f^3(x)=x\\)"],
      ],
    },
    derive: [["\\(f(x)=\\frac{1}{1-x}\\)", "\\(f^2(x)=\\frac{x-1}{x}\\)"], ["\\(f^3(x)\\)", "\\(x\\)"], ["结论", "每 3 个数构成一个循环组"]],
  }, {
    title: "列表确定两个循环组",
    reasoning: [
      { kind: "because", text: "每个三元素循环组的元素之积为 \\(-1\\)，而题设说某个元素的平方等于 \\(A\\) 中所有元素的积" },
      { kind: "therefore", text: "循环组的个数必须为偶数；又因为 \\(|A|\\le8\\)，所以 \\(A\\) 恰含 2 个循环组，共 6 个元素" },
      { kind: "because", text: "此时所有元素的积为 \\(1\\)，故题设中的那个元素满足 \\(u^2=1\\)" },
      { kind: "therefore", text: "\\(u=-1\\)，包含 \\(-1\\) 的循环组为 \\(\\{-1,\\frac{1}{2},2\\}\\)" },
      { kind: "because", text: "第一个循环组的元素和为 \\(\\frac{3}{2}\\)，而 \\(A\\) 中所有元素的和为 \\(\\frac{14}{3}\\)" },
      { kind: "therefore", text: "第二个循环组的元素和为 \\(\\frac{14}{3}-\\frac{3}{2}=\\frac{19}{6}\\)" },
      { kind: "because", text: "任一循环组可写成 \\(p=x,q=\\frac{1}{1-x},r=\\frac{x-1}{x}\\)，直接通分可得 \\(pqr=-1\\)，且 \\((p+q+r)-(pq+qr+rp)=3\\)" },
      { kind: "therefore", text: "设第二个循环组的三个元素为 \\(p,q,r\\)，则 \\(pq+qr+rp=p+q+r-3\\)" },
      { kind: "therefore", text: "\\(p+q+r=\\frac{19}{6}\\)，\\(pq+qr+rp=\\frac{1}{6}\\)，\\(pqr=-1\\)" },
      { kind: "because", text: "以 \\(p,q,r\\) 为根的三次方程为 \\(t^3-\\frac{19}{6}t^2+\\frac{1}{6}t+1=0\\)" },
      { kind: "therefore", text: "\\(6t^3-19t^2+t+6=(t-3)(2t+1)(3t-2)=0\\)" },
      { kind: "therefore", text: "\\(t=3,-\\frac{1}{2},\\frac{2}{3}\\)，所以第二个循环组是 \\(\\{-\\frac{1}{2},\\frac{2}{3},3\\}\\)" },
      { kind: "therefore", text: "\\(A=\\{-1,-\\frac{1}{2},\\frac{1}{2},\\frac{2}{3},2,3\\}\\)" },
    ],
    table: {
      headers: ["循环组", "三个元素", "元素和", "元素积"],
      rows: [
        ["包含 2 的循环组", "\\(\\{2,-1,\\frac{1}{2}\\}\\)", "\\(\\frac{3}{2}\\)", "-1"],
        ["另一个循环组", "\\(\\{-\\frac{1}{2},\\frac{2}{3},3\\}\\)", "\\(\\frac{19}{6}\\)", "-1"],
        ["合并", "6 个元素", "\\(\\frac{14}{3}\\)", "1"],
      ],
    },
    derive: [["含 2 的循环组", "\\(\\{2,-1,\\frac{1}{2}\\}\\)"], ["第二个循环组", "\\(\\{-\\frac{1}{2},\\frac{2}{3},3\\}\\)"], ["结论", "\\(A=\\{-1,-\\frac{1}{2},\\frac{1}{2},\\frac{2}{3},2,3\\}\\)"]],
  }]),

  lesson("set-representation-interval-q01", "把四个实数集合写成区间", "区间表示法", [
    "请用区间法表示下列集合：",
    "（1）\\(\\{x\\mid |x|\\le1\\}\\)；（2）\\(\\{y\\mid y=\\sqrt{x}+2\\}\\)；（3）\\(\\{y\\mid y=-x^2+2x\\}\\)；（4）\\(\\{y\\mid y=x^2-2x+1,x>0\\}\\)。",
  ], [
    "先把每个集合转化为连续的实数取值范围。",
    "有限端点能取用方括号，不能取用圆括号；无穷端点永远用圆括号。",
  ], [{
    title: "逐项确定端点与开闭",
    reasoning: [
      { kind: "because", text: "\\(|x|\\le1\\iff-1\\le x\\le1\\)" },
      { kind: "therefore", text: "第（1）问表示为 \\([-1,1]\\)" },
      { kind: "because", text: "\\(x\\ge0\\)，所以 \\(\\sqrt{x}\\ge0\\)，且 \\(x=0\\) 时 \\(y=2\\)" },
      { kind: "therefore", text: "第（2）问中 \\(y\\ge2\\)，表示为 \\([2,+∞)\\)" },
      { kind: "because", text: "\\(y=-x^2+2x=-(x-1)^2+1\\le1\\)，且 \\(x=1\\) 时等号成立" },
      { kind: "therefore", text: "第（3）问表示为 \\((-∞,1]\\)" },
      { kind: "because", text: "\\(y=x^2-2x+1=(x-1)^2\\ge0\\)，且 \\(x=1>0\\) 时 \\(y=0\\)" },
      { kind: "therefore", text: "第（4）问表示为 \\([0,+∞)\\)" },
    ],
    table: {
      headers: ["原集合", "范围依据", "区间"],
      rows: [
        ["\\(\\{x\\mid |x|\\le1\\}\\)", "\\(-1\\le x\\le1\\)", "\\([-1,1]\\)"],
        ["\\(\\{y\\mid y=\\sqrt{x}+2\\}\\)", "\\(y\\ge2\\)", "\\([2,+∞)\\)"],
        ["\\(\\{y\\mid y=-x^2+2x\\}\\)", "\\(y=-(x-1)^2+1\\le1\\)", "\\((-∞,1]\\)"],
        ["\\(\\{y\\mid y=x^2-2x+1,x>0\\}\\)", "\\(y=(x-1)^2\\ge0\\)，且 0 可取", "\\([0,+∞)\\)"],
      ],
    },
    derive: [["结论", "\\([-1,1];[2,+∞);(-∞,1];[0,+∞)\\)"]],
  }]),

  lesson("set-representation-venn-q01", "由 Venn 图阴影确定区间", "Venn 图法", [
    "已知全集为实数集，\\(A=\\{x\\mid1<x<2\\}\\)，\\(B=\\{x\\mid0<x\\le\\frac{3}{2}\\}\\)。图中阴影表示 B 中不属于 A 的部分，求该集合。",
    { figure: { kind: "venn-two", shade: "B-only", ariaLabel: "阴影为 B 去掉 A 的部分" } },
    "A. \\([0,1]\\)　B. \\((0,1]\\)　C. \\([0,1)\\)　D. \\((0,1)\\)",
  ], [
    "先把阴影视为 B\\A，再比较两个区间。",
    "0 不属于 B，1 属于 B 且不属于 A。",
  ], [{
    title: "把阴影翻译成集合差",
    visual: {
      kind: "number-line-difference",
      ariaLabel: "用三条数轴比较集合 A、集合 B 与集合差 B 去掉 A，得到开区间 0 到闭端点 1",
    },
    reasoning: [
      { kind: "because", text: "阴影在集合 \\(B\\) 内、集合 \\(A\\) 外" },
      { kind: "therefore", text: "阴影表示 \\(B∖A\\)" },
      { kind: "because", text: "\\(A=(1,2)\\)，\\(B=(0,\\frac{3}{2}]\\)，所以 \\(A∩B=(1,\\frac{3}{2}]\\)" },
      { kind: "therefore", text: "\\(B∖A=(0,\\frac{3}{2}]∖(1,\\frac{3}{2}]=(0,1]\\)，选择 B" },
    ],
    derive: [["\\(B∖A\\)", "\\((0,\\frac{3}{2}]∖(1,2)\\)"], ["结论", "\\((0,1]\\)，选择 B"]],
  }]),
  lesson("set-representation-venn-q02", "由离散全集读取 Venn 图阴影", "Venn 图法", [
    "已知全集 \\(U=\\{0,1,2,3,4,5,6,7,8\\}\\)，\\(A=\\{x\\in\\mathbb N\\mid x<5\\}\\)，\\(B=\\{1,3,5,7,8\\}\\)。图中阴影表示 A 中不属于 B 的部分。",
    { figure: { kind: "venn-two", shade: "A-only", ariaLabel: "阴影为 A 去掉 B 的部分" } },
    "A. \\(\\{0,2,4\\}\\)　B. \\(\\{2,4\\}\\)　C. \\(\\{0,4\\}\\)　D. \\(\\{2,4,6\\}\\)",
  ], [
    "先列出 A，再从 A 中删去同时属于 B 的元素。",
    "阴影不包含交集部分。",
  ], [{
    title: "计算集合差",
    table: {
      caption: "逐个检查集合 A 中的元素是否属于 B",
      headers: ["\\(x\\in A\\)", "是否属于 \\(B\\)", "是否保留在 \\(A∖B\\)"],
      rows: [
        ["0", "否", "保留"],
        ["1", "是", "删除"],
        ["2", "否", "保留"],
        ["3", "是", "删除"],
        ["4", "否", "保留"],
      ],
    },
    reasoning: [
      { kind: "because", text: "\\(A=\\{x\\in\\mathbb N\\mid x<5\\}=\\{0,1,2,3,4\\}\\)" },
      { kind: "therefore", text: "\\(A∩B=\\{1,3\\}\\)" },
      { kind: "because", text: "阴影在 \\(A\\) 内、\\(B\\) 外，所以阴影表示 \\(A∖B\\)" },
      { kind: "therefore", text: "\\(A∖B=\\{0,1,2,3,4\\}∖\\{1,3\\}=\\{0,2,4\\}\\)，选择 A" },
    ],
    derive: [["\\(A=\\{0,1,2,3,4\\}\\)", "与 B 公共元素为 1,3"], ["\\(A∖B\\)", "\\(\\{0,2,4\\}\\)，选择 A"]],
  }]),
  lesson("set-representation-venn-q03", "用容斥原理统计两项比赛都参加的人数", "Venn 图法", [
    "2021 年天津市第四十七中学秋季运动会，高一某班 41 名学生中有 10 名没有参加比赛；参加田赛的有 16 人，参加径赛的有 23 人。求田赛和径赛都参加的学生人数。",
  ], [
    "先用总人数减去未参赛人数，得到至少参加一项的人数。",
    "两集合容斥公式为 |A∩B|=|A|+|B|-|A∪B|。",
  ], [{
    title: "代入两集合容斥公式",
    visual: {
      kind: "venn-two-counts",
      ariaLabel: "全班 41 人的 Venn 图，田赛仅参加 8 人，两项都参加 8 人，径赛仅参加 15 人，两项都未参加 10 人",
    },
    reasoning: [
      { kind: "because", text: "全班 41 人，其中 10 人两项比赛都没有参加" },
      { kind: "therefore", text: "\\(|A∪B|=41-10=31\\)" },
      { kind: "because", text: "\\(|A∪B|=|A|+|B|-|A∩B|\\)" },
      { kind: "therefore", text: "\\(|A∩B|=16+23-31=8\\)" },
    ],
    derive: [["至少参加一项", "\\(41-10=31\\)"], ["都参加", "\\(16+23-31=8\\) 人"]],
  }], "2021 天津市第四十七中学秋季运动会测试"),
  lesson("set-representation-venn-q04", "求三天售出商品种类的最小值", "Venn 图法", [
    "某网店连续三天售出商品的种类数分别为 19、13、18；前两天都售出的有 3 种，后两天都售出的有 4 种。",
    "（1）第一天售出但第二天未售出的商品有多少种？（2）这三天售出的商品最少有多少种？",
  ], [
    "第一问直接计算集合差的元素个数。",
    "第二问要让第一天和第三天在第二天之外尽量重合，从而使并集最小。",
  ], [{
    title: "计算第一天与第二天的集合差",
    visual: {
      kind: "venn-day-one-two-counts",
      ariaLabel: "第一天与第二天的 Venn 图：第一天独有 16 种，两天都有 3 种，第二天独有 10 种",
    },
    reasoning: [
      { kind: "because", text: "第一天售出 19 种，前两天都售出的有 3 种" },
      { kind: "therefore", text: "第一天独有的商品数为 \\(|D_1∖D_2|=19-3=16\\)" },
    ],
    derive: [["第一天但第二天未售出", "\\(19-3=16\\) 种"]],
  }, {
    title: "以第二天为基准分区并让外部集合重合",
    visual: {
      kind: "venn-min-union",
      ariaLabel: "先以第二天为基准分区；在第二天之外，第三天独有的 14 种全部包含在第一天独有的 16 种中，因此三天并集最小",
    },
    reasoning: [
      { kind: "because", text: "第三天售出 18 种，其中与第二天共有 4 种" },
      { kind: "therefore", text: "第三天在第二天之外有 \\(|D_3∖D_2|=18-4=14\\) 种" },
      { kind: "because", text: "三天售出的全部商品可分成两块：第二天的 13 种，以及第二天之外由 \\(D_1∖D_2\\) 和 \\(D_3∖D_2\\) 合成的部分" },
      { kind: "therefore", text: "第二天之外需要合并一个 16 元素集合与一个 14 元素集合" },
      { kind: "because", text: "两个集合的并集至少有 16 个元素；当 14 元素集合完全包含在 16 元素集合中时恰好取到 16" },
      { kind: "therefore", text: "三天售出的商品最少有 \\(|D_2|+16=13+16=29\\) 种" },
    ],
    derive: [["第一天在第二天外", "16 种"], ["第三天在第二天外", "\\(18-4=14\\) 种"], ["最小并集", "\\(13+16=29\\) 种"]],
  }]),
];

for (const item of lessons) {
  const dir = path.join(lessonRoot, item.meta.id);
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(dir, "lesson-data.json"), `${JSON.stringify(item, null, 2)}\n`);
}

console.log(`Generated ${lessons.length} set-representation lesson specs.`);
