# tj-2026-nankai-yimo-25

结论：`needs_review`。新输入种类：`authored_fixture`。

[旧数学树](legacy-tree.txt) · [新数学树](notation-tree.txt) · [机器差异](comparison.json) · [旧领域输入运行时树](legacy-domain-runtime.json) · [原 Solver fixture 运行时树](legacy-fixture-runtime.json)

## 差异

### qualifiers

```text
{
  "category": "qualifiers",
  "legacy_only": [],
  "notation_only": [
    {
      "scope": "r.c1.c1",
      "kind": "goal_modifiers",
      "goal_kind": "find_coordinates",
      "target": [
        "ref",
        "r.c1:point:G",
        "point"
      ],
      "at": [
        [
          [
            "relation",
            "=",
            "Add(Mul(Integer(-1), Symbol('length(r.c1:point:F, r.c1:point:G)', real=True)), Mul(Integer(-1), Symbol('length(r.c1:point:E, r.c1:point:G)', real=True)), Symbol('min(Add(Symbol('n_748ef839c13a7706e39645965b297da9f3c22750037831cb3417f574b63fc2a7', real=True), Symbol('n_eb53acc97e234671d48a0fcae9b3e050df83d7bbc42f38330a0b8abed0e1b697', real=True)))', real=True))"
          ]
        ]
      ]
    },
    {
      "scope": "r.c1.c1",
      "kind": "goal_modifiers",
      "goal_kind": "find_equation",
      "target": [
        "ref",
        "r:curve:__curve",
        "curve"
      ],
      "at": [
        [
          [
            "relation",
            "=",
            "Add(Mul(Integer(-1), Symbol('length(r.c1:point:F, r.c1:point:G)', real=True)), Mul(Integer(-1), Symbol('length(r.c1:point:E, r.c1:point:G)', real=True)), Symbol('min(Add(Symbol('n_748ef839c13a7706e39645965b297da9f3c22750037831cb3417f574b63fc2a7', real=True), Symbol('n_eb53acc97e234671d48a0fcae9b3e050df83d7bbc42f38330a0b8abed0e1b697', real=True)))', real=True))"
          ]
        ]
      ]
    },
    {
      "scope": "r.c1.c1",
      "container": "facts",
      "kind": "extremum_variables",
      "operator": "min",
      "target": "Add(Symbol('length(r.c1:point:F, r.c1:point:G)', real=True), Symbol('length(r.c1:point:E, r.c1:point:G)', real=True))",
      "variables": [
        [
          "ref",
          "r.c1:point:E",
          "point"
        ],
        [
          "ref",
          "r.c1:point:G",
          "point"
        ]
      ]
    },
    {
      "scope": "r.c1.c1",
      "container": "goals",
      "kind": "extremum_variables",
      "operator": "min",
      "target": "Add(Symbol('length(r.c1:point:F, r.c1:point:G)', real=True), Symbol('length(r.c1:point:E, r.c1:point:G)', real=True))",
      "variables": [
        [
          "ref",
          "r.c1:point:E",
          "point"
        ],
        [
          "ref",
          "r.c1:point:G",
          "point"
        ]
      ]
    },
    {
      "scope": "r.c1.c0",
      "kind": "goal_modifiers",
      "goal_kind": "find_minimum",
      "target": "Add(Symbol('length(r.c1:point:F, r.c1:point:G)', real=True), Symbol('length(r.c1:point:E, r.c1:point:G)', real=True))",
      "variables": [
        [
          "ref",
          "r.c1:point:E",
          "point"
        ],
        [
          "ref",
          "r.c1:point:G",
          "point"
        ]
      ]
    }
  ]
}
```

### goals r.c1.c1

```text
{
  "category": "goals",
  "scope": "r.c1.c1",
  "legacy_only": [
    {
      "kind": "find_coordinates",
      "target": [
        "ref",
        "r.c1:point:G",
        "point"
      ]
    },
    {
      "kind": "find_equation",
      "target": [
        "ref",
        "r:curve:__curve",
        "curve"
      ]
    }
  ],
  "notation_only": [
    {
      "kind": "find_coordinates",
      "target": [
        "ref",
        "r.c1:point:G",
        "point"
      ],
      "at": [
        [
          [
            "relation",
            "=",
            "Add(Mul(Integer(-1), Symbol('length(r.c1:point:F, r.c1:point:G)', real=True)), Mul(Integer(-1), Symbol('length(r.c1:point:E, r.c1:point:G)', real=True)), Symbol('min(Add(Symbol('n_748ef839c13a7706e39645965b297da9f3c22750037831cb3417f574b63fc2a7', real=True), Symbol('n_eb53acc97e234671d48a0fcae9b3e050df83d7bbc42f38330a0b8abed0e1b697', real=True)))', real=True))"
          ]
        ]
      ]
    },
    {
      "kind": "find_equation",
      "target": [
        "ref",
        "r:curve:__curve",
        "curve"
      ],
      "at": [
        [
          [
            "relation",
            "=",
            "Add(Mul(Integer(-1), Symbol('length(r.c1:point:F, r.c1:point:G)', real=True)), Mul(Integer(-1), Symbol('length(r.c1:point:E, r.c1:point:G)', real=True)), Symbol('min(Add(Symbol('n_748ef839c13a7706e39645965b297da9f3c22750037831cb3417f574b63fc2a7', real=True), Symbol('n_eb53acc97e234671d48a0fcae9b3e050df83d7bbc42f38330a0b8abed0e1b697', real=True)))', real=True))"
          ]
        ]
      ]
    }
  ]
}
```

## 边界

所有原始输入已冻结。旧结构通过生产领域校验并构建实际初始运行时树；新结构当前建立的是数学语义审计树，尚未绑定生产 StateSlot/StateVersion。此报告不裁决哪一侧符合原图。

曲线名称只在同一作用域恰有一个曲线时统一；原始名称与映射均保留。内部 function_variable、复合对象及 minimum_target 的表达差异保存在旧树 annotations 中。旧 Solver 目标描述不会伪装为额外数学题设。
