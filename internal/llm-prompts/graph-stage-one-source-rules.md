提取、复核、修复共用以下题意表示规则；阶段变化不改变这些规则。

比较函数是否相同的题目使用 compare_functions 目标。四组选项是同一道题内的局部比较，不是 children 小问。每个 options 条目有稳定 id、原标签 label、原选项 text、局部 functions 及 left/right 引用；functions 中保留原函数名、自变量和未化简 definition，题面显式指定定义域才填写 domain。同名 f、g 可以在不同选项重复，不能提升到 root.definitions，不能串用其他选项的函数。局部引用写 local:本项函数id；共同基准写在 shared_functions，引用 shared:基准id，候选仍在各项局部作用域。无基准的多组比较 mode=groups，共同基准 mode=shared_baseline，直接比较两个函数 mode=pair（只有一个 options 条目，selection_mode=none，select_relation=null）。共同基准模式每项必须恰有一侧 shared、一侧 local，建议 left=shared:基准id、right=local:候选id；同一函数判定是对称关系，反向引用同样合法，不仅因左右方向要求修复。编译时只规范展示角色为基准在左、候选在右，不修改候选原文、引用字段或源函数身份。

compare_functions 的 select_relation 按题面分别取 equal（选相同）或 different（选不同）。题面明确多选或不定项选择时 selection_mode=multiple，明确单选时为 single；groups/shared_baseline 中题面未明示选择模式时保留 unspecified。系统对未注明选择模式的比较题默认按不定项选择处理：选出全部符合题意的项，项数不预设，最终按精确标签集合评分；这是答题默认规则，提取、复核和修复仍保留来源 unspecified，不把默认规则当成原图明确写了多选。不能仅凭“下列……的是”、选项数量、常见考试形式或求解后的正确项数量反推单选或多选，也不能从猜测的正确标签反推极性。选择模式未明示不等于题目缺失，不因此添加 uncertainty 或改 completeness；选相同还是不同确实看不清时才记 select_relation=unknown 并报告 uncertainty。选项不全用 completeness=incomplete，否则 complete。不能将判定结果、反例、自然定义域或正确标签写进这些字段。保留 sqrt(x^2)、(sqrt(x))^2、abs(x) 的原始结构，不能提前化简成相同写法。original_text、public_content.choices 与 options 的标签、顺序和完整公式必须一致；public_content 对应 choices 的 selection_mode 必须与 compare_functions 目标一致，包括 unspecified。复核若发现两处选择模式错误，须分别指出目标和公开选项的 selection_mode 精确 path，修复也须在各自授权字段同步修正，不能仅改一处后再为通过schema恢复错误猜测。复核和修复必须使用含选项索引的精确 path，修复 A 项不授权更改 B 项或把局部函数移到 root。

例如“（多选）下列两组函数中表示不同函数的是：A. f(u)=u+2，g(v)=v+2；B. f(u)=u^2，g(v)=v^2+1”，目标应为 {"kind":"compare_functions","mode":"groups","select_relation":"different","selection_mode":"multiple","completeness":"complete","shared_functions":[],"options":[{"id":"option_a","label":"A","text":"$f(u)=u+2$，$g(v)=v+2$","functions":[{"id":"left","definition":"f(u)=u+2"},{"id":"right","definition":"g(v)=v+2"}],"left":"local:left","right":"local:right"},{"id":"option_b","label":"B","text":"$f(u)=u^2$，$g(v)=v^2+1$","functions":[{"id":"left","definition":"f(u)=u^2"},{"id":"right","definition":"g(v)=v^2+1"}],"left":"local:left","right":"local:right"}]}。这里仅转录比较任务，不进行判定。

题图边缘若带入本题或相邻题目的“解析”“答案”等印刷解答，不能将解答作为题设、目标或正确标签，也不能转录进 original_text/public_content。以完整题干和所属选项为范围；若无法确定所属关系，报告 uncertainty，不拼接相邻题目。

求具体函数的定义域时，保留未化简的原解析式为函数定义，目标使用 {"kind":"find_domain","object":"函数符号"}。仅题面明确另给输入范围时，目标加 input_domain；未另限范围时省略。不能把推导出的自然定义域或求解答案填入 input_domain。

未给出具体解析式、已知抽象函数某个调用的定义域，要求另一个调用的定义域时，使用 find_abstract_domain。例如“已知 f(t) 的定义域是 [-3,2]，求 f(2x-1) 的定义域”，目标为 {"kind":"find_abstract_domain","known_call":"f(t)","known_domain":"[-3,2]","strength":"exact","target_call":"f(2*x-1)"}。known_call 与 known_domain 必须对应同一句已知条件，target_call 保留所求调用的完整输入与原变量；已知调用中的 t 与目标外层变量 x 可以不同，不改名、不把两者当成同一个绑定变量。没有解析式是这类题的正常题设，不能仅因此报告 ambiguous_symbol、条件缺失或要求重拍，也不能编造 f(x)=x 等具体函数定义。

“定义域是/为/恰为某集合”用 strength=exact；“在某范围内有意义”仅用 meaningful_only，不能为获得可执行路线改成 exact。known_domain 只转录已知调用关于其外层变量的定义域；若已知的是 f(t+2) 的定义域，不能自行推导后把 known_call 改成 f(t)。input_domain 仅在题面另给目标外层自变量范围时填写，不能拿 known_domain、完整输入的推导范围或最终答案代替。各目标独立保留已知调用的归属和所求调用，不能串用其他小问的域。具体函数定义域仍用 find_domain，含参具体函数按给定定义域求参数仍用 match_domain；抽象域任务不使用 find_range，不提前输出逆像、不等式条件或答案。复核与修复分别核对 known_call、known_domain、strength、target_call 及可选 input_domain 的精确字段；修改多个字段须分别有诊断授权，保留其余原文、作用域与条件。

已知含参具体函数的定义域恰为题给集合、求参数范围时，保留原函数定义，目标使用 {"kind":"match_domain","object":"函数符号","domain":"题给定义域","symbol":"待求参数"}。题面“函数中自变量的取值范围为某集合”同样表达已知定义域；domain 只转录这个集合，不能填参数答案，也不能移到 find_domain 的 input_domain。此时不使用 find_range 代替 match_domain，不把“定义域为某集合”提前推导成根式非负、分母非零或对区间内外的量词条件；这些是后续求解步骤。原图确实另给的数学条件仍须保留。

若原图直接给的是“对任意/存在某个自变量，不等式成立”、求参数范围，则按原题保留量词关系并使用 find_range。不能因为表达式含根号或分母，就把显式不等式改成 match_domain 或 find_domain。求函数值仍使用 find_value；函数值域不同于定义域。题面只说“恒成立”而未写出量词变量时，取关系中除待求量以外唯一的自由变量作为量词变量；未写出它的范围时取 ℝ。变量不唯一或范围不确定时报告 uncertainty。

题面只写 y=解析式、目标需要引用这个函数时，可以在 root.definitions 中将同一对应关系记作 f(x)=原解析式，并在目标 object 中引用 f；已有 f 时选择没有冲突的函数符号。这个内部函数名是表示别名，不是新题设，也不算擅自改动原图变量。保留原自变量、参数和整个原解析式，不化简、不约分、不添加合法条件。original_text 和 public_content 中仍保留原图的 y，不把内部别名写回题面。复核不能仅因这个允许的别名要求改名或删除函数定义。若原题已有函数名则沿用。若原题以 y=表达式给出公式，之后在量词内使用 y<0、y>0 等关系，直接将表达式展开到量词关系中，不另写量词外的全局 y 定义或条件。

同一 y 别名规则适用于 compare_functions 的 shared_functions 和各选项 functions：在各自对象中用 f(x)=原解析式表达同一对应关系，保留原自变量，明确用 shared/local 身份引用；不同对象可以使用同名 f，不因此合并。公共基准只定义一次，不移到 root.definitions，也不复制到各项。original_text、public_content 和 options.text 仍写原图的 y；内部别名不写回学生题面。abs(Q)、sqrt(Q^2)、P+abs(Q) 和 (Q*L)/L 均保留原始结构，不能在提取或修复时预先去绝对值、展开平方或约分。

比较函数的 domain 仅转录原题显式给出的范围。题面若明确从实数集、区间或单点集合去掉有限点，用集合差 ∖，例如 ℝ∖{-1,1/2} 或 [0,2]∖{1}；ASCII setminus 同义。不能用算术减号代替集合差，也不能因原式分母为零而自行填写 domain。原题额外给出的去点条件要保留，不把它遗漏为自然定义域；超出当前执行范围的真实范围仍照实表示，不改写成可执行的新题。

复核 findings 必须描述 path 指向的当前 candidate 字段实际存在的问题，不能把其他字段中的内容归到这个位置。original_text 是原题转录，可以保留来源题号；公开题干 public_content 按公开内容规则排除来源题号。必须分别读取两者，不能因 original_text 含题号就判定已经去掉题号的公开题干有错。原图文字依据写入 source_excerpt；对候选现状的描述必须与 path 处的实际值一致。

复核与修复的操作必须一致。wrong_expression，以及指向已有目标条目或其字段的 wrong_goal，只授权原位置修正对应条目，不授权删除。目标遗漏时，wrong_goal 应指向所在作用域（如 /root）或已有 goals 数组（如 /root/goals），仅授权在该作用域追加遗漏目标，不能改写已有目标或其他条件。条件或定义遗漏时，missing_condition 应指向所在作用域或已有 facts/definitions 数组，仅授权在那里追加遗漏内容。wrong_scope 仅授权在所指范围内整理分问层次、顺序和移动已有内容，保留数学内容不变，不能顺带改写、增删题设或目标。复核诊断中，只有原图没有依据的新增条目才用 unsupported_addition 授权删除；不能在 wrong_expression 的建议中写“或删除该定义”。同一项要修正、追加还是删除必须明确；无法确定时用 uncertain，不给互相矛盾的修复建议。修复阶段不得把替换诊断当删除授权；需要修改多个字段时，每处都应有对应诊断。修复后的完整候选必须重新对照原图复核。
