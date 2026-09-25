# Test results — 528 web-sourced leaf photographs

Raw per-photograph output behind `docs/EVALUATION_REPORT.pdf`. Regenerate any of these with
`tools/test_zip.py`; regenerate the report from `stats.json` with `tools/build_report.py`.

The test set itself is not committed — it is 36 MB and not ours to redistribute. These
measurements are what needs versioning.

| File | Threshold | Crop sent | Mismatch gate | Answers | Top-1 right | Top-3 has it |
|---|---|---|---|---|---|---|
| `t080_nocrop.*` | 0.80 | no | on | 39% | 56% | 61% |
| `t080_crop.*` | 0.80 | yes | on | 45% | 73% | 72% |
| `t095_crop_gate-on.*` | 0.95 | yes | on | 25% | 81% | 72% |
| `t095_crop_gate-off.*` | 0.95 | yes | off | 25% | 81% | 83% |
| **`t035_crop_DEPLOYED.*`** | **0.35** | **yes** | **off** | **86%** | **63%** | **88%** |

`t035_crop_DEPLOYED` is the configuration currently in `model/config.json`. The others are kept
so the threshold choice can be re-examined without re-running the whole set.

"Answers" and "top-1 right" are over photographs the service answered rather than abstaining on;
"top-3 has it" is over all 528.

`stats.json` holds the aggregates the report is built from, including the per-crop breakdown
measured with all gates removed — that is, the model's own ability rather than the policy
layered on top of it.

Columns in each CSV: `file`, `true_class`, `true_crop`, `status`, `pred_class`, `confidence`,
`detected_crop`, `top3`, `warnings`, `error`.
