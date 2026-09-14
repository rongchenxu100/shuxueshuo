# 教育知识图谱 · 阅读清单与中文译文

面向本仓库「用图建知识图谱」路线：课程/知识点图、前提依赖、学生掌握图与差分补齐。  
这与 [`README.md`](./README.md) 中的 **大规模图计算引擎**（Pregel 等）不是同一问题。

## 建议阅读顺序

1. **ACE（建教育 KG + 前提边）** → 对齐「怎么建图」
2. **Knowledge Spaces / Learning Spaces** → 对齐「最小学习空间 / Hasse / 差分」
3. **Graph-based Knowledge Tracing 综述** → 对齐「学生长期图谱」可选技术
4. **LLM 赋能知识图谱构建综述** → 以后从题解/教材半自动抽边时再读
5. **无监督前提关系推断** → 前提边自动挖掘的补充方法

## 中文全文译文

| 论文 | 年份 | 与本仓库的对应 | 中文译文 |
|------|------|----------------|----------|
| ACE: AI-Assisted Construction of Educational Knowledge Graphs with Prerequisite Relations | JEDM 2024 | 课程图 schema、前提打分、专家校验、传递推断 | [ACE-JEDM2024-zh.md](./ACE-JEDM2024-zh.md) |
| Knowledge Spaces and Learning Spaces (Doignon & Falmagne) | arXiv 2015 | Hasse 前提、学习空间、外缘与评估 | [KnowledgeSpaces-LearningSpaces-zh.md](./KnowledgeSpaces-LearningSpaces-zh.md) |
| A Survey of Graph-Based Knowledge Tracing … | JEDM 2025 | 学生掌握状态、图结构 KT、路径推荐 | [GbKT-Survey-JEDM2025-zh.md](./GbKT-Survey-JEDM2025-zh.md) |
| LLM-empowered knowledge graph construction: A survey | arXiv 2025 | 本体→抽取→融合；LLM 建图范式 | [LLM-KG-Construction-Survey-zh.md](./LLM-KG-Construction-Survey-zh.md) |
| Inferring Prerequisite Knowledge Concepts in Educational Knowledge Graphs | arXiv 2025 | 无监督多准则挖 prerequisite | [EduKG-Prerequisite-Inference-zh.md](./EduKG-Prerequisite-Inference-zh.md) |

## 原文链接

- ACE：[JEDM 文章页](https://jedm.educationaldatamining.org/index.php/JEDM/article/view/737) · [PDF](https://jedm.educationaldatamining.org/index.php/JEDM/article/download/737/218)
- Knowledge Spaces and Learning Spaces：[arXiv:1511.06757](https://arxiv.org/abs/1511.06757) · [PDF](https://arxiv.org/pdf/1511.06757)
- GbKT 综述：[JEDM](https://jedm.educationaldatamining.org/index.php/JEDM/article/view/1089) · [PDF](https://jedm.educationaldatamining.org/index.php/JEDM/article/download/1089/298)
- LLM-KG 综述：[arXiv:2510.20345](https://arxiv.org/abs/2510.20345) · [PDF](https://arxiv.org/pdf/2510.20345)
- 前提推断：[arXiv:2509.05393](https://arxiv.org/abs/2509.05393) · [PDF](https://arxiv.org/pdf/2509.05393)

## 本仓库产品设计（非译文）

| 文档 | 作用 |
|------|------|
| [`../student-tutor-chat-system-design.md`](../student-tutor-chat-system-design.md) | 学生长期知识图谱 + 题目图差分 |
| [`../basic-inequality-minimal-learning-space.md`](../basic-inequality-minimal-learning-space.md) | 基本不等式 Hasse 前提与最小学习空间 |
| [`../inequality-visual-component-refactor-design.md`](../inequality-visual-component-refactor-design.md) | KnowledgePoint / Family / Problem 实体与边 |

## 说明

- 译文仅供学习交流；正式引用请使用英文原文。
- Doignon & Falmagne 1985 经典原文 *Spaces for the Assessment of Knowledge* 多为付费获取；本清单以 arXiv 综述章 *Knowledge Spaces and Learning Spaces* 作为可免费全文翻译的对应入口。
- 参考文献表一般从略；正文、公式、算法、图表说明尽量保留。
