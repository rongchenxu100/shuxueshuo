请使用给定数学能力，为全部必答目标填写一份FunctionalPlan内容。
只输出一个`functional-plan-content/v2` JSON object，不要输出Markdown、解释或答案。

必须遵守：

1. Scope树与Goal归属完全由Plan Authority Frame拥有。输出不得包含`root_scope`、`children`、
   `scope_ref`或重复的`goal_ref`。`scope_steps`的key只能是Frame中的scope；`goal_plans`的key必须
   恰好覆盖Frame中的全部Goal。
2. 引用和步骤归属遵循下方共用规则。
3. 每个Goal必须输出`answer_from={step_id, return}`，明确指出你计划中产生该Goal最终答案的return。
   Plan Authority Frame的`goal_answers`和Goal专属JSON Schema会重复给出权威`target_ref/answer_type`；它们
   优先于题面措辞中的单复数直觉。Capability Catalog输入的`domain_type`是可选择的数学实体类型，return的
   `type`是产生值的canonical类型，两者不是同一概念。return必须来自该Goal本地步骤或可见祖先scope步骤，
   public return `type`必须与该Goal的`answer_type`逐字一致，并对应`target_ref`。代码会独立验证候选集合：
   合法指针用于消歧；指定step正确且其中只有一个active return满足target/type时，代码只规范化写错的public
   return名称。代码不会改选另一个step；producer为零个、多个或数学步骤不对时，整个失败Goal进入replacement retry。
   Goal没有本地step时省略`steps`，但仍必须输出`answer_from`。
   空的scope step数组与Goal step数组必须省略。
4. `capability_id`、args、return role、结果类型和`return_expectations`必须服从Capability Catalog。
   `binding=same_compiler_selected_object`不允许增加catalog未声明的arg或target。
   只有return明确展示`possible_forms`时才可为它填写`return_expectations`；固定形态return必须省略。
   `free_parameters`必须表示应用本步骤当前scope可见约束后仍然未确定的一组完整独立参数基底。结果仍为开放状态时
   必须填写非空基底；结果已闭合时可以填写`[]`或省略。数学等价的基底均可填写，代码会用runtime约束验证；
   不能根据下游Goal希望求哪个参数来提前删除、替换或收窄基底。
5. 每个catalog声明的public return都会自然存在；允许匿名结果的下游arg，或类型兼容的下游arg消费
   `reference_mode=exact_result` return时，可直接用`{"step_id":"...","return":"..."}`读取它。
   `output_targets`不是声明return，而只是把return写入当前scope
   可见的题面已有具名对象；没有这种对象时必须省略。Goal最终答案用`answer_from`选择producer，代码再根据
   Goal authority验证其对象身份。`reference_mode=exact_result`或`binding=exact_call_result_or_answer`的return
   即使表示题面已有Entity，也禁止填写`output_targets`；后续step必须直接使用它的StepResultRef。
   不要为答案增加`output_targets`，也不要自造target名称或其他绑定字段。
6. `intent`可选，只用于简短说明数学目的。所有step必须通向至少一个必答Goal。

引用与步骤归属（首轮和修复轮共用）：

- Scope直属步骤与Goal局部步骤是互斥的step所有权容器；每个step完整对象只能出现一次。
  多个Goal消费的共同producer放它们的共同祖先scope，且其全部生产条件必须在那里可见。
  只为单个Goal答案服务的步骤放该Goal。不得靠重复step或跨Scope引用代替合法归属。
- 共享题面数学实体不等于共享当前数学状态。兄弟scope若使用不同局部条件、参数值或自由参数基，
  必须各自生成局部状态，不能将局部条件提升到共同祖先。
- args中的普通具名Entity使用数学表达式字符串（如`Γ`、`vertex(Γ)`、`b`）；Fact使用当前scope可见的题设数学条件
  （如`a=1`、`N∈ray(C,D)`、`min(sqrt(2)*MN+AN)=21/4`），路径目标用`min(sqrt(2)*MN+AN)`。
  参数名、必填性、单值/集合基数保持Catalog原约定，例如`"free_parameters":"b"`。禁止自造条件或直接填写计算答案。
  数学表达式仅用于关联原有对象/条件；代码仍按capability读取身份或当前scope最近可见状态，并建立依赖。
  `output_targets`如需绑定已有对象，也使用其数学表达式；绑定身份和exact-result禁用target的规则不变。
  匿名中间结果，以及catalog声明`reference_mode=exact_result`的return，使用较早、可见的
  `{"step_id":"...","return":"..."}`，且consumer参数必须接受该返回类型。
  exact-result即使携带已有Entity身份也不得改写成SourceRef。跨Goal不改变引用形式规则。
- 跨Goal与跨Scope不同：只有在上述引用契约允许StepResultRef、producer Scope对consumer可见，
  且引用恰为producer Goal的`answer_from`时，才能跨Goal读取精确答案；不能读取其内部return。
  普通具名状态供多个Goal共享时，应使用可见Scope直属producer和SourceRef。
- 子孙可读取祖先Scope的共享步骤；兄弟Scope、子到父的状态引用非法。改用StepResultRef不授予权限。
  `answer_from`只选择本Goal或可见祖先Scope步骤的答案，不会发布状态到父Scope。
- `step_id`全题唯一，按依赖顺序输出，禁止forward reference和循环。
  数学参数只能关联当前scope或祖先可见的Entity/Fact；禁止引用兄弟问条件、自造对象或把goal_ref当作数学参数。
  数学条件和最值取等状态不同：`min(S)=k`仅引用已有最值题设，取等点/状态必须读取对应Method的精确结果。

当前题的严格、authority-bound JSON Schema位于user message末尾。