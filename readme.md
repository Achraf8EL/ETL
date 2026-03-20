# ETL - Petroleum Catalog

Projet ETL pour traiter un catalogue pétrolier (source JSON) et produire des données prêtes à l'analyse.

## Objectif

Le script ETL :
1. **Extract** : lit les données brutes (ex: `petroleum_catalog.json`)
2. **Transform** : nettoie / normalise les champs
3. **Load** : écrit un fichier de sortie exploitable (JSON/CSV selon ton script)

## Prérequis

- Python 3.10+
- pip

## Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Exécution

Adapte au nom réel de ton script :

```bash
python3 etl.py
```

ou

```bash
python3 main.py
```

## rename_crd_dirs.py

- `rename_crd_dirs.py` : Renomme les dossiers dans `exports/petroleum/crd` avec des noms lisibles et numérotés (ex: `01__Nom_Lisible`), en interrogeant l'API EIA pour les noms officiels. Nécessite `EIA_API_KEY`.

- `rename_petroleum_top.py` : Renomme les dossiers principaux dans `exports/petroleum` (avec options pour mapping JSON et dry-run).

- `rename_dirs.py` : Script pour renommer des routes spécifiques hardcodées dans `exports/petroleum/crd`.

## Flux de travail

1. Mettre à jour `petroleum_catalog.json`
2. Lancer le script ETL
3. Vérifier les sorties générées

## Git

```bash
git add .
git commit -m "Add .gitignore and README"
git push
```

## Note

Les informations API sont publiques dans ce repo (choix volontaire).