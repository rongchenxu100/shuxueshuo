# Understanding holdout v1

Three newly authored synthetic problem images, unrelated to the five district gold fixtures.
`manifest.json` hashes each PNG, synthetic observation and expected domain graph.
`frozen-protocol.json` is the **first-exposure implementation snapshot**, not a claim that future code must never change.
Each subsequent live output directory records a separate immutable `protocol.json`.

The matching observation files are manually authored synthetic OCR records. They are processed by the production Paddle adapters, evidence builder and validators. Only model responses are substituted in offline replay. Live tests use real DeepSeek vision calls and no business database.

First-exposure scores and final-policy repeat scores are retained separately in `docs/validation/understanding-generalization-20260915`.
These questions are now exposed regression cases; future independent evaluations need new held-out problems.
