---
title: GreenGuard Disease API
emoji: 🌿
colorFrom: green
colorTo: yellow
sdk: docker
app_port: 7860
pinned: false
---

# GreenGuard Disease API

Leaf photo → plant disease for 7 Pakistani crops (wheat, rice, cotton, maize, sugarcane, tomato, potato),
40 classes. EfficientNet-B0 (ONNX) on CPU. Full request/response format: **API_CONTRACT.md**.

## Folder
```
app.py              FastAPI app (endpoints, auth, errors)
predict.py          preprocessing + model + postprocessing (same file tested in the Phase 3 notebook)
model/              model.onnx, labels.json, config.json   ← from hf_model.zip
tests/test_api.py   contract + edge-case tests
client_example.py   example call for the backend team
Dockerfile, requirements.txt
```

## Deploy on Hugging Face Spaces
1. huggingface.co → **New Space** → SDK **Docker** (blank template) → hardware **CPU basic (free)** →
   visibility **Public** (the API key protects it; a private Space would also need an HF token on every call).
2. **Files → Add file → Upload files**: upload everything in this folder, including `model/` with the three
   files from `hf_model.zip`. Commit.
3. **Settings → Variables and secrets → New secret**: name `GREENGUARD_API_KEY`, value = a long random string.
   Share it only with the backend team.
4. Wait for the build (logs tab) until it says *Running*, then check:
   `https://<user>-<space>.hf.space/health`

## Deploy on Render (free alternative)
1. Put this folder (with `model/` files) in a GitHub repo — private is fine.
2. render.com → **New → Web Service** → connect the repo → Runtime **Docker** → Instance **Free**.
3. Environment variables: `GREENGUARD_API_KEY` = your key, `ORT_THREADS` = `1`.
4. Advanced → Health check path: `/health` → **Deploy**.
5. URL: `https://<service-name>.onrender.com` (free instances spin down after ~15 min idle).

## Test it
```bash
curl -X POST "https://<user>-<space>.hf.space/v1/predict" \
     -H "X-API-Key: <key>" -F "image=@leaf.jpg" -F "crop=wheat"
```
Interactive docs: `https://<user>-<space>.hf.space/docs`

## Run locally
```bash
pip install -r requirements.txt pytest httpx
pytest -q                                   # needs model/ files
uvicorn app:app --port 7860                 # then open http://localhost:7860/docs
```

## Notes
- Thresholds (confidence, crop-filtered, crop-mismatch, quality) live in `model/config.json` and were
  calibrated in the Phase 3 notebook — change them there, not in code.
- The free Space sleeps when idle; the first request after that is slow (see API_CONTRACT.md).
