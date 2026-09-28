# q30 性能剖析与隔离实验

日期：2026-09-28。参见 [分析与优化顺序](../../scoped-proof-performance.md)。

- `measurements.json`：三个独立进程、按 baseline → no-debug → metadata-cache 顺序运行的单次测量；没有真实 LLM 调用。
- `profile-summary.json`：原实现开启 cProfile 的函数调用统计；仓库内文件名已规范化为仓库相对路径，用户目录以 `<HOME>` 代替，计时及调用数未修改。累计耗时有嵌套，不能相加，也不能直接和非剖析墙钟时间比较。
- `input-sha256.json`：q30 题意、冻结 ProblemIR 和录制计划指纹。
- `implementation-sha256.json`：测量时生产代码指纹；本次没有修改这些代码。
- `capture.py`：可重现的进程内实验。metadata-cache 同时关闭调试输出，并对事实、提交、快照和调用授权的派生属性安装 cached_property；没有修改磁盘上的实现，没有跳过数学 checker。

三次最终答案均为 4，均有 5 个提交、3 条取等要求；完整事实/证书快照的 SHA-256 完全一致。计时包括录制计划转换及 Runtime 执行、结果写入，不包括进程导入和最后的实验摘要序列化；不是单独的数学内核耗时。

这些是单次观测，不是中位数、p95 或生产 SLA。正式缓存仍需深不可变约束、授权/版本/registry 失效测试和独立冷回放验证，不能把实验 monkeypatch 当成已完成的实现。

复现（仓库根目录；每次换一个尚不存在的输出目录）：

```sh
server/.venv/bin/python docs/validation/scoped-proof-performance/capture.py --mode baseline --output /private/tmp/q30-perf-new-baseline
server/.venv/bin/python docs/validation/scoped-proof-performance/capture.py --mode no-debug --output /private/tmp/q30-perf-new-no-debug
server/.venv/bin/python docs/validation/scoped-proof-performance/capture.py --mode metadata-cache --output /private/tmp/q30-perf-new-cache
```

剖析原实现：使用 `python -m cProfile -o <profile>` 运行 `server/tools/run_basic_inequality_stage4a.py`，指定 `--mode recorded --proof-protocol scoped-facts/v2`，gold、problem-ir、plan 使用 capture.py 中的 q30 冻结输入。不要在普通耗时比较时启用剖析器。
