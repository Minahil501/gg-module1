---
title: GreenGuard Disease API
emoji: 🌿
colorFrom: green
colorTo: yellow
sdk: docker
app_port: 7860
pinned: false
---

# GreenGuard — Module 1: Leaf Disease Detection

**Version:** 1.0 (`efficientnet_b0-1.0`) · **Status:** trained model present, deployable · **Hosting:** Hugging Face Space (Docker) or Render, **not** a local port

> The YAML block above is the Hugging Face Space card. It must stay at the very top of
> this file for the Space to build. GitHub renders it as a table; that is expected.

## 1. What this module does

Takes **one leaf photo**, returns **one plant disease** (or `healthy`), with a confidence
and the top 3 candidates.

- **Model:** EfficientNet-B0, exported to ONNX, run on CPU via `onnxruntime`.
- **Coverage:** **38 reportable classes** across 7 Pakistani field crops — wheat, rice, cotton,
  maize, sugarcane, tomato, potato. The model has 40 outputs, but `wheat_black_point` and
  `wheat_fusarium_foot_rot` are suppressed in `model/config.json`: both affect the grain or stem
  base rather than the leaf, so a leaf photo cannot show them. Authoritative list:
  `GET /v1/classes` — not `model/labels.json`, which still has all 40.
- **Safety behaviour:** rather than guessing, the API returns `status: "uncertain"` with a
  farmer-facing message when confidence falls below the configured threshold. Blur, low light
  and overexposure are reported as `warnings` but do not by themselves force `uncertain`.

### What it does NOT do

This is important, because earlier drafts of this module promised more:

| Not provided | Where it went |
|---|---|
| Nutrient-deficiency detection | **Removed.** Module 2 (`Stress_Module`) covers nutrients. |
| Insect detection | **Removed.** No model exists for it. |
| `farm_id` / `timestamp` in the response | **Not returned.** The backend owns both. |
| Treatment advice, Urdu names | Backend maps `class_id` → advice. |

⚠️ **This diverges from `REST_API_SPEC.md` Section 9 → AI Module 1**, which still documents a
three-part `{disease, nutrient_deficiency, insect}` response. See
[§9 Known contract gaps](#9-known-contract-gaps) — that gap needs a PM decision, it is not
something the backend team can paper over.

## 2. Folder structure

```
Disease_Module/
├── app.py                  # FastAPI app — endpoints, API-key auth, error shapes
├── predict.py              # Validation → normalisation → quality → model → postprocess
├── client_example.py       # Copy-paste example call for the backend team
├── model/
│   ├── model.onnx          # EfficientNet-B0 weights (16 MB, plain binary)
│   ├── labels.json         # 40 class ids, index order = model output order
│   └── config.json         # Preprocessing + all decision thresholds (calibrated)
├── tests/
│   └── test_api.py         # contract + edge-case tests (skipped if model/ absent)
├── tools/
│   ├── test_zip.py         # batch-test the model on a zip/folder of labelled photos
│   └── build_report.py     # render the evaluation report PDF from measured stats
├── test_results/           # per-photo measurements for each threshold tried
├── docs/
│   └── EVALUATION_REPORT.pdf   # ← read this before trusting the model
├── API_CONTRACT.md         # ← the document the backend team integrates against
├── Dockerfile
├── requirements.txt
├── .env.example
├── .gitattributes          # keeps model/ bytes exact (no LFS — see the file)
└── _archive_old_module1/   # superseded drafts — see §10, safe to delete
```

**Do not change thresholds in code.** Confidence, crop-filter, crop-mismatch and image-quality
thresholds all live in `model/config.json`, and `predict.py` reads every one of them from there.
The two decision thresholds were re-tuned on the 528-photo set described in §5 — see
`docs/EVALUATION_REPORT.pdf` §6 for what each value was changed to and why. The crop-mismatch
check is **switched off**: the farmer's crop selection is authoritative.

## 3. Run it locally

```bash
python -m venv venv

# Windows:
venv\Scripts\activate
# Mac/Linux:
source venv/bin/activate

pip install -r requirements.txt
uvicorn app:app --port 7860
```

Then open http://localhost:7860/docs.

Without `GREENGUARD_API_KEY` set, the API-key check is **disabled** and the service logs a
warning — convenient locally, dangerous in production (§9).

## 4. Tests

```bash
pip install pytest httpx
pytest -q
```

18 test functions, 28 collected cases (two are parametrised). **28 passed** as of the last
run, against the real `model/model.onnx`.

The whole module skips itself if `model/model.onnx` is missing, so a green run with no model is
not a pass — check the output says 28 passed, not 28 skipped. Run `pytest tests/` rather than
bare `pytest`, or it will also try to collect the superseded suite in `_archive_old_module1/`.

They cover: health, auth, crop normalisation (`corn`→maize, `paddy`→rice), invalid crop,
missing/empty/corrupt/truncated files, size limits, colour modes and formats, HEIC, EXIF
rotation invariance, and the blur/low-light warnings.

## 5. How well does it actually work?

**Read `docs/EVALUATION_REPORT.pdf` before promising anything to anyone.** Summary, measured on
508 web-sourced photographs with the crop supplied:

| | |
|---|---|
| service answers rather than abstaining | 87% |
| its single best guess is correct | **64%** |
| the correct disease is somewhere in `top3` | **88%** |

The shortlist is the product. The single `prediction` is wrong on roughly one answer in three,
so the interface must show all three ranked possibilities — see the red-flag block in
`API_CONTRACT.md`.

Accuracy is very uneven by crop. Potato (77%), cotton (73%) and maize (73%) are usable;
wheat is 42% after suppressing its two non-leaf classes, and **rice is 34%** — close to
guesswork, and should not be offered to farmers until the model is retrained. Healthy leaves were not tested at all, so the false-alarm rate on a healthy
plant is unknown — the report lists that as the largest open risk.

Re-run it yourself on any labelled zip:

```bash
venv/Scripts/python tools/test_zip.py --zip <your-set>.zip --send-crop
venv/Scripts/python tools/build_report.py test_results/stats.json docs/EVALUATION_REPORT.pdf
```

## 6. Deploy on Hugging Face Spaces

1. huggingface.co → **New Space** → SDK **Docker** (blank template) → hardware **CPU basic
   (free)** → visibility **Public**. The API key protects it; a private Space would also
   require an HF token on every backend call.
2. **Files → Add file → Upload files**: upload everything in this folder **except**
   `_archive_old_module1/`, including all three files in `model/`. Commit.
3. **Settings → Variables and secrets → New secret**: name `GREENGUARD_API_KEY`, value = a
   long random string. Share it with the backend team only, privately.
4. Watch the Logs tab until it says *Running*, then check
   `https://<user>-<space>.hf.space/health`.

## 7. Deploy on Render (free alternative)

1. Push this folder (with `model/` files) to a GitHub repo — private is fine.
2. render.com → **New → Web Service** → connect the repo → Runtime **Docker** → Instance **Free**.
3. Environment variables: `GREENGUARD_API_KEY` = your key, `ORT_THREADS` = `1`
   (the free instance has one core; the Dockerfile default of 2 will thrash).
4. Advanced → Health check path: `/health` → **Deploy**.
5. URL: `https://<service-name>.onrender.com`. Free instances spin down after ~15 min idle.

## 8. Integrating

Read **`API_CONTRACT.md`** — it is the authoritative request/response document, and it is
written for the backend team rather than for us.

Quick check once deployed:

```bash
curl -X POST "https://<user>-<space>.hf.space/v1/predict" \
     -H "X-API-Key: <key>" -F "image=@leaf.jpg" -F "crop=wheat"
```

`client_example.py` shows the same call in Python, with the cold-start retry the free tier needs.

**Cold start:** an idle free Space sleeps. The first request after that can take 30+ seconds.
Use a 60 s timeout, retry once on timeout or 503, and call `/health` when the farmer opens the
app so the Space is awake by the time they photograph a leaf.

## 9. Known contract gaps

These are open issues, not bugs to fix quietly. They need decisions from the PM / backend team.

1. **The response shape does not match `REST_API_SPEC.md` Section 9 → AI Module 1.** The spec
   mandates `{farm_id, timestamp, disease, nutrient_deficiency, insect}` and instructs the
   backend to "store response exactly". This service returns `{status, prediction, top3,
   warnings, ...}` and no nutrient or insect fields. Either the spec is amended or the backend
   writes an adapter — but the two documents cannot both stand.
2. **Auth fails open.** If `GREENGUARD_API_KEY` is unset in the deployment environment,
   `app.py` disables the key check and only logs a warning. A missing secret on a public Space
   therefore yields a fully open API, not a broken one. Verify the secret is set after deploy.
3. **No port 8003.** The rest of the project assigns 8000 = Django, 8001 = Weather, 8002 = Soil,
   8003 = Disease. This module is externally hosted on 7860 and reached by URL, so the
   port-8003 convention in the older docs no longer applies to Module 1.
4. **No CORS headers.** Only the Django backend can call this; a browser cannot call it
   directly. That matches the intended architecture — just do not let the frontend try.
5. **Crop coverage changed.** The architecture docs describe OLID I crops (gourds, eggplant,
   tomato). This model covers wheat/rice/cotton/maize/sugarcane/tomato/potato. **Tomato is the
   only crop in both lists.** Any UI crop picker built from the old docs is wrong — build it
   from `GET /v1/classes`.
6. **This folder is not in git.** The repository `.gitignore` is a whitelist and does not
   include `Disease_Module/`, so none of this is committed. It must be added to the whitelist
   before handover, together with Git LFS for `model.onnx` (16 MB).

## 10. `_archive_old_module1/`

Three superseded attempts at this module, kept only so nothing is lost:

- `api/`, `config/`, `models/` — a stub-mode FastAPI scaffold on port 8003 with the
  three-head contract and no trained model. Its two `class_names.json` files disagree with
  each other, and its documented "Uncertain" threshold rule was never implemented.
- `predict_folder (1).py` — a batch CLI for a different, torch-based v3/v3.1 pipeline whose
  weights are not in the repo.
- `web_test_results.csv` / `.json` — that pipeline's output on 24 web photos. Roughly a third
  are confidently wrong, including healthy leaves scored as deficient at 0.91 and 0.98.
  **Not evidence for this model** — different model, different crops. Kept as a reminder to
  run the same test against the current one.

None of it is referenced by the running service. Delete the folder once the team agrees.
