# Piecewise Area Trends

Use these rules for moving-figure overlap problems that ask for an area range, maximum/minimum, or phase-by-phase behavior.

## Solution Shape

1. Start with one trend step before formulas.
2. Classify every interval or special state in order.
3. State monotonicity in classroom language.
4. Use the trend step to decide which formulas or candidate values are worth calculating.
5. End with one compact final answer step.

The trend step is not just a shape list. For every interval, it must say both:

- what the overlap region shape is, such as `五边形`、`四边形`、`三角形`;
- how the area changes on that interval, such as `面积先变大再变小`、`面积逐渐变小`、`面积逐渐变大`.

Then the trend step must explicitly decide the later calculation agenda. For example: `后续只需讨论 0≤t＜1 时的最大值和最小值，以及 t＝13/4 时的最小值`. Do not automatically create a formula step for every interval; monotone intervals often only need their endpoint candidate, and a middle interval may need no separate calculation if the trend already shows it cannot create the global maximum or minimum.

Do not assign one boundary value to two different shape intervals unless the same geometric shape truly continues across that boundary. If the shape changes at `t=c`, either make `t=c` a separate state or include it on only one side.

Boundary values where the overlap shape changes must not be casually absorbed into a neighboring interval. For example, write `t=2` as a triangle boundary state, `2<t≤4` as the trapezoid phase, `4<t<6` as the pentagon phase, and `6≤t<12` as the next triangle phase when those are the actual shapes. Keep this exact boundary ownership in solution text, visual steps, `policies.range`, minis, and final unions.

For folding pages, distinguish the folded figure shape from the overlap region shape. A vertical fold can produce a triangular folded piece before the fold reaches one side, a quadrilateral/trapezoid in the middle, and a pentagonal folded figure after the fold passes another vertex, even when the overlap region is triangular. Use dynamic folded-polygon rendering and phase-scoped labels rather than forcing one static moving polygon through every interval.

## Trend Step Pattern

Use this compact structure when there are two or three major shape phases:

```json
{
  "id": "q2s1",
  "section": "第（II）②问",
  "title": "第1步：由图形变化判断面积分段",
  "t": 3.75,
  "derive": [
    ["∵", "1＜t≤3 时，△MPN 完全在 △ABC 内"],
    ["∴", "此时重叠部分是整个 △MPN，随着 t 变大，面积变大"],
    ["∵", "3＜t＜9/2 时，重叠部分为五边形"],
    ["∴", "此时重叠部分为五边形，面积先变大再变小"],
    ["∵", "9/2≤t＜5 时，重叠部分为四边形并继续缩小"],
    ["∴", "后续只需计算五边形段极值和右端边界最小值，再合并范围"]
  ],
  "box": [
    "1＜t≤3：三角形，面积变大",
    "3＜t＜9/2：五边形，面积先变大再变小",
    "9/2≤t＜5：四边形，面积变小"
  ],
  "minis": [
    { "title": "1＜t≤3", "caption": "△MPN 完全在 △ABC 内，面积变大。", "t": 2.2 },
    { "title": "3＜t＜9/2", "caption": "重叠部分是五边形，面积先变大再变小。", "t": 3.75 },
    { "title": "9/2≤t＜5", "caption": "重叠部分为四边形并继续缩小。", "t": 4.75 }
  ]
}
```

## Visual Rules

- Use `minis` as representative phase cards, not as a dump of every boundary/candidate value.
- Thumbnail titles should usually be interval labels, such as `1＜t≤3`.
- Thumbnail captions should be one sentence naming the shape and trend.
- Thumbnails should show only the fixed figure, moving figure, and overlap region.
- Do not put point labels, length labels, guide-line labels, or formula cards in thumbnails unless they are essential.
- Keep target overlap area `S` visually consistent across all phases.

## Calculation Steps

- For each formula step, name the overlap shape first.
- Derive the needed lengths, heights, or decomposition immediately before writing the area formula.
- Reuse prior results such as `CG`, `DH`, or `CD` instead of restarting from coordinates.
- If an extremum occurs at a boundary, make sure the policy range or mini can show that boundary.

## Endpoint Checklist

- Problem text, answer chips, solution, visual steps, `policies.range`, minis, formula boxes, and final answer must use the same endpoint inclusiveness.
- If an endpoint is included, use `≤`, compute the attained value, and say it is attained.
- If an endpoint is excluded, use `<`, use a strict bound, and do not claim the extremum is attained.
