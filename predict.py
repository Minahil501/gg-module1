"""
GreenGuard — Module 1 inference: leaf image -> disease prediction.

Pipeline for every uploaded photo
  Stage 1  validate   : size limit, safe decode, pixel limit, minimum size
  Stage 2  normalise  : EXIF rotation, first frame, RGB conversion, downscale like the training data
  Stage 3  quality    : sharpness and brightness checks (warnings only)
  Stage 4  model input: resize shorter side, centre crop, scale, normalise, NCHW  (read from config.json)
  Then     postprocess: optional crop filter + mismatch check, confidence threshold, response JSON

Only needs numpy, Pillow and onnxruntime (pillow-heif optional, for iPhone HEIC photos).
"""
import io
import json
import os
import time
from pathlib import Path

import numpy as np
import onnxruntime as ort
from PIL import Image, ImageOps

try:  # iPhone photos (HEIC); optional
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:
    pass

MAX_FILE_BYTES = 10 * 1024 * 1024      # 10 MB
MAX_PIXELS = 50_000_000                # blocks "image bombs"
MIN_SIDE = 100                         # px
Image.MAX_IMAGE_PIXELS = MAX_PIXELS

CROP_SYNONYMS = {"corn": "maize", "paddy": "rice", "sugar_cane": "sugarcane", "cane": "sugarcane"}
DISPLAY_OVERRIDES = {"leaf_redding": "Leaf Reddening", "healthy": "Healthy"}

UNCERTAIN_MESSAGE = "Image unclear. Please retake the photo in good light, close to one leaf."
QUALITY_HINTS = {
    "BLURRY_IMAGE": "The photo looks blurry — hold the phone steady and tap to focus on the leaf.",
    "LOW_LIGHT": "The photo is too dark — take it in daylight.",
    "OVEREXPOSED": "The photo is too bright — avoid direct sunlight on the leaf or the camera.",
}


class PredictionError(Exception):
    """Error with an API error code and HTTP status."""
    def __init__(self, code, status, message):
        super().__init__(message)
        self.code, self.status, self.message = code, status, message


class GreenGuardPredictor:
    def __init__(self, model_dir="model", threads=None):
        model_dir = Path(model_dir)
        self.cfg = json.loads((model_dir / "config.json").read_text())
        self.labels = json.loads((model_dir / "labels.json").read_text())
        pre = self.cfg["preprocessing"]

        # Stage 4 settings (must match training/evaluation)
        self.resize = int(pre["resize_shorter_side_to"])
        self.crop_size = int(pre["center_crop"])
        self.mean = np.array(pre["mean"], dtype=np.float32)
        self.std = np.array(pre["std"], dtype=np.float32)
        self.pre_downscale = int(self.cfg.get("pre_downscale_max_side", 384))

        # Decision thresholds (calibrated in the Phase 3 notebook)
        self.threshold = float(self.cfg["confidence_threshold"])
        self.threshold_crop = float(self.cfg.get("crop_filtered_threshold", self.threshold))
        self.mismatch_threshold = float(self.cfg.get("crop_mismatch_threshold", 0.80))
        q = self.cfg.get("quality", {})
        self.min_sharpness = float(q.get("min_sharpness", 20.0))
        self.min_brightness = float(q.get("min_brightness", 35.0))
        self.max_brightness = float(q.get("max_brightness", 230.0))

        # Classes the model can output but that must never be reported. Black point
        # affects the grain and fusarium foot rot the stem base, so neither is visible
        # on a leaf: the model could only ever be guessing, and those guesses were
        # absorbing photos belonging to the seven wheat diseases that ARE leaf-visible
        # (measured: wheat top-1 33.3% -> 41.7% once they are suppressed).
        # Suppressing costs nothing at serving time and needs no retraining.
        suppressed = set(self.cfg.get("suppressed_classes", []))
        unknown = suppressed - set(self.labels)
        if unknown:
            raise ValueError(f"suppressed_classes names unknown labels: {sorted(unknown)}")
        self.suppressed = np.array([i for i, l in enumerate(self.labels) if l in suppressed], dtype=int)
        self.num_reportable = len(self.labels) - len(self.suppressed)

        # Class metadata
        self.class_crop = [l.split("_", 1)[0] for l in self.labels]
        self.class_disease = [l.split("_", 1)[1] for l in self.labels]
        self.crops = sorted(set(self.class_crop))
        self.crop_idx = {c: np.array([i for i, cc in enumerate(self.class_crop) if cc == c]) for c in self.crops}
        self.version = f"{self.cfg.get('model', 'model')}-{self.cfg.get('version', '1.0')}"

        # ONNX Runtime session (thread-safe, loaded once)
        so = ort.SessionOptions()
        so.intra_op_num_threads = int(threads or os.getenv("ORT_THREADS", 2))
        self.session = ort.InferenceSession(str(model_dir / "model.onnx"), so,
                                            providers=["CPUExecutionProvider"])
        self.input_name = self.session.get_inputs()[0].name
        n_out = self.session.get_outputs()[0].shape[-1]
        if isinstance(n_out, int) and n_out != len(self.labels):
            raise ValueError(f"model has {n_out} outputs but labels.json has {len(self.labels)}")

    # ---------- naming ----------
    @staticmethod
    def display_name(disease):
        return DISPLAY_OVERRIDES.get(disease, disease.replace("_", " ").title())

    def class_info(self, i, confidence=None):
        d = {"class_id": self.labels[i], "crop": self.class_crop[i], "disease": self.class_disease[i],
             "display_name": self.display_name(self.class_disease[i]),
             "is_healthy": self.class_disease[i] == "healthy"}
        if confidence is not None:
            d["confidence"] = round(float(confidence), 4)
        return d

    def classes(self):
        """Only classes the service can actually return.

        Suppressed ones are left out deliberately: listing a disease that can never
        come back would have the frontend build a picker, and treatment advice, for
        an answer no farmer will ever receive.
        """
        hidden = set(self.suppressed.tolist())
        listed = {c: [i for i in self.crop_idx[c] if i not in hidden] for c in self.crops}
        return {"model_version": self.version,
                "num_classes": self.num_reportable,
                "crops": [{"id": c, "name": c.title(),
                           "classes": [self.class_info(i) for i in listed[c]]}
                          for c in self.crops if listed[c]]}

    def normalize_crop(self, crop):
        if crop is None:
            return None
        c = str(crop).strip().lower().replace(" ", "_").replace("-", "_")
        if not c:
            return None
        c = CROP_SYNONYMS.get(c, c)
        if c not in self.crop_idx:
            raise PredictionError("INVALID_CROP", 422,
                                  f"Unknown crop '{crop}'. Valid crops: {', '.join(self.crops)}.")
        return c

    # ---------- Stage 1 + 2: validate and normalise ----------
    def load_image(self, data: bytes) -> Image.Image:
        if not data:
            raise PredictionError("MISSING_IMAGE", 400, "No image was uploaded.")
        if len(data) > MAX_FILE_BYTES:
            raise PredictionError("FILE_TOO_LARGE", 413, "Image is larger than 10 MB.")
        try:
            with Image.open(io.BytesIO(data)) as probe:
                probe.verify()                                   # structural check
            im = Image.open(io.BytesIO(data))
            if im.width * im.height > MAX_PIXELS:
                raise PredictionError("INVALID_IMAGE", 400, "Image dimensions are too large.")
            if getattr(im, "is_animated", False):
                im.seek(0)                                       # first frame of GIF/WEBP animations
            im = ImageOps.exif_transpose(im)                     # phone rotation
            im.load()
        except PredictionError:
            raise
        except Exception:
            raise PredictionError("INVALID_IMAGE", 400, "File is not a valid image.")
        if min(im.size) < MIN_SIDE:
            raise PredictionError("IMAGE_TOO_SMALL", 400,
                                  f"Image is too small ({im.width}x{im.height}); minimum is {MIN_SIDE}px per side.")
        im = self.to_rgb(im)
        # Training images were stored at <= 384 px (LANCZOS); do the same so the model sees the same scale
        im.thumbnail((self.pre_downscale, self.pre_downscale), Image.LANCZOS)
        return im

    @staticmethod
    def to_rgb(im):
        if im.mode in ("I;16", "I;16B", "I;16L", "I", "F"):     # 16-bit / float images
            a = np.asarray(im, dtype=np.float32)
            a = (a - a.min()) / max(float(a.max() - a.min()), 1e-6) * 255
            return Image.fromarray(a.astype(np.uint8)).convert("RGB")
        if im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info):
            im = im.convert("RGBA")
            bg = Image.new("RGB", im.size, (255, 255, 255))      # transparent -> white
            bg.paste(im, mask=im.getchannel("A"))
            return bg
        return im.convert("RGB")

    # ---------- Stage 3: quality ----------
    @staticmethod
    def quality_scores(im):
        g = np.asarray(im.convert("L"), dtype=np.float32)
        lap = (g[:-2, 1:-1] + g[2:, 1:-1] + g[1:-1, :-2] + g[1:-1, 2:] - 4 * g[1:-1, 1:-1])
        return {"sharpness": float(lap.var()), "brightness": float(g.mean())}

    def quality_warnings(self, scores):
        w = []
        if scores["sharpness"] < self.min_sharpness:
            w.append("BLURRY_IMAGE")
        if scores["brightness"] < self.min_brightness:
            w.append("LOW_LIGHT")
        elif scores["brightness"] > self.max_brightness:
            w.append("OVEREXPOSED")
        return w

    # ---------- Stage 4: model input (identical to torchvision Resize + CenterCrop + ToTensor + Normalize) ----------
    def to_tensor(self, im):
        w, h = im.size
        s = self.resize
        if w <= h:
            nw, nh = s, int(s * h / w)
        else:
            nw, nh = int(s * w / h), s
        im = im.resize((nw, nh), Image.BILINEAR)
        c = self.crop_size
        left, top = int(round((nw - c) / 2.0)), int(round((nh - c) / 2.0))
        im = im.crop((left, top, left + c, top + c))
        x = np.asarray(im, dtype=np.float32) / 255.0
        x = (x - self.mean) / self.std
        return x.transpose(2, 0, 1)[None].astype(np.float32)   # (1, 3, H, W)

    def probs_from_image(self, im):
        probs = self.session.run(None, {self.input_name: self.to_tensor(im)})[0][0].astype(np.float64)
        if len(self.suppressed):
            # Zero then renormalise, so what is left is still a probability
            # distribution and crop_mass keeps its meaning downstream.
            probs[self.suppressed] = 0.0
            probs /= max(probs.sum(), 1e-12)
        return probs

    # ---------- full prediction ----------
    def predict(self, data: bytes, crop=None) -> dict:
        t0 = time.perf_counter()
        crop = self.normalize_crop(crop)
        im = self.load_image(data)
        warnings = self.quality_warnings(self.quality_scores(im))
        probs = self.probs_from_image(im)

        crop_mass = {c: float(probs[idx].sum()) for c, idx in self.crop_idx.items()}
        detected = max(crop_mass, key=crop_mass.get)
        top3_all = [self.class_info(i, probs[i]) for i in np.argsort(-probs)[:3]]

        result = {"status": "ok", "prediction": None, "top3": top3_all,
                  "crop_source": "user" if crop else "model", "detected_crop": detected,
                  "warnings": warnings, "message": None, "model_version": self.version}

        if crop and detected != crop and crop_mass[detected] >= self.mismatch_threshold:
            result["status"] = "uncertain"
            result["warnings"] = warnings + ["CROP_MISMATCH"]
            result["message"] = (f"This looks like a {detected} leaf, not {crop}. "
                                 f"Please check the selected crop or retake the photo.")
        else:
            if crop:
                idx = self.crop_idx[crop]
                p = np.zeros_like(probs)
                p[idx] = probs[idx] / max(probs[idx].sum(), 1e-12)
                threshold = self.threshold_crop
                result["top3"] = [self.class_info(i, p[i]) for i in idx[np.argsort(-p[idx])][:3]]
            else:
                p, threshold = probs, self.threshold
            best = int(np.argmax(p))
            if p[best] >= threshold:
                result["prediction"] = self.class_info(best, p[best])
            else:
                result["status"] = "uncertain"
                hints = [QUALITY_HINTS[w] for w in warnings if w in QUALITY_HINTS]
                result["message"] = " ".join([UNCERTAIN_MESSAGE] + hints)

        result["inference_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        return result
