"""
Script pour exporter les données des routes du catalogue petroleum/cons.

Ce script lit un catalogue JSON contenant les routes feuilles (leafs) de la
catégorie 'petroleum/cons', puis déclenche l'export de chaque route via
l'API locale FastAPI (main.py) pour chaque fréquence disponible.

Prérequis :
- Le serveur FastAPI local doit être lancé : uvicorn main:app --reload
- Le fichier catalogue doit exister : exports/_catalogs/catalog_petroleum_cons_depth12.json
"""
import json
import time
import requests
from pathlib import Path

LOCAL = "http://127.0.0.1:8000"

# où est ton catalogue JSON complet ?
CATALOG_FILE = Path("exports/_catalogs/catalog_petroleum_cons_depth12.json")

# split local
FILE_SIZE = 10000

"""
Fonction principale : exporte toutes les routes feuilles du catalogue.
Pour chaque route feuille et chaque fréquence disponible, appelle
l'endpoint local /export_route_all_split10k afin de déclencher
l'extraction et l'écriture des données en fichiers CSV.
"""

def main():
    cat = json.loads(CATALOG_FILE.read_text(encoding="utf-8"))
    leafs = cat["leafs"]

    print("Leaf datasets:", len(leafs))

    for rec in leafs:
        route = rec["path"]
        freqs = rec.get("frequencies") or []  # Liste des fréquences disponibles pour cette route
        if not freqs:
            continue

        for freq in freqs:
            # call ton endpoint local d’export complet
            url = f"{LOCAL}/export_route_all_split10k"
             # Paramètres envoyés à l'endpoint FastAPI
            params = {
                "route": route,
                "frequency": freq,
                "file_size": FILE_SIZE,
            }
            print("[EXPORT]", route, freq)
            r = requests.get(url, params=params, timeout=60*60)  # 1h
            if r.status_code != 200:
                print("  !! ERROR", r.status_code, r.text[:300])
                continue

            j = r.json()
            print("  -> written", j.get("total_written"), "/", j.get("total_expected"), "files", j.get("files_count"))
            time.sleep(0.2)  # petit sleep

if __name__ == "__main__":
    main()
