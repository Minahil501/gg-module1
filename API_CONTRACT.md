# GreenGuard Disease API — Contract v1.0

Base URL: `https://<hf-username>-<space-name>.hf.space`
Auth: every `/v1/*` request needs the header `X-API-Key: <key>` (shared privately by the AI team).
Model: `efficientnet_b0-1.0` · **38 reportable classes** · 7 crops.

> **Scope warning.** This service returns **disease only**. It does not return nutrient
> deficiency or insect presence, both of which appear under `REST_API_SPEC.md` Section 9 →
> AI Module 1. `farm_id` and `timestamp` *are* returned, as that section requires. See
> [Divergence from REST_API_SPEC.md](#divergence-from-rest_api_specmd) for what is still open.

---

## POST /v1/predict

Identifies the disease on **one leaf photo**.

**Request** — `multipart/form-data`

| Field | Required | Type | Notes |
|---|---|---|---|
| `image` | yes | file | max 10 MB · min 100 px per side · max 50 M pixels |
| `crop` | no | text | `wheat`, `rice`, `cotton`, `maize`, `sugarcane`, `tomato`, `potato` (case-insensitive; `corn` → maize, `paddy` → rice, `cane`/`sugar_cane` → sugarcane). **Send it whenever the farmer has chosen one** — accuracy is materially worse without it. |
| `farm_id` | no | text | Echoed back unchanged on the response. Max 128 characters. Not used by the model. |

**Accepted image formats.** Anything Pillow can decode — JPG, PNG, WEBP, BMP, GIF, TIFF, and
HEIC (iPhone) via `pillow-heif`. There is no format allow-list: a file is accepted if it decodes
and rejected with `INVALID_IMAGE` if it does not. Animated GIF/WEBP use the first frame. EXIF
rotation is applied, transparency is flattened onto white, and 16-bit/float images are rescaled.

**Response 200 — confident**
```json
{
  "status": "ok",
  "farm_id": "farm_001",
  "timestamp": "2026-09-26T04:55:12Z",
  "prediction": {
    "class_id": "wheat_yellow_rust",
    "crop": "wheat",
    "disease": "yellow_rust",
    "display_name": "Yellow Rust",
    "is_healthy": false,
    "confidence": 0.8812
  },
  "top3": [
    {"class_id": "wheat_yellow_rust", "crop": "wheat", "disease": "yellow_rust", "display_name": "Yellow Rust", "is_healthy": false, "confidence": 0.8812},
    {"class_id": "wheat_brown_rust",  "crop": "wheat", "disease": "brown_rust",  "display_name": "Brown Rust",  "is_healthy": false, "confidence": 0.0713},
    {"class_id": "wheat_septoria",    "crop": "wheat", "disease": "septoria",    "display_name": "Septoria",    "is_healthy": false, "confidence": 0.0208}
  ],
  "crop_source": "user",
  "detected_crop": "wheat",
  "warnings": [],
  "message": null,
  "model_version": "efficientnet_b0-1.0",
  "inference_ms": 14.2,
  "request_id": "3f9a1c2b7d4e"
}
```

**Response 200 — uncertain** (confidence below the threshold)
```json
{
  "status": "uncertain",
  "prediction": null,
  "top3": [ ... ],
  "warnings": ["BLURRY_IMAGE"],
  "message": "Image unclear. Please retake the photo in good light, close to one leaf. The photo looks blurry — hold the phone steady and tap to focus on the leaf.",
  "crop_source": "model",
  "detected_crop": "wheat",
  "farm_id": "farm_001",
  "timestamp": "2026-09-26T04:55:13Z",
  "model_version": "efficientnet_b0-1.0",
  "inference_ms": 15.9,
  "request_id": "7c1e4a90b3d2"
}
```

Every key above is present on **every** 200 response. `prediction` and `farm_id` are the only
ones that may be `null` — `farm_id` only when you did not send one. `top3` is always populated,
`warnings` is always an array, and `message` is `null` unless `status` is `uncertain`.

### Field meanings

| Field | Meaning |
|---|---|
| `status` | `ok` = trust `prediction` · `uncertain` = ask the farmer to retake, show `message`; `top3` may still be shown as "possibly…" |
| `prediction` | best class, or `null` when uncertain |
| `top3` | up to 3 most likely classes, highest first. **Always present, including when `status` is `uncertain`** — render it either way. Restricted to the selected crop's classes when `crop` was sent; all 38 reportable classes otherwise |
| `crop_source` | `user` (a valid `crop` was sent) or `model` (no crop sent) |
| `detected_crop` | the crop the model believes the leaf belongs to. **Always present**, including when `crop_source` is `user` — compare the two to see whether the model agreed |
| `warnings` | any of `BLURRY_IMAGE`, `LOW_LIGHT`, `OVEREXPOSED`. (`CROP_MISMATCH` exists but cannot currently occur — see below.) |
| `message` | farmer-facing text when uncertain, else `null` |
| `class_id` | **stable key** — use it to look up treatment advice, Urdu names, etc. Format is `<crop>_<disease>` |
| `display_name` | humanised `disease`, for display only. Do not key off it |
| `is_healthy` | true when `disease == "healthy"` |
| `confidence` | 0–1, rounded to **4 decimal places** |
| `inference_ms` | total server time for validation + preprocessing + model, not model time alone |
| `farm_id` | exactly what you sent, unchanged, or `null` if you sent nothing. Never invented by this service |
| `timestamp` | when the prediction completed. ISO 8601, **UTC**, second precision (`2026-09-26T04:55:12Z`) — convert to Pakistan time for display, store one timezone |
| `request_id` | 12 hex chars, on every response including errors. Quote it when reporting a problem |

### How the decision is made

Understanding this matters, because `confidence` means something different in each branch.

**No `crop` sent.** The top class over all 38 must reach **0.70** (`confidence_threshold`),
otherwise `uncertain`. `confidence` is the raw model probability.

**`crop` sent and the model agrees.** Probabilities are restricted to that crop's classes and
**renormalised to sum to 1**, then the top class must reach **0.35**
(`crop_filtered_threshold`). ⚠️ `confidence` here is a *within-crop* share, not the raw
probability — a class the model gave 0.30 to can be reported at 0.95 once its 6 crop-mates are
removed. Treat confidence as comparable only against other responses from the same branch.

> ## 🚩 Render `top3` on EVERY response. Never branch on `status` to decide whether to show it.
>
> `top3` is present on **every** 200 response, including when `status` is `uncertain` and
> `prediction` is `null`. It is always drawn from the crop the farmer selected. Measured on 508
> web-sourced photographs with the crop supplied:
>
> | what the app renders | how often the farmer sees the right disease |
> |---|---|
> | `prediction` only, when `status == "ok"` | 64% |
> | `top3`, only when `status == "ok"` | 77% |
> | **`top3`, always** | **84%** |
>
> That last row is 7 points better than the middle one for free, and it is purely a frontend
> decision — no setting on this service changes it. Of the photographs the service marks
> `uncertain`, **56% still have the correct disease in `top3`**. Discarding those is throwing
> away more than half of a fallback that already works.
>
> **What `status` is for:** wording, not visibility.
>
> - `ok` → "Most likely **X**. It could also be Y or Z."
> - `uncertain` → "Not sure from this photo. It may be **X**, Y or Z — retake in better light
>   to confirm." Still show all three, and still show `message` and any `warnings`.
>
> Rendering `prediction` alone as a verdict would put a wrong disease in front of a farmer
> roughly **1 time in 3**, with a spraying decision attached.
>
> `top3` is **not equally meaningful for every crop**, because it is 3 items drawn from a
> different number of classes each time:
>
> | crop | classes | top-3 accuracy | by chance alone | worth showing? |
> |---|---|---|---|---|
> | maize | 4 | 96% | 75% | marginal |
> | cotton | 4 | 93% | 75% | marginal |
> | sugarcane | 5 | 92% | 60% | yes |
> | tomato | 9 | 80% | 33% | yes |
> | wheat | 7 | 63% | 43% | marginal |
> | rice | 6 | 62% | 50% | **barely better than chance** |
> | potato | 3 | 100% | 100% | **no — it lists every potato class** |
>
> For potato, showing 3 of 3 classes conveys nothing — show only `prediction` (77% correct)
> for that crop. For rice, neither the top-1 (34%) nor the top-3 (62%, against 50% by chance)
> carries much signal; consider not offering rice until the model is retrained.
>
> Raw per-photo data for every configuration is in `test_results/`.

**`crop` sent and the model disagrees — currently disabled.** There is a crop-mismatch check
that can override the farmer's choice, but `crop_mismatch_threshold` is set to **1.01**, above
any attainable probability mass, so **it never fires and `CROP_MISMATCH` is never returned**.

It was switched off deliberately: the farmer's crop selection is authoritative, and the model's
own crop guess disagreed with it on 38% of test photographs — it was rejecting good answers far
more often than it caught real mistakes. `detected_crop` is still reported, so you can compare
it against the crop you sent. If they differ while `status` is `ok`, the model did not recognise
the crop; treat that response with more caution.

Quality warnings (`BLURRY_IMAGE`, `LOW_LIGHT`, `OVEREXPOSED`) **do not by themselves force
`uncertain`** — a sharp answer on a slightly dark photo still returns `ok` with a warning
attached. They are appended to `message` as extra advice only when the result was already
uncertain.

---

## Errors

```json
{"status": "error", "error": {"code": "INVALID_IMAGE", "message": "File is not a valid image."}, "request_id": "..."}
```

| HTTP | code | When |
|---|---|---|
| 400 | `MISSING_IMAGE` | no `image` field, or the file is empty |
| 400 | `INVALID_IMAGE` | not an image, corrupt, truncated, or over 50 M pixels |
| 400 | `IMAGE_TOO_SMALL` | smaller than 100 px on a side |
| 400 | `INVALID_REQUEST` | not a multipart form / required field missing |
| 401 | `UNAUTHORIZED` | missing or wrong `X-API-Key` |
| 413 | `FILE_TOO_LARGE` | over 10 MB |
| 422 | `INVALID_CROP` | unknown crop value (the message lists the valid ones) |
| 500 | `INTERNAL_ERROR` | unexpected server error — quote `request_id` |
| 503 | `MODEL_NOT_READY` | model still loading, or it failed to load |

`farm_id` is echoed on error responses too, whenever the form was readable — so a failed
prediction can still be traced to a farm. It is **absent** on `401` and `413`, which are decided
before the body is parsed. `request_id` is on every response without exception, so use that as
the correlation key and treat `farm_id` as a convenience.

A `farm_id` longer than 128 characters is rejected with `400 INVALID_REQUEST`. The value is
passed straight back out to your logs and database, so it is bounded rather than echoed blindly.

Two ordering details worth knowing when you debug:

- **`413` is returned before the API key is checked.** An oversized upload is rejected by
  middleware on the `Content-Length` header, before the body is read and before auth. An
  unauthenticated caller can therefore get a 413 rather than a 401.
- **`401` is returned before `503`.** A wrong key looks the same whether or not the model
  finished loading.

---

## GET /v1/classes

All classes grouped by crop — use it to build the crop picker and the `class_id` → advice
lookup, rather than hard-coding either. Needs `X-API-Key`.

⚠️ **This is 38 classes, not 40.** `wheat_black_point` and `wheat_fusarium_foot_rot` are
suppressed and can never be returned by `/v1/predict`, so they are not listed here either.
Black point affects the grain and fusarium foot rot the stem base — neither is visible on a
leaf, so the model could only ever guess at them. Do not carry treatment advice for them, and
do not hard-code the old 40-item list. The suppressed set lives in `model/config.json`.

```json
{
  "model_version": "efficientnet_b0-1.0",
  "num_classes": 40,
  "crops": [
    {
      "id": "cotton",
      "name": "Cotton",
      "classes": [
        {"class_id": "cotton_bacterial_blight", "crop": "cotton", "disease": "bacterial_blight", "display_name": "Bacterial Blight", "is_healthy": false}
      ]
    }
  ],
  "request_id": "a1b2c3d4e5f6"
}
```

Entries here carry **no `confidence` key** — same object as in `top3` otherwise.

## GET /health

No key required. Use it to wake a sleeping Space.

```json
{"status": "ok", "model_version": "efficientnet_b0-1.0", "num_classes": 38}
```

While starting, or if the model failed to load, it returns **HTTP 503** with the standard error
body (`{"status": "error", "error": {"code": "MODEL_NOT_READY", ...}, "request_id": "..."}`),
not the shape above. Check the HTTP status, not the presence of a field.

## GET /

Unauthenticated service banner: `{"service": ..., "docs": "/docs", "health": "/health"}`.
Not part of the integration surface; do not depend on it.

---

## Integration notes

- **Cold start:** the free Space sleeps when idle; the first request can take 30+ s. Use a
  **60 s timeout**, retry once on timeout or 503, and optionally call `/health` when the app
  opens to wake it. `client_example.py` does this.
- **Send `crop` whenever the farmer selected one.** It meaningfully narrows the answer — but
  read the confidence caveat above before storing the number.
- One photo per request, one leaf per photo.
- **Treatment advice is not part of this API.** Map `class_id` to advice in the backend.
- The model covers only the 7 crops listed. A photo of another plant, or a non-leaf photo, will
  still get some answer — `detected_crop` and the confidence thresholds are the only defence,
  and they are not a guarantee.
- **No CORS headers are sent.** Only the Django backend can call this; a browser cannot call it
  directly from the farmer's device.
- **Auth fails open.** If `GREENGUARD_API_KEY` is not set in the deployment environment, the
  key check is silently disabled (a warning is logged at startup). After deploying, confirm
  that a request with no `X-API-Key` returns 401.

---

## Divergence from `REST_API_SPEC.md`

`REST_API_SPEC.md` Section 9 → AI Module 1 documents this response:

```json
{ "farm_id": "...", "timestamp": "...",
  "disease": {"label": "...", "confidence": 0.91},
  "nutrient_deficiency": {"label": "...", "confidence": 0.83},
  "insect": {"label": "...", "confidence": 0.97} }
```

and instructs the backend to "store response exactly". **`farm_id` and `timestamp` now match
the spec. The rest does not.** Concretely:

| Spec expects | This service |
|---|---|
| `farm_id`, `timestamp` | ✅ **returned, in the format the spec shows.** Send `farm_id` as a form field and it is echoed back |
| `disease.label` (e.g. `"Powdery Mildew"`) | `prediction.class_id` (e.g. `"wheat_powdery_mildew"`) + `display_name` |
| `nutrient_deficiency` | **absent** — Module 2 (`Stress_Module`) covers nutrients |
| `insect` | **absent** — no model exists |
| always a label | `prediction` may be `null` when `status` is `uncertain` |
| crops: gourds, eggplant, tomato | wheat, rice, cotton, maize, sugarcane, tomato, potato |

This still needs a decision, not a workaround: either Section 9 is amended to this contract, or
the backend owns a documented adapter. The nutrient and insect fields cannot be adapted around —
no model produces them.

**One point the PM should rule on.** The spec's shape, `disease: {label, confidence}`, has no way
to express "we are not sure". This service abstains on roughly 13% of photographs, and for wheat
and rice the shortlist is doing most of the work. Forcing every response into a single
`{label, confidence}` pair would mean either inventing a label the model did not commit to, or
inventing a low confidence and hoping the backend checks it. If Section 9 is to be met literally,
that ambiguity is what has to be resolved first.
