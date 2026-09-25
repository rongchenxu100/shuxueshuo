# C0 review and regression evidence

`human-review-summary.json` records the historical human review of the 29 public
capability cards. Its review date and approval are not refreshed by an offline test
run.

The other four JSON files are deterministic machine regression baselines. On
2026-09-17 they were refreshed for the repository's recorded-image input and the
already registered internal `organize_expressions` Method. The public capability
cards, recorded occurrences, synthetic scenarios, annotated-plan hashes and case
counts are unchanged. Registry and provenance-dependent artifact hashes changed.
This refresh does not assert a new human page review or a current product admission.

On 2026-09-25 the four machine baselines were regenerated with
`python -m shuxueshuo_server.solver.lesson_capability_coverage_review --batch-id lesson-template-c0-20260925-01 --fixture-dir server/tests/solver/fixtures/lesson_scope_authoring_vnext/public_capability_c0`.
Only the global registry fingerprint changed; all 29 public contracts and coverage
records remained equal. Regression gates compare public contracts, teaching and
coverage data, not unrelated internal registry fingerprints or build provenance
hashes. The historical human review was not modified or promoted to a new approval.
