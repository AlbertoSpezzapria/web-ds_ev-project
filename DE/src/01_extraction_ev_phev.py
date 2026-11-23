"""Monthly BEV / PHEV / total car registrations for Germany (source: Ember).

Mirrors IT/src/01_extraction_ev_phev.py and produces the same columns, with one
deliberate difference: phev_* uses ONLY the "Plug-in hybrid" drivetrain. Ember's
"Hybrid" category is non-plug-in full hybrids (HEV), which are not PHEVs.

Output: DE/interim/germany_ev_monthly.(parquet|csv)
    date, bev_registrations, phev_registrations, total_registrations,
    bev_share, phev_share   (shares are in percent, 0-100)
"""
from pathlib import Path

import pandas as pd

# ------------------------------------------------------------------------------
# CONFIGURATION
# ------------------------------------------------------------------------------
COUNTRY = "Germany"        # value of the "Area" column in the Ember file
START_DATE = "2019-01-01"  # same time window as the Italy pipeline

# BASE_DIR = the folder that contains this script's folder, i.e. .../DE
# (Path(__file__) is this file, .parent is DE/src, .parent.parent is DE)
BASE_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BASE_DIR.parent  # repository root

# The Ember file covers every country and is already in the repo under
# IT/raw_data, so we read it from there instead of keeping a second copy.
INPUT_FILE = REPO_DIR / "IT" / "raw_data" / "ember_dataset.csv"

# Cleaned outputs go to DE/interim (created if it doesn't exist yet).
OUTPUT_DIR = BASE_DIR / "interim"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

if not INPUT_FILE.exists():
    raise FileNotFoundError(f"File not found: {INPUT_FILE}")

# ------------------------------------------------------------------------------
# LOAD AND FILTER
# ------------------------------------------------------------------------------
# The Ember file is in "long" format: one row per (country, month, drivetrain).
# Keep only German rows with monthly frequency (the file also has yearly rows).
# .copy() gives an independent DataFrame instead of a view of the original.
df = pd.read_csv(INPUT_FILE)
df = df[(df["Area"] == COUNTRY) & (df["Data frequency"] == "Monthly")].copy()
if df.empty:
    raise ValueError(f"No monthly rows found for Area == '{COUNTRY}'.")

# ------------------------------------------------------------------------------
# RESHAPE: one row per month, one column per (metric, drivetrain)
# ------------------------------------------------------------------------------
# pivot_table turns the drivetrain values (Battery electric, Plug-in hybrid,
# All drivetrains, ...) into columns. Because we ask for two metrics, the
# columns are pairs, e.g. ("Registrations", "Battery electric").
# aggfunc="sum" only matters if a (month, drivetrain) pair appeared twice.
pivot = df.pivot_table(
    index="Date",
    columns="Drivetrain",
    values=["Registrations", "Share of registrations (%)"],
    aggfunc="sum",
)

# Build the output table column by column. .to_numpy() takes the raw values,
# so they line up by position with the dates in pivot.index.
out = pd.DataFrame({"date": pd.to_datetime(pivot.index)})
out["bev_registrations"] = pivot[("Registrations", "Battery electric")].to_numpy()
out["phev_registrations"] = pivot[("Registrations", "Plug-in hybrid")].to_numpy()
out["total_registrations"] = pivot[("Registrations", "All drivetrains")].to_numpy()
out["bev_share"] = pivot[("Share of registrations (%)", "Battery electric")].to_numpy()
out["phev_share"] = pivot[("Share of registrations (%)", "Plug-in hybrid")].to_numpy()

# Keep the study window and sort chronologically, renumbering rows 0, 1, 2, ...
out = out[out["date"] >= START_DATE].sort_values("date").reset_index(drop=True)

# ------------------------------------------------------------------------------
# CHECKS
# ------------------------------------------------------------------------------
# 1. No missing values (a missing value would also block the int conversion).
if out.isna().any().any():
    print("WARNING: missing values:\n", out[out.isna().any(axis=1)])
for col in ["bev_registrations", "phev_registrations", "total_registrations"]:
    out[col] = out[col].astype("int64")

# 2. No missing months: compare with the full list of month starts ("MS")
#    between the first and last date.
expected = pd.date_range(out["date"].min(), out["date"].max(), freq="MS")
missing = expected.difference(out["date"])
if len(missing):
    print(f"WARNING: missing months: {list(missing.strftime('%Y-%m'))}")

# 3. Ember's share column should match our own computation (Ember rounds to
#    2 decimals, so allow a 0.01 percentage-point difference).
recomputed = 100 * out["bev_registrations"] / out["total_registrations"]
max_diff = (recomputed - out["bev_share"]).abs().max()
if max_diff > 0.01:
    print(f"WARNING: bev_share differs from recomputed share by up to {max_diff:.3f} pp")

# ------------------------------------------------------------------------------
# SAVE
# ------------------------------------------------------------------------------
# Parquet keeps the column types (dates, integers) and is what the model code
# should read; CSV is the human-readable copy (easy to open and to diff in git).
out.to_parquet(OUTPUT_DIR / "germany_ev_monthly.parquet", index=False)
out.to_csv(OUTPUT_DIR / "germany_ev_monthly.csv", index=False)
print(out.tail(10).to_string(index=False))
