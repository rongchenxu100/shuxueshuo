# Q17：把 m² 看成整体消参，再分式分离

入口 `/1/q17/`，分组“消参法求最值”，排在 Q16 后。题目：5m²n²+n⁴=1，求 m²+n² 的最小值（4/5）。

只提供“消参法”路线。5 步：

1. 消参（choice）：选 m²=(1-n⁴)/(5n²)。干扰项漏掉系数 5、分子符号写反，各有整理核对预览。完成后系统补出 n≠0、0<n²≤1，并说明为何消 m² 而不是 n²。
2. 分式分离（fill）：在 m²+n² ≟ □·1/n² + ○·n² 中填 1/5、4/5。确认错误组合后，页面把所填两项通分，与 (1+4n⁴)/(5n²) 比较分子系数。
3. 观察和积结构：1/(5n²) 与 4n²/5 积为 4/25，定积求和。
4. 应用基本不等式：两项和≥4/5。
5. 验证取等：n²=1/2，m²=3/10，代回原条件成立。

HTML 保存展示与本地答案；教师数据在 `server/shuxueshuo_server/tutor_demo/lessons/q17.json`。老师说明提醒题目未给 m、n 为正，并认可因式分解 n²(5m²+n²)=1、换元 a=m²、b=n²。无题目专属 JS、CSS 或 Prompt 特例。

测试入口：`server/tests/tutor_demo/test_q17.py`。覆盖前后端一致性、各步错误与重新尝试、25 种填空组合的通分核对（sympy 验算）、证据分轮累积。真实 DeepSeek 连续 14 轮验收已通过，覆盖整体次数解释、错误组合通分、部分作答与完整路径；记录见 [live-dialogue-review.md](live-dialogue-review.md)。运行方式：`RUN_TUTOR_LIVE=1 uv run pytest tests/tutor_demo/test_q17.py -k live_q17 -q -s`（在 server 目录，需配置 DeepSeek）。
