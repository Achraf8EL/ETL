import os, re, json, requests
from pathlib import Path

EIA_BASE = "https://api.eia.gov/v2"
API_KEY = os.environ.get("EIA_API_KEY")  # ou mets ta clé ici si tu veux

EXPORTS = Path("exports")

def slug(s: str) -> str:
    s = (s or "").strip().replace("&", "and")
    s = re.sub(r"[^\w\s.-]+", "", s)
    s = re.sub(r"\s+", "_", s)
    return s[:140] if s else "UNKNOWN"

def get_name(route: str) -> str:
    url = f"{EIA_BASE}/{route.strip('/')}/"
    r = requests.get(url, params={"api_key": API_KEY}, timeout=60)
    r.raise_for_status()
    j = r.json()
    return (j.get("response", {}) or {}).get("name") or route.split("/")[-1]

routes = [
    "petroleum/crd/api","petroleum/crd/cplc","petroleum/crd/crpdn","petroleum/crd/drill",
    "petroleum/crd/gom","petroleum/crd/nprod","petroleum/crd/pres","petroleum/crd/seis",
    "petroleum/crd/wellcost","petroleum/crd/welldep","petroleum/crd/wellend","petroleum/crd/wellfoot",
]

for route in routes:
    old = EXPORTS / route
    if not old.exists():
        continue
    name = get_name(route)
    leaf = route.split("/")[-1]
    parent = old.parent
    new = parent / f"{leaf}__{slug(name)}"
    if new.exists():
        print("SKIP already exists:", new)
        continue
    old.rename(new)
    print("RENAMED:", old, "->", new)
