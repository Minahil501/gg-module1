"""
Contract + edge-case tests for the GreenGuard API.
Run from the Space folder:   pip install pytest httpx && pytest -q
Needs the real model files in ./model (or set MODEL_DIR).
"""
import io
import os
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

MODEL_DIR = os.getenv("MODEL_DIR", str(Path(__file__).resolve().parents[1] / "model"))
if not (Path(MODEL_DIR) / "model.onnx").exists():
    pytest.skip(f"no model.onnx in {MODEL_DIR}", allow_module_level=True)

os.environ["MODEL_DIR"] = MODEL_DIR
os.environ["GREENGUARD_API_KEY"] = "test-key"

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient  # noqa: E402
import app as app_module  # noqa: E402

KEY = {"X-API-Key": "test-key"}


@pytest.fixture(scope="module")
def client():
    app_module.API_KEY = "test-key"
    with TestClient(app_module.app) as c:
        yield c


def leaf(w=640, h=480, mode="RGB", fmt="JPEG", seed=0, **save):
    rng = np.random.default_rng(seed)
    a = np.zeros((h, w, 3), np.uint8)
    a[..., 1] = 140 + rng.integers(0, 60, (h, w))       # textured green
    a[..., 0] = rng.integers(20, 80, (h, w))
    im = Image.fromarray(a).convert(mode)
    buf = io.BytesIO()
    im.save(buf, fmt, **save)
    return buf.getvalue()


def post(client, data, crop=None, headers=KEY, name="leaf.jpg", farm_id=None):
    files = {"image": (name, data, "application/octet-stream")} if data is not None else None
    form = {k: v for k, v in (("crop", crop), ("farm_id", farm_id)) if v is not None} or None
    return client.post("/v1/predict", files=files, data=form, headers=headers)


def check_success_shape(body):
    assert body["status"] in ("ok", "uncertain")
    for k in ["prediction", "top3", "crop_source", "detected_crop", "warnings", "message",
              "model_version", "inference_ms", "request_id", "farm_id", "timestamp"]:
        assert k in body, k
    assert len(body["top3"]) == 3
    assert body["top3"][0]["confidence"] >= body["top3"][1]["confidence"] >= body["top3"][2]["confidence"]
    if body["status"] == "ok":
        p = body["prediction"]
        assert set(p) >= {"class_id", "crop", "disease", "display_name", "is_healthy", "confidence"}
    else:
        assert body["prediction"] is None and body["message"]


# ---------- service ----------
def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_classes(client):
    r = client.get("/v1/classes", headers=KEY)
    body = r.json()
    assert r.status_code == 200
    assert sum(len(c["classes"]) for c in body["crops"]) == body["num_classes"]


def test_auth(client):
    assert post(client, leaf(), headers={}).status_code == 401
    assert post(client, leaf(), headers={"X-API-Key": "wrong"}).json()["error"]["code"] == "UNAUTHORIZED"


# ---------- normal predictions ----------
def test_predict_jpeg(client):
    r = post(client, leaf())
    assert r.status_code == 200
    check_success_shape(r.json())
    assert r.json()["crop_source"] == "model"


def test_predict_with_crop(client):
    body = post(client, leaf(), crop="wheat").json()
    check_success_shape(body)
    assert body["crop_source"] == "user"
    if "CROP_MISMATCH" not in body["warnings"]:
        assert all(t["crop"] == "wheat" for t in body["top3"])
        if body["prediction"]:
            assert body["prediction"]["crop"] == "wheat"


@pytest.mark.parametrize("crop", ["Wheat ", "WHEAT", "corn", "Sugar cane", "paddy", ""])
def test_crop_normalisation(client, crop):
    assert post(client, leaf(), crop=crop).status_code == 200


def test_invalid_crop(client):
    r = post(client, leaf(), crop="banana")
    assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_CROP"


# ---------- file edge cases ----------
def test_missing_image(client):
    r = post(client, None)
    assert r.status_code == 400 and r.json()["error"]["code"] == "MISSING_IMAGE"


def test_empty_file(client):
    assert post(client, b"").json()["error"]["code"] in ("MISSING_IMAGE", "INVALID_IMAGE")


def test_not_an_image(client):
    r = post(client, b"%PDF-1.4 not really an image" * 50, name="fake.jpg")
    assert r.status_code == 400 and r.json()["error"]["code"] == "INVALID_IMAGE"


def test_truncated_jpeg(client):
    r = post(client, leaf()[:2000])
    assert r.status_code == 400 and r.json()["error"]["code"] == "INVALID_IMAGE"


def test_too_small(client):
    r = post(client, leaf(80, 60))
    assert r.status_code == 400 and r.json()["error"]["code"] == "IMAGE_TOO_SMALL"


def test_too_large(client):
    r = post(client, b"\xff" * (10 * 1024 * 1024 + 200_000))
    assert r.status_code == 413 and r.json()["error"]["code"] == "FILE_TOO_LARGE"


@pytest.mark.parametrize("mode,fmt", [("RGBA", "PNG"), ("L", "PNG"), ("CMYK", "JPEG"), ("P", "GIF"),
                                      ("RGB", "WEBP"), ("RGB", "BMP")])
def test_formats_and_modes(client, mode, fmt):
    r = post(client, leaf(mode=mode, fmt=fmt), name=f"leaf.{fmt.lower()}")
    assert r.status_code == 200, r.text
    check_success_shape(r.json())


def test_heic(client):
    pytest.importorskip("pillow_heif")
    buf = io.BytesIO()
    try:
        Image.open(io.BytesIO(leaf())).save(buf, "HEIF")
    except Exception:
        pytest.skip("HEIC encoder not available here")
    assert post(client, buf.getvalue(), name="leaf.heic").status_code == 200


def test_exif_rotation_same_result(client):
    im = Image.open(io.BytesIO(leaf(640, 480)))
    rotated = im.rotate(90, expand=True)               # stored sideways...
    exif = Image.Exif(); exif[0x0112] = 8              # ...with "rotate back" EXIF tag
    buf = io.BytesIO(); rotated.save(buf, "JPEG", exif=exif.tobytes(), quality=95)
    a = post(client, leaf(640, 480)).json()["top3"][0]["class_id"]
    b = post(client, buf.getvalue()).json()["top3"][0]["class_id"]
    assert a == b


# ---------- quality warnings ----------
def test_dark_image_warns(client):
    dark = (np.ones((400, 400, 3)) * 10).astype(np.uint8)
    buf = io.BytesIO(); Image.fromarray(dark).save(buf, "JPEG")
    body = post(client, buf.getvalue()).json()
    assert "LOW_LIGHT" in body["warnings"]


def test_blurry_image_warns(client):
    flat = np.zeros((400, 400, 3), np.uint8); flat[..., 1] = 120
    buf = io.BytesIO(); Image.fromarray(flat).save(buf, "JPEG")
    assert "BLURRY_IMAGE" in post(client, buf.getvalue()).json()["warnings"]


# ---------- farm_id and timestamp ----------
def test_farm_id_echoed(client):
    body = post(client, leaf(), farm_id="farm_001").json()
    assert body["farm_id"] == "farm_001"


def test_farm_id_null_when_not_sent(client):
    # Always present, never invented: the backend owns this value.
    body = post(client, leaf()).json()
    assert body["farm_id"] is None


def test_farm_id_echoed_on_error(client):
    # A failed prediction must still be traceable to the farm that caused it.
    body = post(client, b"not an image", farm_id="farm_009").json()
    assert body["status"] == "error" and body["farm_id"] == "farm_009"


def test_farm_id_length_capped(client):
    r = post(client, leaf(), farm_id="x" * 129)
    assert r.status_code == 400 and r.json()["error"]["code"] == "INVALID_REQUEST"


def test_timestamp_format(client):
    from datetime import datetime, timezone
    ts = post(client, leaf()).json()["timestamp"]
    parsed = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    # UTC, not Pakistan local time, and roughly now.
    assert abs((datetime.now(timezone.utc) - parsed).total_seconds()) < 120
