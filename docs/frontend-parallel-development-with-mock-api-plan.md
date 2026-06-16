# 前端与 Mock API 并行开发计划

当前背景：后端的“生成网页 API”和“对话修改 API”还未完成，但前端产品形态已经基本明确。为了不阻塞前端开发，先定义稳定的接口契约和 mock 数据，让前端按真实调用路径开发；后端完成后替换 mock 实现，而不是重写页面。

本文是讨论稿，目标是先把前后端协作边界、页面拆分、mock 策略和验收路径说清楚。

## 产品边界

产品采用一个主页面，不单独做工作台：

- 左侧选择对象：`新题目`、`搜索`、`题目`、`网站首页`、`专题`。
- 中间编辑对象：
  - 题目：`编辑模式` 或 `对话模式`。
  - 专题：人工归类和排序。
  - 网站首页：固定首页配置。
- 右侧预览对象：
  - 题目：完整网页预览，支持网页内注释。
  - 专题：专题页预览。
  - 网站首页：首页预览。

不要先把账号强行拆成“老师 / 学生”两类身份。产品按题目内的模式和权限区分能力：

- `编辑模式`：用于修改题目网页。中间是作者对话，右侧是完整网页预览和网页注释；结果会产生持久网页修改、重新生成、发布更新。
- `对话模式`：用于围绕题目学习提问。中间是学习对话，右侧仍是完整网页预览；结果只保存学习问答记录和临时页面动作，不修改网页。

权限规则：

- 题目拥有者在工作台中可以看到 `编辑 / 对话` 模式切换。
- 已发布网页只提供 `对话模式`，不提供编辑入口。
- 学习对话要求登录；每个用户的学习对话都需要保存记录。
- 上传题目后，只要后台生成出可对话的题目上下文，就可以进入 `对话模式`；不要求先发布。

专题和网站首页不做对话框，只做固定管理页面。

## 前端先行原则

1. 前端只依赖接口契约，不依赖后端实现进度。
2. 所有 mock API 必须使用和未来真实 API 一样的 URL、请求体、响应体。
3. 生成网页预览先使用静态 fixture HTML，后续替换成真实生成结果 URL。
4. 自动保存先用 mock mutation 模拟，后续接真实持久化。
5. 状态只保留三种用户可见状态：
   - `草稿`
   - `已发布`
   - `已发布 · 有改动`
6. 不显示版本号，不提供保存按钮；所有编辑默认自动保存。

## 技术假设

建议前端采用：

- `Next.js App Router`
- `React + TypeScript`
- `Tailwind CSS + shadcn/ui`
- `Zod` 定义接口契约
- `Next.js Route Handlers` 提供 mock API
- `iframe + postMessage` 承载完整网页预览与注释定位
- `Playwright` 做关键交互回归

如果后续不是 Next.js，也仍应保留同一套 contract schema 和 mock 数据。

## 已确认的工程边界

- 新建 `frontend/` 子项目承载创作后台源码。不要把后台应用混入现有 `site/`。
- `site/` 继续作为公开发布站点产物目录，未来按用户隔离，例如 `site/users/{userSlug}/...`。
- `site/index.html` 可以提供“进入创作后台”的入口，但不承载后台应用本身。
- mock API 使用 `frontend/` 内的 Next.js Route Handlers。前端开发先打到同路径 mock API，后端 ready 后替换实现。
- 预览 HTML 通过 `previewUrl` 加载，前端组件不硬编码 fixture 路径。

## 数据对象 v0

### Problem

```ts
type PublishStatus = "draft" | "published" | "published_dirty";

type Problem = {
  id: string;
  title: string;
  shortTitle: string;
  status: PublishStatus;
  defaultMode?: ProblemMode;
  canEdit?: boolean;
  canTutor?: boolean;
  subject: "math";
  tags: string[];
  updatedAt: string;
  autosavedAt: string;
  publicUrl: string | null;
  previewUrl: string;
};
```

`ProblemMode` 只影响工作台中当前打开题目的交互模式，不代表用户身份。

```ts
type ProblemMode = "edit" | "tutor";
```

### ProblemMessage

`ProblemMessage` 属于题目的 `编辑模式`，用于作者修改网页。它可能产生网页 patch、重新生成和发布更新。

```ts
type ProblemMessage = {
  id: string;
  problemId: string;
  role: "user" | "assistant" | "system";
  content: string;
  attachments?: MessageAttachment[];
  annotations?: WebAnnotation[];
  createdAt: string;
};

type MessageAttachment = {
  id: string;
  kind: "problem_image" | "reference_image";
  url: string;
  filename?: string;
  mimeType?: string;
  ocrText?: string;
  createdAt: string;
};
```

图片不直接塞进 `content`。用户上传图片时先形成 `MessageAttachment`，再根据上传检测结果决定：

- 新题图片：`新开任务` 或 `覆盖当前`。
- 当前题参考图、批注图、答案图、风格参考图：作为当前消息附件进入题目对话上下文。

右侧预览中产生的现场截图不属于 `MessageAttachment`，只作为 `WebAnnotation.screenshotUrl` 的可选视觉证据。

### TutorSession / TutorMessage

`TutorSession` 属于题目的 `对话模式`，用于学生或访问者围绕网页提问。它不修改网页，只保存学习问答记录和临时页面动作。对话模式要求登录。

```ts
type TutorSession = {
  id: string;
  problemId: string;
  userId: string;
  title?: string;
  currentStepId?: string;
  createdAt: string;
  updatedAt: string;
};

type TutorMessage = {
  id: string;
  sessionId: string;
  role: "user" | "assistant" | "system";
  content: string;
  selectedTargetId?: string;
  currentStepId?: string;
  actions?: TutorAction[];
  createdAt: string;
};

type TutorAction =
  | { type: "scroll_to_step"; stepId: string }
  | { type: "highlight_target"; targetId: string }
  | { type: "show_hint"; text: string };
```

### WebAnnotation

注释由右侧完整网页预览产生，进入中间主对话统一处理。MVP 不做自由框选；只允许点击预定义语义区域，例如原题、原题图片、步骤整体、步骤标题、步骤图形、步骤推导过程、导航条。

```ts
type AnnotationTargetType =
  | "problem_text"
  | "problem_figure"
  | "step"
  | "step_title"
  | "step_figure"
  | "step_derivation"
  | "step_navigation";

type WebAnnotation = {
  id: string;
  problemId: string;
  targetId: string;
  targetType: AnnotationTargetType;
  stepId?: string;
  label: string;
  comment: string;
  screenshotUrl?: string;
  createdAt: string;
};
```

`targetId` 是稳定语义锚点，不是 DOM selector。示例：

- `problem.text`
- `problem.figure.original`
- `step.q2s4`
- `step.q2s4.title`
- `step.q2s4.figure`
- `step.q2s4.derivation`
- `navigation.step_map`

`screenshotUrl` 不是主链路依赖，只在视觉问题、原题图片问题、调试复查时按需生成。

### Topic

```ts
type Topic = {
  id: string;
  title: string;
  description: string;
  status: PublishStatus;
  updatedAt: string;
  autosavedAt: string;
  publicUrl: string | null;
  previewUrl: string;
  items: TopicItem[];
  suggestedProblems: SuggestedProblem[];
};

type TopicItem = {
  id: string;
  problemId: string;
  title: string;
  tags: string[];
  status: PublishStatus;
  order: number;
};

type SuggestedProblem = {
  id: string;
  problemId: string;
  title: string;
  reason: string;
  confidence?: number;
  tags: string[];
};
```

### SiteHome

```ts
type SiteHome = {
  id: string;
  siteName: string;
  description: string;
  status: PublishStatus;
  autosavedAt: string;
  publicUrl: string | null;
  previewUrl: string;
  featuredTopicIds: string[];
  recentProblemLimit: number;
  knowledgeTags: string[];
};
```

## API Contract v0

### 左侧导航

```http
GET /api/nav
```

返回题目、网站首页、专题的列表，用于渲染左侧。

```json
{
  "problems": [],
  "siteHome": {},
  "topics": []
}
```

### 题目

```http
GET /api/problems
POST /api/problems
POST /api/problems/from-upload
GET /api/problems/:problemId
PATCH /api/problems/:problemId
POST /api/problems/:problemId/publish
```

`POST /api/problems` 用于从文字题干新建题目。

`POST /api/problems/from-upload` 是图片上传新建题目的高层入口。前端不直接调用“检测是否是题目”的底层能力；后台内部完成图片存储、题目检测、OCR、题干识别、`Problem` 创建、题目工作区创建和第一条对话消息创建。

mock 响应：

```json
{
  "result": "created",
  "problem": {
    "id": "problem_hongqiao_25",
    "title": "2026 年天津市红桥区三模第 25 题",
    "shortTitle": "红桥三模 25题",
    "status": "draft",
    "previewUrl": "/preview-fixtures/problems/hongqiao-25.html"
  },
  "initialMessage": {
    "id": "msg_1",
    "role": "user",
    "content": "上传题目图片",
    "attachments": [
      {
        "id": "att_1",
        "kind": "problem_image",
        "url": "/uploads/problem_hongqiao_25/original.jpg"
      }
    ]
  }
}
```

如果图片不像完整题目，返回：

```json
{
  "result": "rejected",
  "message": "没有识别到完整题目"
}
```

如果用户在已有题目的对话里上传图片，仍由后端判断。若后端认为它像新题，返回 `decision_required`，前端只展示两个选择：

- `新开任务`
- `覆盖当前`

`PATCH /api/problems/:problemId` 用于自动保存题目元信息，例如标题、标签。

`POST /api/problems/:problemId/publish`：

- `draft -> published`
- `published_dirty -> published`

### 题目编辑对话

```http
GET /api/problems/:problemId/messages
POST /api/problems/:problemId/messages
```

这组接口只用于 `编辑模式`。消息会修改题目网页、生成 preview、改变发布状态。

`POST messages` 请求：

```json
{
  "content": "把这些注释一起处理",
  "annotationIds": ["ann_1", "ann_2", "ann_3"]
}
```

mock 响应：

```json
{
  "messages": [
    {
      "id": "msg_assistant_1",
      "role": "assistant",
      "content": "已处理 3 条注释，并重新生成网页。"
    }
  ],
  "problem": {
    "id": "problem_hongqiao_25",
    "status": "published_dirty",
    "autosavedAt": "2026-06-15T09:00:00.000Z"
  },
  "preview": {
    "previewUrl": "/fixtures/problem/hongqiao-25-after-comments.html"
  }
}
```

后端 ready 后，这个接口内部替换为真实 patch planning、编译和校验。

### 题目学习对话

```http
GET /api/problems/:problemId/tutor-sessions
POST /api/problems/:problemId/tutor-sessions
GET /api/tutor-sessions/:sessionId/messages
POST /api/tutor-sessions/:sessionId/messages
```

这组接口用于 `对话模式`，包括工作台中的对话模式和已发布网页中的“问这道题”。学习对话要求登录，每个会话都需要保存记录。

`POST /api/tutor-sessions/:sessionId/messages` 请求：

```json
{
  "content": "为什么这里要构造 B₁？",
  "currentStepId": "q2s4",
  "selectedTargetId": "step.q2s4.figure",
  "pageState": {
    "scrollY": 1280,
    "sliderValues": {}
  }
}
```

mock 响应：

```json
{
  "messages": [
    {
      "id": "tmsg_assistant_1",
      "role": "assistant",
      "content": "这里构造 B₁ 是为了把 BG 转化成 B₁F，这样双动点路径就变成只研究 F 的折线。",
      "actions": [
        { "type": "highlight_target", "targetId": "step.q2s4.figure" },
        { "type": "show_hint", "text": "先看平行四边形 BGFB₁ 中哪两条边相等。" }
      ]
    }
  ]
}
```

学习对话不返回网页 patch，不改变 `Problem.status`，也不发布更新。

### 网页注释

```http
GET /api/problems/:problemId/annotations
POST /api/problems/:problemId/annotations
PATCH /api/problems/:problemId/annotations/:annotationId
DELETE /api/problems/:problemId/annotations/:annotationId
```

注释创建由右侧 iframe 的语义区域点击触发：

```json
{
  "targetType": "step_figure",
  "targetId": "step.q2s4.figure",
  "stepId": "q2s4",
  "label": "第4步 · 图形",
  "comment": "△AFB₁ 填充更明显"
}
```

前端行为：

- 右侧显示编号 marker。
- 中间主对话中出现“来自网页预览的 N 条注释”。
- 注释不在右侧单独列表展示。
- 注释 marker 的位置由前端根据 `targetId` 查找预定义区域后绘制，不需要持久化 `rect`。
- 需要视觉证据时，可额外附带 `screenshotUrl`，但不作为后端理解上下文的必要条件。

### 生成网页

```http
POST /api/problems/:problemId/generate
```

当前后端未 ready 时，该接口 mock 为：

- 延迟 1-2 秒。
- 返回新的 assistant message。
- 返回新的 `previewUrl`。
- 将状态置为 `draft` 或 `published_dirty`。

后端 ready 后，该接口承载：

- 题干识别。
- 解题方案生成。
- 可视化网页生成。
- 编译校验。
- 失败原因返回。

### 专题

```http
GET /api/topics
POST /api/topics
GET /api/topics/:topicId
PATCH /api/topics/:topicId
POST /api/topics/:topicId/items
PATCH /api/topics/:topicId/items/reorder
DELETE /api/topics/:topicId/items/:itemId
POST /api/topics/:topicId/publish
```

专题没有对话框。它只做：

- 手工添加题目。
- 接受或忽略自动归类建议。
- 拖拽排序。
- 编辑标题和说明。
- 发布更新。

### 自动归类建议

```http
GET /api/topics/:topicId/suggested-problems
POST /api/topics/:topicId/suggested-problems/:suggestedProblemId/accept
POST /api/topics/:topicId/suggested-problems/:suggestedProblemId/ignore
```

`SuggestedProblem` 表示“推荐加入当前专题的题目”，不表示专题本身。mock 阶段使用固定推荐列表。后端 ready 后由 LLM 根据题目标题、标签、题型、地区、考试、题号、知识点推荐。

### 网站首页

```http
GET /api/site/home
PATCH /api/site/home
POST /api/site/home/publish
```

首页是固定结构，不做对话，不做自由搭建器。

可配置：

- 网站名称。
- 首页说明。
- 精选专题。
- 最近发布题目数量。
- 知识点入口。

## 后台题目工作区

后台按 `Problem` 维护工作区文件夹，不按每轮对话维护文件夹。用户看到的是“题目对话”，后台管理的是“题目工作区”。

建议结构：

```text
users/{userId}/problems/{problemId}/
  uploads/
    original.jpg
    reference-1.jpg

  author-conversation/
    messages.jsonl
    annotations.jsonl
    attachments.jsonl

  tutor-sessions/
    {sessionId}/
      messages.jsonl
      learning-log.jsonl

  objects/
    problem.json
    lesson.json
    publish-state.json

  specs/
    01_problem.md
    02_solution.md
    03_visual_steps.md
    geometry-spec.json
    lesson-data.json
    step-decorations.json

  preview/
    index.html

  publish/
    current/
      index.html

  logs/
    generation.log
    validation.log
```

在线读写可以以数据库为主，方便分页、搜索、权限和排序；工作区文件夹同步保存一份完整上下文，方便调试、复现、导出和离线处理。

`author-conversation/messages.jsonl` 示例：

```json
{"id":"msg_1","role":"user","content":"上传题目图片","attachmentIds":["att_1"],"createdAt":"2026-06-16T09:00:00.000Z"}
{"id":"msg_2","role":"assistant","content":"已识别题目并生成网页。","createdAt":"2026-06-16T09:00:03.000Z"}
```

`author-conversation/annotations.jsonl` 示例：

```json
{"id":"ann_1","targetId":"step.q2s4.figure","targetType":"step_figure","stepId":"q2s4","comment":"△AFB₁ 填充更明显","createdAt":"2026-06-16T09:05:00.000Z"}
```

`author-conversation/attachments.jsonl` 示例：

```json
{"id":"att_1","kind":"problem_image","url":"uploads/original.jpg","filename":"original.jpg","createdAt":"2026-06-16T09:00:00.000Z"}
```

`tutor-sessions/{sessionId}/messages.jsonl` 示例：

```json
{"id":"tmsg_1","role":"user","content":"为什么这里要构造 B₁？","currentStepId":"q2s4","selectedTargetId":"step.q2s4.figure","createdAt":"2026-06-16T09:10:00.000Z"}
{"id":"tmsg_2","role":"assistant","content":"这里是为了把 BG 转化成 B₁F。","actions":[{"type":"highlight_target","targetId":"step.q2s4.figure"}],"createdAt":"2026-06-16T09:10:02.000Z"}
```

第一版可以先让 mock API 写内存或 fixtures；但接口设计应默认后台最终会创建并维护这个 `ProblemWorkspace`。

## Mock 数据与静态预览

在 `frontend/` 子项目内新增：

```text
frontend/
  fixtures/
    nav.json
    problems/
      hongqiao-25.json
      heping-24.json
    messages/
      hongqiao-25.json
    annotations/
      hongqiao-25.json
    topics/
      tianjin-sanmo-25.json
    site-home.json
  public/
    preview-fixtures/
      problems/
        hongqiao-25.html
        hongqiao-25-after-comments.html
      topics/
        tianjin-sanmo-25.html
      site/
        home.html
```

关键是 `previewUrl` 一开始就走真实 URL 字段，不在组件里硬编码 fixture。

## 前端页面拆分

### 主 Shell

职责：

- 左侧对象列表。
- 根据选中对象切换中间和右侧。
- 统一自动保存提示。
- 统一发布状态展示。

建议组件：

```text
AppShell
  Sidebar
  MainPane
  PreviewPane
```

### 题目页

工作台题目页有 `编辑 / 对话` 模式切换。只有题目拥有者或有编辑权限的用户能看到 `编辑模式`。

编辑模式中间：

- 题目主对话。
- 注释组消息。
- 底部输入框。

编辑模式右侧：

- 完整网页 iframe。
- 注释模式。
- marker overlay。
- 通过 `postMessage` 获取选区信息。

对话模式中间：

- 学习对话。
- 历史 tutor session 列表或当前 session。
- 底部输入框。

对话模式右侧：

- 同一个完整网页 iframe。
- 当前 step / target 选择只作为提问上下文。
- 后端返回的 `TutorAction` 可触发滚动、高亮、提示。
- 不显示网页编辑注释，不产生网页 patch。

已发布网页只提供 `对话模式`。用户登录后可以和网页对话并保存学习记录；没有编辑入口。

### 专题页

中间：

- 专题标题和说明。
- 已收录题目列表。
- 自动归类建议。
- 新建专题入口。
- 拖拽排序。

右侧：

- 专题页完整预览。

不提供聊天输入框。

### 网站首页页

中间：

- 网站名称和说明。
- 精选专题。
- 最近发布题目数量。
- 知识点入口。
- 未发布改动提醒。

右侧：

- 首页完整预览。

不提供聊天输入框。

## iframe 注释通信 v0

前端预览页与外层应用使用 `postMessage`。

推荐方案：**外层 overlay 绘制注释 marker，iframe 内只提供轻量 preview bridge**。

原因：

- 生成网页本身保持干净，不混入作者编辑 UI。
- 已发布页面和工作台预览可以共享同一份 HTML，避免生成两套 DOM。
- 外层 app 更容易管理 marker 编号、浮层、待发送注释和对话消息。
- iframe 内 bridge 只负责暴露 `targetId`、当前 step、目标元素位置和点击事件，职责稳定。

预览 bridge 最小职责：

- 为预定义区域注册 `targetId`。
- 在点击可注释区域时发出 `preview-target-selected`。
- 在滚动、窗口尺寸变化或外层请求时返回 target 的当前 bounding box。
- 不保存注释，不绘制评论列表，不执行业务修改。

预览页只暴露预定义可注释区域。用户点击原题、原题图片、步骤整体、步骤标题、步骤图形、步骤推导过程或导航条时，预览页发出语义目标事件：

```ts
type PreviewTargetSelectedEvent = {
  type: "preview-target-selected";
  problemId: string;
  targetId: string;
  targetType: AnnotationTargetType;
  stepId?: string;
  label: string;
  screenshotRecommended?: boolean;
};
```

外层应用接收后：

1. 打开轻量注释输入浮层。
2. 用户输入注释文字。
3. 调用 `POST /api/problems/:problemId/annotations`。
4. 在中间对话中增加注释组。
5. 根据 `targetId` 和 bridge 返回的 bounding box，在外层 overlay 中显示编号 marker。

MVP 不要求跨 iframe 精确编辑 DOM，也不持久化自由框选坐标。编辑模式下，注释上下文以 `targetId + targetType + stepId` 为准；截图只在视觉类问题或调试复查时按需捕获。

对话模式复用同一套 `targetId`，但不创建 `WebAnnotation`。用户点击网页区域时，只把 `selectedTargetId` 和 `currentStepId` 带入 tutor message，作为“我正在问哪里”的上下文。

## 开发阶段

### Phase A：契约与骨架

交付：

- Zod schema。
- mock fixtures。
- mock API route handlers。
- mock `POST /api/problems/from-upload`。
- 三栏主 Shell。
- 左侧题目 / 网站 / 专题导航。

验收：

- 不接真实后端也能打开完整产品壳。
- 左侧点击不同对象，中间和右侧能切换模式。

### Phase B：题目对话与预览

交付：

- 题目页编辑模式。
- iframe 完整网页预览。
- 注释 marker。
- 注释进入主对话。
- mock 对话修改接口。

验收：

- 用户能在右侧选区添加 3 条注释。
- 中间显示“来自网页预览的 3 条注释”。
- 点击发送后 mock 返回 assistant 回复，状态变成 `已发布 · 有改动`。

### Phase C：题目对话模式

交付：

- 工作台题目页 `编辑 / 对话` 模式切换。
- mock tutor session。
- 学习对话消息流。
- 右侧网页 target 点击作为 `selectedTargetId`。
- mock `TutorAction` 执行：滚动到 step、高亮 target、显示提示。
- 已发布网页中的“问这道题”入口。

验收：

- 题目拥有者可以在工作台从编辑模式切到对话模式。
- 已发布网页登录后只能进入对话模式。
- 学习对话保存到 tutor session，不改变题目发布状态。

### Phase D：专题与首页管理

交付：

- 专题列表和专题详情。
- 自动归类建议 mock。
- 拖拽排序。
- 首页管理。
- 专题和首页预览。

验收：

- 用户能接受自动归类建议。
- 用户能调整专题题目顺序。
- 用户能发布专题更新。

### Phase E：后端替换

交付：

- 将 mock `generate` 替换为真实生成 API。
- 将 mock `messages` 替换为真实对话修改 API。
- 将 mock `tutor-sessions` 替换为真实学习对话 API。
- 将 mock `publish` 替换为真实发布快照。
- 将 mock `from-upload` 替换为真实上传、检测、OCR、工作区创建链路。

验收：

- 前端组件不改或少改。
- API 响应仍满足 contract schema。
- 失败时前端能展示可理解的错误原因。

## 后端未 ready 时的错误模拟

mock API 需要覆盖成功和失败，避免前端只开发 happy path。

建议模拟：

- 生成中超时。
- 题干识别失败。
- 编译失败。
- 发布失败。
- 注释 `targetId` 失效。
- 图片上传创建题目失败。
- 已有题目对话中上传图片后需要 `decision_required`。
- 自动保存失败后重试。

错误响应格式：

```json
{
  "error": {
    "code": "compile_failed",
    "message": "网页编译失败，请检查第4步图形配置。",
    "retryable": true
  }
}
```

## 和真实后端对接的约束

后端实现完成后应遵守：

- 不改变字段名，必要变更先改 contract。
- 所有响应经过 schema 校验。
- 生成接口返回 `previewUrl`，前端不关心网页存储位置。
- 发布接口返回新的 `status` 和 `publicUrl`。
- 对话修改接口返回 assistant message、problem 状态、preview 信息。
- 学习对话接口返回 tutor message 和可执行 `TutorAction`，不返回网页 patch，不改变 `Problem.status`。
- 消息图片使用 `attachments`，不嵌入 `content`。
- 注释接口只处理语义锚点和文本，不直接执行修改；修改由消息接口统一处理。
- 注释上下文以 `targetId + targetType + stepId` 为准，不要求截图；截图只作为可选视觉证据。

## 需要讨论的决策点

1. 预览页注释 marker 是否采用推荐的“外层 overlay + iframe preview bridge”方案？
2. 发布后的公开页面是由 Next.js 动态路由服务，还是仍然落静态 HTML？
3. 账号系统首版使用 Clerk、Supabase Auth，还是先做内部单用户模式？
4. 后端生成出的页面是否直接兼容当前 `site/problems/...html` 结构？
5. 专题自动归类建议是生成题目后立即写入，还是进入专题页时实时计算？
6. `对话模式` 是否进入第一版 MVP，还是先只做题目编辑模式并预留 tutor API？
7. 已发布网页中的“问这道题”是否与工作台对话模式共用同一套 UI 组件？

## 推荐的第一周目标

第一周不追后端真实生成，只追“产品链路跑通”：

1. 建立 contract schema 和 mock fixtures。
2. 做出主 Shell。
3. 做出题目页中间主对话。
4. 右侧 iframe 加载静态题目 HTML。
5. 支持右侧添加注释并进入中间对话。
6. mock 发送注释，返回 assistant 回复和新的 preview URL。
7. 状态从 `已发布` 变成 `已发布 · 有改动`。
8. 在数据和接口上预留 `TutorSession / TutorMessage`，但是否实现对话模式可按排期决定。

这条链路跑通后，后端可以逐个替换 mock，前端也能持续迭代真实体验。
