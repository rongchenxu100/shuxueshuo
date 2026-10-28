# 验证数据

本目录保留冻结响应、数学证书、机器报告和历史回放资产。它们用于复现指定输入，不代表当前实现状态或当前版本通过率。当前架构、使用方式及未完成工作见[文档索引](../README.md)。

以下文件被现有回归直接读取，不能随文档清理删除：

- `scoped-proof-search-stage-f3/live-kernel-failures.json`
- `scoped-proof-search-stage-f3/live-responses.json.gz`

其他数据可能由复验工具或 fixture 来源清单引用。删除数据前应查验 `server/tests/`、`server/tools/` 和 fixture manifest 的引用；新增批次优先写入独立运行目录，稳定的测试输入放入对应测试 fixture。
