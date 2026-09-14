# 创作后台前端

这是数学可视化题库的创作后台前端子项目。首页默认提供真实三栏工作台：左栏题目列表，中栏突出解析网页，右栏上传与生成进度；没有有效网页时隐藏中栏，上传／进度区域扩展至可用空间。复用 P2 产品 API 与 Worker；网站、专题、发布和对话暂不接入。范围见[工作台首版设计](../docs/workspace-product-design.md)。

原演示工作台仅在服务器环境显式设置 `WORKSPACE_MODE=mock` 时启用，真实接口失败不回退 Mock。

## 启动

```bash
npm run dev
```

该命令只启动前端。完整本地系统使用仓库根目录的 `./deploy/product/manage.sh --mode local services-start`，详见[服务列表](../docs/product-local-services.md)。默认访问：

```text
http://localhost:3000
```

## 验证

```bash
npm test
npm run typecheck
npm run lint
npm run build
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

- 真实工作台使用 `/api/product/v1` 与 `lib/product/` 的合同；原 Mock 路由保留给显式演示与测试，不作为真实产品接口。
- 页面预览通过接口返回的 `previewUrl` 加载，组件不要硬编码 fixture 路径。
- 题目预览必须保留 `previewVersion`；专题预览可带 `previewVersion`，用于后续 iframe 强制刷新。
- `eslint.config.mjs` 当前采用 Next.js 16 文档推荐的 ESLint flat config 写法。升级 `eslint-config-next` 时，先运行 `npm run lint` 验证兼容性。
