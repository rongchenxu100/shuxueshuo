# FR-T1 A0 根式换元：本地实施与验收记录

日期：2026-11-01。结论：**首批根式换元的数学、原图回归与共同教学已实现；按用户本轮要求，B05-v2 已正式编入本地“函数的表示法”专题的换元法小组。** S7 的两张独立新题照片仍缺失，尚未部署。这是 FR-T1 的第一批能力，不代表五种方法全部完成。

本地预览：`/lab/graph-walk/function-representations-formula-a0/`。启动 `python3 -m http.server 8793 --bind 127.0.0.1 --directory site` 后可访问。页面使用共同课包与原生教学运行时，进度只保存在本机，不提交正式练习记录。

正式题页：`/topics/function-representations/variant02/`，题目 ID 为 `function-representations-b05-v2-r4`。专题使用现有 `groupBy: method`，按课包的真实方法自动分组；当前一题位于“求函数的解析式 → 换元法求函数解析式”。正式课程复用同一验证证据，独立计入题量、进度和原生学习记录；实验预览继续独立保留。本次按用户明确的纳题要求调整原纳题时序，S7 留出验收仍单独跟踪。

## 1. 当前开放范围

| 项目 | 实现范围 |
| --- | --- |
| 原关系 | `f(a√x+b)=ux+v√x+w`；单未知函数、单变量、单关系，固定有理系数，a≠0 |
| 原输入 | 自然合法域 `[0,+∞)`；保留原 AST，不先约去非法分母或根式 |
| 常规分支 | a 的正负；右式二次、一次、常量；闭端点；函数名和变量改名 |
| 结果 | `source_domain`、`determined_domain`、`declared_domain`、`requested_domain` 分开保存；式子与确定范围一起输出 |
| 确定范围 | a>0 时 `[b,+∞)`，a<0 时 `(-∞,b]`；未给完整域时不自行声明它就是 f 的全定义域 |
| 全域请求 | 原题明确请求 R 上的完整规则时，保留已确定的半轴规则并返回信息不足 |
| 原文绑定 | 已通过代表题的 TeX 根式、隐式乘法、目标和公式外填空横线；额外条件与不能准确绑定的域表述保守拒绝，不删条件继续执行 |
| 预算 | AST 节点≤128、深度≤16、有理系数分子分母位长≤64；中间多项式次数≤4，输入最终一次、右式最终至多二次；只允许受控幂和非零常数分母 |

尚不支持：仿射／分式整体输入、嵌套根式、额外人为限域、参数系数、多未知函数、多关系、题给一次或二次函数类型。a=0 返回“关系矛盾”或“仅确定一个函数值”的适用性诊断，不进入除法执行；完整退化关系求解留待后续批次。机器内核的域语义支持不等于所有自然语言域表述均已通过拍题验收。

## 2. 图谱、执行与教学

`type-function-formula` 由 `planned` 激活，当前只关联 `method-function-substitution`；其他三个新专题题型仍待建设。新增一个方法，复用并补齐四个技能的真实绑定：提取表达式有意义的条件、换元、代数式化简、等式变形与推导。每个调用都有输入、输出、局部验证与依据，方法最终另作独立核验。

独立验证器重新读取原关系，以 `s≥0，x=s²` 证明候选代回后的多项式恒等零；按 a 的符号重建输入像集，校验非负逆代见证与完整覆盖。验证器不调用恢复函数，不用有限数值点代替证明。篡改式子、域、端点或逆代都会失败。

代表题为 B05-v2：`f(√x+1)=2x+1`。未知函数在提取、记法和阶段一保留为未知，不伪造函数定义或先填答案。运行结果为 `f(t)=2t²−4t+3，t≥1`。

学习过程为读题、判型、连接题目线索与方法，再完成四张推导判断卡：

1. 整体换元，确定新变量范围。
2. 利用非负条件，合法反解原变量。
3. 将原式右边全部改写为新变量。
4. 写出完整答案：点选范围填入最终解析式，同步预览数轴；覆盖说明可展开查看。

卡片使用公式对照与箭头；目标栏提交前显示“待求”。四步均由同一证据生成，前端与服务端原生评分一致。错答不推进；刷新可恢复；AI 回放与学生作答进度独立。当前是选择式判断，尚不提供自由键入等价公式的作答框。

**按本轮页面反馈，选法判断节点与连线卡提前接入 A0。** `rule-function-formula-method` 已绑定题型与选法契约；四类线索和五种方法预先连好，学生直接点选方法，一次提交核验。提交前不自动突出本题正确方法，完成后保留整张关系图并标注“本题选择”。当前声明的根式整体输入可换元，也可配凑；配凑返回“也适用，步骤暂未开放”，不判错、不伪造可执行路线。换元通过后沿真实判断边进入四张推导卡。其余方法仅作选法比较，尚未注册空执行节点。“多项式恒等式比较系数”新技能仍属于 B 批。

读题已简化为“只求出函数解析式”与“求出函数解析式，并写出适用范围”。用“适用范围”区分本题能确定规则的范围与未知函数可能更大的全定义域。D3 改变评分契约后，正式题身份升级为 `function-representations-b05-v2-r2`，网址保持不变，旧题身份的学习记录不覆盖。

## 3. 原图与真实调用证据

| 证据 | 路径与说明 |
| --- | --- |
| 原页 | `internal/senior-high/source-images/function-representations-planning-20261030/source-image-04.png` |
| 仅题目裁片与哈希 | `internal/senior-high/source-images/function-formula-a0-20261101/`，manifest 记录原页哈希、矩形、四点选题边界及送题裁片哈希 |
| 真实模型运行 | `internal/solver-runs/function-formula-a0-20261101/b05-v2-original/`；实际两次网络调用：提取一次、原图复核一次，复核无问题 |
| 可复现录制 | `server/tests/search/fixtures/function-formula/b05-v2-recorded-20261101/`；保留真实请求／回复、账本、用量与图片哈希；服务侧标识已脱敏，模型正文未改写 |
| 共同课程导出 | 初版为 `internal/solver-runs/function-formula-a0-20261101/course-export-v3/`；选法卡版为同目录的 `course-export-method-connections/`（run_id `031444b179c7486598cca9b9f9253003`）。沿用真实录制的原关系，重新执行选法、求解、验证与课程导出，无新增模型调用 |
| 静态课包 | `site/data/graph-walk/function-representations-formula-a0.{source,evidence,replay}.json` 及 `.json`；页面由现有构建器生成 |

裁片保留原题像素，四点区域外置白以排除印刷解析，没有重写、旋转或生成题面。真实模型识别保留 `f(\sqrt{x}+1)`，未误读为 `f(\sqrt{x+1})`。本次是原图经产品预处理后的 CLI 真实调用，不冒称浏览器上传实测。已认证拍题 API、课程生成、评分与刷新复用通过录制回归验证。

B05-v2、W04、W11 都是开发回归题。另有方向、次数退化与 36 组系数网格验证，但这些不是独立留出照片。首次提取后的原文绑定曾因填空线在数学片段外而拒绝，修复绑定后以同一原始回复重验；没有修改识别正文来绕过检查。

## 4. 检查结果与复现

A0 首次实施的后端聚合回归 **447 项通过**，覆盖新增 A0、原图录制与拍题 API，以及记法、阶段一／二／三契约、版本、已有定义域／求值／值域课程。测试使用独立数据目录 `/private/tmp/sss-function-formula-20261101` 和实例 `function-formula-a0`，没有使用日常产品数据库。

```sh
cd server
env PRODUCT_TEST_DATA_DIR=/private/tmp/sss-function-formula-20261101 PRODUCT_TEST_INSTANCE=function-formula-a0 uv run pytest -q \
  tests/solver/test_graph_function_formula.py tests/search/test_function_formula_photo.py \
  tests/solver/test_graph_stage_one_features.py tests/solver/test_graph_stage_one_contracts.py \
  tests/solver/test_graph_stage_two_input_values.py tests/solver/test_graph_stage_three_contracts.py \
  tests/solver/test_graph_function_evaluation_runtime_contract.py tests/solver/test_graph_stage_three_revision_manifest.py \
  tests/solver/test_math_notation.py tests/solver/test_graph_stage_two_recognition.py \
  tests/solver/test_graph_stage_two_selection.py tests/solver/test_graph_stage_three_function_domain.py \
  tests/solver/test_graph_stage_three_function_evaluation_acceptance.py tests/solver/test_graph_stage_three_function_range.py --tb=short
```

回归过程中补齐了目标枚举及旧目标缺少的字段说明，没有放宽数学或来源检查。旧求值课程 Q28d、Q29b 一次出现超时／结算回执中断，原预算单独重跑通过，最终 447 项聚合运行也通过。

A0 首次实施的前端聚合回归 **77 项通过**，覆盖实验路径与正式专题隔离、每个错误选项、各确认前缀恢复、AI 进度隔离、前后端评分一致及最终答案必须带域。当时公共图谱构建为 110 节点、365 边；生成物包含因统一内容版本更新而变化的旧知识页，以及手机样式版本更新的 29 个既有课页；旧专题题目源清单和分组没有混入新题。

```sh
node --test tools/tests/function-representations-topic.test.mjs tools/tests/graph-walk-topic.test.mjs tools/tests/graph-walk-function-formula.test.mjs tools/tests/graph-walk-function-evaluation.test.mjs tools/tests/graph-walk-function-range.test.mjs tools/tests/graph-walk-ui.test.mjs
node tools/build-public-knowledge-graph.mjs --check
node tools/export-public-knowledge.mjs --check
node tools/build-graph-walk-topic.mjs --check
node tools/build-graph-walk-topic.mjs --source site/data/graph-walk/function-representations-formula-a0.source.json --check
```

浏览器检查：完整走通七个决策；错误开端点与“多项式所以全实域”均停留原步；刷新保留完成状态；切到 AI 回放再切回仍保留学生结果。390px 视口的题干、公式与按钮可读；手机宽度通过顶部按钮展开图谱，收起会遮挡题干的浮动缩略图。截图见 `internal/review-analysis/function-formula-a0-20261101/`。

同日正式纳题补验：专题／方法分组／原生课包相关 **28 项 Node 测试通过**；独立测试实例运行 `tests/auth/test_function_domain_topic.py -k function-representations`，**1 项 API 集成测试通过**，覆盖未完成时禁止标记完成、禁止跳步、逐步评分、重复请求幂等、记录恢复及最终已练标记。图谱、专题首页和全部正式课包的构建检查无差异，`git diff --check` 通过。浏览器从专题的换元法小组进入正式题页，显示独立的初始作答状态；截图为 `internal/review-analysis/function-formula-a0-20261101/topic-enrolled.png`。未执行线上部署。

同日页面批注改进：选法连线、已有值域选法和流式状态机合计 **99 项 Node 测试通过**；数学恢复、来源选法、原图拍题及原生练习 API 合计 **42 项后端测试通过**；共享阶段三契约、阶段二选法和版本清单另有 **87 项通过**。覆盖五种比较方法只对应一条真实执行路线、错误线索／方法不推进、配凑适用但未开放、刷新保留未评分连线，以及新版正式题的逐步评分与记录恢复。当前公共图谱为 **111 节点、367 边**，正式与实验课包构建检查均无差异，新增选法代码及测试通过 Ruff 检查。

浏览器实测了待定系数法的错误反馈、配凑法的适用提示、选择换元后进入推导、未提交连线刷新恢复，以及 390px 宽度的上下布局。截图位于上述验收目录：`reading-concise.png`、`method-connections-desktop.png`、`method-connections-mobile.png`。课程沿用原网址；评分契约使用 r2 身份，测试数据库中的旧身份没有被重写。

最新交互调整：初始预连五条线索—方法关系，学生直接点方法；完成态保留同一只读图并标注“本题选择”。线索改为“已知复合函数的解析式”，配本题函数式。导出记录为 `course-export-method-map/`，run_id 为 `77197ee5846447a48c38bd3bcc534b5e`，正式身份为 r3。按用户要求仅运行必要单元测试：选法来源 3 项、函数解析式课包与评分及连线绘制 6 项通过；未运行数据库或全量回归。页面核对确认完成态保留五条箭头及本题路线，公式中的根号不受连线绘制影响。

本轮答案卡调整：选法线索定名为“已知复合函数的解析式”，显示完整已知等式。第 7 步改为“写出完整答案”，复用 choice 评分，新增展示元数据 answer_completion；点选范围同步填入答案和数轴，草稿用蓝色、完成态用绿色，开闭端点随选项显示。正确反馈提醒保留范围，各错误选项解释全实数、原变量范围或漏端点的误解；覆盖证明放进折叠区。导出目录为 `course-export-answer/`，run_id 为 `22c55be019f944b0a855b9230cfa86fb`，正式身份为 r4。仅运行 6 项相关 Python 单元测试与 7 项课包、评分和界面渲染单元测试，全部通过。

## 5. 分阶段状态与剩余门槛

| 阶段 | 当前状态 |
| --- | --- |
| S0 范围与复用 | A0 范围、预算、退化与拒绝类别已实现并回归 |
| S1 题源 | B05-v2 原页、裁片、真实录制及金标回归已冻结；W04、W11 为公开数学回归 |
| S2 表示 | 未知函数、根式位置、原关系、域与身份已接入；代表题原图通过 |
| S3 图谱与路由 | 一个真实换元方法、受限结构判型、公共选法判断与线索连线卡、四个公共技能绑定已接入 |
| S4 数学 | 恢复、独立恒等和覆盖验证、版本依赖、续算通过 |
| S5 教学 | 静态预览、拍题课程与原生评分共用；错答、恢复和窄屏已检查 |
| S6 正式编排 | B05-v2 已编入独立专题的换元法小组，共一道正式练习；发布课包与学习记录接入已验证，预览保持独立 |
| S7 新题与服务 | 原图开发回归与本地服务回归通过；两张未参与开发的新照片尚缺，门槛未关闭 |

用户已授权继续 A1，一次式换元及三道新题的结果见 [A1 验收记录](function-formula-a1-acceptance.md)。A0 两张留出照片仍单独跟踪，后续按设计进入 A2 分式、A3 配凑执行、B 待定系数、C 构造方程组、D 赋值。当前纳题不代表整个题型或真实新照片泛化已经通过。
