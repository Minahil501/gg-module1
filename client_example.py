"""
Example client for the backend team.
    pip install requests
    python client_example.py leaf.jpg wheat
"""
import sys
import time

import requests

BASE_URL = "https://<hf-username>-<space-name>.hf.space"   # change this
API_KEY = "<your-api-key>"                                  # change this
TIMEOUT = 60                                                # free Space may need ~30 s to wake up


def predict(image_path, crop=None, retries=1):
    for attempt in range(retries + 1):
        try:
            with open(image_path, "rb") as f:
                r = requests.post(f"{BASE_URL}/v1/predict",
                                  headers={"X-API-Key": API_KEY},
                                  files={"image": f},
                                  data={"crop": crop} if crop else None,
                                  timeout=TIMEOUT)
            if r.status_code == 503 and attempt < retries:   # model still loading
                time.sleep(5)
                continue
            return r.status_code, r.json()
        except requests.Timeout:
            if attempt == retries:
                raise
    return r.status_code, r.json()


if __name__ == "__main__":
    status, body = predict(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
    print(status)
    if body.get("status") == "ok":
        p = body["prediction"]
        print(f"{p['crop']}: {p['display_name']} ({p['confidence']:.0%})  warnings={body['warnings']}")
    elif body.get("status") == "uncertain":
        print("Uncertain:", body["message"])
        print("Possibly:", ", ".join(f"{t['display_name']} ({t['confidence']:.0%})" for t in body["top3"]))
    else:
        print("Error:", body["error"])
