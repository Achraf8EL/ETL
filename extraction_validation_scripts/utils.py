def get_datasets(base_dir):
    datasets = []

    for path in base_dir.rglob("*"):
        if path.is_dir():
            csv_files = list(path.glob("*.csv"))
            if csv_files:
                datasets.append(path)

    return datasets
