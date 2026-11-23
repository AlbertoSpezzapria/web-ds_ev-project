"""Monthly petrol (Euro-super 95) and diesel pump prices for Germany, taxes included.

Source: European Commission Weekly Oil Bulletin, historical .xlsx, sheet
"Prices with taxes". Weekly values in EUR/1000 l are converted to EUR/l and
averaged per calendar month. Mirrors IT/src/02_extraction_prices.py.
"""
from pathlib import Path

import pandas as pd

COUNTRY_CODE = "DE"
START_DATE = "2019-01-01"

BASE_DIR = Path(__file__).resolve().parent.parent          # .../DE
REPO_DIR = BASE_DIR.parent
# Multi-country file already in the repo under IT/raw_data.
INPUT_FILE = REPO_DIR / "IT" / "raw_data" / "Weekly_Oil_Bulletin.xlsx"
OUTPUT_DIR = BASE_DIR / "interim"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

if not INPUT_FILE.exists():
    raise FileNotFoundError(f"File not found: {INPUT_FILE}")

# Header spans 3 rows: (series code, fuel name, unit).
raw = pd.read_excel(INPUT_FILE, sheet_name="Prices with taxes", header=[0, 1, 2])


def find_column(series_code: str):
    """Return the column whose first header level equals series_code."""
    matches = [c for c in raw.columns if str(c[0]).strip() == series_code]
    if len(matches) != 1:
        raise ValueError(f"Expected one column '{series_code}', found {len(matches)}")
    return matches[0]


petrol_col = find_column(f"{COUNTRY_CODE}_price_with_tax_euro95")
diesel_col = find_column(f"{COUNTRY_CODE}_price_with_tax_diesel")
date_col = raw.columns[0]

weekly = pd.DataFrame({
    "date": pd.to_datetime(raw[date_col], format="%d/%m/%y", errors="coerce"),
    "petrol_price_eur_l": pd.to_numeric(raw[petrol_col], errors="coerce") / 1000.0,
    "diesel_price_eur_l": pd.to_numeric(raw[diesel_col], errors="coerce") / 1000.0,
}).dropna(subset=["date"])

monthly = (
    weekly.set_index("date")
    .resample("MS")
    .mean()
    .round(4)
    .reset_index()
)
monthly = monthly[monthly["date"] >= START_DATE].reset_index(drop=True)

# --- checks -------------------------------------------------------------------
if monthly[["petrol_price_eur_l", "diesel_price_eur_l"]].isna().any().any():
    print("WARNING: NaN values in the monthly price series:")
    print(monthly[monthly.isna().any(axis=1)])
lo, hi = monthly[["petrol_price_eur_l", "diesel_price_eur_l"]].stack().agg(["min", "max"])
if lo < 0.8 or hi > 3.0:
    print(f"WARNING: prices outside the plausible 0.8-3.0 EUR/l range ({lo}, {hi})")

monthly.to_parquet(OUTPUT_DIR / "germany_fuel_prices.parquet", index=False)
monthly.to_csv(OUTPUT_DIR / "germany_fuel_prices.csv", index=False)
print(monthly.tail(10).to_string(index=False))
