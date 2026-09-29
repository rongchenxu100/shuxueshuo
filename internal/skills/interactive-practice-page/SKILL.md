---
name: interactive-practice-page
description: Create or revise a student-facing interactive math practice page in the shuxueshuo site/1 lesson system, with independent static exercise flow, shared JS components, a per-problem teacher JSON, and on-demand tutor dialogue. Use for adding questions like Q01 or extending this practice bank; not for solver-generated explanation pages or the separate senior-high learning-topic compiler.
---

# 交互练习题网页

为数学说新增可以独立练习、按需与老师对话的题目。默认沿用 Q01 的架构和视觉，不复制一份题目专用 JS，也不把课程布局搬入教师 JSON。

## 先确认边界

**HTML 是学生看到的课程；JSON 是老师理解和判断这节课所需的教学说明。**

- 每题 HTML 承担原题、题意整理、步骤展示、推导、图形，以及组件候选项和本地答案。
- 公共 JS/CSS 承担组件行为、本地校验、状态与步骤推进、对话接线。
- 每题教师 JSON 定义题目、可行路径、各步关键输入、通过标准、提示依据与参考结论。
- Context 保存本次练习的实际输入、路径尝试与对话，不能写回教学文件。
- 点选不调用 API。学生主动发送文字或请求提示时，才同步未确认的操作，由后台重放校验后加载 JSON + Context + 通用 Prompt 调用老师。

本 skill 服务于这套手工编写课程的练习系统，不导入另一套 lesson-spec/compiler/solver 流水线。用户明确要求别的系统时遵循其范围。

## 工作入口

从 shuxueshuo 仓库根目录读取：

1. `docs/interactive-lesson-shared-runtime-design.md`：职责、同步语义和当前边界。
2. `site/1/q01/index.html` 与 `server/shuxueshuo_server/tutor_demo/lessons/q01.json`：可运行样本；它们不是必须复制的教学步骤。
3. 本 skill 的 [authoring-contract.md](references/authoring-contract.md)：编写字段、模板约束和现有组件的能力边界。

涉及交互行为时再读 `site/assets/practice/components.js`、`context.js`、`runtime.js` 和后台 `contracts.py`；涉及同步时读 `session.py` 和 `test_local_practice.py`。当前实现优先于过期文档；不要只照抄示例假设已有功能支持任意题目。

## 设计教学节点

从用户给出的题目或图片准确整理题意，独立验证解法、定义域、界的方向和取等可达性。若题干关键条件无法辨认，应先澄清，而不是补造条件。

- 只展示本题可完整练习的可行路径，数量由题目决定，不强制两条路径或三个步骤。
- 每步先写出：向学生提出的问题、需要他提供的关键信息、接受的等价答案、不足或错误的表达、完成后得到的结论。
- 一步突出一个数学判断。选择方法不自动等于完成本步；信息齐全后确认结束本步，不在老师回复中强行追加下一步问题。
- 通过组件设计引导操作，少写“点击方框”之类的操作教程。提示使用已有图标与呼吸邀请，不增加可见倒计时或自动模型调用。
- 不把填模板、接受提示或系统给出的推导记成学生独立推导；不把“不直接”判成数学上不可行。
- 每个步骤先选择已有组件。需要新交互时，仅扩展本题确实需要的公共组件及对应本地/后台校验；不要硬套 Q01 的正项槽位或预建通用 DSL。
- 计算板、自由图形探索和动态讨论步骤仍是后续方向，只有用户明确需要且本题适合时才纳入本次实现。

## 实现顺序

1. 检查现有题号、章节分类和工作区改动，选定稳定题目 ID、路径 ID、节点 ID；不覆盖已有题目。
2. 新建 `site/1/<lesson-id>/index.html`，复用页面外壳、公共资源与 DOM 挂载点。将题目内容与只读推导写入本题 HTML 模板，在 `practice-config` 中声明组件及本地答案。
3. 新建 `server/shuxueshuo_server/tutor_demo/lessons/<lesson-id>.json`。ID、版本、问题、组件、候选项与答案同页面对齐；语义判定与教学参考留在教师 JSON。
4. 需要的新能力同时更新公共组件、本地校验和后台契约；不把题目变量、具体答案或路线 ID 加入通用 Prompt。参考结论不等于学生作答证据。
5. 增加该题的一致性与操作序列测试，逐条练习路径验证。题目完整可用后，在 `site/1/index.html` 对应题型中新增链接，更新可见题数、提示和返回入口；不链接旧题解页，不把未完成题目伪装成可练习。
6. 用静态服务和浏览器验收，再验证按需对话同步。保留其他题目和相关组件的原有行为。

代码和教学文件可有少量有意重复，靠测试检查一致性。不为消除重复引入整页生成器、数据库或新框架。

## 验收

以真实行为验证，不只检查文件存在或固定文案：

- 后台不可用时仍能打开并完成所有已声明路径；初始加载、点选和确认不请求 tutor API。
- 至少一个代表性错误不能推进，修正后可以推进；等价的数学项顺序按节点设计接受。
- 页面与教师 JSON 的节点、组件、候选项、答案、反馈及版本一致；模板引用存在，ID 不与 `completion` 等页面容器冲突。
- 用相同操作序列比较 `PracticeContext` 与服务端 `Session` 的状态，覆盖新增组件或路径分支；不要仅跑仍然只引用 Q01 的旧测试来宣称新题通过。
- 在已有本地进度后发起对话，模型获得当前节点和已通过步骤；重试不重复推进，失败后仍可点选，旧回复不覆盖重新练习。
- 对新增教学契约验证疑问、信息不足、正确表达、错误表达和只猜最终答案等代表场景。先使用可重复的测试；真实 DeepSeek 验收仅在相应调用授权与配置下进行，不能用 mock 结果声称真实对话通过。
- 浏览器检查桌面和窄屏的公式、图形、候选菜单、输入栏与完成状态，保存有代表性的截图。

常用命令（在仓库根目录启动静态页；测试在 `server/` 中运行）：

```sh
python3 -m http.server 8765 --bind 127.0.0.1 --directory site
```

```sh
uv run pytest tests/tutor_demo -q
uv run uvicorn shuxueshuo_server.tutor_demo.api:app --host 127.0.0.1 --port 8766
```

复用正在运行的服务，不为测试停止不属于本任务的后台。密钥仍留在服务端，不打印或复制到静态文件。

## 交付

说明题目入口、教师 JSON、支持的路径、实际测试和尚未支持的能力。变更公共组件时说明其他题目的回归结果。没有独立请求就不发布站点、不推送代码；Git 提交遵循当前用户的授权范围。刷新恢复、账号和跨设备进度不能因新页面可运行就声称已经实现。
