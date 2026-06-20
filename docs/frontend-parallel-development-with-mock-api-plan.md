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
4. 对话式修改先用 mock mutation / 本地对话记录模拟，后续接真实消息持久化与网页 patch。
5. 状态只保留三种用户可见状态：
  - `草稿`
  - `已发布`
  - `已发布 · 有改动`
6. 不显示版本号。结构化元信息后续通过抽屉/弹层自动保存；题目内容修改以主对话消息提交作为保存边界。

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
- 预览刷新不能只依赖 URL 字符串变化；生成和修改接口应返回 `previewVersion`，前端用它决定 iframe reload。
- 发布后的公开页面继续落静态 HTML，不走 Next.js 动态路由。Next.js 只负责创作后台。
- 第一版账号先用内部单用户 hardcode 模式；所有需要用户信息的地方通过 `useCurrentUser()` 或服务端等价封装获取，后续正式上线前再替换为 Clerk。
- 后端生成页面应复用现有 lesson runtime / CSS / DOM 结构；路径结构可从 `site/problems/...` 迁移到 `site/users/{userSlug}/...`，但页面运行时保持兼容。
- 专题自动归类建议在题目生成成功后异步写入，专题页只读取预计算的 `SuggestedProblem`。

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
  previewVersion: string;
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

`POST /api/problems` 用于从文字题干新建题目。Phase 2 的成功、失败、中断等 mock 场景通过 `x-mock-scenario` header 控制，不进入正式 JSON request body contract。

`POST /api/problems/from-upload` 是图片上传新建题目的高层入口。前端不直接调用“检测是否是题目”的底层能力；后台内部完成图片存储、题目检测、OCR、题干识别、`Problem` 创建、题目工作区创建和第一条对话消息创建。

真实链路可能持续 10-30 秒，因此契约从一开始就按 job + SSE 流式反馈设计。mock 阶段用 Next.js Route Handlers 的 `ReadableStream` 模拟分段事件，前端现在就实现进度渲染。

启动上传：

```json
{
  "jobId": "job_upload_1",
  "streamUrl": "/api/problem-upload-jobs/job_upload_1/events"
}
```

事件流：

```http
GET /api/problem-upload-jobs/:jobId/events
```

SSE 事件示例：

```text
event: progress
data: {"stage":"stored","message":"图片已上传"}

event: progress
data: {"stage":"detecting","message":"正在识别题目…"}

event: progress
data: {"stage":"ocr","message":"正在提取题干…"}

event: progress
data: {"stage":"generating","message":"正在生成解题方案…"}

event: progress
data: {"stage":"compiling","message":"正在编译网页…"}

event: done
data: {"result":"created","problem":{"id":"problem_hongqiao_25","title":"2026 年天津市红桥区三模第 25 题","shortTitle":"红桥三模 25题","status":"draft","previewUrl":"/preview-fixtures/problems/hongqiao-25.html","previewVersion":"mock-1"},"initialMessage":{"id":"msg_1","role":"user","content":"上传题目图片","attachments":[{"id":"att_1","kind":"problem_image","url":"/uploads/problem_hongqiao_25/original.jpg"}]}}
```

如果 mock 阶段暂时不实现 SSE，也必须保持同样的状态模型。同步 mock 响应可作为临时降级：

```json
{
  "result": "created",
  "problem": {
    "id": "problem_hongqiao_25",
    "title": "2026 年天津市红桥区三模第 25 题",
    "shortTitle": "红桥三模 25题",
    "status": "draft",
    "previewUrl": "/preview-fixtures/problems/hongqiao-25.html",
    "previewVersion": "mock-1"
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

`PATCH /api/problems/:problemId` 用于后续题目信息抽屉/弹层里的结构化元信息自动保存，例如标题、标签。

当前 Phase 2 的主工作流已经调整为 Codex 风格对话页：题目生成成功后，中间栏保留创建历史和后续作者消息，题目内容修改通过 `POST /api/problems/:problemId/messages` 进入对话式保存与网页 patch 链路。标题、标签、分类等结构化字段不再常驻中间栏，避免把主工作区变回表单页；需要编辑时后续通过顶部栏入口打开抽屉/弹层。

自动保存规则：

- 用户停止输入 1.5 秒后触发保存。
- 即使持续编辑，也最多每 30 秒强制保存一次。
- 前端乐观更新 UI，显示“正在保存 / 刚刚已保存 / 保存失败”。
- 请求带 `expectedAutosavedAt` 做乐观锁，避免多标签页或多窗口覆盖。

请求示例：

```json
{
  "patch": {
    "title": "红桥三模 25题",
    "tags": ["二次函数综合", "路径最值"]
  },
  "expectedAutosavedAt": "2026-06-16T09:00:00.000Z"
}
```

如果后端发现 `expectedAutosavedAt` 与当前记录不一致，返回：

```http
409 Conflict
```

```json
{
  "error": {
    "code": "autosave_conflict",
    "message": "这个题目已在其他窗口被更新，请刷新后再继续编辑。",
    "retryable": false
  }
}
```

`POST /api/problems/:problemId/publish`：

- `draft -> published`
- `published_dirty -> published`

发布实现建议：

- 后端将编译好的静态 HTML 写入 `site/users/{userSlug}/problems/{problemSlug}/index.html`。
- 公开页面由 CDN / Nginx 直接服务，保持弱网和移动端访问性能。
- Next.js 不负责公开题目页 SSR；公开页面的“问这道题”入口通过轻量 JS widget 或链接进入对话模式。

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
    "previewUrl": "/fixtures/problem/hongqiao-25-after-comments.html",
    "previewVersion": "mock-2"
  }
}
```

后端 ready 后，这个接口内部替换为真实 patch planning、编译和校验。

前端刷新预览规则：

- 如果 `previewUrl` 改变，直接加载新的 iframe URL。
- 如果 `previewUrl` 不变但 `previewVersion` 改变，前端在 iframe URL 上拼接或更新 `?v={previewVersion}` 强制 reload。
- `previewVersion` 可以是时间戳、内容 hash、编译 run id；前端只做字符串比较。

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
- 返回新的 `previewVersion`。
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

`SuggestedProblem` 表示“推荐加入当前专题的题目”，不表示专题本身。mock 阶段使用固定推荐列表。

真实实现建议：

- 每次题目生成成功后，后端异步触发归类建议 job。
- job 根据题目标题、标签、题型、地区、考试、题号、知识点生成 `SuggestedProblem`。
- 专题页只读取预计算结果，不在用户打开专题页时实时调用 LLM。
- 后台可以批量重跑归类建议，避免多个专题页同时打开时产生不可控延迟和 LLM 调用压力。

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

注释模式交互：

- 编辑模式下提供显式 `注释` toggle。
- 默认关闭，用户可以像普通网页一样滚动和阅读预览，避免误触。
- 打开后，可注释区域显示轻量 hover 边界；点击区域才创建注释输入浮层。
- 已创建的 marker 即使 toggle 关闭也可以保留只读显示；只有新增注释能力受 toggle 控制。
- 对话模式不显示编辑注释 toggle。

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

`对话模式` 组件建议：

- 共用核心组件：`TutorChat`、`TutorMessageList`、`TutorInput`、`TutorActionExecutor`。
- 不共用外层 Shell：工作台用三栏布局承载 `TutorChat`；已发布网页用浮层、侧边抽屉或 bottom sheet 承载 `TutorChat`。
- 两处共用同一套 `TutorSession / TutorMessage / TutorAction` contract。

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
- 当 iframe 内页面滚动、resize、滑块变化、局部动画或字体加载导致布局变化时，主动发出 `layout-changed` 事件。外层收到后 debounce 150ms，批量刷新所有可见 marker 的位置。
- 从 Phase 0 起就校验 `postMessage` origin。即使当前 preview 同源，未来 preview HTML 放到独立子域时也不需要重构通信安全模型。
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

## 分步实现计划

实现顺序按“可独立验收、可替换 mock、尽早暴露交互风险”来切。不要先追完整功能；先把主壳、接口契约、iframe 预览、注释闭环跑通。

### Phase 0：frontend 子项目与契约底座

目标：建立前端工程边界，让后续页面都基于同一套 contract 和 mock route handler 开发。

交付：

- 新建 `frontend/` Next.js App Router 子项目。
- 建立基础目录：
  - `app/`
  - `components/`
  - `lib/contracts/`
  - `lib/api/`
  - `lib/mock/`
  - `fixtures/`
  - `public/preview-fixtures/`
- 用 Zod 定义 v0 contract：
  - `Problem`
  - `ProblemMessage`
  - `MessageAttachment`
  - `WebAnnotation`
  - `Topic`
  - `SuggestedProblem`
  - `SiteHome`
  - `TutorSession / TutorMessage / TutorAction`
- 建立 typed API client，前端组件只通过 client 访问 API。
- 建立 hardcode `useCurrentUser()` / server current user helper。
- 建立 Next.js Route Handlers mock API。
- 建立 mock fixtures 和静态 preview fixtures。

验收：

- `frontend/` 可独立启动。
- contract schema 可在前端和 mock route handler 中复用。
- `GET /api/nav` 能返回题目、网站首页、专题。
- `previewUrl`、`previewVersion`、`status` 等核心字段已贯穿 mock 数据。

非目标：

- 不做真实上传。
- 不做真实生成。
- 不做真实认证。

### Phase 1：统一主壳与对象切换

目标：先验证“左侧选对象，中间编辑对象，右侧预览对象”的产品壳。

交付：

- 三栏主 Shell：
  - `Sidebar`
  - `MainPane`
  - `PreviewPane`
- 左侧导航：
  - `新题目`
  - `搜索`
  - `题目`
  - `网站 / 首页`
  - `专题`
- 题目、专题、首页三种对象切换。
- 状态展示：
  - `草稿`
  - `已发布`
  - `已发布 · 有改动`
- 自动保存状态 UI：
  - `正在保存`
  - `刚刚已保存`
  - `保存失败`

验收：

- 左侧点击题目，中间显示题目编辑占位，右侧加载题目 preview fixture。
- 左侧点击专题，中间显示专题管理占位，右侧加载专题 preview fixture。
- 左侧点击首页，中间显示首页管理占位，右侧加载首页 preview fixture。
- 无需真实后端即可完整切换对象。

非目标：

- 不做注释。
- 不做对话发送。
- 不做拖拽排序。

### Phase 2：题目创建、上传进度与对话式修改保存

目标：把“新题目入口”做成 Codex 风格空态/对话态，并把创建成功后的题目页定义为主对话页。Phase 2 不再把标题、标签表单常驻在中间栏；题目生成、上传进度、创建历史和后续修改请求都进入同一个对话流。结构化题目信息通过顶部栏弹层编辑，并接入自动保存。

交付：

- `POST /api/problems`：文字题干新建 mock。
  - mock 场景使用 `x-mock-scenario` header，不写入正式 request body。
- `POST /api/problems/from-upload`：启动上传 job mock。
- `GET /api/problem-upload-jobs/:jobId/events`：SSE / `ReadableStream` 进度 mock。
- `PATCH /api/problems/:problemId`：题目信息弹层自动保存标题和标签，保留 409 conflict 形态。
- `新题目` 空态：
  - 右侧预览收起。
  - composer 居中展示。
  - 不显示自动保存状态。
- `新题目` 对话态：
  - 用户发送后 composer 固定在中间栏底部。
  - 上方展示用户消息、图片缩略图、系统反馈和错误。
  - 回车发送，Shift+Enter 换行。
  - 发送后清空 composer；失败时保留历史并允许重试。
- 上传进度 UI：
  - 图片已上传
  - 正在识别题目
  - 正在提取题干
  - 正在生成解题方案
  - 正在编译网页
  - 完成 / 失败
- 创建成功后的跳转：
  - 新 problem 插入左侧题目列表顶部。
  - 自动选中新 problem。
  - 中间栏切换为题目对话页，并保留创建历史。
  - 右侧预览恢复并加载 problem preview。
- 题目对话页：
  - 中间栏只承载对话历史和底部 composer。
  - 题目标题、发布状态、保存状态放在顶部栏。
  - 右侧承担网页预览，不在中间栏常驻标题/标签表单。
  - 顶部栏提供 `题目信息` 弹层，编辑标题和标签后乐观更新本地 UI。
  - 停止输入 1.5 秒触发 `PATCH`；持续输入最多 30 秒强制触发一次。
  - mock 409 conflict 显示“这个题目已在其他窗口被更新，请刷新后再继续编辑。”，用户输入不被清空。
  - 后续作者输入暂以本地对话记录保存，Phase 3 接 `POST /api/problems/:problemId/messages` 真实 mock。

验收：

- 点击 `新题目` 后，右侧预览收起，composer 居中。
- 输入文字并发送后，进入对话态，能看到用户消息和系统状态。
- 文字创建成功后，左侧顶部新增 draft 题目，自动进入该题目，右侧加载 preview。
- 点击 `新题目` 上传图片后，前端能显示分段进度，完成后自动进入新题目。
- 上传成功后，创建历史里的图片以缩略图展示，点击可放大查看。
- 上传失败、SSE 中断、非题目图片能显示明确错误，不跳转，不清空历史。
- 创建成功后进入题目页，中间栏保留创建历史，底部 composer 固定悬浮。
- 题目页不显示“题目信息 / 标题 input / 标签 textarea”常驻表单。
- 点击顶部栏 `题目信息`，修改标题或标签后，左侧列表和顶部标题乐观更新，随后显示正在保存并回到刚刚已保存。
- 标题包含 `[conflict]` 时，显示其他窗口更新冲突提示，保存状态为失败。

非目标：

- 不要求生成结果真实正确。
- 不要求文件真正落工作区。
- 不实现 `decision_required`；已有题目对话中上传图片后的“新开任务 / 覆盖当前”留到 Phase 3。
- 不实现常驻题目信息表单；标题/标签只在顶部栏弹层中编辑。

### Phase 3：题目编辑模式与完整网页预览

目标：完成作者编辑模式的文字修改主链路：中间栏发送网页修改请求，mock API 返回 assistant 回复和新的 `previewVersion`，右侧完整网页 iframe 强制刷新。

交付：

- 题目页 `编辑模式`，不实现学习对话模式切换。
- 中间 Codex 风格主对话：
  - 无头像
  - 文档式消息
  - 底部 composer
  - 消息模型统一为 `ProblemMessage`
- 右侧完整网页 iframe：
  - 全量渲染
  - 内部滚动
  - 不切换单步预览
- `GET /api/problems/:problemId/messages` mock：已有 fixture 返回历史消息，新建 mock 题返回空数组。
- `POST /api/problems/:problemId/messages` mock：
  - 请求 `{ content, annotationIds? }`
  - 返回 user message、assistant message、更新后的 `Problem` 和 `preview`
  - `published -> published_dirty`，`draft` 保持 `draft`
  - `previewUrl` 可不变，但 `previewVersion` 必须变化
- 已有题目编辑页只支持文字修改；附件入口隐藏或禁用，图片上传 decision_required 留到后续。

验收：

- 用户输入“把第4步图形填充更明显”，mock 返回回复。
- `Problem.status` 从 `published` 变成 `published_dirty`。
- 如果 `previewUrl` 不变但 `previewVersion` 变化，iframe 能强制刷新。
- 新建题目后继续发送修改请求，状态保持 `draft`，消息流正常追加。

非目标：

- 不做网页注释。
- 不做真实 patch planning。
- 不做已有题目对话中的图片上传 decision_required。

### Phase 4：网页注释闭环

目标：验证差异化能力：用户在网页上选位置，注释进入主对话，AI 统一处理多条注释。

交付：

- iframe preview bridge：
  - 注册 `targetId`
  - `preview-target-selected`
  - `layout-changed`
  - target bounding box 查询
  - origin 校验
- 外层 overlay：
  - marker 编号
  - marker 位置刷新
  - 注释浮层
- 编辑模式 `注释` toggle：
  - 默认关闭
  - 开启后 hover 显示可注释区域
  - 已有 marker 可只读显示
- `POST /api/problems/:problemId/annotations` mock。
- 中间主对话显示“来自网页预览的 N 条注释”。
- 发送多条注释到 `POST /api/problems/:problemId/messages`。

验收：

- 用户能在右侧添加 3 条注释：
  - 原题图片
  - 第4步图形
  - 导航条
- 中间对话显示 3 条注释，并可一次发送处理。
- iframe 滚动、resize、滑块变化后 marker 不漂移。
- 注释 toggle 关闭时不能新增注释，但已有 marker 仍可查看。

非目标：

- 不做自由框选。
- 不要求截图作为主链路。

### Phase 5：发布模拟与静态站点路径

目标：在真实后端前，把发布、公开路径和状态流转跑通。

交付：

- `POST /api/problems/:problemId/publish` mock。
- `POST /api/topics/:topicId/publish` mock。
- `POST /api/site/home/publish` mock。
- `publicUrl` mock 到 `site/users/{userSlug}/...` 风格。
- 发布按钮状态：
  - 草稿：`发布`
  - 已发布：`打开页面`
  - 已发布 · 有改动：`发布更新`
- `site/index.html` 后续入口设计记录，不在本 phase 必须实现。

验收：

- 题目发布后状态变成 `已发布`，出现 `publicUrl`。
- 已发布题目再次修改后变成 `已发布 · 有改动`。
- 点击 `发布更新` 后恢复 `已发布`。

非目标：

- 不真正写入 `site/users/...`。
- 不接 CDN / Nginx。

### Phase 6：专题与网站首页管理

目标：完成非对话型内容组织页面，验证“题目生成后自动归类，人工校正”的流程。

交付：

- 专题详情页：
  - 标题和说明
  - 已收录题目
  - 拖拽排序
  - 添加题目
  - 移出专题
  - `SuggestedProblem`
- `GET /api/topics/:topicId/suggested-problems` mock。
- 接受 / 忽略自动归类建议 mock。
- 网站首页管理：
  - 网站名称和说明
  - 精选专题
  - 最近发布题目数量
  - 知识点入口
- 专题页和首页完整预览。

验收：

- 用户能接受一个 `SuggestedProblem`，题目进入专题列表。
- 用户能拖拽调整专题题目顺序并自动保存。
- 用户能编辑首页精选专题并看到右侧预览变化。

非目标：

- 不做专题对话。
- 不做自由布局搭建器。

### Phase 7：对话模式契约落地

目标：实现最小学习对话体验，但不阻塞前面的作者编辑链路。

数据模型和 API contract 从 Phase 0 开始保留；完整 UI 到本 phase 再做。

交付：

- 工作台题目页 `编辑 / 对话` 模式切换。
- `TutorChat` 核心组件：
  - `TutorMessageList`
  - `TutorInput`
  - `TutorActionExecutor`
- mock tutor session。
- 右侧网页 target 点击作为 `selectedTargetId`。
- mock `TutorAction`：
  - `scroll_to_step`
  - `highlight_target`
  - `show_hint`
- 已发布网页“问这道题”入口的组件封装。

验收：

- 题目拥有者可以在工作台从编辑模式切到对话模式。
- 已发布网页登录后只能进入对话模式。
- 学习对话保存到 tutor session，不改变题目发布状态。
- 工作台和发布页共用 `TutorChat` 核心组件，但使用不同 Shell。

非目标：

- 不要求真实 tutor LLM 效果。
- 不做语音。

### Phase 8：真实后端替换

目标：逐个替换 mock，实现过程中不改变前端 contract。

替换顺序建议：

1. `from-upload`：真实上传、检测、OCR、工作区创建、SSE 进度。
2. `generate`：真实生成网页和 `previewVersion`。
3. `messages`：真实作者对话修改、patch planning、编译校验。
4. `publish`：真实静态发布到 `site/users/{userSlug}/...`。
5. `suggested-problems`：真实异步归类建议 job。
6. `tutor-sessions`：真实学习对话。
7. 账号系统：从 hardcode current user 替换为 Clerk。

验收：

- 前端组件不改或少改。
- API 响应仍满足 contract schema。
- 失败时前端能展示可理解的错误原因。
- `ProblemWorkspace` 中能找到对应 uploads、conversation、specs、preview、publish、logs。

## 后端未 ready 时的错误模拟

mock API 需要覆盖成功和失败，避免前端只开发 happy path。

建议模拟：

- 生成中超时。
- 题干识别失败。
- 编译失败。
- 发布失败。
- 注释 `targetId` 失效。
- 图片上传创建题目失败。
- 上传 job SSE 中断。
- 自动保存 409 conflict。
- previewVersion 更新但 previewUrl 不变。
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
- 生成、对话修改和上传完成事件都返回 `previewVersion`，前端用它判断是否刷新 iframe。
- 发布接口返回新的 `status` 和 `publicUrl`。
- 对话修改接口返回 assistant message、problem 状态、preview 信息。
- 学习对话接口返回 tutor message 和可执行 `TutorAction`，不返回网页 patch，不改变 `Problem.status`。
- 消息图片使用 `attachments`，不嵌入 `content`。
- 注释接口只处理语义锚点和文本，不直接执行修改；修改由消息接口统一处理。
- 注释上下文以 `targetId + targetType + stepId` 为准，不要求截图；截图只作为可选视觉证据。

## 决策结论

1. 预览页注释 marker 采用“外层 overlay + iframe preview bridge”方案。
2. 发布后的公开页面继续落静态 HTML，不走 Next.js 动态路由。
3. 账号系统第一版使用内部单用户 hardcode 模式，正式上线前优先接 Clerk。
4. 后端生成页面兼容现有 lesson runtime / CSS / DOM 结构；路径结构可调整到 `site/users/{userSlug}/...`。
5. 专题自动归类建议在题目生成成功后异步写入，专题页读取预计算结果。
6. `对话模式` 的数据模型和 API contract 进入 MVP；完整 UI 实现放到 Phase 7。
7. 已发布网页中的“问这道题”和工作台对话模式共用核心 `TutorChat` 组件，但使用不同 Shell。

## 推荐的第一周目标

第一周只追 Phase 0-2：把工程底座、主壳、对象切换、上传进度和题目对话页跑通。不要急着做注释闭环。

1. 新建 `frontend/` 子项目并能本地启动。
2. 建立 Zod contract schema 和 typed API client。
3. 建立 Next.js Route Handlers mock API。
4. 建立 hardcode current user helper。
5. 做出三栏主 Shell 和左侧题目 / 网站 / 专题导航。
6. 左侧点击题目、专题、首页时，中间和右侧能切换。
7. 右侧 iframe 能加载静态 preview fixture。
8. 做出 `POST /api/problems/from-upload` job + SSE mock，并展示分段进度。
9. 做出题目创建后的对话式保存占位；顶部栏题目信息弹层接入标题/标签 autosave 和 409 conflict UI。
10. 在 schema 中保留 `TutorSession / TutorMessage / TutorAction`，但第一周不实现对话模式 UI。

第一周完成后，第二周进入 Phase 3-4：题目编辑对话、previewVersion 刷新、注释 overlay、注释进入主对话。
