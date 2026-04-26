# shuxueshuo

中考数学可视化题库网站。

这个仓库同时承载两部分内容：

- `site/`：对外静态网站，包含首页、导航页与题目页
- `internal/`：内部内容生产系统，包含原题图片、Codex skills、模板与接题规范

项目目标是把各地中考真题，以及一模、二模中的典型题，制作成交互式网页，让学生不只是“看答案”，而是能够通过动点、旋转、折叠等操作真正理解题目的变化过程和解题逻辑。

## 当前结构

```text
.
├── internal/
│   ├── docs/
│   ├── skills/
│   ├── source-images/
│   └── templates/
├── site/
│   ├── assets/
│   ├── data/
│   ├── nav/
│   └── problems/        # 例：problems/tj/24/<problem-id>.html
├── LICENSE
└── README.md
```

## 网站信息架构

前期网站采用纯 `HTML/CSS/JS`，用户浏览路径固定为：

1. 先地区
2. 再题位
3. 再进入具体题目实例

例如：

- 天津
- 24 题
- 2025 年部分区二模 24 题（示例）

这里的“24题”是题位聚合，不是某一道具体题目。具体题目以 **HTML 文件** 形式放在 `site/problems/<城市>/<题位>/` 下，文件名为 `problem-id.html`（例如 `site/problems/tj/24/tj-2025-bufenqu-ermo-24.html`），同题位多题同目录并列。

## 题目唯一标识

每道具体题目使用统一的 `problem-id`：

```text
地区-年份-考试-题位
```

例如：

- `tj-2025-bufenqu-ermo-24`

网站导航通过 `site/data/problems.json` 维护题库总索引。

## 题目页约定

前期所有题目页都使用统一页面骨架，包含：

- 题目标题与来源信息
- 原题图片或题干信息
- 可视化交互区域
- 解题步骤同步区域
- 关键结论与总结
- 返回导航入口

这样做便于后续 skill 稳定产出，也便于维护统一的视觉和交互规范。

## Internal 内容生产层

`internal/` 用来沉淀题目接入与批量生产能力，不会直接暴露到网站导航中。

- `internal/source-images/`：原题图片素材库，按 `problem-id` 对齐
- `internal/skills/`：不同题型与接题流程的 Codex skills
- `internal/templates/`：题目页模板和示例输入输出
- `internal/docs/`：命名规则、索引规则、接题流程

## 本地预览

因为导航页会读取 `site/data/problems.json`，最稳妥的预览方式是从仓库根目录启动一个本地静态服务器：

```bash
python3 -m http.server 8000
```

然后访问：

- `http://localhost:8000/site/`
- `http://localhost:8000/site/nav/`

为了方便前期直接双击打开 HTML 文件，导航页也内置了一个与 JSON 同步的前端兜底数据文件。

## 下一步建议

- 完善首页内容与品牌表达
- 扩展更多地区与题位
- 将 skill 输出流程逐步标准化
- 补充题目页模板和元信息校验脚本
