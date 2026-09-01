请基于下面的 verified ExplanationSnapshot 摘要，输出 LessonIR 的文字步骤草稿。

你只做“讲解分组 + 讲解文字优化”，不重新解题。

## 输出格式

返回 JSON 对象：

```json
{
  "steps": [
    {
      "id": "string",
      "candidate_group_ids": ["一个或多个 candidate candidate_group_ids"],
      "source_step_ids": ["兼容字段；优先使用 candidate_group_ids"],
      "title": "string",
      "nav_title": "string",
      "goal": "string",
      "derive": [["标签", "面向学生的讲解句"]],
      "box": ["重要结论文字"]
    }
  ]
}
```

## 讲解步骤分组策略

{
  "granularity": "每个 lesson step 只讲一个认知动作",
  "do_not": [
    "不要把一个完整小问直接合并成一个 lesson step，除非它本来只有一个认知动作。",
    "不要机械地保持 one method per lesson step；相邻的纯坐标/代数准备可以合并。",
    "不要跨 scope 合并。"
  ],
  "keep_separate_when_present": [
    "求/化简函数解析式或含参解析式",
    "由角度、等长、旋转、正方形等几何关系得到辅助对象",
    "联立直线/曲线或筛选候选点",
    "把多动点路径转化为单动点路径",
    "用将军饮马、两点距离或几何不等式说明最小值",
    "由最小值或条件反求参数",
    "极值状态下恢复最终答案点"
  ],
  "merge_when_adjacent": [
    "同一认知动作内的坐标准备和代入验算",
    "同一 recipe 内部的候选生成与选择，若学生只需要理解一个动作",
    "纯代数化简链条，若没有新的几何思想"
  ],
  "target_step_count_hint": {
    "candidate_group_count": 12,
    "recommended_min": 5,
    "recommended_max": 9,
    "note": "这是软约束；优先保证认知动作清晰。"
  },
  "style_reference": "目标粒度类似人工 lesson-data：一个复杂 25 题通常拆成约 6-8 个学生步骤，而不是每个小问一个步骤。"
}

## 安全规则

[
  "只返回 JSON，不要使用 Markdown 代码块。",
  "优先用 candidate_group_ids 引用候选步骤；只能组合 candidate_groups 中已有的 candidate_group_id，不要发明新的 id。",
  "source_step_ids 是真实解题来源引用，若同一个 source_step_id 被拆成多个 candidate_group_id，不要只用 source_step_ids 合并它们。",
  "不要新增 handle、事实、数值、答案、点、线或条件。",
  "不要提到 runtime ContextPath 或内部 method 路径。",
  "讲解文字使用适合初中生的中文表达。",
  "不要只按大问/小问整体分组；较长小问通常需要拆成多个讲解步骤。",
  "若 merge_suggestions 给出 candidate_group_ids，可以按建议合并这些简单连续步骤；仍必须保留所有 source_step_ids/capability_ids 的事实边界。",
  "若 candidate_group 提供 teaching_expansion_draft，优先使用该草稿，不要根据 method_id 自己猜证明。",
  "若 candidate_group 提供 required_references，它们是代码确认的跨问复用关系；可润色但不要重新计算这些结论。",
  "可以把一个 executable recipe 拆成多个 LessonIR steps，但 source_step_ids 必须仍来自 candidate_groups。",
  "teaching_expansion_draft 中 explanation_only_label=true 的辅助点只用于讲解，不是新的 FunctionalPlan return。",
  "示例讲解只用于学习标题、derive 标签、步骤粒度和讲解风格；不要复制示例题的点名、数值、答案或 source_step_ids。",
  "title 尽量使用“第 N 步：动作 + 目的”的格式，不要写“第一部分/第二部分”这类系统拆分词。",
  "derive 标签优先使用证明流标签：作、∵、∴。代入、化简、解方程、筛选等动作词应写在正文里，不作为标签。",
  "每个 derive item 只表达一个逻辑动作：∵ 只写依据/前提，∴ 只写由前文推出的方程、化简结果、解或结论。",
  "不要在同一个 derive item 中写“……所以/因此/∴……”；必须拆成相邻的 ∵/代入/化简/解 与 ∴ 两行。",
  "不要输出标签“代入”“化简”“解”“筛选”；例如写成 [\"∴\", \"代入得 a-b=3\"] 或 [\"∴\", \"解得 a=1，b=-2\"]。",
  "title 写带当前题上下文的解题思路，例如“第1步：求 C、D 点坐标，代入求函数解析式”。",
  "nav_title 写短导航标题，不必带所有点名，例如“代入已知点求解析式”。",
  "若 candidate_group 提供 teaching_substep_title/nav_title 与 required_terms，title/nav_title 必须覆盖这些教学关键词；可加入当前题点名，但不要偏离该认知动作。",
  "box 只能写学生可读关键结论，例如 C(0,-3)、y=x²-2x-3、a=3/4；不要写 answer:*、fact:*、i_1.parabola = ... 或 Python/SymPy 表达式。",
  "answers 中的每个最终答案都必须以学生可读形式出现在相关最终讲解步骤的 box 中。"
]

## 讲解草稿使用规则

- `candidate_groups[].teaching_expansion_draft` 是代码根据已验算的步骤、facts 和 recipe/method 模板生成的可信草稿。
- 若某个候选步骤包含 `teaching_expansion_draft`，讲解时必须优先使用其中的 `proof_draft`、`student_intent_draft`、`bound_roles` 和 `recommended_lesson_splits`。
- 请优先用 `candidate_group_ids` 选择候选；同一个 `source_step_id` 可能已经被代码拆成多个 `candidate_group_id`。
- 你可以把一个 executable recipe 拆成多个 LessonIR steps，只要 `candidate_group_ids` 来自候选列表。
- 如果候选或草稿同时涉及“构造/路径转化”和“求最值/计算表达式”，必须拆成两个 LessonIR steps：先讲转化，再讲最值，不要合并到同一个标题或 derive 中。
- 每个 derive item 只能表达一个逻辑动作：
  - `作`：只写构造。
  - `∵`：只写已知、依据、计算前提，例如 `A(-1,0)和D(2,-3)在抛物线上，代入得方程组`。
  - `∴`：只写由前文推出的方程、化简结果、解或结论，例如 `a·(-1)²+b·(-1)-3=0 → a-b=3`、`a=1，b=-2`。
- 不要使用 `代入 / 化简 / 解 / 筛选` 作为标签；这些词可以写在正文里。
- 不要写 `["解", "令 x=0 得 y=-3，所以 C(0,-3)"]`；应拆成 `["∵", "令 x=0 得 y=-3"]`、`["∴", "C(0,-3)"]`。
- 不要写 `["代入", "a·(-1)²+b·(-1)-3=0 → a-b=3"]`；应写成 `["∴", "a·(-1)²+b·(-1)-3=0 → a-b=3"]`。
- 不要写 `["∵", "A(-1,0)在抛物线上，代入得 a·(-1)²+b·(-1)-3=0 → a-b=3"]`；应拆成 `["∵", "A(-1,0)在抛物线上"]`、`["∴", "代入得 a·(-1)²+b·(-1)-3=0 → a-b=3"]`。
- draft 标记为 `partial` 或 `gap` 时，只能用谨慎表达补充，不要硬写未验证的具体三角形、点名或结论。
- `explanation_only_label=true` 的辅助点只用于学生讲解，不是 StepIntent 中的 creates，也不是新的 runtime fact。
- 不要使用 draft 没有明确给出的“对称”“旋转”“相似”“对顶角”等几何关系来补证明。
- `title` 写带当前题上下文的解题思路；`nav_title` 写短导航标题，不必带所有点名。
- `box` 只能写学生可读关键结论，例如 `C(0,-3)`、`y=x²-2x-3`、`a=3/4`。
- `box` 不要写 `answer:*`、`fact:*`、`i_1.parabola = ...` 或 `x**2 - 2*x - 3` 这类内部/Python 表达式。

## 当前题目

{
  "original_text": [
    "已知抛物线 y=-x²+bx+c（b，c 为常数，c>1）的顶点为 P，与 x 轴相交于 A，B 两点（点 A 在点 B 的左侧），与 y 轴相交于点 C，对称轴与 x 轴相交于点 M。点 E 在对称轴上，以 AE 为边的正方形 AEKG 的顶点 G 在 x 轴下方。",
    "（Ⅰ）若 b=-2，c=3。",
    "① 求点 P 和点 A 的坐标；",
    "② 当点 G 在抛物线上时，求点 E 的坐标；",
    "（Ⅱ）若点 A 的坐标为（-c，0），点 F 是 AE 的中点，对角线 AK 和 EG 相交于点 H，当 HF+FM+MG 取得最小值为 3√5 时，求点 E 的坐标。"
  ],
  "scopes": [
    {
      "label": "整题",
      "parent": null,
      "scope_id": "problem"
    },
    {
      "label": "第（Ⅰ）问",
      "parent": "problem",
      "scope_id": "i"
    },
    {
      "asks": [
        "P",
        "A"
      ],
      "label": "第（Ⅰ）①问",
      "parent": "i",
      "scope_id": "i_1"
    },
    {
      "asks": [
        "E"
      ],
      "label": "第（Ⅰ）②问",
      "parent": "i",
      "scope_id": "i_2"
    },
    {
      "asks": [
        "E"
      ],
      "label": "第（Ⅱ）问",
      "parent": "problem",
      "scope_id": "ii"
    }
  ],
  "question_goals": [
    {
      "answer_key": "P",
      "description": "第（Ⅰ）①问输出P",
      "handle": "answer:i_1.P",
      "required": true,
      "scope_id": "i_1",
      "target_handle": "point:problem:P",
      "value_type": "Point"
    },
    {
      "answer_key": "A",
      "description": "第（Ⅰ）①问输出A",
      "handle": "answer:i_1.A",
      "required": true,
      "scope_id": "i_1",
      "target_handle": "point:problem:A",
      "value_type": "Point"
    },
    {
      "answer_key": "E",
      "description": "第（Ⅰ）②问输出E",
      "handle": "answer:i_2.E",
      "required": true,
      "scope_id": "i_2",
      "target_handle": "point:problem:E",
      "value_type": "PointList"
    },
    {
      "answer_key": "E",
      "description": "第（Ⅱ）问输出E",
      "handle": "answer:ii.E",
      "required": true,
      "scope_id": "ii",
      "target_handle": "point:problem:E",
      "value_type": "Point"
    }
  ]
}

## 已验算答案

{
  "i_1": {
    "P": [
      "-1",
      "4"
    ],
    "A": [
      "-3",
      "0"
    ]
  },
  "i_2": {
    "E": [
      [
        "-1",
        "2 - sqrt(6)"
      ],
      [
        "-1",
        "2 + sqrt(6)"
      ]
    ]
  },
  "ii": {
    "E": [
      "-2",
      "3/2"
    ]
  }
}


## 示例讲解

下面是相似题或同题型 mock 的 LessonIR 示例。它不是当前题条件，只学习：

- 标题如何写成“第 N 步：动作 + 目的”。
- derive 如何使用 `作 / ∵ / ∴` 组织证明流；代入、化简、解方程、筛选等动作词写在正文里。
- recipe 如何拆成多个学生认知步骤。
- 不要复制示例题的点名、数值、答案或 source_step_ids。

[
  {
    "problem_id": "fallback-QuadraticSquareReflectionPathMinimumSolver-lesson",
    "family_id": "QuadraticSquareReflectionPathMinimumSolver",
    "title": "通用讲解示例",
    "original_text": [
      "抽象示例：先由题设条件推出中间结论，再代入计算最终答案。"
    ],
    "retrieval": {
      "goal_types": [],
      "capability_ids": []
    },
    "example": {
      "lesson_ir": {
        "steps": [
          {
            "id": "mock_step_1",
            "title": "第1步：整理题设条件，得到可用结论",
            "source_step_ids": [
              "mock_step"
            ],
            "derive": [
              [
                "∵",
                "题目给出了可代入的条件。"
              ],
              [
                "∴",
                "先求出后续会用到的中间量。"
              ]
            ],
            "box": [
              "得到中间结论"
            ]
          }
        ]
      }
    }
  }
]

## 可分组的候选步骤

[
  {
    "candidate_group_id": "derive_parabola_i",
    "source_step_id": "derive_parabola_i",
    "teaching_substep_id": null,
    "teaching_substep_title": null,
    "teaching_substep_nav_title": null,
    "teaching_substep_title_required_terms": [],
    "teaching_substep_nav_title_required_terms": [],
    "teaching_focus": null,
    "scope_id": "i",
    "capability_id": "quadratic_from_constraints",
    "method_ids": [
      "quadratic_from_constraints"
    ],
    "target": "fact:i:derive_parabola_i_coefficients",
    "goal_type": "quadratic_from_constraints",
    "strategy": "",
    "reason": "代入本问给定系数得到完整抛物线。",
    "reads": [
      "symbol_value_b",
      "symbol_value_c"
    ],
    "produces": [
      {
        "handle": "fact:i:derive_parabola_i_coefficients",
        "valid_scope": "i",
        "description": "quadratic_from_constraints return coefficients",
        "output_type": "Coefficients"
      },
      {
        "handle": "fact:i:derive_parabola_i_parabola",
        "valid_scope": "i",
        "description": "quadratic_from_constraints return parabola",
        "output_type": "Parabola"
      }
    ],
    "trace_refs": [
      "trace:derive_parabola_i:0:quadratic_from_constraints"
    ],
    "trace_summaries": [
      {
        "trace_id": "trace:derive_parabola_i:0:quadratic_from_constraints",
        "method_id": "quadratic_from_constraints",
        "trace_fragments": [
          {
            "return": "coefficients",
            "runtime_type": "Coefficients",
            "value": {
              "b": "-2",
              "c": "3"
            }
          },
          {
            "return": "parabola",
            "runtime_type": "Parabola",
            "value": "-x**2 - 2*x + 3"
          }
        ],
        "checks": []
      }
    ],
    "method_explanation": {
      "quadratic_from_constraints": {
        "role_schema": {
          "constraints": "用于确定当前问二次函数的系数约束。",
          "result_parabola": "由约束得到的当前问抛物线解析式。",
          "parabola_title_action": "标题动词；完全确定时为求，含后续参数时为化简。",
          "completed_square_suffix": "配方形式补充说明；没有配方形式时为空。"
        },
        "student_goal_template": "代入当前问给出的约束，确定二次函数解析式。",
        "student_title_template": "{parabola_title_action}函数解析式",
        "student_nav_title_template": "{parabola_title_action}解析式",
        "student_title_templates_by_goal": {},
        "derive_templates": [
          "∵{constraints}",
          "∴y＝{result_parabola}{completed_square_suffix}"
        ],
        "box_templates": [
          "y＝{result_parabola}"
        ],
        "explanation_level": "template",
        "role_binding_strategy": "role_name_registry",
        "role_binder_id": "quadratic_from_constraints"
      }
    },
    "teaching_expansion_draft": {
      "confidence": "complete",
      "bound_roles": {
        "constraints": "b＝－2，c＝3",
        "result_parabola": "－x²－2x＋3",
        "parabola_title_action": "求",
        "completed_square_suffix": "＝－(x＋1)²＋4"
      },
      "unbound_roles": [],
      "student_title": "求函数解析式",
      "student_nav_title": "求解析式",
      "proof_draft": [
        "∵b＝－2，c＝3",
        "∴y＝－x²－2x＋3＝－(x＋1)²＋4"
      ],
      "box": [
        "y＝－x²－2x＋3"
      ],
      "llm_can_complete": [
        "可以把 method 计算草稿改写成更自然的初中数学推导。",
        "可以根据 trace 中的 calculation/conclusion 补充代入、化简、筛选等过渡句。"
      ],
      "llm_must_not_invent": [
        "不得新增题目中不存在、draft 中也没有给出的点名、线段名或事实。",
        "不得新增数值、答案或坐标。",
        "不得把 method trace 中的临时变量当作学生讲解里的已知对象。"
      ]
    }
  },
  {
    "candidate_group_id": "derive_x_intercept_A_i",
    "source_step_id": "derive_x_intercept_A_i",
    "teaching_substep_id": null,
    "teaching_substep_title": null,
    "teaching_substep_nav_title": null,
    "teaching_substep_title_required_terms": [],
    "teaching_substep_nav_title_required_terms": [],
    "teaching_focus": null,
    "scope_id": "i",
    "capability_id": "quadratic_x_axis_intercept_point",
    "method_ids": [
      "quadratic_x_axis_intercept_point"
    ],
    "target": "fact:i:derive_x_intercept_A_i_point",
    "goal_type": "quadratic_x_axis_intercept_point",
    "strategy": "",
    "reason": "求横轴左侧交点。",
    "reads": [
      "function:problem:parabola"
    ],
    "produces": [
      {
        "handle": "fact:i:derive_x_intercept_A_i_point",
        "valid_scope": "i",
        "description": "quadratic_x_axis_intercept_point return point",
        "output_type": "Point"
      },
      {
        "handle": "answer:i_1.A",
        "valid_scope": "i",
        "description": "quadratic_x_axis_intercept_point return point",
        "output_type": "Point"
      }
    ],
    "trace_refs": [
      "trace:derive_x_intercept_A_i:0:quadratic_x_axis_intercept_point"
    ],
    "trace_summaries": [
      {
        "trace_id": "trace:derive_x_intercept_A_i:0:quadratic_x_axis_intercept_point",
        "method_id": "quadratic_x_axis_intercept_point",
        "trace_fragments": [
          {
            "return": "point",
            "runtime_type": "Point",
            "value": [
              "-3",
              "0"
            ]
          }
        ],
        "checks": []
      }
    ],
    "method_explanation": {
      "quadratic_x_axis_intercept_point": {
        "role_schema": {
          "parabola": "当前抛物线解析式。",
          "intercept_equation": "令 y=0 后得到的一元二次方程。",
          "target_point": "需要求出的 x 轴交点。",
          "known_point": "可选的已知 x 轴交点。"
        },
        "student_goal_template": "令 y=0，求抛物线与 x 轴的交点。",
        "student_title_template": "求抛物线与 x 轴交点",
        "student_nav_title_template": "",
        "student_title_templates_by_goal": {},
        "derive_templates": [
          "∵x 轴交点满足 y＝0，即 {intercept_equation}",
          "∴{target_point}"
        ],
        "box_templates": [],
        "explanation_level": "template",
        "role_binding_strategy": "role_name_registry",
        "role_binder_id": "quadratic_x_axis_intercept_point"
      }
    },
    "teaching_expansion_draft": {
      "confidence": "complete",
      "bound_roles": {
        "parabola": "y＝－x²－2x＋3",
        "intercept_equation": "－x²－2x＋3＝0",
        "target_point": "A(－3,0)",
        "known_point": "已知交点"
      },
      "unbound_roles": [],
      "student_title": "求抛物线与 x 轴交点",
      "student_nav_title": "",
      "proof_draft": [
        "∵x 轴交点满足 y＝0，即 －x²－2x＋3＝0",
        "∴A(－3,0)"
      ],
      "box": [],
      "llm_can_complete": [
        "可以把 method 计算草稿改写成更自然的初中数学推导。",
        "可以根据 trace 中的 calculation/conclusion 补充代入、化简、筛选等过渡句。"
      ],
      "llm_must_not_invent": [
        "不得新增题目中不存在、draft 中也没有给出的点名、线段名或事实。",
        "不得新增数值、答案或坐标。",
        "不得把 method trace 中的临时变量当作学生讲解里的已知对象。"
      ]
    }
  },
  {
    "candidate_group_id": "derive_vertex_P_i",
    "source_step_id": "derive_vertex_P_i",
    "teaching_substep_id": null,
    "teaching_substep_title": null,
    "teaching_substep_nav_title": null,
    "teaching_substep_title_required_terms": [],
    "teaching_substep_nav_title_required_terms": [],
    "teaching_focus": null,
    "scope_id": "i_1",
    "capability_id": "quadratic_vertex_point",
    "method_ids": [
      "quadratic_vertex_point"
    ],
    "target": "fact:i_1:derive_vertex_P_i_point",
    "goal_type": "quadratic_vertex_point",
    "strategy": "",
    "reason": "由抛物线解析式求顶点。",
    "reads": [
      "function:problem:parabola"
    ],
    "produces": [
      {
        "handle": "fact:i_1:derive_vertex_P_i_point",
        "valid_scope": "i_1",
        "description": "quadratic_vertex_point return point",
        "output_type": "Point"
      },
      {
        "handle": "answer:i_1.P",
        "valid_scope": "i_1",
        "description": "quadratic_vertex_point return point",
        "output_type": "Point"
      }
    ],
    "trace_refs": [
      "trace:derive_vertex_P_i:0:quadratic_vertex_point"
    ],
    "trace_summaries": [
      {
        "trace_id": "trace:derive_vertex_P_i:0:quadratic_vertex_point",
        "method_id": "quadratic_vertex_point",
        "trace_fragments": [
          {
            "return": "point",
            "runtime_type": "Point",
            "value": [
              "-1",
              "4"
            ]
          }
        ],
        "checks": []
      }
    ],
    "required_references": [
      "由第（Ⅰ）问已得相关结论，继续计算。"
    ],
    "method_explanation": {
      "quadratic_vertex_point": {
        "role_schema": {
          "parabola_vertex_form": "抛物线配方后的顶点式。",
          "vertex_point": "由顶点式读出的顶点坐标。"
        },
        "student_goal_template": "把二次函数整理成顶点式，读出顶点坐标。",
        "student_title_template": "求二次函数顶点",
        "student_nav_title_template": "",
        "student_title_templates_by_goal": {},
        "derive_templates": [
          "∵{parabola_vertex_form}",
          "∴{vertex_point}"
        ],
        "box_templates": [],
        "explanation_level": "template",
        "role_binding_strategy": "role_name_registry",
        "role_binder_id": "quadratic_vertex_point"
      }
    },
    "teaching_expansion_draft": {
      "confidence": "complete",
      "bound_roles": {
        "parabola_vertex_form": "y＝－(x＋1)²＋4",
        "vertex_point": "P(－1,4)"
      },
      "unbound_roles": [],
      "student_title": "求二次函数顶点",
      "student_nav_title": "",
      "proof_draft": [
        "∵y＝－(x＋1)²＋4",
        "∴P(－1,4)"
      ],
      "box": [],
      "llm_can_complete": [
        "可以把 method 计算草稿改写成更自然的初中数学推导。",
        "可以根据 trace 中的 calculation/conclusion 补充代入、化简、筛选等过渡句。"
      ],
      "llm_must_not_invent": [
        "不得新增题目中不存在、draft 中也没有给出的点名、线段名或事实。",
        "不得新增数值、答案或坐标。",
        "不得把 method trace 中的临时变量当作学生讲解里的已知对象。"
      ]
    }
  },
  {
    "candidate_group_id": "parameterize_axis_point_E_i",
    "source_step_id": "parameterize_axis_point_E_i",
    "teaching_substep_id": null,
    "teaching_substep_title": null,
    "teaching_substep_nav_title": null,
    "teaching_substep_title_required_terms": [],
    "teaching_substep_nav_title_required_terms": [],
    "teaching_focus": null,
    "scope_id": "i_2",
    "capability_id": "quadratic_axis_parameterized_point",
    "method_ids": [
      "quadratic_axis_parameterized_point"
    ],
    "target": "point:problem:E",
    "goal_type": "quadratic_axis_parameterized_point",
    "strategy": "",
    "reason": "把对称轴上的目标点表示为单参数点。",
    "reads": [
      "function:problem:parabola"
    ],
    "produces": [
      {
        "handle": "fact:i_2:parameterize_axis_point_E_i_point",
        "valid_scope": "i_2",
        "description": "quadratic_axis_parameterized_point return point",
        "output_type": "Point"
      },
      {
        "handle": "fact:i_2:E_point",
        "valid_scope": "i_2",
        "description": "quadratic_axis_parameterized_point return point",
        "output_type": "Point"
      },
      {
        "handle": "fact:i_2:parameterize_axis_point_E_i_parameter",
        "valid_scope": "i_2",
        "description": "quadratic_axis_parameterized_point return parameter",
        "output_type": "Symbol"
      }
    ],
    "trace_refs": [
      "trace:parameterize_axis_point_E_i:0:quadratic_axis_parameterized_point"
    ],
    "trace_summaries": [
      {
        "trace_id": "trace:parameterize_axis_point_E_i:0:quadratic_axis_parameterized_point",
        "method_id": "quadratic_axis_parameterized_point",
        "trace_fragments": [
          {
            "return": "point",
            "runtime_type": "Point",
            "value": [
              "-1",
              "_axis_param_E"
            ]
          },
          {
            "return": "parameter",
            "runtime_type": "Symbol",
            "value": "_axis_param_E"
          }
        ],
        "checks": []
      }
    ],
    "required_references": [
      "由第（Ⅰ）问已得相关结论，继续计算。"
    ],
    "method_explanation": {
      "quadratic_axis_parameterized_point": {
        "role_schema": {
          "target": "对称轴上的目标点。",
          "axis_equation": "当前抛物线的对称轴方程。",
          "parameterized_point": "目标点的参数化坐标。"
        },
        "student_goal_template": "把对称轴上的点设成一个参数点。",
        "student_title_template": "设对称轴上的参数点",
        "student_nav_title_template": "",
        "student_title_templates_by_goal": {},
        "derive_templates": [
          "∵{target} 在对称轴 {axis_equation} 上",
          "∴设 {parameterized_point}"
        ],
        "box_templates": [
          "{parameterized_point}"
        ],
        "explanation_level": "template",
        "role_binding_strategy": "role_name_registry",
        "role_binder_id": "quadratic_axis_parameterized_point"
      }
    },
    "teaching_expansion_draft": {
      "confidence": "complete",
      "bound_roles": {
        "target": "E",
        "axis_equation": "x＝－1",
        "parameterized_point": "E(－1,t)"
      },
      "unbound_roles": [],
      "student_title": "设对称轴上的参数点",
      "student_nav_title": "",
      "proof_draft": [
        "∵E 在对称轴 x＝－1 上",
        "∴设 E(－1,t)"
      ],
      "box": [
        "E(－1,t)"
      ],
      "llm_can_complete": [
        "可以把 method 计算草稿改写成更自然的初中数学推导。",
        "可以根据 trace 中的 calculation/conclusion 补充代入、化简、筛选等过渡句。"
      ],
      "llm_must_not_invent": [
        "不得新增题目中不存在、draft 中也没有给出的点名、线段名或事实。",
        "不得新增数值、答案或坐标。",
        "不得把 method trace 中的临时变量当作学生讲解里的已知对象。"
      ]
    }
  },
  {
    "candidate_group_id": "derive_square_vertex_G_i",
    "source_step_id": "derive_square_vertex_G_i",
    "teaching_substep_id": null,
    "teaching_substep_title": null,
    "teaching_substep_nav_title": null,
    "teaching_substep_title_required_terms": [],
    "teaching_substep_nav_title_required_terms": [],
    "teaching_focus": null,
    "scope_id": "i_2",
    "capability_id": "square_adjacent_vertex_from_side",
    "method_ids": [
      "square_adjacent_vertex_from_side"
    ],
    "target": "point:problem:G",
    "goal_type": "square_adjacent_vertex_from_side",
    "strategy": "",
    "reason": "将正方形已知边旋转得到相邻顶点。",
    "reads": [
      "point:problem:E",
      "point:problem:A",
      "fact:problem:square_b19d8510e827"
    ],
    "produces": [
      {
        "handle": "fact:i_2:derive_square_vertex_G_i_adjacent_vertex",
        "valid_scope": "i_2",
        "description": "square_adjacent_vertex_from_side return adjacent_vertex",
        "output_type": "Point"
      },
      {
        "handle": "fact:i_2:G_adjacent_vertex",
        "valid_scope": "i_2",
        "description": "square_adjacent_vertex_from_side return adjacent_vertex",
        "output_type": "Point"
      }
    ],
    "trace_refs": [
      "trace:derive_square_vertex_G_i:0:square_adjacent_vertex_from_side"
    ],
    "trace_summaries": [
      {
        "trace_id": "trace:derive_square_vertex_G_i:0:square_adjacent_vertex_from_side",
        "method_id": "square_adjacent_vertex_from_side",
        "trace_fragments": [
          {
            "return": "adjacent_vertex",
            "runtime_type": "Point",
            "value": [
              "_axis_param_E - 3",
              "-2"
            ]
          }
        ],
        "checks": []
      }
    ],
    "required_references": [
      "由第（Ⅰ）问已得点 A，继续计算。"
    ],
    "method_explanation": {
      "square_adjacent_vertex_from_side": {
        "role_schema": {
          "target_label": "学生可见的目标顶点点名。",
          "projection_construction": "为目标顶点作坐标辅助线的构造说明。",
          "square_name": "学生可见的正方形名称。",
          "side_equal_statement": "正方形相邻边相等的结论。",
          "square_right_angle_statement": "正方形公共顶点处的直角结论。",
          "projection_right_angles": "坐标辅助线形成的直角关系。",
          "matching_angle_statement": "对应的非直角锐角关系。",
          "triangle_congruence": "学生可见的全等直角三角形。",
          "length_correspondence": "全等后对应的坐标长度关系。",
          "target_position_condition": "用于选择目标点的方位条件。",
          "target_point": "学生可见的目标顶点坐标。"
        },
        "student_goal_template": "利用正方形相邻边垂直且等长，求相邻顶点坐标。",
        "student_title_template": "由正方形求相邻顶点{target_label}",
        "student_nav_title_template": "正方形求顶点{target_label}",
        "student_title_templates_by_goal": {},
        "derive_templates": [
          "作{projection_construction}",
          "∵四边形 {square_name} 是正方形",
          "∴{side_equal_statement}，{square_right_angle_statement}",
          "∵{projection_right_angles}",
          "∴{matching_angle_statement}",
          "∴{triangle_congruence}",
          "∴{length_correspondence}",
          "∵{target_position_condition}",
          "∴{target_point}"
        ],
        "box_templates": [
          "{target_point}"
        ],
        "explanation_level": "template",
        "role_binding_strategy": "role_name_registry",
        "role_binder_id": "square_adjacent_vertex_from_side"
      }
    },
    "teaching_expansion_draft": {
      "confidence": "complete",
      "bound_roles": {
        "target_label": "G",
        "projection_construction": "GQ⊥x轴于 Q",
        "square_name": "AEKG",
        "side_equal_statement": "AE＝AG",
        "square_right_angle_statement": "∠EAG＝90°",
        "projection_right_angles": "∠EMA＝∠GQA＝90°",
        "matching_angle_statement": "∠EAM＝∠AGQ",
        "triangle_congruence": "Rt△AEM≌Rt△GAQ",
        "length_correspondence": "AQ＝ME＝t，GQ＝AM＝2",
        "target_position_condition": "G 在 x 轴下方",
        "target_point": "G(t－3,－2)"
      },
      "unbound_roles": [],
      "student_title": "由正方形求相邻顶点G",
      "student_nav_title": "正方形求顶点G",
      "proof_draft": [
        "作GQ⊥x轴于 Q",
        "∵四边形 AEKG 是正方形",
        "∴AE＝AG，∠EAG＝90°",
        "∵∠EMA＝∠GQA＝90°",
        "∴∠EAM＝∠AGQ",
        "∴Rt△AEM≌Rt△GAQ",
        "∴AQ＝ME＝t，GQ＝AM＝2",
        "∵G 在 x 轴下方",
        "∴G(t－3,－2)"
      ],
      "box": [
        "G(t－3,－2)"
      ],
      "llm_can_complete": [
        "可以把 method 计算草稿改写成更自然的初中数学推导。",
        "可以根据 trace 中的 calculation/conclusion 补充代入、化简、筛选等过渡句。"
      ],
      "llm_must_not_invent": [
        "不得新增题目中不存在、draft 中也没有给出的点名、线段名或事实。",
        "不得新增数值、答案或坐标。",
        "不得把 method trace 中的临时变量当作学生讲解里的已知对象。"
      ]
    }
  },
  {
    "candidate_group_id": "solve_axis_point_candidates_i",
    "source_step_id": "solve_axis_point_candidates_i",
    "teaching_substep_id": null,
    "teaching_substep_title": null,
    "teaching_substep_nav_title": null,
    "teaching_substep_title_required_terms": [],
    "teaching_substep_nav_title_required_terms": [],
    "teaching_focus": null,
    "scope_id": "i_2",
    "capability_id": "point_candidates_from_curve_point_condition",
    "method_ids": [
      "point_candidates_from_curve_point_condition"
    ],
    "target": "fact:i_2:solve_axis_point_candidates_i_candidates",
    "goal_type": "point_candidates_from_curve_point_condition",
    "strategy": "",
    "reason": "把参数化顶点代入抛物线并回代目标轴上点。",
    "reads": [
      "point:problem:G",
      "function:problem:parabola",
      "fact:i_2:parameterize_axis_point_E_i_parameter",
      "point:problem:E"
    ],
    "produces": [
      {
        "handle": "fact:i_2:solve_axis_point_candidates_i_candidates",
        "valid_scope": "i_2",
        "description": "point_candidates_from_curve_point_condition return candidates",
        "output_type": "PointList"
      },
      {
        "handle": "answer:i_2.E",
        "valid_scope": "i_2",
        "description": "point_candidates_from_curve_point_condition return candidates",
        "output_type": "PointList"
      }
    ],
    "trace_refs": [
      "trace:solve_axis_point_candidates_i:0:point_candidates_from_curve_point_condition"
    ],
    "trace_summaries": [
      {
        "trace_id": "trace:solve_axis_point_candidates_i:0:point_candidates_from_curve_point_condition",
        "method_id": "point_candidates_from_curve_point_condition",
        "trace_fragments": [
          {
            "return": "candidates",
            "runtime_type": "PointList",
            "value": [
              [
                "-1",
                "2 + sqrt(6)"
              ],
              [
                "-1",
                "2 - sqrt(6)"
              ]
            ]
          }
        ],
        "checks": []
      }
    ],
    "required_references": [
      "由第（Ⅰ）问已得相关结论，继续计算。"
    ],
    "method_explanation": {
      "point_candidates_from_curve_point_condition": {
        "role_schema": {
          "target_label": "目标点点名。",
          "curve_kind": "曲线类型的学生化名称。",
          "curve_point": "带参数的曲线点。",
          "curve_equation": "当前问已经确定的曲线方程。",
          "substitution_equation": "把曲线点代入曲线后的方程。",
          "parameter_equation": "整理后的参数方程。",
          "auxiliary_parameter": "为简化方程引入的辅助参数。",
          "auxiliary_equation": "辅助参数满足的方程。",
          "auxiliary_solutions": "辅助参数的解。",
          "parameter_solutions": "原参数的解。",
          "target_candidates": "目标点候选列表。"
        },
        "student_goal_template": "把同参数曲线点代入已知曲线，解出参数并回代目标点。",
        "student_title_template": "代入{curve_kind}求点{target_label}候选",
        "student_nav_title_template": "求点{target_label}候选",
        "student_title_templates_by_goal": {},
        "derive_templates": [
          "∵{curve_point} 在 {curve_equation} 上",
          "∴{substitution_equation}",
          "∴{parameter_equation}",
          "设{auxiliary_parameter}",
          "∴{auxiliary_equation}",
          "∴{auxiliary_solutions}",
          "∴{parameter_solutions}",
          "∴{target_candidates}"
        ],
        "box_templates": [
          "{target_candidates}"
        ],
        "explanation_level": "template",
        "role_binding_strategy": "role_name_registry",
        "role_binder_id": "point_candidates_from_curve_point_condition"
      }
    },
    "teaching_expansion_draft": {
      "confidence": "complete",
      "bound_roles": {
        "target_label": "E",
        "curve_kind": "抛物线",
        "curve_point": "G(t－3,－2)",
        "curve_equation": "y＝－x²－2x＋3",
        "substitution_equation": "－2＝－(t－3)²－2(t－3)＋3",
        "parameter_equation": "(t－3)²＋2(t－3)－5＝0",
        "auxiliary_parameter": "u＝t－3",
        "auxiliary_equation": "u²＋2u－5＝0",
        "auxiliary_solutions": "u＝－1±√6",
        "parameter_solutions": "t＝2±√6",
        "target_candidates": "E(－1,2＋√6) 或 E(－1,2－√6)"
      },
      "unbound_roles": [],
      "student_title": "代入抛物线求点E候选",
      "student_nav_title": "求点E候选",
      "proof_draft": [
        "∵G(t－3,－2) 在 y＝－x²－2x＋3 上",
        "∴－2＝－(t－3)²－2(t－3)＋3",
        "∴(t－3)²＋2(t－3)－5＝0",
        "设u＝t－3",
        "∴u²＋2u－5＝0",
        "∴u＝－1±√6",
        "∴t＝2±√6",
        "∴E(－1,2＋√6) 或 E(－1,2－√6)"
      ],
      "box": [
        "E(－1,2＋√6) 或 E(－1,2－√6)"
      ],
      "llm_can_complete": [
        "可以把 method 计算草稿改写成更自然的初中数学推导。",
        "可以根据 trace 中的 calculation/conclusion 补充代入、化简、筛选等过渡句。"
      ],
      "llm_must_not_invent": [
        "不得新增题目中不存在、draft 中也没有给出的点名、线段名或事实。",
        "不得新增数值、答案或坐标。",
        "不得把 method trace 中的临时变量当作学生讲解里的已知对象。"
      ]
    }
  },
  {
    "candidate_group_id": "derive_parametric_parabola_ii",
    "source_step_id": "derive_parametric_parabola_ii",
    "teaching_substep_id": null,
    "teaching_substep_title": null,
    "teaching_substep_nav_title": null,
    "teaching_substep_title_required_terms": [],
    "teaching_substep_nav_title_required_terms": [],
    "teaching_focus": null,
    "scope_id": "ii",
    "capability_id": "quadratic_from_constraints",
    "method_ids": [
      "quadratic_from_constraints"
    ],
    "target": "fact:ii:derive_parametric_parabola_ii_coefficients",
    "goal_type": "quadratic_from_constraints",
    "strategy": "",
    "reason": "代入横轴交点条件，把函数化成只含主参数的形式。",
    "reads": [
      "point:problem:A",
      "symbol:problem:c"
    ],
    "produces": [
      {
        "handle": "fact:ii:derive_parametric_parabola_ii_coefficients",
        "valid_scope": "ii",
        "description": "quadratic_from_constraints return coefficients",
        "output_type": "Coefficients"
      },
      {
        "handle": "fact:ii:derive_parametric_parabola_ii_parabola",
        "valid_scope": "ii",
        "description": "quadratic_from_constraints return parabola",
        "output_type": "Parabola"
      }
    ],
    "trace_refs": [
      "trace:derive_parametric_parabola_ii:0:quadratic_from_constraints"
    ],
    "trace_summaries": [
      {
        "trace_id": "trace:derive_parametric_parabola_ii:0:quadratic_from_constraints",
        "method_id": "quadratic_from_constraints",
        "trace_fragments": [
          {
            "return": "coefficients",
            "runtime_type": "Coefficients",
            "value": {
              "b": "1 - c"
            }
          },
          {
            "return": "parabola",
            "runtime_type": "Parabola",
            "value": "-c*x + c - x**2 + x"
          }
        ],
        "checks": []
      }
    ],
    "method_explanation": {
      "quadratic_from_constraints": {
        "role_schema": {
          "constraints": "用于确定当前问二次函数的系数约束。",
          "result_parabola": "由约束得到的当前问抛物线解析式。",
          "parabola_title_action": "标题动词；完全确定时为求，含后续参数时为化简。",
          "completed_square_suffix": "配方形式补充说明；没有配方形式时为空。"
        },
        "student_goal_template": "代入当前问给出的约束，确定二次函数解析式。",
        "student_title_template": "{parabola_title_action}函数解析式",
        "student_nav_title_template": "{parabola_title_action}解析式",
        "student_title_templates_by_goal": {},
        "derive_templates": [
          "∵{constraints}",
          "∴y＝{result_parabola}{completed_square_suffix}"
        ],
        "box_templates": [
          "y＝{result_parabola}"
        ],
        "explanation_level": "template",
        "role_binding_strategy": "role_name_registry",
        "role_binder_id": "quadratic_from_constraints"
      }
    },
    "teaching_expansion_draft": {
      "confidence": "complete",
      "bound_roles": {
        "constraints": "b＝1－c",
        "result_parabola": "－x²＋(1－c)x＋c",
        "parabola_title_action": "化简",
        "completed_square_suffix": ""
      },
      "unbound_roles": [],
      "student_title": "化简函数解析式",
      "student_nav_title": "化简解析式",
      "proof_draft": [
        "∵b＝1－c",
        "∴y＝－x²＋(1－c)x＋c"
      ],
      "box": [
        "y＝－x²＋(1－c)x＋c"
      ],
      "llm_can_complete": [
        "可以把 method 计算草稿改写成更自然的初中数学推导。",
        "可以根据 trace 中的 calculation/conclusion 补充代入、化简、筛选等过渡句。"
      ],
      "llm_must_not_invent": [
        "不得新增题目中不存在、draft 中也没有给出的点名、线段名或事实。",
        "不得新增数值、答案或坐标。",
        "不得把 method trace 中的临时变量当作学生讲解里的已知对象。"
      ]
    }
  },
  {
    "candidate_group_id": "derive_path_minimum_ii",
    "source_step_id": "derive_path_minimum_ii",
    "teaching_substep_id": null,
    "teaching_substep_title": null,
    "teaching_substep_nav_title": null,
    "teaching_substep_title_required_terms": [],
    "teaching_substep_nav_title_required_terms": [],
    "teaching_focus": null,
    "scope_id": "ii",
    "capability_id": "quadratic_square_path_minimum",
    "method_ids": [
      "quadratic_square_path_minimum"
    ],
    "target": "fact:ii:derive_path_minimum_ii_minimum_expression",
    "goal_type": "quadratic_square_path_minimum",
    "strategy": "",
    "reason": "原子完成正方形路径降维、轨迹、拉直和达到性；达到点的正方形动点身份由代码绑定。",
    "reads": [
      "function:problem:parabola",
      "fact:ii:minimum_target_5babd8366140",
      "fact:problem:square_b19d8510e827"
    ],
    "produces": [
      {
        "handle": "fact:ii:derive_path_minimum_ii_minimum_expression",
        "valid_scope": "ii",
        "description": "quadratic_square_path_minimum return minimum_expression",
        "output_type": "MinimumExpression"
      },
      {
        "handle": "fact:ii:derive_path_minimum_ii_attainment_point",
        "valid_scope": "ii",
        "description": "quadratic_square_path_minimum return attainment_point",
        "output_type": "Point"
      }
    ],
    "trace_refs": [
      "trace:derive_path_minimum_ii:0:quadratic_square_path_minimum"
    ],
    "trace_summaries": [
      {
        "trace_id": "trace:derive_path_minimum_ii:0:quadratic_square_path_minimum",
        "method_id": "quadratic_square_path_minimum",
        "trace_fragments": [
          {
            "return": "minimum_expression",
            "runtime_type": "MinimumExpression",
            "value": "sqrt(5)*Abs(c + 1)/2"
          },
          {
            "return": "attainment_point",
            "runtime_type": "Point",
            "value": [
              "1/4 - 3*c/4",
              "-c/2 - 1/2"
            ]
          }
        ],
        "checks": [
          "point_on_moving_locus",
          "point_on_minimum_segment"
        ]
      }
    ],
    "recipe_explanation": {
      "recipe_id": "quadratic_square_path_minimum",
      "title": "二次函数与正方形中的路径最小值",
      "summary": "Use the square midpoint/center relations to reduce the given path to one moving point, derive its locus from the quadratic state, and straighten the resulting broken path to obtain the minimum and its attainment point.",
      "method_sequence": [
        "quadratic_square_path_minimum_kernel"
      ],
      "role_schema": {
        "original_objective": "题设要求最小化的原路径。",
        "reduced_objective": "利用正方形中点、中心关系化简后的单动点路径。",
        "moving_point": "化简后路径中唯一的动点。",
        "attainment_point": "使路径取得最小值时动点的位置。",
        "minimum_strategy": "经过验证的折线拉直最值策略。",
        "minimum_expression": "路径的最小值表达式。"
      },
      "student_intent_template": "先利用正方形的中点和中心关系把原路径化为单动点折线，再把折线拉直，得到最小值及其达到位置。",
      "student_title_template": "正方形关系降维，再用将军饮马求最短路径",
      "student_nav_title_template": "正方形路径最值",
      "student_title_templates_by_goal": {},
      "proof_outline_templates": [
        "由正方形的中点、中心和等边关系，把 {original_objective} 等价化为 {reduced_objective}。",
        "根据二次函数状态确定 {moving_point} 的运动轨迹。",
        "使用 {minimum_strategy} 拉直折线，并检查达到点仍在合法轨迹上。",
        "因此最小值为 {minimum_expression}，在 {attainment_point} 处取得。"
      ],
      "recommended_lesson_splits": [
        "利用正方形关系完成路径降维。",
        "确定动点轨迹并拉直折线求最小值。"
      ],
      "teaching_substep_specs": [],
      "allowed_llm_completion": [
        "可以把 verified evidence 中的等价关系改写成初中生易读的语言。",
        "不得自造点名、轨迹、对称点、最小值或达到点。"
      ],
      "method_trace_usage": "method trace 只用于计算细节和验算，不用于猜证明。",
      "role_binder_id": "quadratic_square_path_minimum"
    },
    "teaching_expansion_draft": {
      "confidence": "complete",
      "bound_roles": {
        "original_objective": "HF+FM+MG",
        "reduced_objective": "AG+MG",
        "moving_point": "G",
        "attainment_point": [
          "1/4 - 3*c/4",
          "-c/2 - 1/2"
        ],
        "minimum_strategy": "reflection",
        "minimum_expression": "sqrt(5)*Abs(c + 1)/2"
      },
      "unbound_roles": [],
      "student_intent_draft": "先利用正方形的中点和中心关系把原路径化为单动点折线，再把折线拉直，得到最小值及其达到位置。",
      "proof_draft": [
        "FM=AE/2",
        "HF=AG/2",
        "AE=AG",
        "HF+FM=AG",
        "HF+FM+MG=AG+MG",
        "经过验证的折线拉直策略为：reflection。",
        "因此最小值为 √5|c+1|/2，在 ['1/4 - 3*c/4', '-c/2 - 1/2'] 处取得。"
      ],
      "box": [
        "最小值＝√5|c+1|/2",
        "G(1/4-3c/4,-c/2-1/2)"
      ],
      "recommended_lesson_splits": [
        "利用正方形关系完成路径降维。",
        "确定动点轨迹并拉直折线求最小值。"
      ],
      "llm_can_complete": [
        "可以把 verified evidence 中的等价关系改写成初中生易读的语言。",
        "不得自造点名、轨迹、对称点、最小值或达到点。"
      ],
      "llm_must_not_invent": [
        "不得新增题目中不存在、draft 中也没有给出的点名、线段名或事实。",
        "不得新增数值、答案或坐标。",
        "不得把 method trace 中的临时变量当作学生讲解里的已知对象。",
        "只能使用 verified Macro evidence 中的角色、表达式和达到点。"
      ]
    },
    "method_explanation": {
      "quadratic_square_path_minimum": {
        "confidence": "trace_only"
      }
    }
  },
  {
    "candidate_group_id": "solve_parameter_c_ii",
    "source_step_id": "solve_parameter_c_ii",
    "teaching_substep_id": null,
    "teaching_substep_title": null,
    "teaching_substep_nav_title": null,
    "teaching_substep_title_required_terms": [],
    "teaching_substep_nav_title_required_terms": [],
    "teaching_focus": null,
    "scope_id": "ii",
    "capability_id": "parameter_from_expression_value",
    "method_ids": [
      "parameter_from_expression_value"
    ],
    "target": "symbol:problem:c",
    "goal_type": "parameter_from_expression_value",
    "strategy": "",
    "reason": "令最小值表达式等于题设值并按参数范围取解。",
    "reads": [
      "fact:ii:derive_path_minimum_ii_minimum_expression",
      "fact:ii:minimum_value_given_a9def99c2a2e",
      "symbol:problem:c"
    ],
    "produces": [
      {
        "handle": "fact:ii:solve_parameter_c_ii_parameter_value",
        "valid_scope": "ii",
        "description": "parameter_from_expression_value return parameter_value",
        "output_type": "ParameterValue"
      },
      {
        "handle": "fact:ii:c_parameter_value",
        "valid_scope": "ii",
        "description": "parameter_from_expression_value return parameter_value",
        "output_type": "ParameterValue"
      }
    ],
    "trace_refs": [
      "trace:solve_parameter_c_ii:0:parameter_from_expression_value"
    ],
    "trace_summaries": [
      {
        "trace_id": "trace:solve_parameter_c_ii:0:parameter_from_expression_value",
        "method_id": "parameter_from_expression_value",
        "trace_fragments": [
          {
            "return": "parameter_value",
            "runtime_type": "ParameterValue",
            "value": "5"
          }
        ],
        "checks": []
      }
    ],
    "method_explanation": {
      "parameter_from_expression_value": {
        "role_schema": {
          "expression": "前序步骤得到的含参表达式。",
          "target_value": "题设给出的表达式取值。",
          "parameter": "需要反求的参数。",
          "parameter_value": "解出的参数值。"
        },
        "student_goal_template": "把题设给定值代入已得到的表达式，解出参数。",
        "student_title_template": "由表达式取值反求参数",
        "student_nav_title_template": "",
        "student_title_templates_by_goal": {},
        "derive_templates": [
          "∵{expression}＝{target_value}",
          "∴{parameter}＝{parameter_value}"
        ],
        "box_templates": [
          "{parameter}＝{parameter_value}"
        ],
        "explanation_level": "template",
        "role_binding_strategy": "role_name_registry",
        "role_binder_id": "parameter_from_expression_value"
      }
    },
    "teaching_expansion_draft": {
      "confidence": "complete",
      "bound_roles": {
        "expression": "√5|c＋1|/2",
        "target_value": "3√5",
        "parameter": "c",
        "parameter_value": "5"
      },
      "unbound_roles": [],
      "student_title": "由表达式取值反求参数",
      "student_nav_title": "",
      "proof_draft": [
        "∵√5|c＋1|/2＝3√5",
        "∴c＝5"
      ],
      "box": [
        "c＝5"
      ],
      "llm_can_complete": [
        "可以把 method 计算草稿改写成更自然的初中数学推导。",
        "可以根据 trace 中的 calculation/conclusion 补充代入、化简、筛选等过渡句。"
      ],
      "llm_must_not_invent": [
        "不得新增题目中不存在、draft 中也没有给出的点名、线段名或事实。",
        "不得新增数值、答案或坐标。",
        "不得把 method trace 中的临时变量当作学生讲解里的已知对象。"
      ]
    }
  },
  {
    "candidate_group_id": "evaluate_point_A_ii",
    "source_step_id": "evaluate_point_A_ii",
    "teaching_substep_id": null,
    "teaching_substep_title": null,
    "teaching_substep_nav_title": null,
    "teaching_substep_title_required_terms": [],
    "teaching_substep_nav_title_required_terms": [],
    "teaching_focus": null,
    "scope_id": "ii",
    "capability_id": "evaluate_point_at_parameter",
    "method_ids": [
      "evaluate_point_at_parameter"
    ],
    "target": "point:problem:A",
    "goal_type": "evaluate_point_at_parameter",
    "strategy": "",
    "reason": "把主参数代入横轴交点坐标。",
    "reads": [
      "symbol:problem:c",
      "point:problem:A"
    ],
    "produces": [
      {
        "handle": "fact:ii:evaluate_point_A_ii_evaluated_point",
        "valid_scope": "ii",
        "description": "evaluate_point_at_parameter return evaluated_point",
        "output_type": "Point"
      },
      {
        "handle": "fact:ii:A_evaluated_point",
        "valid_scope": "ii",
        "description": "evaluate_point_at_parameter return evaluated_point",
        "output_type": "Point"
      }
    ],
    "trace_refs": [
      "trace:evaluate_point_A_ii:0:evaluate_point_at_parameter"
    ],
    "trace_summaries": [
      {
        "trace_id": "trace:evaluate_point_A_ii:0:evaluate_point_at_parameter",
        "method_id": "evaluate_point_at_parameter",
        "trace_fragments": [
          {
            "return": "evaluated_point",
            "runtime_type": "Point",
            "value": [
              "-5",
              "0"
            ]
          }
        ],
        "checks": []
      }
    ],
    "method_explanation": {
      "evaluate_point_at_parameter": {
        "role_schema": {
          "source_point": "代入前的含参点坐标。",
          "parameter": "已求出的参数名。",
          "parameter_value": "已求出的参数值。",
          "evaluated_point": "代入参数后的点坐标。"
        },
        "student_goal_template": "把已求出的参数代入含参点坐标，得到定点坐标。",
        "student_title_template": "代入参数求点坐标",
        "student_nav_title_template": "代入参数求点坐标",
        "student_title_templates_by_goal": {},
        "derive_templates": [
          "∵{source_point}，{parameter}＝{parameter_value}",
          "∴{evaluated_point}"
        ],
        "box_templates": [
          "{evaluated_point}"
        ],
        "explanation_level": "template",
        "role_binding_strategy": "role_name_registry",
        "role_binder_id": "evaluate_point_at_parameter"
      }
    },
    "teaching_expansion_draft": {
      "confidence": "complete",
      "bound_roles": {
        "source_point": "A(－5,0)",
        "parameter": "c",
        "parameter_value": "5",
        "evaluated_point": "A(－5,0)"
      },
      "unbound_roles": [],
      "student_title": "代入参数求点坐标",
      "student_nav_title": "代入参数求点坐标",
      "proof_draft": [
        "∵A(－5,0)，c＝5",
        "∴A(－5,0)"
      ],
      "box": [
        "A(－5,0)"
      ],
      "llm_can_complete": [
        "可以把 method 计算草稿改写成更自然的初中数学推导。",
        "可以根据 trace 中的 calculation/conclusion 补充代入、化简、筛选等过渡句。"
      ],
      "llm_must_not_invent": [
        "不得新增题目中不存在、draft 中也没有给出的点名、线段名或事实。",
        "不得新增数值、答案或坐标。",
        "不得把 method trace 中的临时变量当作学生讲解里的已知对象。"
      ]
    }
  },
  {
    "candidate_group_id": "evaluate_minimum_point_G_ii",
    "source_step_id": "evaluate_minimum_point_G_ii",
    "teaching_substep_id": null,
    "teaching_substep_title": null,
    "teaching_substep_nav_title": null,
    "teaching_substep_title_required_terms": [],
    "teaching_substep_nav_title_required_terms": [],
    "teaching_focus": null,
    "scope_id": "ii",
    "capability_id": "evaluate_point_at_parameter",
    "method_ids": [
      "evaluate_point_at_parameter"
    ],
    "target": "point:problem:G",
    "goal_type": "evaluate_point_at_parameter",
    "strategy": "",
    "reason": "把已求出的二次函数参数代入 Macro 返回的取等号点 G。",
    "reads": [
      "symbol:problem:c",
      "fact:ii:derive_path_minimum_ii_attainment_point"
    ],
    "produces": [
      {
        "handle": "fact:ii:evaluate_minimum_point_G_ii_evaluated_point",
        "valid_scope": "ii",
        "description": "evaluate_point_at_parameter return evaluated_point",
        "output_type": "Point"
      },
      {
        "handle": "fact:ii:G_evaluated_point",
        "valid_scope": "ii",
        "description": "evaluate_point_at_parameter return evaluated_point",
        "output_type": "Point"
      }
    ],
    "trace_refs": [
      "trace:evaluate_minimum_point_G_ii:0:evaluate_point_at_parameter"
    ],
    "trace_summaries": [
      {
        "trace_id": "trace:evaluate_minimum_point_G_ii:0:evaluate_point_at_parameter",
        "method_id": "evaluate_point_at_parameter",
        "trace_fragments": [
          {
            "return": "evaluated_point",
            "runtime_type": "Point",
            "value": [
              "-7/2",
              "-3"
            ]
          }
        ],
        "checks": []
      }
    ],
    "method_explanation": {
      "evaluate_point_at_parameter": {
        "role_schema": {
          "source_point": "代入前的含参点坐标。",
          "parameter": "已求出的参数名。",
          "parameter_value": "已求出的参数值。",
          "evaluated_point": "代入参数后的点坐标。"
        },
        "student_goal_template": "把已求出的参数代入含参点坐标，得到定点坐标。",
        "student_title_template": "代入参数求点坐标",
        "student_nav_title_template": "代入参数求点坐标",
        "student_title_templates_by_goal": {},
        "derive_templates": [
          "∵{source_point}，{parameter}＝{parameter_value}",
          "∴{evaluated_point}"
        ],
        "box_templates": [
          "{evaluated_point}"
        ],
        "explanation_level": "template",
        "role_binding_strategy": "role_name_registry",
        "role_binder_id": "evaluate_point_at_parameter"
      }
    },
    "teaching_expansion_draft": {
      "confidence": "complete",
      "bound_roles": {
        "source_point": "G(－7/2,－3)",
        "parameter": "c",
        "parameter_value": "5",
        "evaluated_point": "G(－7/2,－3)"
      },
      "unbound_roles": [],
      "student_title": "代入参数求点坐标",
      "student_nav_title": "代入参数求点坐标",
      "proof_draft": [
        "∵G(－7/2,－3)，c＝5",
        "∴G(－7/2,－3)"
      ],
      "box": [
        "G(－7/2,－3)"
      ],
      "llm_can_complete": [
        "可以把 method 计算草稿改写成更自然的初中数学推导。",
        "可以根据 trace 中的 calculation/conclusion 补充代入、化简、筛选等过渡句。"
      ],
      "llm_must_not_invent": [
        "不得新增题目中不存在、draft 中也没有给出的点名、线段名或事实。",
        "不得新增数值、答案或坐标。",
        "不得把 method trace 中的临时变量当作学生讲解里的已知对象。"
      ]
    }
  },
  {
    "candidate_group_id": "recover_target_point_E_ii",
    "source_step_id": "recover_target_point_E_ii",
    "teaching_substep_id": null,
    "teaching_substep_title": null,
    "teaching_substep_nav_title": null,
    "teaching_substep_title_required_terms": [],
    "teaching_substep_nav_title_required_terms": [],
    "teaching_focus": null,
    "scope_id": "ii",
    "capability_id": "square_adjacent_vertex_from_side",
    "method_ids": [
      "square_adjacent_vertex_from_side"
    ],
    "target": "fact:ii:recover_target_point_E_ii_adjacent_vertex",
    "goal_type": "square_adjacent_vertex_from_side",
    "strategy": "",
    "reason": "由定值相邻顶点和正方形方向恢复目标点。",
    "reads": [
      "symbol:problem:c",
      "point:problem:G",
      "point:problem:A",
      "fact:problem:square_b19d8510e827"
    ],
    "produces": [
      {
        "handle": "fact:ii:recover_target_point_E_ii_adjacent_vertex",
        "valid_scope": "ii",
        "description": "square_adjacent_vertex_from_side return adjacent_vertex",
        "output_type": "Point"
      },
      {
        "handle": "answer:ii.E",
        "valid_scope": "ii",
        "description": "square_adjacent_vertex_from_side return adjacent_vertex",
        "output_type": "Point"
      }
    ],
    "trace_refs": [
      "trace:recover_target_point_E_ii:0:square_adjacent_vertex_from_side"
    ],
    "trace_summaries": [
      {
        "trace_id": "trace:recover_target_point_E_ii:0:square_adjacent_vertex_from_side",
        "method_id": "square_adjacent_vertex_from_side",
        "trace_fragments": [
          {
            "return": "adjacent_vertex",
            "runtime_type": "Point",
            "value": [
              "-2",
              "3/2"
            ]
          }
        ],
        "checks": []
      }
    ],
    "method_explanation": {
      "square_adjacent_vertex_from_side": {
        "role_schema": {
          "target_label": "学生可见的目标顶点点名。",
          "projection_construction": "为目标顶点作坐标辅助线的构造说明。",
          "square_name": "学生可见的正方形名称。",
          "side_equal_statement": "正方形相邻边相等的结论。",
          "square_right_angle_statement": "正方形公共顶点处的直角结论。",
          "projection_right_angles": "坐标辅助线形成的直角关系。",
          "matching_angle_statement": "对应的非直角锐角关系。",
          "triangle_congruence": "学生可见的全等直角三角形。",
          "length_correspondence": "全等后对应的坐标长度关系。",
          "target_position_condition": "用于选择目标点的方位条件。",
          "target_point": "学生可见的目标顶点坐标。"
        },
        "student_goal_template": "利用正方形相邻边垂直且等长，求相邻顶点坐标。",
        "student_title_template": "由正方形求相邻顶点{target_label}",
        "student_nav_title_template": "正方形求顶点{target_label}",
        "student_title_templates_by_goal": {},
        "derive_templates": [
          "作{projection_construction}",
          "∵四边形 {square_name} 是正方形",
          "∴{side_equal_statement}，{square_right_angle_statement}",
          "∵{projection_right_angles}",
          "∴{matching_angle_statement}",
          "∴{triangle_congruence}",
          "∴{length_correspondence}",
          "∵{target_position_condition}",
          "∴{target_point}"
        ],
        "box_templates": [
          "{target_point}"
        ],
        "explanation_level": "template",
        "role_binding_strategy": "role_name_registry",
        "role_binder_id": "square_adjacent_vertex_from_side"
      }
    },
    "teaching_expansion_draft": {
      "confidence": "complete",
      "bound_roles": {
        "target_label": "E",
        "projection_construction": "GQ⊥x轴于 Q，ER⊥x轴于 R",
        "square_name": "AEKG",
        "side_equal_statement": "AG＝AE",
        "square_right_angle_statement": "∠GAE＝90°",
        "projection_right_angles": "∠GQA＝∠ERA＝90°",
        "matching_angle_statement": "∠GAQ＝∠AER",
        "triangle_congruence": "Rt△AGQ≌Rt△EAR",
        "length_correspondence": "AR＝QG＝3，ER＝AQ＝3/2",
        "target_position_condition": "按正方形顶点顺序选取 E",
        "target_point": "E(－2,3/2)"
      },
      "unbound_roles": [],
      "student_title": "由正方形求相邻顶点E",
      "student_nav_title": "正方形求顶点E",
      "proof_draft": [
        "作GQ⊥x轴于 Q，ER⊥x轴于 R",
        "∵四边形 AEKG 是正方形",
        "∴AG＝AE，∠GAE＝90°",
        "∵∠GQA＝∠ERA＝90°",
        "∴∠GAQ＝∠AER",
        "∴Rt△AGQ≌Rt△EAR",
        "∴AR＝QG＝3，ER＝AQ＝3/2",
        "∵按正方形顶点顺序选取 E",
        "∴E(－2,3/2)"
      ],
      "box": [
        "E(－2,3/2)"
      ],
      "llm_can_complete": [
        "可以把 method 计算草稿改写成更自然的初中数学推导。",
        "可以根据 trace 中的 calculation/conclusion 补充代入、化简、筛选等过渡句。"
      ],
      "llm_must_not_invent": [
        "不得新增题目中不存在、draft 中也没有给出的点名、线段名或事实。",
        "不得新增数值、答案或坐标。",
        "不得把 method trace 中的临时变量当作学生讲解里的已知对象。"
      ]
    }
  }
]

## 输出结构提醒

{
  "steps": [
    {
      "candidate_group_ids": [
        "一个或多个 candidate_groups 中的 candidate_group_id"
      ],
      "id": "string",
      "source_step_ids": [
        "兼容字段；优先使用 candidate_group_ids"
      ],
      "title": "string",
      "nav_title": "string",
      "goal": "string",
      "derive": [
        [
          "标签",
          "面向学生的讲解句"
        ]
      ],
      "box": [
        "重要结论文字"
      ]
    }
  ]
}