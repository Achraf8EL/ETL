def get_dataset_size(dataset):
    size = sum(f.stat().st_size for f in dataset.glob("*.csv"))
    return round(size / 1e6, 2)
