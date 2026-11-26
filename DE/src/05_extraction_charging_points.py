"""Monthly stock of public charging points in Germany (source: Bundesnetzagentur only).

Official source page: https://www.bundesnetzagentur.de/ladeinfrastruktur
Two files from that page are used (in DE/raw_data/charging_points/):

1. "Ladeinfrastruktur in Zahlen" (xlsx, sheet "3.1 Ladepunkte")
   Official QUARTERLY stock of public charging points (normal / fast / total) on
   the 1st of Jan, Apr, Jul, Oct since 2017. This sets the LEVEL.

2. "Liste der Ladesäulen" / Ladesäulenregister (csv, ~58 MB, not committed to git)
   Every charging station in the published register, with its commissioning
   date (Inbetriebnahmedatum) and number of charging points. Counting the
   points commissioned before each month gives the MONTHLY SHAPE.
   It is not used for the level because it counts fewer points than the
   official statistics:
     - it only lists stations whose BNetzA notification procedure is complete
       (the file's own header says the real number is higher);
     - stations decommissioned in the past are no longer in it, so the gap
       grows going back in time (about 13.4k vs 19.8k official in Jan 2019).

Method (same idea as the electricity script): on each official quarter date,
ratio = official stock / register count. The ratio is linearly interpolated over
the months in between and multiplied by the register count. On quarter dates the
result equals the official figure exactly.

Stocks are measured on the 1st day of each month, like the official table
("Stand 01. Oktober 2026" = stock at 2026-10-01). Units are charging POINTS,
not stations: a station with 2 sockets counts as 2.

Normal points (Normalladepunkte, AC up to 22 kW) = total - fast; fast points
(Schnellladepunkte) are those above 22 kW, mostly DC.

Output: DE/interim/germany_charging_points.(parquet|csv), same columns as Italy
(common/SCHEMA.md):
    date, charging_points_normal, charging_points_fast, source,
    charging_points_total, is_interpolated, population,
    charging_points_per_100k, charging_points_normal_per_100k, charging_points_fast_per_100k
source = "BNetzA_official" on quarter dates, "BNetzA_register_scaled" in the
other months (is_interpolated = True). The raw register count is not saved:
it is not a reliable level.
Needs DE/interim/germany_population (script 04).
"""
from pathlib import Path
from urllib.request import Request, urlopen

import pandas as pd

# ------------------------------------------------------------------------------
# CONFIGURATION AND PATHS
# ------------------------------------------------------------------------------
START_DATE = "2019-01-01"  # same time window as the other tables

BASE_DIR = Path(__file__).resolve().parent.parent  # .../DE
RAW_DIR = BASE_DIR / "raw_data" / "charging_points"
INTERIM_DIR = BASE_DIR / "interim"
INTERIM_DIR.mkdir(parents=True, exist_ok=True)

FILE_STATS = RAW_DIR / "Ladesaeuleninfrastruktur_in_Zahlen.xlsx"
FILE_POPULATION = INTERIM_DIR / "germany_population.parquet"  # output of script 04

# Direct link to the register CSV, taken from the BNetzA page. The file name
# contains the publication date: update it when a newer list is published.
REGISTER_URL = (
    "https://data.bundesnetzagentur.de/Bundesnetzagentur/DE/Fachthemen/"
    "ElektrizitaetundGas/E-Mobilitaet/Ladesaeulenregister_BNetzA_2026-11-12.csv"
)
FILE_REGISTER = RAW_DIR / REGISTER_URL.rsplit("/", 1)[1]  # same name as on the server


def ensure_register() -> None:
    """The register CSV is too big for git (see .gitignore): download it from BNetzA if missing."""
    if FILE_REGISTER.exists():
        return
    print(f"Downloading {REGISTER_URL} ...")
    # Some servers reject requests without a browser-like User-Agent.
    req = Request(REGISTER_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req) as resp:
        FILE_REGISTER.write_bytes(resp.read())


def load_official_quarterly() -> pd.DataFrame:
    """Sheet "3.1 Ladepunkte" -> date, official_normal, official_fast, official_total."""
    raw = pd.read_excel(FILE_STATS, sheet_name="3.1 Ladepunkte", header=None)

    # The table is horizontal: one label column holds "Anzahl Ladepunkte" (the
    # row with the dates), "Normalladepunkte", "Schnellladepunkte" and
    # "Ladepunkte insgesamt"; each column to the right of it is one quarter.
    # We locate the labels by searching every cell instead of hard-coding
    # row/column numbers, so the code survives small layout changes.
    labels = {
        "Anzahl Ladepunkte": "date",
        "Normalladepunkte": "official_normal",
        "Schnellladepunkte": "official_fast",
        "Ladepunkte insgesamt": "official_total",
    }
    found = {
        labels[str(raw.iat[r, c]).strip()]: (r, c)  # output name -> (row, column) of the label
        for r in range(raw.shape[0])
        for c in range(raw.shape[1])
        if str(raw.iat[r, c]).strip() in labels
    }
    if len(found) != 4:
        raise ValueError(f"Unexpected layout in {FILE_STATS.name}: found {found}")

    # Read each labelled row from the column after the label to the end of the
    # sheet; each becomes a column of the output. dropna() removes empty cells.
    label_col = found["date"][1]
    df = pd.DataFrame({
        name: raw.iloc[row, label_col + 1:].to_numpy() for name, (row, _) in found.items()
    }).dropna()
    df["date"] = pd.to_datetime(df["date"])
    return df.astype({c: "int64" for c in df.columns if c != "date"}).reset_index(drop=True)


def load_register_monthly(dates: pd.DatetimeIndex) -> pd.DataFrame:
    """For each date, the points commissioned BEFORE it (= stock on that day), by type."""
    # The CSV is Latin-1 encoded, ';'-separated, with 10 lines of notes before
    # the header. Only the first 8 columns are needed (they include the
    # commissioning date and the number of points); dtype=str avoids pandas
    # guessing types on a 58 MB file.
    df = pd.read_csv(
        FILE_REGISTER, sep=";", encoding="latin1", skiprows=10, usecols=range(8), dtype=str
    )
    df["commissioned"] = pd.to_datetime(df["Inbetriebnahmedatum"], format="%d.%m.%Y", errors="coerce")
    df["points"] = pd.to_numeric(df["Anzahl Ladepunkte"], errors="coerce")
    bad = df["commissioned"].isna() | df["points"].isna()
    if bad.any():
        print(f"WARNING: dropping {bad.sum()} register rows without date or point count")
    df = df[~bad]
    # "Schnellladeeinrichtung" = fast charger, "Normalladeeinrichtung" = normal.
    df["fast"] = df["Art der Ladeeinrichtung"].str.startswith("Schnell")

    out = pd.DataFrame({"date": dates})
    for name, mask in [("register_total", slice(None)), ("register_fast", df["fast"])]:
        # Sort by commissioning date and take the running total of points:
        # cum[i] = points of the first i+1 stations to be commissioned.
        sub = df.loc[mask].sort_values("commissioned")
        cum = sub["points"].cumsum().to_numpy()
        # searchsorted(side="left") gives, for each date, how many stations were
        # commissioned strictly before it; the stock is the running total there.
        idx = sub["commissioned"].searchsorted(dates, side="left")
        out[name] = [int(cum[i - 1]) if i > 0 else 0 for i in idx]
    return out


def scale_to_official(monthly: pd.DataFrame, official: pd.DataFrame, reg_col: str, off_col: str) -> pd.Series:
    """Rescale a register count so that it matches the official stock on quarter dates."""
    # Ratio official/register: known on quarter dates, NaN in the other months.
    ratio = monthly[["date"]].merge(
        official[["date", off_col]], on="date", how="left"
    )[off_col] / monthly[reg_col]
    # Fill the months in between with a straight line between the two nearest
    # quarters; after the last quarter keep the last ratio.
    ratio = ratio.interpolate(method="linear").ffill().bfill()
    return (monthly[reg_col] * ratio).round().astype("int64")


def build() -> pd.DataFrame:
    ensure_register()
    official = load_official_quarterly()

    # Monthly dates from START_DATE to the latest official quarter
    # (we don't extrapolate beyond the official data).
    last_official = official["date"].max()
    dates = pd.date_range(START_DATE, last_official, freq="MS")

    monthly = load_register_monthly(dates)
    monthly["charging_points_total"] = scale_to_official(monthly, official, "register_total", "official_total")
    monthly["charging_points_fast"] = scale_to_official(monthly, official, "register_fast", "official_fast")

    # Check 1: quarter dates must match the official table exactly.
    chk = monthly.merge(official, on="date")
    if (chk["charging_points_total"] != chk["official_total"]).any():
        print("WARNING: monthly totals don't match the official quarterly figures")
    # Check 2: a stock of chargers should never go down from one month to the next.
    if (monthly["charging_points_total"].diff().dropna() < 0).any():
        print("WARNING: the stock decreases in some months:")
        print(monthly[monthly["charging_points_total"].diff() < 0])

    # Normal = total - fast (on quarter dates this equals the official normal count).
    monthly["charging_points_normal"] = monthly["charging_points_total"] - monthly["charging_points_fast"]
    on_quarter = monthly["date"].isin(official["date"])
    monthly["is_interpolated"] = ~on_quarter
    monthly["source"] = on_quarter.map({True: "BNetzA_official", False: "BNetzA_register_scaled"})

    # --- density per 100,000 inhabitants ---------------------------------------
    if not FILE_POPULATION.exists():
        raise FileNotFoundError(f"{FILE_POPULATION} not found: run 04_extraction_population.py first")
    pop = pd.read_parquet(FILE_POPULATION, columns=["date", "population"])
    monthly = monthly.merge(pop, on="date", how="left")
    for col, name in [("charging_points_total", "charging_points_per_100k"),
                      ("charging_points_normal", "charging_points_normal_per_100k"),
                      ("charging_points_fast", "charging_points_fast_per_100k")]:
        monthly[name] = (monthly[col] / monthly["population"] * 100_000).round(2)

    return monthly[[
        "date", "charging_points_normal", "charging_points_fast", "source",
        "charging_points_total", "is_interpolated", "population",
        "charging_points_per_100k", "charging_points_normal_per_100k", "charging_points_fast_per_100k",
    ]]


if __name__ == "__main__":
    df = build()
    # Parquet for code, CSV for people and git diffs.
    df.to_parquet(INTERIM_DIR / "germany_charging_points.parquet", index=False)
    df.to_csv(INTERIM_DIR / "germany_charging_points.csv", index=False)
    print(df.to_string(index=False))
