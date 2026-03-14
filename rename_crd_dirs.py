import os
import re
import time
import random
from pathlib import Path
import requests

EIA_BASE = "https://api.eia.gov/v2"
API_KEY = os.environ.get("EIA_API_KEY")
if not API_KEY:
    raise RuntimeError("EIA_API_KEY manquante. Fais: export EIA_API_KEY='...'")

BASE = Path("exports/petroleum/crd")

def slugify(s: str) -> str:
    s = (s or "").strip().replace("&", "and")
    s = re.sub(r"[^\w\s.-]+", "", s)
    s = re.sub(r"\s+", "_", s)
    return s[:140] if s else "UNKNOWN"

def safe_get_json(url: str, params: dict, retries: int = 10, timeout: int = 60) -> dict:
    headers = {"User-Agent": "ETL-Rename/1.0", "Accept": "application/json"}
    base_sleep = 0.7
    last = None
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, timeout=timeout, headers=headers)
            last = r.text[:250]
        except Exception as e:
            last = str(e)
            r = None

        if r is None or r.status_code in (429, 500, 502, 503, 504):
            time.sleep(base_sleep * (2 ** attempt) + random.random() * 0.2)
            continue

        try:
            payload = r.json()
        except Exception:
            time.sleep(base_sleep * (2 ** attempt) + random.random() * 0.2)
            continue

        if isinstance(payload, str) and "Something unexpected happened" in payload:
            time.sleep(base_sleep * (2 ** attempt) + random.random() * 0.2)
            continue

        if isinstance(payload, dict) and "error" in payload:
            raise RuntimeError(f"EIA error: {payload['error']}")

        return payload

    raise RuntimeError(f"EIA API failed after retries. Last response: {last}")

def parent_children(parent_route: str) -> dict:
    url = f"{EIA_BASE}/{parent_route.strip('/')}/"
    md = safe_get_json(url, {"api_key": API_KEY})
    routes = (md.get("response", {}) or {}).get("routes", []) or []
    return {x["id"]: (x.get("name") or x["id"]) for x in routes if isinstance(x, dict) and x.get("id")}

def find_existing_dir(base: Path, leaf_id: str) -> Path | None:
    """
    Trouve le dossier réel pour leaf_id:
    - base/leaf_id
    - base/{leaf_id}__{leaf_id}
    - base/{leaf_id}__*
    """
    direct = base / leaf_id
    if direct.exists():
        return direct

    exact = base / f"{leaf_id}__{leaf_id}"
    if exact.exists():
        return exact

    matches = sorted(base.glob(f"{leaf_id}__*"))
    if matches:
        return matches[0]

    return None

def main():
    parent_route = "petroleum/crd"
    child_map = parent_children(parent_route)
    ordered_ids = sorted(child_map.keys())

    print("[INFO] Found children:", ordered_ids)

    for idx, leaf_id in enumerate(ordered_ids, start=1):
        old_dir = find_existing_dir(BASE, leaf_id)
        if old_dir is None:
            print("[SKIP missing]", BASE / leaf_id, "(also tried api__api / api__*)")
            continue

        new_dir = BASE / f"{idx:02d}__{slugify(child_map[leaf_id])}"

        if new_dir.exists():
            print("[SKIP exists]", new_dir)
            continue

        old_dir.rename(new_dir)
        print("RENAMED:", old_dir, "->", new_dir)

    print("[DONE] Rename finished.")

if __name__ == "__main__":
    main()
