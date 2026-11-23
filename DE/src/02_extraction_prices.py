"""Monthly petrol (Euro-super 95) and diesel pump prices for Germany, taxes included.

Source: European Commission Weekly Oil Bulletin, historical .xlsx, sheet
"Prices with taxes". Weekly values in EUR/1000 l are converted to EUR/l and
averaged per calendar month. Mirrors IT/src/02_extraction_prices.py.

Output: DE/interim/germany_fuel_prices.(parquet|csv)
    date, petrol_price_eur_l, diesel_price_eur_l
"""
from pathlib import Path

import pandas as pd

# ------------------------------------------------------------------------------
# CONFIGURATION
# ------------------------------------------------------------------------------
COUNTRY_CODE = "DE"        # columns in the bulletin are named e.g. "DE_price_with_tax_euro95"
START_DATE = "2019-01-01"  # same time window as the Italy pipeline

BASE_DIR = Path(__file__).resolve().parent.parent  # .../DE
REPO_DIR = BASE_DIR.parent                         # repository root

# The bulletin covers every EU country and is already in the repo under
# IT/raw_data, so we read it from there instead of keeping a second copy.
INPUT_FILE = REPO_DIR / "IT" / "raw_data" / "Weekly_Oil_Bulletin.xlsx"
OUTPUT_DIR = BASE_DIR / "interim"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

if not INPUT_FILE.exists():
    raise FileNotFoundError(f"File not found: {INPUT_FILE}")

# ------------------------------------------------------------------------------
# LOAD
# ------------------------------------------------------------------------------
# The column header spans 3 rows in the Excel sheet:
#   (series code, fuel name, unit), e.g. ("DE_price_with_tax_euro95", "Euro-super 95 (I)", "1000 l")
# header=[0, 1, 2] makes each column name a tuple of those 3 values.
raw = pd.read_excel(INPUT_FILE, sheet_name="Prices with taxes", header=[0, 1, 2])


def find_column(series_code: str):
    """Return the column whose first header level (the series code) equals series_code.

    Matching the exact code is safer than searching for text inside the fuel
    name, and failing loudly if there isn't exactly one match catches layout
    changes in future versions of the file.
    """
    matches = [c for c in raw.columns if str(c[0]).strip() == series_code]
    if len(matches) != 1:
        raise ValueError(f"Expected one column '{series_code}', found {len(matches)}")
    return matches[0]


petrol_col = find_column(f"{COUNTRY_CODE}_price_with_tax_euro95")
diesel_col = find_column(f"{COUNTRY_CODE}_price_with_tax_diesel")
date_col = raw.columns[0]  # the first column holds the bulletin dates

# ------------------------------------------------------------------------------
# WEEKLY TABLE
# ------------------------------------------------------------------------------
# errors="coerce" turns anything that isn't a valid date/number (e.g. notes at
# the bottom of the sheet) into NaT/NaN instead of raising an error; those rows
# are then dropped. Dividing by 1000 converts EUR per 1000 litres to EUR per litre.
weekly = pd.DataFrame({
    "date": pd.to_datetime(raw[date_col], format="%d/%m/%y", errors="coerce"),
    "petrol_price_eur_l": pd.to_numeric(raw[petrol_col], errors="coerce") / 1000.0,
    "diesel_price_eur_l": pd.to_numeric(raw[diesel_col], errors="coerce") / 1000.0,
}).dropna(subset=["date"])

# ------------------------------------------------------------------------------
# WEEKLY -> MONTHLY
# ------------------------------------------------------------------------------
# resample("MS") groups the rows by calendar month (labelled with the month
# start, e.g. 2024-03-01) and .mean() averages the weekly prices of each month.
# resample needs the dates in the index, hence set_index / reset_index.
monthly = (
    weekly.set_index("date")
    .resample("MS")
    .mean()
    .round(4)  # 4 decimals = 1/100 of a cent per litre
    .reset_index()
)
monthly = monthly[monthly["date"] >= START_DATE].reset_index(drop=True)

# ------------------------------------------------------------------------------
# CHECKS
# ------------------------------------------------------------------------------
# A NaN means a whole month without bulletin data.
if monthly[["petrol_price_eur_l", "diesel_price_eur_l"]].isna().any().any():
    print("WARNING: NaN values in the monthly price series:")
    print(monthly[monthly.isna().any(axis=1)])
# Prices outside 0.8-3.0 EUR/l would point to a unit error (e.g. forgetting /1000).
lo, hi = monthly[["petrol_price_eur_l", "diesel_price_eur_l"]].stack().agg(["min", "max"])
if lo < 0.8 or hi > 3.0:
    print(f"WARNING: prices outside the plausible 0.8-3.0 EUR/l range ({lo}, {hi})")

# ------------------------------------------------------------------------------
# SAVE (parquet for code, CSV for people and git diffs)
# ------------------------------------------------------------------------------
monthly.to_parquet(OUTPUT_DIR / "germany_fuel_prices.parquet", index=False)
monthly.to_csv(OUTPUT_DIR / "germany_fuel_prices.csv", index=False)
print(monthly.tail(10).to_string(index=False))
