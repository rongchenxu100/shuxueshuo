# 内容模型与命名约定

## 1. problem-id

每道具体题目都使用统一的 `problem-id`：

```text
地区-年份-考试-题位
```

示例：

- `tj-2025-bufenqu-ermo-24`

约定：

- 地区使用简短 slug，例如 `tj`
- 年份使用四位数字
- 考试使用短 slug，例如 `zhongkao`、`nankai-yimo`
- 题位直接使用题号，例如 `24`

## 2. 网站目录落点

每道题的网页为**单个 HTML 文件**（文件名为 `problem-id` + `.html`），按城市 slug、题位分目录平铺，**不再为每题单独建子文件夹**：

```text
site/problems/<城市>/<题位>/<problem-id>.html
```

同题位下多道实例并列在同一目录，例如：

```text
site/problems/tj/24/tj-2025-bufenqu-ermo-24.html
```

静态资源与题页同目录，文件名建议带 `problem-id` 前缀，例如 `tj-2025-bufenqu-ermo-24-diagram.svg`，避免同目录下多题冲突。

## 3. 网站总索引

题目总索引固定为：

```text
site/data/problems.json
```

前期总索引是唯一元信息源，每个题目对象最小字段为：

- `id`
- `city`
- `cityLabel`
- `year`
- `exam`
- `examLabel`
- `slot`
- `title`
- `tags`
- `path`
- `status`

## 4. 用户导航结构

用户浏览逻辑固定为：

1. 先地区
2. 再题位
3. 再看具体题目实例

注意：

- “24题”表示题位聚合，不表示单独一题
- 目录为 `城市/题位` 两层，其下为多个 `problem-id.html`；年份、考试等仍写在 `problems.json` 与题页元信息中
- 导航靠总索引筛选，题位下题目列表也来自总索引
