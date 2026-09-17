# tj-2026-heping-ermo-25

结论：`needs_review`。新输入种类：`recorded_workflow_candidate`。

[旧数学树](legacy-tree.txt) · [新数学树](notation-tree.txt) · [机器差异](comparison.json) · [旧领域输入运行时树](legacy-domain-runtime.json) · [原 Solver fixture 运行时树](legacy-fixture-runtime.json)

## 差异

### state_conditions

```text
{
  "category": "state_conditions",
  "legacy_only": [],
  "notation_only": [
    {
      "scope": "r.c1",
      "condition": [
        [
          [
            "relation",
            "=",
            "Add(Mul(Integer(-1), Symbol('length(r.c1:point:F, r:point:M)', real=True)), Mul(Integer(-1), Symbol('length(r:point:G, r:point:M)', real=True)), Mul(Integer(-1), Symbol('length(r.c1:point:F, r.c1:point:H)', real=True)), Symbol('min(Add(Symbol('n_028c8dde1596c89f37e057b9adf63e0022fc3c87933139a1e9bbec06815bfefd', real=True), Symbol('n_6e2cdc73b8d0cf87b61ebc8fd6c76f8761f2e4d5f3076f7feaa0c110aa5e4e68', real=True), Symbol('n_992d8c21c087dc42a1b2731d3818290dddc78a141b52538bfeb9007f463d3c6b', real=True)))', real=True))"
          ]
        ]
      ]
    }
  ]
}
```

### facts r.c1

```text
{
  "category": "facts",
  "scope": "r.c1",
  "legacy_only": [
    [
      "=",
      [
        "call",
        "midpoint",
        [
          "ref",
          "r:point:A",
          "point"
        ],
        [
          "ref",
          "r:point:K",
          "point"
        ]
      ],
      [
        "ref",
        "r.c1:point:H",
        "point"
      ]
    ],
    [
      "=",
      [
        "call",
        "midpoint",
        [
          "ref",
          "r:point:E",
          "point"
        ],
        [
          "ref",
          "r:point:G",
          "point"
        ]
      ],
      [
        "ref",
        "r.c1:point:H",
        "point"
      ]
    ],
    [
      "∈",
      [
        "ref",
        "r.c1:point:H",
        "point"
      ],
      [
        "call",
        "segment",
        [
          "ref",
          "r:point:A",
          "point"
        ],
        [
          "ref",
          "r:point:K",
          "point"
        ]
      ]
    ],
    [
      "∈",
      [
        "ref",
        "r.c1:point:H",
        "point"
      ],
      [
        "call",
        "segment",
        [
          "ref",
          "r:point:E",
          "point"
        ],
        [
          "ref",
          "r:point:G",
          "point"
        ]
      ]
    ]
  ],
  "notation_only": [
    [
      "relation",
      "=",
      "Add(Mul(Integer(-1), Symbol('length(r.c1:point:F, r:point:M)', real=True)), Mul(Integer(-1), Symbol('length(r:point:G, r:point:M)', real=True)), Mul(Integer(-1), Symbol('length(r.c1:point:F, r.c1:point:H)', real=True)), Symbol('min(Add(Symbol('n_028c8dde1596c89f37e057b9adf63e0022fc3c87933139a1e9bbec06815bfefd', real=True), Symbol('n_6e2cdc73b8d0cf87b61ebc8fd6c76f8761f2e4d5f3076f7feaa0c110aa5e4e68', real=True), Symbol('n_992d8c21c087dc42a1b2731d3818290dddc78a141b52538bfeb9007f463d3c6b', real=True)))', real=True))"
    ],
    [
      "∈",
      [
        "ref",
        "r.c1:point:H",
        "point"
      ],
      [
        "∩",
        [
          "call",
          "line",
          [
            "ref",
            "r:point:A",
            "point"
          ],
          [
            "ref",
            "r:point:K",
            "point"
          ]
        ],
        [
          "call",
          "line",
          [
            "ref",
            "r:point:E",
            "point"
          ],
          [
            "ref",
            "r:point:G",
            "point"
          ]
        ]
      ]
    ]
  ]
}
```

## 边界

所有原始输入已冻结。旧结构通过生产领域校验并构建实际初始运行时树；新结构当前建立的是数学语义审计树，尚未绑定生产 StateSlot/StateVersion。此报告不裁决哪一侧符合原图。

曲线名称只在同一作用域恰有一个曲线时统一；原始名称与映射均保留。内部 function_variable、复合对象及 minimum_target 的表达差异保存在旧树 annotations 中。旧 Solver 目标描述不会伪装为额外数学题设。
