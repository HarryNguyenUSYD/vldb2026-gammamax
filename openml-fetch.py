from ucimlrepo import fetch_ucirepo
from pathlib import Path
import pandas as pd

DATASETS = {
    "bank_marketing": 222,
    "census_income_kdd": 117,
    "adult": 20,
    "support2": 880,
}

root = Path(__file__).resolve().parent / "benchmark-datasets"
root.mkdir(parents=True, exist_ok=True)

for name, dataset_id in DATASETS.items():
    print(f"Downloading {name} (UCI {dataset_id})...")

    dataset = fetch_ucirepo(id=dataset_id)

    X = dataset.data.features
    y = dataset.data.targets

    # Keep everything in one table where possible
    if y is not None and len(y.columns) > 0:
        df = pd.concat([X.reset_index(drop=True),
                        y.reset_index(drop=True)], axis=1)
    else:
        df = X.copy()

    out = root / f"{name}_{dataset_id}"
    out.mkdir(parents=True, exist_ok=True)

    df.to_csv(out / "clean.csv", index=False)

    with open(out / "metadata.txt", "w", encoding="utf-8") as f:
        f.write(f"UCI ID: {dataset_id}\n")
        f.write(f"Name: {dataset.metadata.name}\n")
        f.write(f"Rows: {len(df)}\n")
        f.write(f"Columns: {len(df.columns)}\n")
        f.write("\nColumn types:\n")
        f.write(df.dtypes.to_string())

    print(f"  saved {len(df):,} rows x {len(df.columns)} columns")
