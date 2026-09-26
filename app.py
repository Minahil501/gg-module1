"""
GreenGuard Disease API (Hugging Face Space, FastAPI).

Endpoints
  GET  /health        — liveness + model version (no key needed; use it to wake the Space)
  GET  /v1/classes    — all classes grouped by crop
  POST /v1/predict    — multipart form: image (file, required), crop + farm_id (text, optional)

Auth: header X-API-Key must equal the GREENGUARD_API_KEY secret (auth is off if the secret is not set).
"""
import logging
import os
import secrets
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, File, Form, Header, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from predict import MAX_FILE_BYTES, GreenGuardPredictor, PredictionError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("greenguard")

API_KEY = os.getenv("GREENGUARD_API_KEY")
MODEL_DIR = os.getenv("MODEL_DIR", "model")
state = {"predictor": None, "load_error": None}


@asynccontextmanager
async def lifespan(app):
    try:
        state["predictor"] = GreenGuardPredictor(MODEL_DIR)
        log.info("Model loaded: %s (%d classes)", state["predictor"].version, len(state["predictor"].labels))
    except Exception as e:  # keep the server up so /health can report the problem
        state["load_error"] = str(e)
        log.exception("Model failed to load")
    if not API_KEY:
        log.warning("GREENGUARD_API_KEY is not set — API key check is DISABLED")
    yield


app = FastAPI(title="GreenGuard Disease API", version="1.0", lifespan=lifespan)


def new_id():
    return uuid.uuid4().hex[:12]


def utc_now():
    """Second-precision UTC, the format REST_API_SPEC.md Section 9 shows.

    Always UTC, never Pakistan local time: the backend stores one timezone and
    renders whatever the farmer should see. A mix of zones in one column is a
    bug that surfaces months later.
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def error(status, code, message, request_id=None, farm_id=None):
    body = {"status": "error", "error": {"code": code, "message": message},
            "request_id": request_id or new_id()}
    if farm_id is not None:
        # Echoed when the form was parsed, so a failure can be traced to a farm.
        # Absent on 401 and 413, which are decided before the body is read --
        # request_id is the correlation key that is always present.
        body["farm_id"] = farm_id
    return JSONResponse(status_code=status, content=body)


def auth_error(x_api_key, request_id):
    if API_KEY and not (x_api_key and secrets.compare_digest(x_api_key, API_KEY)):
        return error(401, "UNAUTHORIZED", "Missing or invalid API key.", request_id)
    return None


def not_ready(request_id):
    if state["predictor"] is None:
        return error(503, "MODEL_NOT_READY", "Model is not loaded yet. Try again shortly.", request_id)
    return None


@app.middleware("http")
async def reject_large_uploads(request: Request, call_next):
    # Reject oversized uploads from the Content-Length header before reading the body
    size = request.headers.get("content-length")
    if request.url.path == "/v1/predict" and size and size.isdigit() and int(size) > MAX_FILE_BYTES + 64 * 1024:
        return error(413, "FILE_TOO_LARGE", "Image is larger than 10 MB.")
    return await call_next(request)


@app.exception_handler(RequestValidationError)
async def validation_handler(request, exc):
    return error(400, "INVALID_REQUEST", "Request is not in the expected format (multipart form with 'image').")


@app.exception_handler(Exception)
async def unhandled_handler(request, exc):
    rid = new_id()
    log.exception("Unhandled error %s", rid)
    return error(500, "INTERNAL_ERROR", "Something went wrong. Please try again.", rid)


@app.get("/")
def root():
    return {"service": "GreenGuard Disease API", "docs": "/docs", "health": "/health"}


@app.get("/health")
def health():
    p = state["predictor"]
    if p is None:
        return error(503, "MODEL_NOT_READY", f"Model not loaded: {state['load_error'] or 'starting'}")
    return {"status": "ok", "model_version": p.version, "num_classes": p.num_reportable}


@app.get("/v1/classes")
def classes(x_api_key: Optional[str] = Header(None)):
    rid = new_id()
    fail = auth_error(x_api_key, rid) or not_ready(rid)
    if fail:
        return fail
    return {**state["predictor"].classes(), "request_id": rid}


@app.post("/v1/predict")
def predict(image: Optional[UploadFile] = File(None),
            crop: Optional[str] = Form(None),
            farm_id: Optional[str] = Form(None),
            x_api_key: Optional[str] = Header(None)):
    # sync function: FastAPI runs it in a thread pool, so the model never blocks the server loop
    rid = new_id()
    fail = auth_error(x_api_key, rid) or not_ready(rid)
    if fail:
        return fail
    # farm_id is passed straight back out, so bound it rather than echoing an
    # arbitrary payload into the backend's logs and database.
    if farm_id is not None and len(farm_id) > 128:
        return error(400, "INVALID_REQUEST", "farm_id must be 128 characters or fewer.", rid)
    if image is None:
        return error(400, "MISSING_IMAGE", "No image was uploaded (form field 'image').", rid, farm_id)
    data = image.file.read(MAX_FILE_BYTES + 1)
    try:
        result = state["predictor"].predict(data, crop)
    except PredictionError as e:
        return error(e.status, e.code, e.message, rid, farm_id)
    # The backend owns both of these; we echo rather than invent. timestamp is when
    # the prediction completed, which is what belongs against a stored result.
    result["farm_id"] = farm_id
    result["timestamp"] = utc_now()
    result["request_id"] = rid
    log.info("%s farm=%s %s crop=%s -> %s %s (%.0f ms)", rid, farm_id, image.filename, crop,
             result["status"], (result["prediction"] or {}).get("class_id"), result["inference_ms"])
    return result
