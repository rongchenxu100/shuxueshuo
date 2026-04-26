# 新题接入流程

## 目标

从原题图片出发，产出符合网站结构的一道具体题目页面，并把它插入正确的题位聚合中。

## 标准步骤

1. 确定题目的 `problem-id`
2. 将原题图片放入 `internal/source-images/<problem-id>/`
3. 选择合适的题型 skill
4. 基于统一题页模板生成单文件题页（并视需要同目录放置静态资源）：
   - `site/problems/<城市>/<题位>/<problem-id>.html`
   - 同目录静态资源用带 `problem-id` 前缀的文件名（如 `…-diagram.svg`），避免同题位多题重名
5. 向 `site/data/problems.json` 增加一条元信息
6. 检查导航页是否能在正确的“地区 -> 题位”下聚合出该题

## 选择 skill 的建议

- 动点题：使用 `dynamic-point-problem`
- 旋转题：使用 `rotation-problem`
- 折叠题：使用 `folding-problem`
- 相似题：使用 `similarity-problem`
- 函数图像题：使用 `function-graph-problem`
- 题型不明确或只是先接入占位页：使用 `common-problem-ingest`

## 接入完成后的检查

- 页面路径是否唯一且稳定
- 页面是否沿用统一题页骨架
- 标签与考试来源是否正确
- 导航页是否按题位正确聚合
- 局部资源是否与该题 HTML 同目录、且命名不与同题位其他题冲突
