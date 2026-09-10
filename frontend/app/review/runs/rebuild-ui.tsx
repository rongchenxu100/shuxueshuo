"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { EditableProblemSchema, ProblemPreviewSchema, RebuildPlanSchema, RebuildPlan, StartSchema, pageValidityLabel, reviewFetch } from "@/lib/review/contracts";
import styles from "./review.module.css";

const titles: Record<string, string> = { source: "来源入库", observation: "OCR 与观察", extraction: "题意校验 / 抽取", projection: "输入投影", solver: "Solver", evidence: "教学证据", lesson: "学生讲解", visual: "图形生成", page: "页面编译" };
const showStages = (keys: string[]) => keys.map((key) => titles[key] ?? key).join(" → ") || "无";
const post = (body: unknown) => ({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

export function RebuildPanel({ runId, request, onValidity }: { runId: string; request: { stage?: string; count: number }; onValidity: (value: string) => void }) {
  const router = useRouter();
  const [plan, setPlan] = useState<RebuildPlan | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    let active = true;
    let pending = false;
    const update = async () => {
      if (pending) return;
      pending = true;
      try {
        const value = RebuildPlanSchema.parse(await reviewFetch(`/api/review/runs/${runId}/rebuild-plan${request.stage ? `?requested_stage=${request.stage}` : ""}`));
        if (active) { setPlan(value); onValidity(value.page_validity); setError(""); }
      } catch (e) { if (active) { setError(String(e)); onValidity("unknown"); setPlan(null); } }
      finally { pending = false; }
    };
    void update();
    const timer = setInterval(update, 5000);
    return () => { active = false; clearInterval(timer); };
  }, [runId, request.stage, request.count, refresh, onValidity]);
  async function rebuild() {
    if (!plan) return;
    setBusy(true); setError("");
    try {
      // Submit exactly the reviewed fingerprint. The API rejects stale previews.
      const result = StartSchema.parse(await reviewFetch(`/api/review/runs/${runId}/rebuild`, post(plan)));
      router.push(result.review_url);
    } catch (e) { setError(String(e)); setPlan(null); }
    finally { setBusy(false); }
  }
  return <section id="rebuild" className={styles.panel}>
    <h2>修改与重建</h2>
    <p><strong>{pageValidityLabel(plan?.page_validity)}</strong> · 保存修改后，点击重建才会开始执行。</p>
    {plan?.latest_run_id && plan.latest_run_id !== runId && <p>本页属于历史运行。<Link href={`/review/runs/${plan.latest_run_id}`}>查看最新请求的构建及其成功／失败状态 →</Link></p>}
    {plan && <>
      <p>复用：{showStages(plan.reuse_stages)}</p>
      <p><strong>重建：{showStages(plan.rerun_stages)}</strong></p>
      <p>{plan.calls_models ? `涉及模型调用：${showStages(plan.model_stages)}` : "无需模型调用"}</p>
      {request.stage && plan.rerun_stages[0] !== request.stage && <p>所选阶段的上游已失效，实际范围已提前至{titles[plan.rerun_stages[0]]}。</p>}
      {!!plan.reasons.length && <details><summary>查看 {plan.reasons.length} 项失效原因</summary><ul>{plan.reasons.map((reason, i) => <li key={i}>{titles[reason.stage]}：{reason.message}</li>)}</ul></details>}
      <button onClick={rebuild} disabled={busy || !plan.available}>{busy ? "正在提交…" : "按影响范围重建"}</button>
    </>}
    <button onClick={() => setRefresh((n) => n + 1)} disabled={busy}>刷新影响范围</button>
    {error && <p role="alert" className={styles.error}>{error}</p>}
    <ProblemEditor key={runId} runId={runId} onSaved={() => setRefresh((n) => n + 1)} />
  </section>;
}

function ProblemEditor({ runId, onSaved }: { runId: string; onSaved: () => void }) {
  const [base, setBase] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [schema, setSchema] = useState<unknown>(null);
  const [preview, setPreview] = useState<ReturnType<typeof ProblemPreviewSchema.parse> | null>(null);
  const [checkedText, setCheckedText] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  async function load() {
    setBusy(true);
    try {
      const value = EditableProblemSchema.parse(await reviewFetch(`/api/review/runs/${runId}/problem`));
      setBase(value.base_revision_id); setText(JSON.stringify(value.domain, null, 2)); setSchema(value.schema); setPreview(null); setMessage("");
    } catch (e) { setMessage(String(e)); }
    finally { setBusy(false); }
  }
  async function check(save: boolean) {
    setBusy(true); setMessage("");
    try {
      const value = ProblemPreviewSchema.parse(await reviewFetch(`/api/review/runs/${runId}/problem/${save ? "revisions" : "preview"}`, post({ base_revision_id: base, domain: JSON.parse(text) })));
      setPreview(value); setCheckedText(text);
      if (save && value.ok && value.base_revision_id) {
        setBase(value.base_revision_id); setPreview(null); onSaved();
        setMessage("题意已保存。查看影响范围后点击重建；尚未调用模型。");
      }
    } catch (e) { setMessage(String(e)); setPreview(null); }
    finally { setBusy(false); }
  }
  return <details className={styles.artifact}><summary>编辑题意 JSON</summary>
    <p>编辑题干、条件和目标；保存前重新执行 Schema、数学合同及题型校验。</p>
    <button onClick={load} disabled={busy}>{base ? "重新载入已保存题意" : "载入题意"}</button>
    {base && <>
      <small>基础修订：{base}</small>
      <textarea className={styles.editor} aria-label="题意 JSON" spellCheck={false} value={text} onChange={(e) => setText(e.target.value)} />
      <button disabled={busy} onClick={() => check(false)}>校验并预览差异</button>
      <button disabled={busy || !preview?.ok || checkedText !== text} onClick={() => check(true)}>保存题意修订</button>
      <details><summary>对应 Schema</summary><pre>{JSON.stringify(schema, null, 2)}</pre></details>
    </>}
    {preview && <div><h3>{preview.ok ? "校验通过" : "校验未通过，未保存"}</h3>
      <pre>{JSON.stringify(preview.diff, null, 2)}</pre>
      <details open={!preview.ok}><summary>字段诊断</summary><pre>{JSON.stringify(preview.diagnostics, null, 2)}</pre></details>
      {preview.affected_stages && <p>影响：{showStages(preview.affected_stages)}</p>}
    </div>}
    {message && <p role="status">{message}</p>}
  </details>;
}
