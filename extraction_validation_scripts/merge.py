import pandas as pd

def merge_dataset(dataset, output_dir):
    csv_files = sorted(dataset.glob("*.csv"))

    df_list = []

    for f in csv_files:
        try:
            df = pd.read_csv(f, low_memory=False)
            df_list.append(df)
        except:
            print("Error reading:", f)

    if df_list:
        merged = pd.concat(df_list)

        output_file = output_dir / (dataset.name + "_MERGED.csv")

        merged.to_csv(output_file, index=False)

        return output_file, len(merged)

    return None, 0
