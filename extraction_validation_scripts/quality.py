import re

pattern = re.compile(r'file(\d+)\.csv')

def check_missing_files(dataset):
    files = sorted(dataset.glob("*.csv"))

    numbers = []

    for f in files:
        m = pattern.search(f.name)
        if m:
            numbers.append(int(m.group(1)))

    if numbers:
        missing = set(range(min(numbers), max(numbers)+1)) - set(numbers)
        return sorted(missing)

    return []
