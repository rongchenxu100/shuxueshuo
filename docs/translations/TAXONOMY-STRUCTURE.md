# Marble Skill Taxonomy · 知识图谱结构设计

> 基于本仓库 `data/` JSON 数据与 `schema/` 的说明文档。  
> 版本参考：v1 · Topics 1,590 · Edges 3,221 · Subjects 8（其中 Mathematics 503）

本仓库是 **纯数据发布包**（无 Neo4j / 运行时 API）：微主题节点 + 先修依赖边构成 DAG，并挂接课程标准与家长向领域摘要。

---

## 1. 总体架构

| 层面 | 实现 |
|------|------|
| 存储 | `data/*.json`（UTF-8） |
| 图节点 | `data/topics.json` |
| 图边 | `data/dependencies.json` |
| 课标 | `data/curriculum-standards.json` |
| 领域摘要 | `data/clusters.json` |
| 清单 | `data/manifest.json`（计数 + SHA-256） |
| 约束 | `schema/*.schema.json` + `scripts/validate.mjs` |

```text
内部 DB / exportTaxonomy.mjs（上游，不在本仓库）
        ↓ 导出
data/topics.json                 ← 节点
data/dependencies.json           ← 边（DAG）
data/curriculum-standards.json   ← 标准实体
data/clusters.json               ← domain×年龄摘要
data/manifest.json
        ↓
node scripts/validate.mjs
```

数学相关规模：

| 指标 | 数值 |
|------|-----:|
| Mathematics topics | 503 |
| 触达数学的边 | ~1,051 |
| 数学内部边 | ~985 |
| hard / soft（数学内部） | ~722 / ~263 |

---

## 2. 结构总览（四层对象）

```text
Curriculum（课标体系）
   └── Standard（课标条目）
          ▲
          │ standards[] 显式引用
Topic ──────── depends_on ────────► Topic
（节点）      hard|soft + reason     （先修节点）
          │
          │ subject + domain + age 隐式对齐
          ▼
       Cluster（家长摘要，无 topic ID 外键）
```

要点：

- **Topic ↔ Topic** 只有一种显式关系：先修依赖 `depends_on`。
- **Topic → Standard** 通过 `standards[]` 显式引用。
- **Topic ≈ Cluster** 通过 `(subject, domain, age)` 隐式对齐，无边表。
- **Curriculum** 是 Standard 的分组壳。

---

## 3. 实体说明

### 3.1 Topic（主图节点）

可教的细粒度学习点（micro-topic）。ID 形如 `mt_…`。定义见 `schema/topics.schema.json`。

#### 关键字段

| 字段 | 含义 | 例子（读写数字到 20） |
|------|------|------------------------|
| `id` | 稳定标识符 | `mt_fR0UtsSREU` |
| `type` | 技能形态 | `PROCEDURAL` |
| `subject` | 学科 | `Mathematics` |
| `domain` | 学科内领域 | `Number Representation & Place Value` |
| `name` | 短标题 | `Reading and writing numbers to 20` |
| `description` | 学什么（一句话） | `Read and write numerals from 0 to 20` |
| `ageRangeStart` / `ageRangeEnd` | 大致适龄（岁） | `5` – `6` |
| `centrality` | 图枢纽程度（0–1） | ≈ `0.59`（全库最高 `1.0` = One-to-one counting） |
| `evidence` | 掌握证据清单 | 能认 / 能写 / 能用数字表示数量 |
| `assessmentPrompt` | 家长/老师检查问句；`{{name}}` 可换孩子名 | `Can {{name}} read a number like '17'…?` |
| `standards` | 对齐的课标 key 列表 | `ccss-math:K.CC.3`, `uk-nc-2013:Maths/Y1/NPV/5` |

#### `type` 五种形态

| type | 含义 | 数学例子 | 数学数量（约） |
|------|------|----------|---------------:|
| `CONCEPTUAL` | 概念理解 | One-to-one counting | 129 |
| `PROCEDURAL` | 程序/操作技能 | Reading and writing numbers to 20 | 263 |
| `REPRESENTATIONAL` | 表征（图、坐标等） | Representing Addition and Subtraction | 35 |
| `LANGUAGE` | 术语与符号语言 | Reading +, −, and = symbols | 20 |
| `META` | 元认知/策略 | Addition and subtraction strategies | 56 |

#### 数学 `domain` 列表

Geometry、Measurement、Fractions、Multiplication & Division、Addition & Subtraction、Number Representation & Place Value、Mathematical Thinking、Algebra、Data & Statistics、Ratio & Proportion、Probability、Counting & Cardinality。

> `type`、`subject`、`domain` 是 **节点属性**，不是独立实体表。

### 3.2 Curriculum（课标体系）

官方标准的分组容器。字段含 `slug`、`country`、`name`、`version`、`textIncluded`、`license`、`sourceUrl` 等。

常见例子：

| slug | 名称 |
|------|------|
| `ccss-math` | Common Core State Standards for Mathematics（US） |
| `uk-nc-2013` | 英格兰国家课程标准（GB） |
| `ccss-ela` | Common Core ELA |
| `ngss-k5` / `ngss-ms` | Next Generation Science Standards |
| … | 见 `curriculum-standards.json` |

### 3.3 Standard（课标条目）

Curriculum 下的一条可引用标准。键格式：`"<curriculum-slug>:<code>"`。

示例：

| key | 所属 Curriculum | 要点 |
|-----|-----------------|------|
| `ccss-math:K.CC.3` | ccss-math | Write numbers from 0 to 20… |
| `uk-nc-2013:Maths/Y1/NPV/5` | uk-nc-2013 | Read and write numbers from 1 to 20… |

完整文本在条目的 `data` 对象中（部分源为 codes-only，无全文）。

### 3.4 Cluster（领域摘要）

面向家长的 `(subject, domain, ageRangeStart)` 一段摘要。定义见 `schema/clusters.schema.json`。

- **不含** topic ID；与 Topic 的关联是隐式的。
- 同一 domain 可按年龄有多段 cluster。

---

## 4. 边关系

### 4.1 Topic ↔ Topic：唯一显式边 `depends_on`

文件：`data/dependencies.json`  
Schema：`schema/dependencies.schema.json`

```json
{
  "topicId": "mt_09sySPqM9Z",
  "prerequisiteId": "mt_ndGqFPWyen",
  "strength": "hard",
  "reason": "Understanding a/b as a parts of size 1/b is prerequisite to understanding a/b as sum of 1/b"
}
```

| 字段 | 含义 |
|------|------|
| `topicId` | **后继主题**：当前要学的 Topic |
| `prerequisiteId` | **先修主题**：须先掌握的 Topic |
| `strength` | `hard`（硬性先修）或 `soft`（辅助/有帮助） |
| `reason` | 为什么依赖（可展示给家长/老师）；可为 `null` |

**语义：**

> `topicId` **depends on** `prerequisiteId`  
> 反向：掌握 `prerequisiteId` **解锁** `topicId`

图性质：文档声明为 **DAG**（有向无环）。本仓库 validator 校验引用完整性，但**不**强制拓扑无环检查。

本仓库 **没有** `part_of`、同义边、父子树边等其它 Topic↔Topic 关系。

#### 硬依赖例子（hard）

```text
prerequisiteId: Fractions of a whole          （部分–整体分数）
        ↓ 先掌握
topicId:        Understanding fractions (9+) （理解 a/b）
strength: hard
reason:  先把 a/b 看成「a 个大小为 1/b 的部分」，
         才能再理解「a/b 是若干个 1/b 之和」
```

#### 软依赖例子（soft）

```text
prerequisiteId: Counting in 2s     （按 2 跳数）
        ↓ 有帮助
topicId:        Odd and even numbers（奇偶数）
strength: soft
reason:  偶数与「按 2 数」有联系
```

#### 基数 ← 一一对应

```text
topicId:        How Many in Total?
prerequisiteId: One-to-one counting
strength: hard
reason:  基数原则建立在一一对应上——
         必须先数对，最后一个数才表示「多少」
```

#### 跨学科也是同一种边

```text
topicId:        Science · Rock layers and Earth's history
prerequisiteId: Mathematics · 3-D shapes (age 9+)
strength: soft
reason:  解读地球剖面图，建立在「从 2D 表征识别 3D 形状」上
```

### 4.2 Topic → Standard（嵌入式链接）

存在 Topic 的 `standards: string[]`，不是独立边表。  
校验器检查每个 key 是否存在于 `curriculum-standards.json`。

### 4.3 Topic ≈ Cluster（隐式）

用 `(subject, domain)` + 年龄接近对齐，无外键、无边表。

---

## 5. 端到端例子

### 5.1 读写数字到 20

```text
Topic: Reading and writing numbers to 20
  type     = PROCEDURAL
  subject  = Mathematics
  domain   = Number Representation & Place Value
  age      = 5–6
  centrality ≈ 0.59

  standards[] ──► Standard ccss-math:K.CC.3
                  └─ Curriculum ccss-math
             ──► Standard uk-nc-2013:Maths/Y1/NPV/5
                  └─ Curriculum uk-nc-2013

  (subject, domain, age≈5) ≈ Cluster
    「Your child is building number foundations — learning to read and write numbers…」
```

### 5.2 先修 DAG 片段（学习方向：先修 → 后继）

```text
                    One-to-one counting
                    (CONCEPTUAL, centrality=1.0)
                           │
          ┌────────────────┼────────────────┐
          ▼                ▼                ▼
 How Many in Total?   Counting objects   Rote counting
                      to 20              to 100
```

数据中每条边存为「后继 depends_on 先修」；产品路径展开时按「先修解锁后继」方向使用。

---

## 6. 关键文件

```text
data/
  topics.json                  # 图节点
  dependencies.json            # 先修边
  curriculum-standards.json    # Curriculum + Standard
  clusters.json                # 领域摘要
  manifest.json                # 版本 / 计数 / checksum
schema/
  topics.schema.json
  dependencies.schema.json
  curriculum-standards.schema.json
  clusters.schema.json
scripts/validate.mjs           # 结构与引用完整性校验
```

使用方式（无运行时）：

```js
import topics from './data/topics.json' with { type: 'json' };
import deps from './data/dependencies.json' with { type: 'json' };

const byId = new Map(topics.topics.map(t => [t.id, t]));
const prereqs = deps.dependencies
  .filter(d => d.topicId === 'mt_fR0UtsSREU')
  .map(d => byId.get(d.prerequisiteId).name);
```

校验：

```bash
npm run validate   # → node scripts/validate.mjs
```

---

## 7. 一句话对照

| 对象 / 字段 | 回答的问题 |
|-------------|------------|
| Topic 字段 | 这门技能点是什么、什么形态、适龄、怎么验、在图里多重要 |
| depends_on 边 | 学 A 之前要不要先会 B（硬/软 + 原因） |
| Curriculum | 这套官方课标体系是谁发的 |
| Standard | 体系里哪一条条文 |
| Cluster | 这个学科领域在这个年龄段，家长该怎么理解 |

---

## 参考

- 仓库说明：[`README.md`](./README.md)
- 数据来源与许可证：[`PROVENANCE.md`](./PROVENANCE.md)
- 交互可视化（站外）：https://withmarble.com/curriculum
