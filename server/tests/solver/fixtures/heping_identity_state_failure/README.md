# Recorded identity/state failures

Unchanged raw responses from acceptance-20260910 / five-by-three / tj-2026-heping-ermo-25,
sample-01 and sample-03, semantic attempts 1 and 2. Model: deepseek-v4-flash.

These are regression inputs, not authored correct plans. Sample-01 must remain rejected;
sample-03's repair should execute successfully after state/liveness correction.
request-baselines.json records original system hashes and system+user character counts.
Offline tests must not call a provider or replace erroneous model responses with expected answers.

request-replay-baselines.json records the offline replay budget as of 2026-09-17.
The system prompts, capability catalog and problem payload are unchanged from the
recording. The existing optional Method `parameters` schema and typed identity-error
fields account for the updated request sizes. The original recording metrics remain
in request-baselines.json; no model was called to refresh the replay budget.
