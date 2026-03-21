
"""
Script pour renommer les dossiers dans exports/petroleum/crd.

Ce script interroge l'API EIA pour obtenir les noms des sous-routes de 'petroleum/crd',
puis renomme les dossiers existants en ajoutant le code court et un nom lisible.

Prérequis :
- Clé API EIA dans la variable d'environnement EIA_API_KEY.
- Dossiers à renommer dans exports/petroleum/crd.
"""
import os, re, json, requests
from pathlib import Path

EIA_BASE = "https://api.eia.gov/v2"
API_KEY = os.environ.get("EIA_API_KEY")  # ou mets ta clé ici si tu veux

EXPORTS = Path("exports")


# Transforme une chaîne de caractères en un nom de dossier valide (sans caractères spéciaux)
def slug(s: str) -> str:
    s = (s or "").strip().replace("&", "and")
    s = re.sub(r"[^\w\s.-]+", "", s)
    s = re.sub(r"\s+", "_", s)
    return s[:140] if s else "UNKNOWN"

"""
get_name () Interroge l'API EIA pour obtenir le nom officiel et lisible d'une route.
L'API EIA expose pour chaque route un champ "name" contenant le libellé complet en anglais. 
En cas d'absence, le dernier segment de la route est utilisé comme valeur de secours (fallback).
"""

def get_name(route: str) -> str:
    url = f"{EIA_BASE}/{route.strip('/')}/"
    r = requests.get(url, params={"api_key": API_KEY}, timeout=60)
    r.raise_for_status()
    j = r.json()
    return (j.get("response", {}) or {}).get("name") or route.split("/")[-1]


# Les 12 routes feuilles de la catégorie "Crude Reserves & Production"
routes = [
    "petroleum/crd/api","petroleum/crd/cplc","petroleum/crd/crpdn","petroleum/crd/drill",
    "petroleum/crd/gom","petroleum/crd/nprod","petroleum/crd/pres","petroleum/crd/seis",
    "petroleum/crd/wellcost","petroleum/crd/welldep","petroleum/crd/wellend","petroleum/crd/wellfoot",
]

# RENOMMAGE DES DOSSIERS

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
