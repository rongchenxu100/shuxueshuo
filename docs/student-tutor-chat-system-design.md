# 学生助教对话系统设计

## 1. 目标

助教在当前题目、课程步骤和学生交互状态下回答问题。它帮助学生理解已有教学事实，不替代 solver 创建新的未经验证答案。

## 2. 核心原则

-事实来自 Context 和已发布 lesson assets；
-回答明确区分题目条件、已证明结论和提示；
-优先引导，不直接泄露后续步骤；
-无法从当前证据回答时明确说明限制；
-对话不修改 PlannerStateContext 或课程事实；
-所有引用可追溯到 problem/lesson source。

## 3. 总体链路

```text
user message + current UI state
→ TutorContext projection
→ intent/policy
→ retrieval of lesson facts
→ response generation
→ citation/safety validation
→ UI response
```

## 4. TutorContext

包含最小必要信息：

- problem id 与题目摘要；
- lesson id/version；
-当前 step 和已完成步骤；
-允许引用的 Explanation/Lesson facts；
-当前 visual roles 和交互状态；
-学生最近消息；
-回答策略和 reveal boundary。

不包含：

- expected answer 的隐藏副本；
-全部 solver debug；
- StateVersionId、runtime path；
-无关题目或其他学生数据；
-完整历史 prompt。

## 5. 回答类型

```text
clarify_question
concept_explanation
step_hint
error_diagnosis
evidence_reference
interaction_guidance
cannot_answer
```

类型决定允许使用的事实和答案揭示程度。

### Hint progression

建议采用逐级提示：

1. 指向相关条件或图形；
2. 提醒可用方法；
3. 给出关键关系；
4. 展示当前步骤的完整推导。

默认不跨过学生尚未到达的 goal boundary。

## 6. Fact retrieval

检索以 stable source refs 为主：

- ProblemIR condition/goal；
- ExplanationSnapshot teaching trace；
- LessonIR step；
- VisualStepIR object/role；
-已发布互动状态。

向量或关键词搜索只能召回候选，最终回答必须绑定可验证 source refs。

## 7. 数学约束

-不重新选择 capability 或执行隐藏 solver 路线；
-若需要计算，调用受控 deterministic evaluator；
-不能修改已有公式、数值和对象身份；
-引用图中对象时使用 role binding；
-学生输入与题设冲突时指出冲突，而不是覆盖 Context；
-问题超出当前课程证据时可建议回到 solver/教师流程。

## 8. 会话状态

会话保存：

- stable session id；
- lesson/version；
-消息摘要；
-当前 step；
-已使用 hint level；
-显式用户偏好。

课程版本变化时，旧会话不得静默绑定新事实。应迁移可兼容摘要或开启新 session。

## 9. API

最小接口：

```text
POST /tutor/sessions
GET  /tutor/sessions/{id}
POST /tutor/sessions/{id}/messages
POST /tutor/sessions/{id}/feedback
```

响应包括：

- response type；
-文本/结构化内容；
- source citations；
-可选 UI action；
- safety/policy metadata；
-新的 hint level。

## 10. UI actions

助教可建议受限动作：

-跳到某 lesson step；
-高亮某 visual role；
-播放某 beat；
-重置交互；
-展开某条已验证推导。

客户端只执行白名单 action，不能执行模型生成的任意脚本。

## 11. 隐私与安全

-只保存完成服务所需的数据；
-日志中避免原始个人信息；
-学生内容与系统事实分区；
-拒绝不适当或无关请求时仍提供课程内替代帮助；
-模型输出经过 schema、citation 和 UI-action validation；
-防止用户文本注入内部 prompt 指令。

## 12. 质量评估

核心指标：

-事实正确率；
-citation coverage；
-hint appropriateness；
-过早泄露答案比例；
-学生修正错误的成功率；
-无法回答时的诚实率；
-延迟和 token 成本。

不要只用“用户是否得到最终答案”评价助教。

## 13. 测试

-当前/未来步骤 reveal boundary；
-同名对象 role 引用；
-错误学生假设；
-缺少证据时 cannot_answer；
-citation 指向有效 source；
-UI action 白名单；
-lesson version 变化；
-prompt injection；
-多轮 hint progression；
-移动端上下文切换。

## 14. Context 集成

Track G 中 TutorContext 是 LessonPageContext 的受限 projection。它只保存会话状态和 source refs，不复制完整 Planner/Explanation Context。

## 15. 相关文档

- `docs/llm-context-model-design.md`
- `docs/explanation-builder-design.md`
- `docs/frontend-parallel-development-with-mock-api-plan.md`
