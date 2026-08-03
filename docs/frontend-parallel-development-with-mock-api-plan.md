# 前端并行开发与 Mock API 计划

## 1. 目标

在 solver、lesson pipeline 和在线服务尚在迭代时，前端通过稳定的 API contract 和版本化 mock 数据独立开发。Mock 用于并行协作，不成为另一套产品语义。

## 2. 产品界面

主界面采用工作台结构：

-左侧：题目、步骤目录和资产状态；
-中间：讲解正文与交互图形；
-右侧：助教对话、证据和当前步骤上下文；
-底部或浮层：播放、步骤切换和运行状态。

界面第一屏直接进入可用课程，不建立营销 landing page。

## 3. 前后端边界

前端消费服务端已经验证的结构：

```text
Problem summary
LessonIR
VisualStepIR compiled scene
Voiceover/Animation timeline
Tutor response
Job status and diagnostics
```

前端不读取 solver 内部的 StateVersion、runtime path、compiler id 或 checkpoint。

## 4. 核心资源

建议保持以下资源边界：

| Resource | 用途 |
|---|---|
| `Problem` | 题目文本、图片和 scope 摘要 |
| `Lesson` | 课程版本、步骤和发布状态 |
| `Scene` | 某一步的编译后视觉场景 |
| `Timeline` | beat 与音频时间 |
| `TutorSession` | 对话和当前 lesson context |
| `Job` | 异步生成、编译和发布进度 |

响应必须带 schema/version 和 stable ids。

## 5. API 形态

API 名称可随服务实现调整，但语义应覆盖：

```text
GET  /problems/{id}
POST /lessons
GET  /lessons/{id}
GET  /lessons/{id}/steps/{step_id}
GET  /lessons/{id}/scenes/{scene_id}
GET  /lessons/{id}/timeline
POST /tutor/sessions
POST /tutor/sessions/{id}/messages
GET  /jobs/{id}
GET  /jobs/{id}/events
```

长任务使用 job + SSE/event stream；页面刷新后可以按 job id 恢复状态。

## 6. Mock contract

Mock fixture 必须：

-与正式 schema 共用类型或从同一 schema 生成；
-带固定 fixture version；
-覆盖 loading/success/partial/error；
-覆盖无音频、无交互、视觉 gap 和 tutor unavailable；
-不包含前端自行创造的 solver 字段；
-在 CI 中通过正式 decoder/validator。

禁止在组件中散落临时 JSON。Fixture 统一放在测试资产目录并有明确场景名。

## 7. 开发模式

前端 data provider 只暴露一种业务接口，底层可切换：

```text
MockLessonApi
HttpLessonApi
```

组件不判断当前是否 mock。切换只发生在 app bootstrap 或测试环境。

## 8. 页面状态

必须明确处理：

-题目加载；
-lesson 生成中；
-部分步骤可用；
-视觉或音频单项失败；
-solver/retry 失败；
-网络重连；
-job 已取消或失效；
-schema version 不兼容。

局部资产失败不应让整个页面空白；但数学事实不可用时不得展示猜测内容。

## 9. 交互与可访问性

-键盘可切换步骤和播放；
-按钮使用图标和 tooltip；
-图形对象具有可读 label/description；
-移动端保持题目、讲解和图形可访问；
-文本不与画布控件重叠；
-reduce-motion 下仍能理解步骤变化；
-音频提供文字同步内容。

## 10. Tutor 集成

发送消息时只提交：

- session id；
-当前 lesson/step id；
-用户问题；
-允许的选区或交互状态摘要。

服务端负责构造 TutorContext。前端不拼接完整 solver prompt。

## 11. 并行协作流程

1. 后端先提交 schema 和最小 fixture。
2. 前端基于 mock 完成交互和视觉测试。
3. CI 用正式 decoder 校验所有 fixture。
4. 后端实现真实 endpoint。
5. contract tests 比较 mock/real 响应形状。
6. 集成环境切换 Http provider。
7. 删除只服务临时接口的兼容字段。

Breaking change 必须升级 schema version，并同步 fixture、decoder 和文档。

## 12. 测试

-组件 loading/error/partial states；
-Mock 与 real decoder parity；
-job/SSE 重连；
-lesson step navigation；
-scene 与 timeline 同步；
-TutorContext 切换；
-桌面和移动端截图；
-键盘与 reduce-motion；
-schema incompatibility fail loud。

## 13. 完成标准

-前端可完全依赖 mock 完成核心课程流程；
-同一构建切换 real API 无组件逻辑差异；
-fixture 全部通过正式 schema validation；
-真实 lesson 能完成题目、讲解、图形、音频和助教闭环；
-错误状态可恢复且不展示未验证数学事实。

## 14. 相关文档

- `docs/online-service-development-plan.md`
- `docs/student-tutor-chat-system-design.md`
- `docs/visual-step-ir-design.md`
