"""
Batch-test the disease model on a zip (or folder) of leaf photos.

The point of this script is to answer one question honestly: **when this model
commits to an answer, how often is it right?** Overall accuracy is not that
number, because the model is allowed to abstain (`status: "uncertain"`). A model
that abstains on everything scores 0% accuracy and is useless; one that answers
everything at 60% accuracy is worse than useless for a farmer, because it is
confidently wrong 4 times in 10. So the headline figures here are:

    coverage   -- share of photos the model was willing to answer
    precision  -- accuracy *among those answers*   <- the number that matters
    recall     -- coverage x precision, i.e. share of all photos answered right

Run it two ways:

    # local model files, no server, no API key -- start here
    venv/Scripts/python tools/test_zip.py --zip leaves.zip

    # the deployed Space, end to end over HTTP
    venv/Scripts/python tools/test_zip.py --zip leaves.zip \
        --url https://<user>-<space>.hf.space --key <api-key>

Add --send-crop to pass the true crop with each photo, the way the app will
when the farmer picks one. Compare the two runs: --send-crop should raise
precision, and if it does not, the crop-filter renormalisation described in
API_CONTRACT.md is doing more harm than good.

GROUND TRUTH comes from the path, so name things after what they are. Both of
these work, and folder-per-class is the least error-prone:

    wheat_yellow_rust/img_01.jpg          <- folder per class
    wheat_yellow_rust_01.jpg              <- class id in the filename
    Wheat___Yellow_Rust/img_01.jpg        <- separators and case are ignored

Photos whose class cannot be identified are still predicted, but are excluded
from every score and listed at the end as UNSCORED, so a badly named zip shows
up as a small sample rather than a silently wrong accuracy.

Outputs zip_test_results.csv and zip_test_results.json next to this script's
working directory.
"""

import argparse
import csv
import json
import re
import shutil
import sys
import tempfile
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff", ".heic", ".heif"}
MODULE_DIR = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------- ground truth

def normalise(text):
    """Lowercase and collapse every run of non-letters to a single underscore.

    'Wheat___Yellow Rust (1).jpg' and 'wheat_yellow_rust_1.jpg' must reduce to
    the same thing, otherwise ground truth depends on how the zip was authored.
    """
    return re.sub(r"[^a-z]+", "_", text.lower()).strip("_")


def initials(words):
    return "".join(word[0] for word in words if word)


def unique_codes(pairs):
    """{code: class_id}, dropping any code claimed by more than one class.

    An ambiguous code must not silently resolve to whichever class was seen
    first -- that would score real predictions against invented ground truth.
    Dropped codes simply fall through to the next matching strategy.
    """
    counts = Counter(code for code, _ in pairs)
    return {code: label for code, label in pairs if counts[code] == 1}


class Matcher:
    """Reads the true class out of a file path.

    Four strategies, most specific first:

      1. full class id anywhere in the path      wheat_yellow_rust/img.jpg
      2. whole-class code as a whole token       wyr_01.jpg
      3. crop folder + disease code as a token   wheat/yr_01.jpg
      4. crop name only, disease unknown         tomato/mystery.jpg

    Codes are the initials of each word, generated from labels.json rather than
    hard-coded, so they stay correct if the class list ever changes. Codes are
    matched as whole tokens, never as substrings: 'wb' (wheat_blast) is a
    substring of 'wbr' (wheat_brown_rust), so substring matching would mislabel
    every brown rust photo as blast.
    """

    def __init__(self, labels):
        self.labels = labels
        self.by_length = sorted(labels, key=len, reverse=True)
        self.crops = sorted({l.split("_", 1)[0] for l in labels}, key=len, reverse=True)

        # "wheat_yellow_rust" -> "wyr"
        self.class_codes = unique_codes([(initials(l.split("_")), l) for l in labels])

        # within a crop: "yellow_rust" -> "yr"
        self.disease_codes = {}
        for crop in self.crops:
            members = [l for l in labels if l.split("_", 1)[0] == crop]
            self.disease_codes[crop] = unique_codes(
                [(initials(l.split("_", 1)[1].split("_")), l) for l in members])

        self.ambiguous = sorted({initials(l.split("_")) for l in labels} - set(self.class_codes))

    def truth_for(self, rel_path):
        """(class_id, crop, how_it_matched); class_id and crop may be None."""
        key = normalise(str(rel_path))
        tokens = set(key.split("_"))

        for label in self.by_length:                       # 1
            if normalise(label) in key:
                return label, label.split("_", 1)[0], "class id"

        for token in tokens:                               # 2
            if token in self.class_codes:
                label = self.class_codes[token]
                return label, label.split("_", 1)[0], f"code '{token}'"

        for crop in self.crops:                            # 3
            if crop in key:
                for token in tokens:
                    if token in self.disease_codes[crop]:
                        label = self.disease_codes[crop][token]
                        return label, crop, f"{crop} + code '{token}'"
                return None, crop, "crop only"             # 4

        return None, None, None


# ---------------------------------------------------------------- backends

class LocalBackend:
    """Calls predict.py in-process. Tests the model, not the HTTP layer."""

    name = "local model files"

    def __init__(self, model_dir):
        sys.path.insert(0, str(MODULE_DIR))
        from predict import GreenGuardPredictor, PredictionError
        self.error_type = PredictionError
        self.predictor = GreenGuardPredictor(model_dir)
        self.version = self.predictor.version
        self.labels = self.predictor.labels

    def predict(self, data, crop=None):
        try:
            return self.predictor.predict(data, crop), None
        except self.error_type as exc:
            return None, f"{exc.code}: {exc.message}"


class HttpBackend:
    """Calls the deployed /v1/predict. Tests the whole service."""

    name = "deployed HTTP API"

    def __init__(self, url, key, timeout):
        import requests
        self.requests = requests
        self.url = url.rstrip("/")
        self.headers = {"X-API-Key": key} if key else {}
        self.timeout = timeout

        health = requests.get(f"{self.url}/health", timeout=timeout)
        if health.status_code != 200:
            raise SystemExit(f"/health returned {health.status_code}: {health.text[:200]}")
        self.version = health.json().get("model_version", "unknown")

        classes = requests.get(f"{self.url}/v1/classes", headers=self.headers, timeout=timeout)
        if classes.status_code != 200:
            raise SystemExit(f"/v1/classes returned {classes.status_code}: {classes.text[:200]}"
                             "\nA 401 here means --key is missing or wrong.")
        self.labels = [c["class_id"] for crop in classes.json()["crops"] for c in crop["classes"]]

    def predict(self, data, crop=None):
        response = self.requests.post(
            f"{self.url}/v1/predict",
            headers=self.headers,
            files={"image": ("leaf.jpg", data)},
            data={"crop": crop} if crop else None,
            timeout=self.timeout,
        )
        body = response.json()
        if response.status_code != 200:
            return None, f"HTTP {response.status_code} {body.get('error', {}).get('code', '?')}"
        return body, None


# ---------------------------------------------------------------- collect images

def gather(zip_path, folder):
    """Returns (list of (relative_path, absolute_path), tempdir to clean up)."""
    if zip_path:
        tmp = Path(tempfile.mkdtemp(prefix="ggtest_"))
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(tmp)
        root, cleanup = tmp, tmp
    else:
        root, cleanup = Path(folder), None

    files = []
    for path in sorted(root.rglob("*")):
        # __MACOSX holds AppleDouble stubs that look like images but are not.
        if path.is_file() and path.suffix.lower() in IMAGE_EXTS and "__MACOSX" not in path.parts:
            files.append((path.relative_to(root), path))
    return files, cleanup


# ---------------------------------------------------------------- reporting

def pct(numerator, denominator):
    return f"{100.0 * numerator / denominator:5.1f}%" if denominator else "    --"


def report(rows, labels):
    errors = [r for r in rows if r["error"]]
    # A rejected file is not an abstention -- the model never saw it. Counting it
    # as one would understate coverage and hide the real reason in the reasons list.
    scored = [r for r in rows if r["true_class"] and not r["error"]]
    unscored = [r for r in rows if not r["true_class"] and not r["error"]]
    answered = [r for r in scored if r["status"] == "ok"]
    correct = [r for r in answered if r["pred_class"] == r["true_class"]]

    print("\n" + "=" * 78)
    print("RESULTS")
    print("=" * 78)
    print(f"  images            {len(rows)}")
    print(f"  scored            {len(scored)}   (ground truth found in the path)")
    print(f"  unscored          {len(unscored)}   (excluded from every figure below)")
    print(f"  errors            {len(errors)}")

    if not scored:
        print("\n  No ground truth could be read from any path, so nothing can be scored.")
        print("  Rename the files or folders after their class id -- see the header of")
        print("  this script -- and run it again.")
        return

    print(f"\n  coverage          {pct(len(answered), len(scored))}"
          f"   ({len(answered)}/{len(scored)} answered rather than 'uncertain')")
    print(f"  precision         {pct(len(correct), len(answered))}"
          f"   ({len(correct)}/{len(answered)} of the answers given were right)   <-- the one that matters")
    print(f"  recall            {pct(len(correct), len(scored))}"
          f"   ({len(correct)}/{len(scored)} of all photos answered correctly)")

    top3 = [r for r in scored if r["true_class"] in r["top3_classes"]]
    crop_ok = [r for r in scored if r["true_crop"] and r["detected_crop"] == r["true_crop"]]
    print(f"\n  top-3 hit rate    {pct(len(top3), len(scored))}   (true class anywhere in top3)")
    print(f"  crop detection    {pct(len(crop_ok), len(scored))}   (detected_crop == true crop)")

    # The dangerous bucket: committed to an answer and got it wrong.
    wrong = [r for r in answered if r["pred_class"] != r["true_class"]]
    if wrong:
        print(f"\n  CONFIDENTLY WRONG {len(wrong)} photo(s) -- status 'ok' but the wrong class.")
        print("  These are the failures that reach a farmer as fact:")
        for r in sorted(wrong, key=lambda r: -r["confidence"])[:12]:
            print(f"    {r['confidence']:.2f}  {r['true_class']:32s} -> {r['pred_class']}")
        if len(wrong) > 12:
            print(f"    ... and {len(wrong) - 12} more, see the CSV")

    missed = [r for r in scored if r["status"] == "uncertain"]
    if missed:
        print(f"\n  abstained on {len(missed)} photo(s); most common reasons:")
        for reason, n in Counter(w for r in missed for w in (r["warnings"] or ["(low confidence)"])).most_common():
            print(f"    {n:4d}  {reason}")

    per_class = defaultdict(lambda: {"n": 0, "ok": 0, "right": 0})
    for r in scored:
        bucket = per_class[r["true_class"]]
        bucket["n"] += 1
        if r["status"] == "ok":
            bucket["ok"] += 1
            if r["pred_class"] == r["true_class"]:
                bucket["right"] += 1
    print(f"\n  {'class':34s}{'n':>4s}{'answered':>10s}{'right':>7s}{'precision':>11s}")
    print("  " + "-" * 64)
    for name in sorted(per_class, key=lambda k: (per_class[k]["right"] / max(per_class[k]["ok"], 1), -per_class[k]["n"])):
        b = per_class[name]
        print(f"  {name:34s}{b['n']:>4d}{b['ok']:>10d}{b['right']:>7d}{pct(b['right'], b['ok']):>11s}")

    if unscored:
        print("\n  UNSCORED (no class id recognised in the path):")
        for r in unscored[:10]:
            print(f"    {r['file'][:50]:52s} -> {r['pred_class'] or r['status']}")
        if len(unscored) > 10:
            print(f"    ... and {len(unscored) - 10} more")

    if errors:
        print("\n  ERRORS:")
        for r in errors[:10]:
            print(f"    {r['file'][:50]:52s} {r['error']}")

    n = len(scored)
    print(f"\n  Sample size is {n}. A percentage from {n} photos has a margin of roughly "
          f"+/-{100.0 / max(n ** 0.5, 1):.0f}")
    print("  points, so treat small differences between runs as noise.")


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    source = ap.add_mutually_exclusive_group(required=True)
    source.add_argument("--zip", help="zip file of test images")
    source.add_argument("--folder", help="folder of test images instead of a zip")
    ap.add_argument("--url", help="deployed base URL; omit to run the local model files")
    ap.add_argument("--key", help="X-API-Key for --url")
    ap.add_argument("--model-dir", default=str(MODULE_DIR / "model"), help="local model/ folder")
    ap.add_argument("--send-crop", action="store_true",
                    help="send the true crop with each photo, as the app does when the farmer picks one")
    ap.add_argument("--timeout", type=float, default=60.0, help="HTTP timeout (free Spaces cold-start slowly)")
    ap.add_argument("--limit", type=int, help="stop after N images, for a quick smoke test")
    ap.add_argument("--list-truth", action="store_true",
                    help="show how each filename decodes to a class, then exit without running the model")
    ap.add_argument("--out", default="zip_test_results", help="output basename")
    args = ap.parse_args()

    backend = HttpBackend(args.url, args.key, args.timeout) if args.url else LocalBackend(args.model_dir)
    matcher = Matcher(backend.labels)

    files, cleanup = gather(args.zip, args.folder)
    if args.limit:
        files = files[:args.limit]
    if not files:
        raise SystemExit("No images found. Supported extensions: " + ", ".join(sorted(IMAGE_EXTS)))

    if args.list_truth:
        # Check the decoding before trusting any score: ground truth read wrongly
        # produces a confident, completely meaningless accuracy figure.
        print(f"{'file':52s}{'true class':34s}matched by")
        print("-" * 104)
        unknown = 0
        for rel, _ in files:
            true_class, true_crop, how = matcher.truth_for(rel)
            unknown += not true_class
            if true_class:
                shown = true_class
            elif true_crop:
                shown = f"?? (crop: {true_crop})"
            else:
                shown = "??"
            print(f"{str(rel)[:50]:52s}{shown:34s}{how or '-'}")
        print(f"\n{len(files) - unknown}/{len(files)} resolved to a class.")
        print("\nCodes generated from labels.json (crop + disease initials):")
        for code, label in sorted(matcher.class_codes.items(), key=lambda kv: kv[1]):
            print(f"  {code:8s}{label}")
        if matcher.ambiguous:
            print(f"\nAmbiguous, ignored: {', '.join(matcher.ambiguous)}")
        if cleanup:
            shutil.rmtree(cleanup, ignore_errors=True)
        return

    print(f"backend    {backend.name}")
    print(f"model      {backend.version}  ({len(backend.labels)} classes)")
    print(f"images     {len(files)} from {args.zip or args.folder}")
    print(f"crop sent  {'yes (true crop)' if args.send_crop else 'no (model decides)'}")
    print()

    rows = []
    try:
        for i, (rel, abs_path) in enumerate(files, 1):
            true_class, true_crop, _ = matcher.truth_for(rel)
            body, error = backend.predict(abs_path.read_bytes(),
                                          true_crop if (args.send_crop and true_crop) else None)

            if error:
                row = {"file": str(rel), "true_class": true_class, "true_crop": true_crop,
                       "status": "error", "pred_class": None, "confidence": 0.0,
                       "detected_crop": None, "top3_classes": [], "warnings": [], "error": error}
            else:
                prediction = body.get("prediction") or {}
                row = {"file": str(rel), "true_class": true_class, "true_crop": true_crop,
                       "status": body.get("status"), "pred_class": prediction.get("class_id"),
                       "confidence": prediction.get("confidence") or 0.0,
                       "detected_crop": body.get("detected_crop"),
                       "top3_classes": [t["class_id"] for t in body.get("top3", [])],
                       "warnings": body.get("warnings") or [], "error": None}
            rows.append(row)

            if row["error"]:
                mark = "ERR"
            elif not true_class:
                mark = "?  "
            elif row["pred_class"] == true_class:
                mark = "OK "
            elif row["status"] == "uncertain":
                mark = "-- "
            else:
                mark = "BAD"
            print(f"[{i:4d}/{len(files)}] {mark} {str(rel)[:44]:46s}"
                  f"{(row['pred_class'] or row['status'] or '')[:30]:32s}{row['confidence']:.2f}")
    finally:
        if cleanup:
            shutil.rmtree(cleanup, ignore_errors=True)

    report(rows, backend.labels)

    Path(f"{args.out}.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    with open(f"{args.out}.csv", "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["file", "true_class", "true_crop", "status", "pred_class",
                         "confidence", "detected_crop", "top3", "warnings", "error"])
        for r in rows:
            writer.writerow([r["file"], r["true_class"], r["true_crop"], r["status"],
                             r["pred_class"], r["confidence"], r["detected_crop"],
                             " ".join(r["top3_classes"]), " ".join(r["warnings"]), r["error"]])
    print(f"\nwrote {args.out}.csv and {args.out}.json")


if __name__ == "__main__":
    main()
