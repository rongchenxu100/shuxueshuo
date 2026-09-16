# 简洁整题 IR 人工夹具

当前 gold.json 和五题 JSON 使用独立 `problem-domain/v2` 简洁整题契约。旧三对象金标、生成脚本和 schema 已归档到 `docs/validation/understanding-simplified-20260915/previous-step2.zip`，不作为当前运行依赖。

- 2026-09-16：七题批测输入已切换到 [选定图片集](integration-images-20260916/README.md)，四题裁剪、西青采用用户新图、函数题原样保留。K 题缺少图1～4是用户有意设置的缺图识别用例，无需补图。批测统一采用 image-only 输入，不复用旧整页 OCR；本目录历史观察记录继续保留。

- `k-quad/source.png`、layout/text/formula/observation/context、三轮 legacy 返回及 provenance 均保持原始导出证据，不来自模型重生成。
- `author_gold.py` 是本题人工金标的可读构造脚本，只用于夹具，不是运行时按名称展开定义。
- 金标由原图可读文字编写；本题“□ABCD”由用户明确确认按平行四边形解释；四幅图缺失，不默认交点 interior=true；保留 AECD 交点的局部名字 X，但不表示 X≠O；共线关系可确认其为 O；不加入求解结果。
- 2026-09-15 定义展开规则修订：人工参考保留四分支，以 kind=any_of、branches 表示；现行验收允许代码证明等价的两分支，已知 BD 平分 AC 单独记录。此次修改来自用户确认的抽取规则；没有新真实调用或新模型输出。旧失败审计保持原样。
- 五题紧凑表达由已有人工 v2 表达改写，函数/点/关系/目标沿用旧五题金标；原有 `internal/problem-domain-fixtures` 未修改。此处只测试独立表达，不证明新 adapter 投影。
- schema 快照从 `contracts.py` 生成；不存在手写第二份 schema。
- 新模型响应只能与人工金标对照，不能反过来改写金标获得通过。记录型离线用例不宣称真实模型集成通过。

- `v6-recorded-output.json` 是 v6 单次真实响应原样复制，用于用户确认后的离线重评；不是新的模型调用，也不覆盖旧冻结金标或旧失败记录。
