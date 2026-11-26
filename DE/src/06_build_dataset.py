"""Final monthly dataset for Germany: all raw features + derived features (IT/datasets.pdf).

Column names and definitions follow common/SCHEMA.md (Italian pipeline names).

Run order (from the repository root):
    .venv/bin/python DE/src/01_extraction_ev_phev.py
    .venv/bin/python DE/src/02_extraction_prices.py
    .venv/bin/python DE/src/03_extraction_electricity.py      (needs 02)
    .venv/bin/python DE/src/04_extraction_population.py
    .venv/bin/python DE/src/05_extraction_charging_points.py  (needs 04)
    .venv/bin/python common/src/build_incentives.py --country DE
    .venv/bin/python DE/src/06_build_dataset.py

Inputs (DE/interim/): germany_ev_monthly, germany_fuel_prices,
germany_electricity_prices, germany_charging_points (includes population),
germany_incentive_amount, germany_incentive_dummy.

Output: DE/processed/germany_dataset.(parquet|csv), one row per month, only the
months covered by EVERY input (inner join): currently 2019-01 to 2026-10.

Columns added here (the others come unchanged from the interim tables):
    country                           "DE"
    elec_price_estimated              1 if the month's half-year has no Eurostat price yet
    ev_share                          bev_share + plug-in_share (percent)
    diesel_ev_cost_ratio              cost_diesel_100km / cost_ev_100km
    petrol_ev_saving_100km            cost_petrol_100km - cost_ev_100km (EUR saved per 100 km)
    diesel_ev_saving_100km            cost_diesel_100km - cost_ev_100km
    charging_points_per_1k_cars       charging_points_total / total_registrations * 1000 (PDF formula;
                                      very seasonal because monthly registrations are)
    charging_points_per_1k_cars_12m   same, dividing by registrations of the last 12 months
                                      (NaN in the first 11 months)
    month_sin, month_cos              sin/cos(2*pi*month/12): December and January are neighbours
    d_<col>                           change from the previous month (t - t-1)
    <col>_lag<k>                      value k months earlier, k = 1..12

Lags and differences need earlier months, so they are NaN at the start of the
series (up to 12 rows). The rows are kept: the modelling code decides how to
handle them.
"""
from pathlib import Path

import numpy as np
import pandas as pd

# ------------------------------------------------------------------------------
# CONFIGURATION
# ------------------------------------------------------------------------------
COUNTRY = "DE"
MAX_LAG = 12  # months

# Columns that get lags t-1..t-12: target history (baseline model), prices,
# cost spreads and incentives, as listed in the PDF.
LAG_COLS = [
    "bev_share", "plug-in_share", "ev_share",
    "petrol_price_eur_l", "diesel_price_eur_l", "elec_domestic_price_eur_kwh",
    "petrol_ev_cost_ratio", "petrol_phev_cost_ratio", "diesel_ev_cost_ratio",
    "petrol_ev_saving_100km", "diesel_ev_saving_100km",
    "incentive_amount_eur", "incentive_amount_phev_eur",
    "incentive_announced_dummy", "incentive_cut_announced_dummy",
    "incentive_application_pending_dummy",
]

# Columns that get a month-on-month difference (to make series stationary).
DIFF_COLS = [
    "bev_share", "plug-in_share", "ev_share",
    "petrol_price_eur_l", "diesel_price_eur_l", "elec_domestic_price_eur_kwh",
    "petrol_ev_cost_ratio", "diesel_ev_cost_ratio",
    "incentive_amount_eur", "charging_points_total",
]

# ------------------------------------------------------------------------------
# PATHS
# ------------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent  # .../DE
INTERIM_DIR = BASE_DIR / "interim"
OUTPUT_DIR = BASE_DIR / "processed"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def read_interim(name: str) -> pd.DataFrame:
    """Read one of the parquet tables produced by the earlier scripts."""
    path = INTERIM_DIR / f"germany_{name}.parquet"
    if not path.exists():
        raise FileNotFoundError(f"{path} not found: run the earlier scripts first")
    return pd.read_parquet(path)


def merge_raw() -> pd.DataFrame:
    """Join all interim tables on date, keeping only months present in all of them."""
    ev = read_interim("ev_monthly")
    fuel = read_interim("fuel_prices")
    elec = read_interim("electricity_prices")
    # 1 where the half-year had no Eurostat anchor yet (price extrapolated).
    elec["elec_price_estimated"] = elec["eurostat_sem_anchor_eur_kwh"].isna().astype("int64")
    elec = elec.drop(columns="eurostat_sem_anchor_eur_kwh")
    # source / is_interpolated describe how each month was built: kept in the
    # interim table for traceability, not needed as model features.
    charging = read_interim("charging_points").drop(columns=["source", "is_interpolated"])
    amount = read_interim("incentive_amount")
    dummy = read_interim("incentive_dummy")

    df = ev
    for other in [fuel, elec, charging, amount, dummy]:
        df = df.merge(other, on="date", how="inner")
    df = df.sort_values("date").reset_index(drop=True)

    # The inner join must not leave holes in the monthly sequence.
    expected = pd.date_range(df["date"].min(), df["date"].max(), freq="MS")
    if len(expected) != len(df):
        raise ValueError("Missing months after the merge: check the interim tables")

    df.insert(0, "country", COUNTRY)
    return df


def add_derived(df: pd.DataFrame) -> pd.DataFrame:
    """Add the derived features of the PDF (section 2) not already in the interim tables."""
    out = df.copy()

    # --- derived target -------------------------------------------------------
    # All cars with a plug (BEV + PHEV), in percent like the other shares.
    out["ev_share"] = (
        100 * (out["bev_registrations"] + out["plug-in_registrations"]) / out["total_registrations"]
    ).round(2)

    # --- relative convenience of electric driving -----------------------------
    # (petrol_*_cost_ratio already comes from the electricity table.)
    out["diesel_ev_cost_ratio"] = (out["cost_diesel_100km"] / out["cost_ev_100km"]).round(3)
    # EUR saved per 100 km when driving electric instead of petrol/diesel.
    out["petrol_ev_saving_100km"] = out["cost_petrol_100km"] - out["cost_ev_100km"]
    out["diesel_ev_saving_100km"] = out["cost_diesel_100km"] - out["cost_ev_100km"]

    # --- infrastructure vs car sales ---------------------------------------------
    # (per 100k inhabitants already comes from the charging points table.)
    out["charging_points_per_1k_cars"] = out["charging_points_total"] / out["total_registrations"] * 1000
    registrations_12m = out["total_registrations"].rolling(12).sum()  # NaN for the first 11 months
    out["charging_points_per_1k_cars_12m"] = out["charging_points_total"] / registrations_12m * 1000

    # --- seasonality ------------------------------------------------------------
    # Placing the months on a circle makes December (12) and January (1) as close
    # as any other two consecutive months.
    month = out["date"].dt.month
    out["month_sin"] = np.sin(2 * np.pi * month / 12)
    out["month_cos"] = np.cos(2 * np.pi * month / 12)

    # --- month-on-month differences -------------------------------------------
    # .diff() = value this month minus value last month (rows are sorted by date).
    diffs = {f"d_{col}": out[col].diff() for col in DIFF_COLS}

    # --- lags ---------------------------------------------------------------
    # .shift(k) moves the series down k rows, so row t gets the value of t-k.
    lags = {
        f"{col}_lag{k}": out[col].shift(k)
        for col in LAG_COLS
        for k in range(1, MAX_LAG + 1)
    }

    # Add the many new columns in one go (faster and avoids pandas warnings).
    out = pd.concat([out, pd.DataFrame(diffs), pd.DataFrame(lags)], axis=1)

    # Round the float columns to a readable precision.
    float_cols = out.select_dtypes("float").columns
    out[float_cols] = out[float_cols].round(5)
    return out


if __name__ == "__main__":
    dataset = add_derived(merge_raw())

    # Parquet for code, CSV for people and git diffs.
    dataset.to_parquet(OUTPUT_DIR / "germany_dataset.parquet", index=False)
    dataset.to_csv(OUTPUT_DIR / "germany_dataset.csv", index=False)

    n_lag = sum("_lag" in c for c in dataset.columns)
    print(f"{len(dataset)} months ({dataset['date'].min():%Y-%m} to {dataset['date'].max():%Y-%m}), "
          f"{dataset.shape[1]} columns ({n_lag} lag columns)")
    preview = [
        "date", "bev_share", "ev_share", "cost_petrol_100km", "cost_ev_100km",
        "petrol_ev_cost_ratio", "charging_points_per_100k",
        "charging_points_per_1k_cars_12m", "incentive_amount_eur",
    ]
    print(dataset[preview].tail(6).to_string(index=False))
