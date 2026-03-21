import csv

def count_rows(csv_file):
    try:
        with open(csv_file, "r", encoding="utf8") as f:
            reader = csv.reader(f)
            next(reader, None)
            return sum(1 for _ in reader)
    except:
        return 0


def validate_dataset(dataset_path):
    csv_files = sorted(dataset_path.glob("*.csv"))

    if not csv_files:
        return None

    total_rows = sum(count_rows(f) for f in csv_files)

    return {
        "dataset": str(dataset_path),
        "files": len(csv_files),
        "rows": total_rows
    }
