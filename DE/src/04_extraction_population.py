"""Monthly population of Germany (source: Eurostat demo_pjan, population on 1 January).

Same output as IT/src/05_popolazione.py (see common/SCHEMA.md). Italy has
monthly ISTAT figures; Eurostat only gives Germany's population on 1 January
of each year, so the monthly series is built in two steps:
  - between two published 1 January values: linear interpolation;
  - after the last published value: linear extrapolation, continuing the
    monthly change of the last published year (e.g. Jan 2024 -> Jan 2025).
Eurostat publishes with about a year of delay, so the latest months are
always extrapolated. Note: Eurostat flags 2023 as a break in series (census
revision), hence the small step between 2022 and 2023.

Raw file (DE/raw_data/population/), downloaded from the Eurostat SDMX API:
  https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1/data/demo_pjan/A.NR.TOTAL.T.DE?format=SDMX-CSV&startPeriod=2018

Output: DE/interim/germany_population.(parquet|csv)
    date, population, source   (source: Eurostat / Linear_Interpolation / Linear_Extrapolation)
Must run before 05_extraction_charging_points.py, which uses it.
"""
from pathlib import Path

import pandas as pd

# ------------------------------------------------------------------------------
# CONFIGURATION AND PATHS
# ------------------------------------------------------------------------------
START_DATE = "2019-01-01"
END_DATE = "2026-11-01"  # last month needed by the other DE tables

BASE_DIR = Path(__file__).resolve().parent.parent  # .../DE
FILE_POPULATION = BASE_DIR / "raw_data" / "population" / "demo_pjan_DE.csv"
INTERIM_DIR = BASE_DIR / "interim"
INTERIM_DIR.mkdir(parents=True, exist_ok=True)


def build() -> pd.DataFrame:
    pop = pd.read_csv(FILE_POPULATION, usecols=["TIME_PERIOD", "OBS_VALUE"])
    # TIME_PERIOD is the year: the value refers to 1 January of that year.
    pop["date"] = pd.to_datetime(pop["TIME_PERIOD"].astype(str) + "-01-01")
    known = pop.set_index("date")["OBS_VALUE"].astype(float).sort_index()

    # Every month from the first published year to END_DATE.
    months = pd.date_range(min(known.index.min(), pd.Timestamp(START_DATE)), END_DATE, freq="MS")
    series = known.reindex(months)

    source = pd.Series("Linear_Interpolation", index=months)
    source[series.notna()] = "Eurostat"

    # 1. Months between two known 1 January values: straight line between them.
    series = series.interpolate(method="linear", limit_area="inside")

    # 2. Months after the last known value: keep the monthly change of the last
    #    published year (last value - previous value, divided by 12 months).
    last_date = known.index[-1]
    monthly_change = (known.iloc[-1] - known.iloc[-2]) / 12
    after = months > last_date
    months_after = ((months[after].year - last_date.year) * 12
                    + months[after].month - last_date.month)
    series[after] = known.iloc[-1] + monthly_change * months_after
    source[after] = "Linear_Extrapolation"

    out = pd.DataFrame({"date": months, "population": series.round().astype("int64"),
                        "source": source.to_numpy()})
    return out[out["date"] >= START_DATE].reset_index(drop=True)


if __name__ == "__main__":
    df = build()
    # Parquet for code, CSV for people and git diffs.
    df.to_parquet(INTERIM_DIR / "germany_population.parquet", index=False)
    df.to_csv(INTERIM_DIR / "germany_population.csv", index=False)
    print(df.groupby("source")["date"].agg(["min", "max", "count"]))
    print(df.tail(4).to_string(index=False))
