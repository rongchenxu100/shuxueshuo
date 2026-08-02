# 高中学习专题与题目聚合页公共契约

本契约适用于高中知识专题页及其在线题目聚合页。领域 skill 负责数学内容，本契约负责信息架构、交互和发布一致性。

## 1. 路由与目录

- `chapters.json` 中的专题 section 使用 `presentation: "learning"` 并声明 `topicId`。
- 专题数据只写入 `internal/senior-high/catalog/learning-topics.json`。
- 路由格式为 `?chapter=<chapter>&section=<section>&module=<module>`；`module=overview` 为专题总览。
- 左侧目录按“章节 → 专题 → 模块”展示。目录文字负责跳转，箭头只负责展开或收起。
- 浏览器前进、后退和直接链接必须恢复同一模块状态。

## 2. 专题模型

- `learningTopics[]` 包含 `id`, `chapterId`, `sectionId`, `title`, `introduction`, `mapNodes`, `modules`。
- `mapNodes[]` 的 `moduleId` 必须引用真实模块；知识导图节点与左侧目录指向一致。
- `modules[]` 的类型只能是 `knowledge` 或 `assessment`，状态只能是 `published` 或 `pending`。
- `pending` 模块只展示已确认的 `knownPoints` 和明确待补状态，不编写推测性教材内容。

## 3. 总览页

- 包含简短知识引入、响应式知识导图和模块入口。
- 导图忠实反映知识层级，不把例题或页面装饰混入知识节点。
- 桌面端可横向组织；手机端重排为纵向结构，不允许依靠缩小整张 SVG 解决空间问题。
- 每个导图节点可通过键盘访问，并具有文本替代。

## 4. 知识模块页

- 顺序为：模块标题 → 核心知识 → 按知识点分组的例题 → 归纳总结。
- 概念、性质和方法必须保留层级，不得为了卡片整齐而直接平铺。
- 例题保留教材式小分组和原题文本，不新增抽象的“本题考查……”标题。
- 题量较多时，按知识方法划分 exercise section；每个知识块提供紧凑的“对应练习（n）→”锚点，每个练习组提供“返回对应知识点”。
- 长页面使用共享的返回顶部按钮。

## 5. 在线作答

- 知识例题和综合练习使用同一套 typed `answerSchema` 与提交控件。
- 每个已发布题必须具有：`lessonId`、非空 `hints`、`answerSchema` 和可访问的详情页。
- 支持至少：`single-choice`、序号选择、数学表达式、关系序列和分小题输入。
- 数学键盘只提供当前题可能需要的符号；输入获得焦点时可展开，答案区域保持清晰的试卷式白色书写空间。
- 提示只放在 `?` 浮层或解析页中，不在题卡正文暴露解法结构。
- 多小题必须一题一输入框并一次提交全部答案；不能用一个大文本框要求学生自行编号。
- 选择题选项在宽屏可两列；窄屏和长公式选项必须单列。

## 6. 综合练习页

- `assessment` 模块保持原题顺序和题号，不额外包装成静态卡片链接。
- 每题直接显示题干、答案控件、提交按钮、提示入口和详情页链接。
- 选择、填空和解答题都必须可以在聚合页作答。
- 若原选项无法覆盖独立验算得到的完整答案，将题目改成书面作答；不得保留错误选项并猜测命题意图。
- `pending` 题保留题号和待核对说明，但不显示答案控件或解析链接。

## 7. 详情页

- 详情页由 `lesson-data.json` 编译，不直接编辑 HTML。
- 原题、聚合页题干与详情页题干必须来自同一 lesson source。
- 原题卡复用公共 `answer-chip` 展示最终答案，不另造答案区域。
- 详情页答案必须由聚合页同一份 `answerSchema` 生成，禁止在 lesson spec 中重复维护另一份答案。
- 学习专题聚合页默认隐藏答案以支持在线作答；进入题目详情页后才在原题卡展示答案。
- `answer-chip` 只展示最终结果；完整的数学推导仍放在下方解析步骤中。
- 只显示具体考试或试卷来源；隐藏“培训教材”“教材习题”“知识模块”等泛化来源。
- 推导采用完整的已知 → 变形 → 结论链。`derive` 只做摘要，不能替代 `reasoning`。
- 表格用于有限枚举和分类，数轴用于区间结论，Venn 图用于集合区域与计数；无教学增益时不添加图形。

## 8. 构建与验收

```bash
node tools/build-text-page.mjs internal/senior-high/lesson-specs/<lesson-id>/
node tools/build-senior-high-library.mjs
node --test tools/tests/text-lessons.test.mjs tools/tests/senior-high-library.test.mjs
```

- 验证 topic、module、map node 与 lesson 引用唯一且文件存在。
- 验证 answer schema 与标准答案，覆盖退化情形、端点、互异性和多解。
- 在桌面与手机下检查目录、导图、长选项、数学键盘、分题输入和返回顶部控件。
- 聚合页与详情页均不得出现原始 TeX、空分子/分母、重叠标签或错误阴影。
- 回归检查其他 worksheet、collection 和历史链接保持兼容。
