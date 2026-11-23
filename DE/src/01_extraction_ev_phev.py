"""Monthly BEV / PHEV / total car registrations for Germany (source: Ember).

Mirrors IT/src/01_extraction_ev_phev.py and produces the same columns, with one
deliberate difference: phev_* uses ONLY the "Plug-in hybrid" drivetrain. Ember's
"Hybrid" category is non-plug-in full hybrids (HEV), which are not PHEVs.
"""
from pathlib import Path

import pandas as pd

COUNTRY = "Germany"
START_DATE = "2019-01-01"  # same window as the Italy pipeline

BASE_DIR = Path(__file__).resolve().parent.parent          # .../DE
REPO_DIR = BASE_DIR.parent
# The Ember file is multi-country and already in the repo under IT/raw_data:
# read it from there instead of duplicating it.
INPUT_FILE = REPO_DIR / "IT" / "raw_data" / "ember_dataset.csv"
OUTPUT_DIR = BASE_DIR / "interim"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

if not INPUT_FILE.exists():
    raise FileNotFoundError(f"File not found: {INPUT_FILE}")

df = pd.read_csv(INPUT_FILE)
df = df[(df["Area"] == COUNTRY) & (df["Data frequency"] == "Monthly")].copy()
if df.empty:
    raise ValueError(f"No monthly rows found for Area == '{COUNTRY}'.")

# One row per month, one column per (metric, drivetrain).
pivot = df.pivot_table(
    index="Date",
    columns="Drivetrain",
    values=["Registrations", "Share of registrations (%)"],
    aggfunc="sum",
)

out = pd.DataFrame({"date": pd.to_datetime(pivot.index)})
out["bev_registrations"] = pivot[("Registrations", "Battery electric")].to_numpy()
out["phev_registrations"] = pivot[("Registrations", "Plug-in hybrid")].to_numpy()
out["total_registrations"] = pivot[("Registrations", "All drivetrains")].to_numpy()
out["bev_share"] = pivot[("Share of registrations (%)", "Battery electric")].to_numpy()
out["phev_share"] = pivot[("Share of registrations (%)", "Plug-in hybrid")].to_numpy()

out = out[out["date"] >= START_DATE].sort_values("date").reset_index(drop=True)

# --- checks -------------------------------------------------------------------
if out.isna().any().any():
    print("WARNING: missing values:\n", out[out.isna().any(axis=1)])
for col in ["bev_registrations", "phev_registrations", "total_registrations"]:
    out[col] = out[col].astype("int64")

expected = pd.date_range(out["date"].min(), out["date"].max(), freq="MS")
missing = expected.difference(out["date"])
if len(missing):
    print(f"WARNING: missing months: {list(missing.strftime('%Y-%m'))}")

# Ember's share column should match our own computation (rounded to 2 decimals).
recomputed = 100 * out["bev_registrations"] / out["total_registrations"]
max_diff = (recomputed - out["bev_share"]).abs().max()
if max_diff > 0.01:
    print(f"WARNING: bev_share differs from recomputed share by up to {max_diff:.3f} pp")

out.to_parquet(OUTPUT_DIR / "germany_ev_monthly.parquet", index=False)
out.to_csv(OUTPUT_DIR / "germany_ev_monthly.csv", index=False)
print(out.tail(10).to_string(index=False))
