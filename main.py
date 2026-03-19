
import json
from datetime import datetime

import os
import io
import re
import time
import random
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Iterable

import requests
import pandas as pd
from dotenv import load_dotenv

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse, StreamingResponse

from collections import deque  

load_dotenv()

EIA_API_KEY = os.getenv("EIA_API_KEY")
if not EIA_API_KEY:
    raise RuntimeError("EIA_API_KEY manquante. Ajoutez-la dans un fichier .env (EIA_API_KEY=...)")

EIA_BASE = "https://api.eia.gov/v2"

EXPORT_BASE_DIR = Path("exports")
EXPORT_BASE_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="EIA Exporter", version="9.2.0")  

_METADATA_CACHE: Dict[str, dict] = {}
_CHILDREN_MAP_CACHE: Dict[str, Dict[str, str]] = {}

"""
    Normalise les noms des fichiers et limite leur nombre de caractères à 180.
"""
def safe_filename(s: str) -> str:
    s = str(s).replace("/", "_")
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", s)
    return s[:180]

"""
    Normalise les noms de dossiers et les limite à 140 caractères.
"""
def slugify_folder(s: str) -> str:
    s = (s or "").strip()
    s = s.replace("&", "and")
    s = re.sub(r"[^\w\s.-]+", "", s)
    s = re.sub(r"\s+", "_", s)
    return s[:140] if s else "UNKNOWN"

"""
    Permet de forcément renvoyer une valeur valide ou nulle afin de faciliter les traitements en aval.
"""
def parse_int(x) -> Optional[int]:
    try:
        return int(x)
    except Exception:
        return None

"""
    Retourne l'heure actuelle au format ISO.
"""
def now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

"""
    Convertit une liste de dictionnaires en bytes au format CSV.
"""
def to_csv_bytes(rows: List[Dict]) -> bytes:
    df = pd.DataFrame(rows)
    buff = io.StringIO()
    df.to_csv(buff, index=False)
    return buff.getvalue().encode("utf-8")

"""
    Génère un fichier CSV à l'endroit voulu
"""
def write_csv(path: Path, rows: List[Dict]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(to_csv_bytes(rows))
    return len(rows)

"""
    Compte rapidement les lignes d'un CSV (sans charger en mémoire).
    On retire 1 pour l'en-tête.
"""
def count_csv_rows_fast(path: Path) -> int:
    n = 0
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            n += chunk.count(b"\n")
    return max(0, n - 1)

"""
    Transforme n'importe quelle chaîne de caractères en liste de chaînes de caractères.
"""
def parse_csv_list(s: Optional[str]) -> List[str]:
    if not s:
        return []
    return [x.strip() for x in s.split(",") if x.strip()]

"""
    Génère le chemin du checkpoint pour un export donné.
"""
def checkpoint_path(out_dir: Path) -> Path:
    return out_dir / "_checkpoint.json"

"""
    Génère  checkpoint d'un export afin d'obtenir ses informations
"""
def write_checkpoint(out_dir: Path, payload: dict) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    p = checkpoint_path(out_dir)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)

"""
    Lit les informations d'un export
"""
def read_checkpoint(out_dir: Path) -> Optional[dict]:
    p = checkpoint_path(out_dir)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None

"""
    Normalise les noms de fichiers avec la fréquence
"""
def _prefix_for(route: str, frequency: str) -> str:
    return f"{safe_filename(route.replace('/','_'))}_{frequency}"

"""
    Retourne les fichiers prefix_fileXXXX.csv triés par index.
    Ignore LAST.
"""
def _list_chunk_files(out_dir: Path, prefix: str) -> List[Path]:
    pat = re.compile(rf"^{re.escape(prefix)}_file(\d{{4}})\.csv$")
    files = []
    if out_dir.exists():
        for p in out_dir.iterdir():
            m = pat.match(p.name)
            if m:
                files.append((int(m.group(1)), p))
    return [p for _, p in sorted(files, key=lambda x: x[0])]

"""
    Retourne l'index du prochain fichier à créer sur disque.
"""
def _next_file_index_from_disk(out_dir: Path, prefix: str) -> int:
    files = _list_chunk_files(out_dir, prefix)
    if not files:
        return 1
    last = files[-1].name
    m = re.search(r"_file(\d{4})\.csv$", last)
    return int(m.group(1)) + 1 if m else 1

"""
    Compte le nombre total de lignes (sans headers) déjà écrites sur disque
    (fichiers chunk + éventuellement LAST).
"""
def _rows_written_from_disk(out_dir: Path, prefix: str) -> int:
    total = 0
    for p in _list_chunk_files(out_dir, prefix):
        total += count_csv_rows_fast(p)
    lastp = out_dir / f"{prefix}_LAST.csv"
    if lastp.exists():
        total += count_csv_rows_fast(lastp)
    return total

"""
    Etat détaillé de où on en est.
"""
def export_status(out_dir: Path, prefix: str, file_size: int) -> dict:
    ck = read_checkpoint(out_dir)
    chunk_files = _list_chunk_files(out_dir, prefix)
    last_file = chunk_files[-1].name if chunk_files else None
    last_path = str(chunk_files[-1].resolve()) if chunk_files else None

    next_file_index_disk = _next_file_index_from_disk(out_dir, prefix)
    rows_disk = _rows_written_from_disk(out_dir, prefix)
    next_offset_disk = rows_disk

    return {
        "out_dir": str(out_dir.resolve()),
        "prefix": prefix,
        "file_size": file_size,
        "chunk_files_count": len(chunk_files),
        "last_chunk_file": last_file,
        "last_chunk_path": last_path,
        "rows_written_disk": rows_disk,
        "next_offset_disk": next_offset_disk,
        "next_file_index_disk": next_file_index_disk,
        "checkpoint_exists": ck is not None,
        "checkpoint": ck,
    }

"""
    Wrapper HTTP permettant de sécuriser les appels à l'API EIA.
"""
def _safe_get_json(url: str, params, timeout: int = 60, retries: int = 8) -> dict:
    headers = {
        "User-Agent": "ETL-EIA-Exporter/1.0 (+http://127.0.0.1)",
        "Accept": "application/json",
    }
    base_sleep = 0.6

    last_text = None
    last_status = None

    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, timeout=timeout, headers=headers)
        except Exception as e:
            if attempt == retries - 1:
                raise HTTPException(status_code=502, detail=f"Network error calling EIA: {e}")
            time.sleep(base_sleep * (2 ** attempt) + random.random() * 0.2)
            continue

        last_status = r.status_code
        last_text = r.text[:400]

        if r.status_code in (429, 500, 502, 503, 504):
            if attempt == retries - 1:
                raise HTTPException(status_code=r.status_code, detail=r.text)
            time.sleep(base_sleep * (2 ** attempt) + random.random() * 0.2)
            continue

        try:
            payload = r.json()
        except Exception:
            if attempt == retries - 1:
                raise HTTPException(
                    status_code=502,
                    detail=f"Non-JSON from EIA. HTTP {r.status_code}. Body: {last_text}"
                )
            time.sleep(base_sleep * (2 ** attempt) + random.random() * 0.2)
            continue

        if isinstance(payload, str):
            if "Something unexpected happened" in payload:
                if attempt == retries - 1:
                    raise HTTPException(status_code=502, detail={"message": payload, "url": url})
                time.sleep(base_sleep * (2 ** attempt) + random.random() * 0.2)
                continue
            raise HTTPException(status_code=502, detail={"message": "Unexpected JSON string", "payload": payload})

        if isinstance(payload, dict) and "error" in payload:
            err = payload.get("error", {}) or {}
            raise HTTPException(status_code=400, detail={"code": err.get("code"), "message": err.get("message")})

        if isinstance(payload, dict) and "response" not in payload and "error" not in payload:
            if attempt == retries - 1:
                raise HTTPException(status_code=502, detail={"message": "Unexpected JSON dict shape", "payload": payload})
            time.sleep(base_sleep * (2 ** attempt) + random.random() * 0.2)
            continue

        if r.status_code != 200:
            raise HTTPException(status_code=r.status_code, detail=payload)

        return payload

    raise HTTPException(status_code=502, detail={"message": "EIA request failed", "status": last_status, "body": last_text})


def get_metadata(path: str) -> dict:
    path = path.strip("/")
    if path in _METADATA_CACHE:
        return _METADATA_CACHE[path]
    url = f"{EIA_BASE}/{path}/"
    md = _safe_get_json(url, params={"api_key": EIA_API_KEY}, timeout=120)
    _METADATA_CACHE[path] = md
    return md

def get_routes(md: dict) -> List[Dict]:
    resp = md.get("response", {}) or {}
    return resp.get("routes", []) or []

def get_freqs(md: dict) -> List[str]:
    resp = md.get("response", {}) or {}
    freqs = resp.get("frequency", []) or []
    out = []
    for f in freqs:
        if isinstance(f, dict) and f.get("id"):
            out.append(f["id"])
    return out

def get_data_fields(md: dict) -> List[str]:
    resp = md.get("response", {}) or {}
    data = resp.get("data", {}) or {}
    if isinstance(data, dict):
        return list(data.keys())
    return []

def get_facets(md: dict) -> List[str]:
    resp = md.get("response", {}) or {}
    facets = resp.get("facets", []) or []
    out = []
    for f in facets:
        if isinstance(f, dict) and f.get("id"):
            out.append(f["id"])
    return out

def is_leaf(md: dict) -> bool:
    resp = md.get("response", {}) or {}
    has_freq = isinstance(resp.get("frequency"), list) and len(resp.get("frequency")) > 0
    has_data = isinstance(resp.get("data"), dict)
    has_children = len(resp.get("routes", []) or []) > 0
    return has_freq and has_data and (not has_children)

def discover_leaf_routes(root: str, max_depth: int = 8) -> List[str]:
    root = root.strip("/")
    stack: List[Tuple[str, int]] = [(root, 0)]
    seen = set()
    leafs: List[str] = []

    while stack:
        path, depth = stack.pop()
        if path in seen:
            continue
        seen.add(path)

        try:
            md = get_metadata(path)
        except Exception:
            continue

        if is_leaf(md):
            leafs.append(path)
            continue

        if depth >= max_depth:
            continue

        for r in get_routes(md):
            if isinstance(r, dict) and r.get("id"):
                stack.append((f"{path}/{r['id']}".strip("/"), depth + 1))

    return sorted(set(leafs))

def get_children_map(parent_route: str) -> Dict[str, str]:
    parent_route = parent_route.strip("/")
    if parent_route in _CHILDREN_MAP_CACHE:
        return _CHILDREN_MAP_CACHE[parent_route]

    md = get_metadata(parent_route)
    routes = (md.get("response", {}) or {}).get("routes", []) or []
    out: Dict[str, str] = {}
    for r in routes:
        if isinstance(r, dict) and r.get("id"):
            out[r["id"]] = r.get("name") or r["id"]

    _CHILDREN_MAP_CACHE[parent_route] = out
    return out

def numbered_leaf_dir(route: str) -> Path:
    """
    route ex: petroleum/sum/mkt
    -> exports/petroleum/sum/03__Prices_Sales_Volumes_Stocks_by_State
    """
    parts = route.strip("/").split("/")
    parent = "/".join(parts[:-1])     # petroleum/sum
    leaf_id = parts[-1]              # mkt

    child_map = get_children_map(parent)
    leaf_name = child_map.get(leaf_id, leaf_id)

    ordered_ids = sorted(child_map.keys())
    idx = ordered_ids.index(leaf_id) + 1 if leaf_id in ordered_ids else 999
    num = f"{idx:02d}"

    return EXPORT_BASE_DIR / parent / f"{num}__{slugify_folder(leaf_name)}"

def route_to_dir(route: str) -> Path:
    """
    applique 01__Nom_Complet pour les leaf routes petroleum/*/<leaf> (3 segments)
    sinon fallback exports/<route>
    """
    route = route.strip("/")
    parts = route.split("/")
    if len(parts) == 3 and parts[0] == "petroleum":
        return numbered_leaf_dir(route)
    return EXPORT_BASE_DIR / route

def build_names_map(root: str, max_depth: int = 8) -> dict:
    root = root.strip("/")
    names = {}
    stack = [(root, 0)]
    seen = set()

    while stack:
        path, depth = stack.pop()
        if path in seen:
            continue
        seen.add(path)

        try:
            md = get_metadata(path)
        except Exception:
            continue

        routes = md.get("response", {}).get("routes", []) or []
        for r in routes:
            if not isinstance(r, dict) or "id" not in r:
                continue
            child = f"{path}/{r['id']}".strip("/")
            names[child] = {"name": r.get("name"), "description": r.get("description")}
            if depth + 1 < max_depth:
                stack.append((child, depth + 1))

    return names

def pick_better_name(path: str, md: dict, names_map: dict) -> tuple:
    resp = md.get("response", {}) or {}
    if path in names_map:
        n = names_map[path].get("name")
        d = names_map[path].get("description")
        return (n, d)
    return (resp.get("name"), resp.get("description"))


def _export_route_all_split10k_generator(
    route: str,
    frequency: str,
    data_field: str,
    api_page_size: int,
    file_size: int,
    sleep_ms: int,
    start: Optional[str],
    end: Optional[str],
    verify: bool = False,
    start_offset: int = 0,
    resume: bool = False,
) -> Iterable[str]:
    """
    Generator stream: logs pendant l'export.
    resume=True => lit _checkpoint.json ET l'état disque, puis reprend sans doublons.
    start_offset => si resume=False, permet de forcer l'offset (sans écraser ce qui existe).
    filenames basés sur prefix unique => export_status fiable.
    """
    route = route.strip("/")
    out_dir = route_to_dir(route) / frequency / "ALL_NO_FILTER"
    out_dir.mkdir(parents=True, exist_ok=True)

    base_url = f"{EIA_BASE}/{route}/data/"

    prefix = _prefix_for(route, frequency)

    st = export_status(out_dir, prefix, file_size)

    offset = int(st["next_offset_disk"])
    file_index = int(st["next_file_index_disk"])
    total_written = int(st["rows_written_disk"])

    
    if not resume and start_offset and int(start_offset) > 0:
        forced = int(start_offset)
        offset = max(offset, forced)

        if st["chunk_files_count"] == 0 and not st["checkpoint_exists"]:
            file_index = (offset // file_size) + 1
            total_written = offset

    if resume:
        ck = read_checkpoint(out_dir)
        if ck:
            ck_offset = int(ck.get("next_offset", offset))
            ck_file_index = int(ck.get("next_file_index", file_index))
            ck_written = int(ck.get("total_written", total_written))

            offset = max(offset, ck_offset)
            file_index = max(file_index, ck_file_index)
            total_written = max(total_written, ck_written)

            yield (
                f"[RESUME] checkpoint+disk merge: "
                f"next_offset={offset} total_written={total_written} next_file_index={file_index}\n"
            )
        else:
            yield "[RESUME] no checkpoint found, using disk state\n"

    yield (
        f"[STATE] out_dir={st['out_dir']}\n"
        f"[STATE] prefix={prefix} file_size={file_size}\n"
        f"[STATE] disk_rows={st['rows_written_disk']} disk_next_offset={st['next_offset_disk']} "
        f"disk_next_file_index={st['next_file_index_disk']}\n"
        f"[STATE] checkpoint_exists={st['checkpoint_exists']}\n"
    )

    yield (
        f"[START] route={route} frequency={frequency} api_page_size={api_page_size} "
        f"file_size={file_size} start={start} end={end} start_offset={offset} resume={resume}\n"
    )

    total_expected: Optional[int] = None
    buffer_rows: List[Dict] = []
    files_written: List[str] = []

    try:
        while True:
            params_items = [
                ("api_key", EIA_API_KEY),
                ("frequency", frequency),
                ("data[]", data_field),
                ("sort[0][column]", "period"),
                ("sort[0][direction]", "desc"),
                ("offset", str(offset)),
                ("length", str(api_page_size)),
            ]
            if start:
                params_items.append(("start", start))
            if end:
                params_items.append(("end", end))

            payload = _safe_get_json(base_url, params=params_items, timeout=240)
            resp = payload.get("response", {}) or {}
            rows = resp.get("data", []) or []

            if total_expected is None:
                total_expected = parse_int(resp.get("total"))
                yield f"[INFO] total_expected={total_expected}\n"

            if not rows:
                yield "[INFO] no more rows from API\n"
                break

            buffer_rows.extend(rows)
            offset += api_page_size
            yield f"[FETCH] offset={offset} got_rows={len(rows)} buffer={len(buffer_rows)}\n"

            while len(buffer_rows) >= file_size:
                chunk = buffer_rows[:file_size]
                buffer_rows = buffer_rows[file_size:]

                fname = out_dir / f"{prefix}_file{file_index:04d}.csv"
                written = write_csv(fname, chunk)
                total_written += written
                files_written.append(str(fname))
                yield f"[WRITE] {fname} rows={written} total_written={total_written}\n"

                file_index += 1

                write_checkpoint(out_dir, {
                    "route": route,
                    "frequency": frequency,
                    "total_expected": total_expected,
                    "total_written": total_written,
                    "next_offset": offset,
                    "next_file_index": file_index,
                    "updated_at": now_iso(),
                })

            if len(rows) < api_page_size:
                yield "[INFO] last API page reached (rows < api_page_size)\n"
                break

            if total_expected is not None and offset >= total_expected:
                yield "[INFO] offset >= total_expected => stop\n"
                break

            if sleep_ms:
                time.sleep(sleep_ms / 1000.0)

        if buffer_rows:
            last_fname = out_dir / f"{prefix}_LAST.csv"
            written = write_csv(last_fname, buffer_rows)
            total_written += written
            files_written.append(str(last_fname))
            yield f"[WRITE-LAST] {last_fname} rows={written} total_written={total_written}\n"

            write_checkpoint(out_dir, {
                "route": route,
                "frequency": frequency,
                "total_expected": total_expected,
                "total_written": total_written,
                "next_offset": offset,
                "next_file_index": file_index,
                "updated_at": now_iso(),
            })

        if verify:
            actual_rows = _rows_written_from_disk(out_dir, prefix)
            ok = (total_expected is None) or (actual_rows == total_expected)
            yield f"[VERIFY] actual_rows={actual_rows} total_expected={total_expected} ok={ok}\n"

        write_checkpoint(out_dir, {
            "route": route,
            "frequency": frequency,
            "total_expected": total_expected,
            "total_written": total_written,
            "next_offset": offset,
            "next_file_index": file_index,
            "updated_at": now_iso(),
            "finished": True,
        })

        yield f"[DONE] total_written={total_written} out_dir={out_dir.resolve()}\n"

    except GeneratorExit:
       
        return
    except Exception as e:
        write_checkpoint(out_dir, {
            "route": route,
            "frequency": frequency,
            "total_expected": total_expected,
            "total_written": total_written,
            "next_offset": offset,
            "next_file_index": file_index,
            "updated_at": now_iso(),
            "error": str(e),
        })
        yield f"[ERROR] {type(e).__name__}: {e}\n"
        return
@app.get("/export_status")
def export_status_endpoint(
    route: str = Query(..., description="Ex: petroleum/pri/allmg"),
    frequency: str = Query(..., description="Ex: monthly"),
    file_size: int = Query(10000, ge=1000, le=200000),
):
    route = route.strip("/")
    out_dir = route_to_dir(route) / frequency / "ALL_NO_FILTER"
    prefix = _prefix_for(route, frequency)
    return JSONResponse(export_status(out_dir, prefix, file_size))

def export_route_all_split10k(
    route: str,
    frequency: str,
    data_field: str,
    api_page_size: int,
    file_size: int,
    sleep_ms: int,
    start: Optional[str],
    end: Optional[str],
    verify: bool = False,
) -> dict:
    """
    Export qui retourne un JSON final (sans resume ici).
    """
    route = route.strip("/")
    out_dir = route_to_dir(route) / frequency / "ALL_NO_FILTER"
    out_dir.mkdir(parents=True, exist_ok=True)

    base_url = f"{EIA_BASE}/{route}/data/"
    offset = 0
    total_expected: Optional[int] = None

    buffer_rows: List[Dict] = []
    file_index = 1
    total_written = 0
    files: List[str] = []

    prefix = _prefix_for(route, frequency)

    while True:
        params_items = [
            ("api_key", EIA_API_KEY),
            ("frequency", frequency),
            ("data[]", data_field),
            ("sort[0][column]", "period"),
            ("sort[0][direction]", "desc"),
            ("offset", str(offset)),
            ("length", str(api_page_size)),
        ]
        if start:
            params_items.append(("start", start))
        if end:
            params_items.append(("end", end))

        payload = _safe_get_json(base_url, params=params_items, timeout=240)
        resp = payload.get("response", {}) or {}
        rows = resp.get("data", []) or []

        if total_expected is None:
            total_expected = parse_int(resp.get("total"))

        if not rows:
            break

        buffer_rows.extend(rows)
        offset += api_page_size

        while len(buffer_rows) >= file_size:
            chunk = buffer_rows[:file_size]
            buffer_rows = buffer_rows[file_size:]

            fname = out_dir / f"{prefix}_file{file_index:04d}.csv"
            written = write_csv(fname, chunk)
            total_written += written
            files.append(str(fname))
            file_index += 1

        if len(rows) < api_page_size:
            break

        if total_expected is not None and offset >= total_expected:
            break

        if sleep_ms:
            time.sleep(sleep_ms / 1000.0)

    if buffer_rows:
        fname = out_dir / f"{prefix}_LAST.csv"
        written = write_csv(fname, buffer_rows)
        total_written += written
        files.append(str(fname))

    actual_rows = None
    verify_ok = None
    if verify:
        actual_rows = 0
        for fp in files:
            actual_rows += count_csv_rows_fast(Path(fp))
        verify_ok = (total_expected is None) or (actual_rows == total_expected)

    return {
        "route": route,
        "frequency": frequency,
        "start": start,
        "end": end,
        "total_expected": total_expected,
        "total_written": total_written,
        "files_count": len(files),
        "out_dir": str(out_dir.resolve()),
        "files_preview": files[:10],
        "verify": verify,
        "actual_rows": actual_rows,
        "verify_ok": verify_ok,
    }


@app.get("/tree_verbose")
def tree_verbose(
    root: str = Query(..., description="Ex: petroleum/sum"),
    max_depth: int = Query(6, ge=1, le=12),
    max_leaf_routes: int = Query(200, ge=1, le=50000),
):
    leafs = discover_leaf_routes(root, max_depth=max_depth)[:max_leaf_routes]
    names_map = build_names_map(root, max_depth=max_depth)

    out = []
    for p in leafs:
        try:
            md = get_metadata(p)
            resp = md.get("response", {}) or {}
            name, desc = pick_better_name(p, md, names_map)
            out.append({
                "path": p,
                "name": name,
                "description": desc,
                "frequencies": get_freqs(md),
                "facets": get_facets(md),
                "data_fields": get_data_fields(md),
                "startPeriod": resp.get("startPeriod"),
                "endPeriod": resp.get("endPeriod"),
            })
        except Exception as e:
            out.append({"path": p, "error": True, "reason": str(e)})

    return JSONResponse(out)

@app.get("/curl_commands")
def curl_commands(
    root: str = Query(..., description="Ex: petroleum/sum"),
    frequencies: str = Query("monthly,weekly", description="Ex: monthly,weekly"),
    max_depth: int = Query(8, ge=1, le=20),
    max_leaf_routes: int = Query(5000, ge=1, le=50000),
    api_page_size: int = Query(5000, ge=1, le=5000),
    file_size: int = Query(10000, ge=1000, le=200000),
    sleep_ms: int = Query(200, ge=0, le=2000),
    verify: bool = Query(True),
    resume: bool = Query(False, description="Si true: ajoute &resume=1 dans les commandes curl"),
):
    """
    Génère des commandes curl (stream) pour chaque leaf route sous root,
    uniquement pour les fréquences disponibles.
    """
    wanted = set(parse_csv_list(frequencies))

    resp = tree_verbose(root=root, max_depth=min(max_depth, 12), max_leaf_routes=max_leaf_routes)
    arr = json.loads(resp.body.decode("utf-8"))

    cmds = []
    for node in arr:
        path = node.get("path")
        freqs = set(node.get("frequencies") or [])
        for f in sorted(list(wanted.intersection(freqs))):
            url = (
                "http://127.0.0.1:8000/export_route_all_split10k_stream"
                f"?route={path}&frequency={f}&api_page_size={api_page_size}"
                f"&file_size={file_size}&sleep_ms={sleep_ms}"
                f"&verify={'true' if verify else 'false'}"
            )
            if resume:
                url += "&resume=1"
            cmds.append({
                "route": path,
                "frequency": f,
                "name": node.get("name"),
                "curl": f'curl -sS -N --no-progress-meter "{url}" | tee logs_{safe_filename(path)}_{f}.log'
            })

    return JSONResponse({"root": root, "count": len(cmds), "commands": cmds})


@app.get("/health")
def health():
    return {"status": "ok", "exports_dir": str(EXPORT_BASE_DIR.resolve())}

@app.get("/export_status")
def export_status_endpoint(
    route: str = Query(..., description="Ex: petroleum/sum/snd"),
    frequency: str = Query(..., description="monthly / annual / weekly / four-week-average"),
    file_size: int = Query(10000, ge=1000, le=200000),
):
    route = route.strip("/")
    out_dir = route_to_dir(route) / frequency / "ALL_NO_FILTER"
    prefix = _prefix_for(route, frequency)
    return JSONResponse(export_status(out_dir, prefix, file_size))

@app.get("/export_route_all_split10k")
def export_route_all_split10k_endpoint(
    route: str = Query(..., description="Ex: petroleum/sum/mkt"),
    frequency: str = Query(..., description="monthly / annual / weekly / four-week-average"),
    data_field: str = Query("value"),
    api_page_size: int = Query(5000, ge=1, le=5000),
    file_size: int = Query(10000, ge=1000, le=200000),
    sleep_ms: int = Query(400, ge=0, le=2000),
    start: Optional[str] = Query(None, description="Optionnel. Ex: 2020-01 (monthly) ou 2018 (annual)"),
    end: Optional[str] = Query(None, description="Optionnel. Ex: 2020-12 (monthly) ou 2023 (annual)"),
    verify: bool = Query(False, description="Recompte les lignes des CSV et vérifie total_expected"),
):
    return export_route_all_split10k(
        route=route,
        frequency=frequency,
        data_field=data_field,
        api_page_size=api_page_size,
        file_size=file_size,
        sleep_ms=sleep_ms,
        start=start,
        end=end,
        verify=verify,
    )

@app.get("/export_route_all_split10k_stream")
def export_route_all_split10k_stream(
    route: str = Query(..., description="Ex: petroleum/sum/mkt"),
    frequency: str = Query(..., description="monthly / annual / weekly / four-week-average"),
    data_field: str = Query("value"),
    api_page_size: int = Query(5000, ge=1, le=5000),
    file_size: int = Query(10000, ge=1000, le=200000),
    sleep_ms: int = Query(400, ge=0, le=2000),
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    verify: bool = Query(False),
    start_offset: int = Query(0, ge=0, description="Reprendre à partir d'un offset précis (si resume=false)"),
    resume: bool = Query(False, description="Si true: lit _checkpoint.json + scan disque et reprend automatiquement"),
):
    gen = _export_route_all_split10k_generator(
        route=route,
        frequency=frequency,
        data_field=data_field,
        api_page_size=api_page_size,
        file_size=file_size,
        sleep_ms=sleep_ms,
        start=start,
        end=end,
        verify=verify,
        start_offset=start_offset,
        resume=resume,
    )
    return StreamingResponse(gen, media_type="text/plain; charset=utf-8")
