# 创作后台前端

这是数学可视化题库的创作后台前端子项目。Phase 0 先建立 Next.js App Router 工程、接口契约、mock API、fixture 数据和静态预览入口，后续页面开发应沿真实 API 路径接入。

## 启动

```bash
npm run dev
```

默认访问：

```text
http://localhost:3000
```

## 验证

```bash
npm test
npm run typecheck
npm run lint
```

## 目录

```text
app/                 Next.js App Router 页面与 Route Handlers
fixtures/            mock API 使用的契约数据
lib/api/             前端 API client
lib/contracts/       Zod 接口契约与契约测试
lib/mock/            fixture 读取工具
public/preview-fixtures/  静态 HTML 预览 fixture
```

## 开发说明

- mock API 必须保持与未来真实 API 相同的 URL、请求体和响应体。
- 页面预览通过接口返回的 `previewUrl` 加载，组件不要硬编码 fixture 路径。
- 题目预览必须保留 `previewVersion`；专题预览可带 `previewVersion`，用于后续 iframe 强制刷新。
- `eslint.config.mjs` 当前采用 Next.js 16 文档推荐的 ESLint flat config 写法。升级 `eslint-config-next` 时，先运行 `npm run lint` 验证兼容性。
