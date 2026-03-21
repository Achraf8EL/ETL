import pandas as pd

def analyze_file(file):
    df = pd.read_csv(file)

    return {
        "shape": df.shape,
        "columns": list(df.columns),
        "missing": df.isna().sum().to_dict()
    }
