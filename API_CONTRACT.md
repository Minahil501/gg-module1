# GreenGuard Disease API — Contract v1.0

Base URL: `https://<hf-username>-<space-name>.hf.space`
Auth: every `/v1/*` request needs the header `X-API-Key: <key>` (shared privately by the AI team).

---

## POST /v1/predict

Identifies the disease on **one leaf photo**.

**Request** — `multipart/form-data`

| Field | Required | Type | Notes |
|---|---|---|---|
| `image` | yes | file | JPG, PNG, WEBP, HEIC, BMP, GIF · max 10 MB · min 100 px per side |
| `crop` | no | text | `wheat`, `rice`, `cotton`, `maize`, `sugarcane`, `tomato`, `potato` (case-insensitive; `corn` → maize, `paddy` → rice) |

**Response 200 — confident**
```json
{
  "status": "ok",
  "prediction": {
    "class_id": "wheat_yellow_rust",
    "crop": "wheat",
    "disease": "yellow_rust",
    "display_name": "Yellow Rust",
    "is_healthy": false,
    "confidence": 0.88
  },
  "top3": [
    {"class_id": "wheat_yellow_rust", "crop": "wheat", "disease": "yellow_rust", "display_name": "Yellow Rust", "is_healthy": false, "confidence": 0.88},
    {"class_id": "wheat_brown_rust",  "crop": "wheat", "disease": "brown_rust",  "display_name": "Brown Rust",  "is_healthy": false, "confidence": 0.07},
    {"class_id": "wheat_septoria",    "crop": "wheat", "disease": "septoria",    "display_name": "Septoria",    "is_healthy": false, "confidence": 0.02}
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

**Response 200 — uncertain** (low confidence or crop mismatch)
```json
{
  "status": "uncertain",
  "prediction": null,
  "top3": [ ... ],
  "warnings": ["BLURRY_IMAGE"],
  "message": "Image unclear. Please retake the photo in good light, close to one leaf. The photo looks blurry — hold the phone steady and tap to focus on the leaf.",
  ...
}
```

### Field meanings
| Field | Meaning |
|---|---|
| `status` | `ok` = trust `prediction` · `uncertain` = ask the farmer to retake (show `message`); `top3` can still be shown as "possibly…" |
| `prediction` | best class, or `null` when uncertain |
| `top3` | 3 most likely classes (only the selected crop's classes when `crop` is sent, unless there is a crop mismatch) |
| `crop_source` | `user` (crop was sent) or `model` (model decided the crop) |
| `detected_crop` | the crop the model thinks the leaf belongs to |
| `warnings` | any of `BLURRY_IMAGE`, `LOW_LIGHT`, `OVEREXPOSED`, `CROP_MISMATCH` |
| `message` | farmer-facing text when uncertain, else `null` |
| `class_id` | **stable key** — use it to look up treatment advice, Urdu names, etc. |
| `confidence` | 0–1 |

`CROP_MISMATCH`: the farmer selected one crop but the photo clearly shows another. Status is `uncertain`,
`detected_crop` holds the crop the model sees, and `top3` covers all crops.

---

## Errors

```json
{"status": "error", "error": {"code": "INVALID_IMAGE", "message": "File is not a valid image."}, "request_id": "..."}
```

| HTTP | code | When |
|---|---|---|
| 400 | `MISSING_IMAGE` | no `image` field / empty file |
| 400 | `INVALID_IMAGE` | not an image, corrupt, or dimensions too large |
| 400 | `IMAGE_TOO_SMALL` | smaller than 100 px on a side |
| 400 | `INVALID_REQUEST` | not a multipart form |
| 401 | `UNAUTHORIZED` | missing / wrong `X-API-Key` |
| 413 | `FILE_TOO_LARGE` | over 10 MB |
| 422 | `INVALID_CROP` | unknown crop value |
| 500 | `INTERNAL_ERROR` | unexpected server error (quote `request_id` when reporting) |
| 503 | `MODEL_NOT_READY` | model still loading / failed to load |

---

## GET /v1/classes
All classes grouped by crop (for crop pickers and lookups). Needs `X-API-Key`.

## GET /health
No key. `{"status": "ok", "model_version": "...", "num_classes": 40}` or 503 while starting.

---

## Integration notes
- **Cold start:** the free Space sleeps when idle; the first request can take 30+ s. Use a **60 s timeout**,
  retry once on timeout/503, and optionally call `/health` when the app opens to wake it.
- One photo per request, one leaf per photo, crop sent whenever the farmer selected it.
- Treatment advice is **not** part of this API — map `class_id` to advice in the backend.
- The model covers only the 7 crops above; photos of other plants or non-leaf images may still get a prediction.
