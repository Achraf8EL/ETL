from config import EXPORT_DIR, OUTPUT_DIR
from utils import get_datasets
from validation import validate_dataset
from quality import check_missing_files
from merge import merge_dataset
from analysis import analyze_file
from size_analysis import get_dataset_size


def main():

    print("Détection des datasets...\n")

    datasets = get_datasets(EXPORT_DIR)

    for dataset in datasets:

        print("\n==============================")
        print("Dataset:", dataset)

        val = validate_dataset(dataset)
        if val:
            print("Files:", val["files"])
            print("Rows:", val["rows"])

        missing = check_missing_files(dataset)
        print("Missing files:", missing if missing else "None")

        print("Size (MB):", get_dataset_size(dataset))

        output, rows = merge_dataset(dataset, OUTPUT_DIR)
        if output:
            print("Merged file:", output)
            print("Merged rows:", rows)

            analysis = analyze_file(output)
            print("Shape:", analysis["shape"])
            print("Columns:", analysis["columns"])

    print("\n TEST OK")


if __name__ == "__main__":
    main()
