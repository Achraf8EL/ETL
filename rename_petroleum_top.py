import os
import re
import json
import argparse
from pathlib import Path
from typing import Dict, Optional

import requests
from dotenv import load_dotenv

load_dotenv()

EIA_API_KEY = os.getenv("EIA_API_KEY")
EIA_BASE = "https://api.eia.gov/v2"

EXPORTS_DIR_DEFAULT = Path("exports") / "petroleum"


def slugify_folder(s: str) -> str:
    s = (s or "").strip()
    s = s.replace("&", "and")
    s = re.sub(r"[^\w\s.-]+", "", s)
    s = re.sub(r"\s+", "_", s)
    s = s.strip("._-")
    return s[:140] if s else "UNKNOWN"


def fetch_petroleum_children_map() -> Dict[str, Dict[str, Optional[str]]]:
    """
    Retourne un mapping:
      id -> {name, description}
    pour petroleum/*
    """
    url = f"{EIA_BASE}/petroleum/"
    r = requests.get(url, params={"api_key": EIA_API_KEY}, timeout=60)
    r.raise_for_status()
    payload = r.json()
    routes = (payload.get("response", {}) or {}).get("routes", []) or []

    out = {}
    for rr in routes:
        if isinstance(rr, dict) and rr.get("id"):
            out[rr["id"]] = {
                "name": rr.get("name"),
                "description": rr.get("description"),
            }
    return out


def unique_target(base_dir: Path, target_name: str) -> Path:
    """
    Si le dossier existe déjà, ajoute __DUP1, __DUP2...
    """
    t = base_dir / target_name
    if not t.exists():
        return t
    for i in range(1, 1000):
        cand = base_dir / f"{target_name}__DUP{i}"
        if not cand.exists():
            return cand
    raise RuntimeError(f"Impossible de trouver un nom libre pour {target_name}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--petroleum-dir", default=str(EXPORTS_DIR_DEFAULT), help="ex: exports/petroleum")
    parser.add_argument("--apply", action="store_true", help="Applique réellement les renommages")
    parser.add_argument("--prefix-id", action="store_true", help="Garde l'id en début (recommandé)")
    parser.add_argument("--write-mapping", action="store_true", help="Ecrit un fichier _folder_mapping.json")
    args = parser.parse_args()

    petroleum_dir = Path(args.petroleum_dir).resolve()
    if not petroleum_dir.exists():
        raise SystemExit(f"Dossier introuvable: {petroleum_dir}")

    if not EIA_API_KEY:
        raise SystemExit("EIA_API_KEY manquante (dans .env ou export EIA_API_KEY=...)")

    meta = fetch_petroleum_children_map()

    actions = []
    for child in sorted([p for p in petroleum_dir.iterdir() if p.is_dir()]):
        folder_id = child.name

        # ignore les dossiers déjà renommés (ex: cons__Consumption)
        if "__" in folder_id:
            continue

        info = meta.get(folder_id)
        if not info:
            # pas trouvé dans l'API => on skip
            continue

        name = info.get("name") or folder_id
        nice = slugify_folder(name)

        if args.prefix_id:
            new_name = f"{folder_id}__{nice}"
        else:
            new_name = nice

        target = unique_target(petroleum_dir, new_name)

        actions.append({
            "from": str(child),
            "to": str(target),
            "id": folder_id,
            "name": name,
            "description": info.get("description"),
        })

    # Affichage plan
    print(f"\nPetroleum dir: {petroleum_dir}")
    print(f"Actions: {len(actions)}")
    for a in actions:
        print(f"- {Path(a['from']).name}  ->  {Path(a['to']).name}   ({a['name']})")

    if args.write_mapping:
        mapping_path = petroleum_dir / "_folder_mapping.json"
        mapping_path.write_text(json.dumps(actions, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nMapping écrit: {mapping_path}")

    if not args.apply:
        print("\n(DRY-RUN) Rien n'a été modifié. Relance avec --apply pour renommer réellement.")
        return

    # Apply
    for a in actions:
        Path(a["from"]).rename(Path(a["to"]))

    print("\n✅ Renommage terminé.")


if __name__ == "__main__":
    main()
