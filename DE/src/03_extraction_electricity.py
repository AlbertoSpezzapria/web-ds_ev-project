"""Monthly household electricity price for Germany in EUR/kWh (all taxes included).

Same method as IT/src/03_extraction_electricity.py, but with Eurostat sources only:
  - monthly SHAPE: HICP electricity index, CP0451, dataset prc_hicp_minr (2025=100).
    An index says how prices move month to month, but has no unit (not EUR).
  - LEVEL: nrg_pc_204, band DC (2 500-4 999 kWh/year), all taxes, EUR/kWh.
    A real price, but only one value per half-year ("semester").

For each half-year: k = Eurostat price / mean of the 6 monthly index values,
then monthly price = index * k. So the 6 monthly prices of a half-year average
exactly to the Eurostat price, while following the monthly ups and downs of
the index. Half-years that Eurostat hasn't published yet reuse the last
available k (forward fill).

Note: Eurostat froze prc_hicp_midx (base 2015) at Dec 2025. prc_hicp_minr has
one continuous 2025=100 series from 2019, so (unlike the ISTAT files for Italy)
no rebasing step is needed.

Raw files (DE/raw_data/electricity/), downloaded from the Eurostat SDMX API:
  https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1/data/prc_hicp_minr/M.I25.CP0451.DE?format=SDMX-CSV&startPeriod=2019-01
  https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1/data/nrg_pc_204/S.E7000.KWH2500-4999.KWH.I_TAX.EUR.DE?format=SDMX-CSV&startPeriod=2019-S1

Output: DE/interim/germany_electricity_prices.(parquet|csv)
    date, elec_price_eur_kwh, eurostat_sem_anchor_eur_kwh
"""
from pathlib import Path

import numpy as np
import pandas as pd

# ------------------------------------------------------------------------------
# PATHS
# ------------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent  # .../DE
RAW_DIR = BASE_DIR / "raw_data" / "electricity"
INTERIM_DIR = BASE_DIR / "interim"
INTERIM_DIR.mkdir(parents=True, exist_ok=True)

FILE_HICP = RAW_DIR / "hicp_electricity_cp0451_monthly.csv"
FILE_EUROSTAT = RAW_DIR / "nrg_pc_204_semiannual.csv"


def load_hicp(filepath: Path) -> pd.DataFrame:
    """Monthly HICP electricity index -> columns: date, index_val.

    TIME_PERIOD looks like "2024-03"; adding "-01" gives a full date
    (first day of the month), the same convention as the other tables.
    """
    df = pd.read_csv(filepath, usecols=["TIME_PERIOD", "OBS_VALUE"])
    df["date"] = pd.to_datetime(df["TIME_PERIOD"] + "-01")
    return (
        df.rename(columns={"OBS_VALUE": "index_val"})[["date", "index_val"]]
        .sort_values("date")
        .reset_index(drop=True)
    )


def load_eurostat(filepath: Path) -> pd.DataFrame:
    """Half-yearly price (band DC, all taxes, EUR/kWh) -> semester, eurostat_eur_kwh.

    The download is already filtered to band DC, but we filter again in case
    the file is re-downloaded with more bands. TIME_PERIOD looks like "2024-S1".
    """
    df = pd.read_csv(filepath, usecols=["nrg_cons", "TIME_PERIOD", "OBS_VALUE"])
    df = df[df["nrg_cons"] == "KWH2500-4999"]
    return df.rename(
        columns={"TIME_PERIOD": "semester", "OBS_VALUE": "eurostat_eur_kwh"}
    )[["semester", "eurostat_eur_kwh"]]


def build_monthly_electricity_prices() -> pd.DataFrame:
    hicp = load_hicp(FILE_HICP)

    # Label each month with its half-year in the same format as Eurostat
    # ("2024-S1" for Jan-Jun, "2024-S2" for Jul-Dec), so the tables can be joined.
    hicp["semester"] = (
        hicp["date"].dt.year.astype(str)
        + "-S"
        + np.where(hicp["date"].dt.month <= 6, "1", "2")
    )

    eurostat = load_eurostat(FILE_EUROSTAT)

    # Average index value per half-year.
    sem_mean = hicp.groupby("semester", as_index=False)["index_val"].mean()

    # Attach the Eurostat price to each half-year (left join: half-years not yet
    # published by Eurostat stay in the table with a NaN price).
    anchor = sem_mean.merge(eurostat, on="semester", how="left").sort_values("semester")

    # k converts "index points" into EUR/kWh for that half-year.
    # ffill() copies the last known k into half-years without a Eurostat price.
    anchor["k_factor"] = (anchor["eurostat_eur_kwh"] / anchor["index_val"]).ffill()

    unanchored = anchor.loc[anchor["eurostat_eur_kwh"].isna(), "semester"].tolist()
    if unanchored:
        print(f"NOTE: no Eurostat price yet for {unanchored}; reusing the last k_factor.")

    # Give every month the k of its half-year, then convert index -> EUR/kWh.
    out = hicp.merge(anchor[["semester", "k_factor", "eurostat_eur_kwh"]], on="semester")
    out["elec_price_eur_kwh"] = (out["index_val"] * out["k_factor"]).round(5)

    # Check: each published half-year's monthly mean must equal the Eurostat price
    # (that is the whole point of the method; a mismatch means a bug).
    check = out.dropna(subset=["eurostat_eur_kwh"]).groupby("semester").agg(
        monthly_mean=("elec_price_eur_kwh", "mean"), eurostat=("eurostat_eur_kwh", "first")
    )
    if ((check["monthly_mean"] - check["eurostat"]).abs() > 1e-3).any():
        print("WARNING: monthly prices don't average back to the Eurostat anchor:\n", check)

    # Keep the Eurostat half-year price next to the monthly value for traceability
    # (NaN in half-years where it was extrapolated with the previous k).
    return out[["date", "elec_price_eur_kwh", "eurostat_eur_kwh"]].rename(
        columns={"eurostat_eur_kwh": "eurostat_sem_anchor_eur_kwh"}
    )


if __name__ == "__main__":
    df_elec = build_monthly_electricity_prices()
    # Parquet for code, CSV for people and git diffs.
    df_elec.to_parquet(INTERIM_DIR / "germany_electricity_prices.parquet", index=False)
    df_elec.to_csv(INTERIM_DIR / "germany_electricity_prices.csv", index=False)
    print(df_elec.to_string(index=False))
