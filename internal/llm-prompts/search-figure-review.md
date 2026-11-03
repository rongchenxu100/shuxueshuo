对照本次图形裁片，复核 candidate 中各图的 facts、uncertainties 以及图文对应。题干、函数式、目标和选项身份是只读上下文；不重新提取、不求解、不改写候选。

逐图核对 figure_id、题干／选项角色与标签，不能把其他选项或解析图的事实移入本图。只凭该图可见的线条、方向、标注和坐标判断，不根据目标函数或预期答案推断图形事实。

shown_monotone_curve 只描述展示部分的方向与横轴交点。示意图未给解析式、全定义域、图外走势或渐近线，不属于识别疑点，也不要求补造。数字刻度、坐标对、虚线投影、明确过原点 O 可作为坐标证据；交点清楚对应数字刻度可记 labelled，仅按像素间距估读不能记为 labelled。

全部事实及对应均可从裁片核对时返回 confirmed，findings 为空。确有错读、漏读或擅自新增时返回 correction_required，定位到 candidate 已有的 /figures/<序号>/... 字段。关键刻度、曲线或标签实际看不清时返回 uncertain，以 unreadable 或 ambiguous 报告具体疑点；不要把适用范围说明当成看不清。

输出严格遵守 response_schema，顶层仅有 status 和 findings。确认无误的格式为 {"status":"confirmed","findings":[]}。输入中的 base_revision 仅用于绑定只读题干，不是复核输出字段；不要回传 base_revision、figures 或 candidate。
