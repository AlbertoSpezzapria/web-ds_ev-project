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

From the domestic price, like the Italy script (IT/src/03_elettricità.py), we
derive the public charging price, the blended price an EV driver actually
pays (home + public charging) and the running cost per 100 km of BEV, PHEV and
HEV. The two Germany-specific parameters come from these sources:

  PUBLIC_TO_DOMESTIC_RATIO = 1.77
    vzbv (Verbraucherzentrale Bundesverband), position paper "Elektromobilität
    stärken - öffentliche Ladepreise senken", 26.05.2025, p. 5:
    mid-2024 average public price 67 ct/kWh AC and 75 ct/kWh DC
    (data: Edison Media "Charging Radar" 2024) vs 40.22 ct/kWh household price
    (data: BDEW Strompreisanalyse May 2025).
    Mean of AC and DC = 71 ct/kWh -> 71 / 40.22 = 1.77.
    https://www.vzbv.de/sites/default/files/2025-06/25-05-26_Positionspapier_G%C3%BCnstig%20Laden_barrierefrei.pdf
    Cross-check: LichtBlick "Ladesäulencheck 2024" finds lower prices
    (AC 55, DC 66 ct/kWh vs 42 ct/kWh household -> 1.44), so 1.77 is the upper
    end of the published range (ad-hoc/roaming prices, not cheap subscriptions).

  HOME_CHARGING_SHARE = 0.72
    Nationale Leitstelle Ladeinfrastruktur (NOW GmbH), "Ladeinfrastruktur nach
    2025/2030: Szenarien für den Markthochlauf", Neuauflage 2024, printed p. 26 (PDF p. 13):
    home-charging share for 2023 assumed at 70-74 % (mid-point 72 %), based on
    surveys by UScale, dena, KfW, Fraunhofer ISI and NPM.
    https://nationale-leitstelle.de/wp-content/uploads/2025/09/Studie-LIS-2025-2030-Neuauflage-2024.pdf
    The remaining 28 % is charged at the public price (it also includes
    workplace charging, which is often cheaper: a conservative choice).

Both are kept constant over time, as in the Italy pipeline (2.1 and 0.80 there).
Vehicle consumptions are the same as Italy, so costs are comparable.

Output: DE/interim/germany_electricity_prices.(parquet|csv)
    date, elec_domestic_price_eur_kwh, elec_public_price_eur_kwh,
    cost_ev_100km, cost_phev_100km, cost_hev_100km, eurostat_sem_anchor_eur_kwh,
    petrol_ev_cost_ratio, petrol_phev_cost_ratio, petrol_hev_cost_ratio
Needs DE/interim/germany_fuel_prices (script 02) for the PHEV/HEV costs.
"""
from pathlib import Path

import numpy as np
import pandas as pd

# ------------------------------------------------------------------------------
# PARAMETERS (sources in the module docstring)
# ------------------------------------------------------------------------------
PUBLIC_TO_DOMESTIC_RATIO = 1.77  # public charging price / household price (Germany)
HOME_CHARGING_SHARE = 0.72       # share of EV charging done at home (Germany)

# Vehicle consumptions, identical to the Italy pipeline (common/SCHEMA.md).
CONS_EV_KWH = 18.0         # BEV, kWh/100 km incl. charging losses
PHEV_ELECTRIC_SHARE = 0.5  # share of PHEV km driven on electricity (utility factor)
CONS_PHEV_KWH = 19.0       # PHEV in electric mode, kWh/100 km
CONS_PHEV_PETROL = 6.0     # PHEV with empty battery, l/100 km
CONS_HEV_PETROL = 5.0      # full hybrid, l/100 km

# ------------------------------------------------------------------------------
# PATHS
# ------------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent  # .../DE
RAW_DIR = BASE_DIR / "raw_data" / "electricity"
INTERIM_DIR = BASE_DIR / "interim"
INTERIM_DIR.mkdir(parents=True, exist_ok=True)

FILE_HICP = RAW_DIR / "hicp_electricity_cp0451_monthly.csv"
FILE_EUROSTAT = RAW_DIR / "nrg_pc_204_semiannual.csv"
FILE_FUEL = INTERIM_DIR / "germany_fuel_prices.parquet"  # output of script 02


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
    out["elec_domestic_price_eur_kwh"] = (out["index_val"] * out["k_factor"]).round(5)

    # Check: each published half-year's monthly mean must equal the Eurostat price
    # (that is the whole point of the method; a mismatch means a bug).
    check = out.dropna(subset=["eurostat_eur_kwh"]).groupby("semester").agg(
        monthly_mean=("elec_domestic_price_eur_kwh", "mean"), eurostat=("eurostat_eur_kwh", "first")
    )
    if ((check["monthly_mean"] - check["eurostat"]).abs() > 1e-3).any():
        print("WARNING: monthly prices don't average back to the Eurostat anchor:\n", check)

    # --- public and blended charging price -------------------------------------
    domestic = out["elec_domestic_price_eur_kwh"]
    out["elec_public_price_eur_kwh"] = (domestic * PUBLIC_TO_DOMESTIC_RATIO).round(5)
    # What an average EV driver pays per kWh: home share at the domestic price,
    # the rest at the public price.
    blended = (HOME_CHARGING_SHARE * domestic
               + (1 - HOME_CHARGING_SHARE) * out["elec_public_price_eur_kwh"])

    # --- running cost per 100 km ------------------------------------------------
    out["cost_ev_100km"] = (blended * CONS_EV_KWH).round(2)
    # PHEV and HEV also burn petrol: take the monthly petrol price from script 02.
    if not FILE_FUEL.exists():
        raise FileNotFoundError(f"{FILE_FUEL} not found: run 02_extraction_prices.py first")
    fuel = pd.read_parquet(FILE_FUEL, columns=["date", "petrol_price_eur_l", "cost_petrol_100km"])
    out = out.merge(fuel, on="date", how="left")
    # PHEV: half of the km on electricity, half on petrol (utility factor 0.5).
    out["cost_phev_100km"] = (
        PHEV_ELECTRIC_SHARE * blended * CONS_PHEV_KWH
        + (1 - PHEV_ELECTRIC_SHARE) * out["petrol_price_eur_l"] * CONS_PHEV_PETROL
    ).round(2)
    out["cost_hev_100km"] = (out["petrol_price_eur_l"] * CONS_HEV_PETROL).round(2)

    # --- convenience ratios (> 1: the alternative is cheaper than petrol) --------
    for kind in ["ev", "phev", "hev"]:
        out[f"petrol_{kind}_cost_ratio"] = (
            out["cost_petrol_100km"] / out[f"cost_{kind}_100km"]
        ).round(3)

    # Keep the Eurostat half-year price next to the monthly value for traceability
    # (NaN in half-years where it was extrapolated with the previous k).
    # Same columns and order as the Italy table.
    return out.rename(columns={"eurostat_eur_kwh": "eurostat_sem_anchor_eur_kwh"})[[
        "date", "elec_domestic_price_eur_kwh", "elec_public_price_eur_kwh",
        "cost_ev_100km", "cost_phev_100km", "cost_hev_100km", "eurostat_sem_anchor_eur_kwh",
        "petrol_ev_cost_ratio", "petrol_phev_cost_ratio", "petrol_hev_cost_ratio",
    ]]


if __name__ == "__main__":
    df_elec = build_monthly_electricity_prices()
    # Parquet for code, CSV for people and git diffs.
    df_elec.to_parquet(INTERIM_DIR / "germany_electricity_prices.parquet", index=False)
    df_elec.to_csv(INTERIM_DIR / "germany_electricity_prices.csv", index=False)
    print(df_elec.to_string(index=False))
