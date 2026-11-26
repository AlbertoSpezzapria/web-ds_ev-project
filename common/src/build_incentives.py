"""Monthly incentive features for one country, built from a hand-curated events table.

Shared by all countries. Usage (from the repository root):
    .venv/bin/python common/src/build_incentives.py --country DE
    .venv/bin/python common/src/build_incentives.py --country IT

Input: <CC>/raw_data/incentives/incentive_events_<CC>.csv (CC = DE, IT, ...).
An empty table with the required columns is in
common/templates/incentive_events_TEMPLATE.csv. It has one row per
"regime" (a period with constant rules), with the official sources. Each row
keeps three kinds of dates, so the announcement-to-activation lag stays traceable:
  announced_date        : first official announcement
  active_from/active_to : registration dates the regime applies to (inclusive).
                          This is when the incentive is ACTUALLY active for buyers,
                          retroactivity included.
  application_open_date : when buyers could actually apply
change_type is one of: new, increase, cut, end (see common/SCHEMA.md).

Outputs (<CC>/interim/, prefix = germany / italy / ...):

1. <prefix>_incentive_amount.(csv|parquet)
   incentive_amount_eur       max PUBLIC grant for a standard BEV (PDF definition)
   incentive_total_eur        same, including the manufacturer share (what buyers saw)
   incentive_amount_phev_eur  max public grant for a PHEV
   incentive_regime           regime active for most days of the month
   Monthly values are day-weighted means over the month's days: e.g. Dec 2023
   = 4500 EUR * 17/31, because the bonus stopped on 18 Dec.

2. <prefix>_incentive_dummy.(csv|parquet)
   incentive_announced_dummy            1 while a NEW/HIGHER incentive is announced
                                        but not yet active (expected: buyers wait)
   incentive_cut_announced_dummy        1 while a CUT/END is announced but not yet
                                        effective (expected: buyers pull forward)
   incentive_application_pending_dummy  1 while cars already qualify but the
                                        application process isn't open yet
                                        (buyers face uncertainty)
   A month is 1 when the window covers at least half of its days.

3. <prefix>_incentive_lags.csv: one row per regime with the lags in days
   (announcement -> activation, announcement -> application opening).
"""
import argparse
from pathlib import Path

import pandas as pd

# ------------------------------------------------------------------------------
# CONFIGURATION AND PATHS
# ------------------------------------------------------------------------------
START_DATE = "2019-01-01"
END_DATE = "2026-11-01"   # default last month (same window as the other tables)
DUMMY_MIN_SHARE = 0.5     # share of a month's days a window must cover for the dummy to be 1

REPO_DIR = Path(__file__).resolve().parent.parent.parent  # repository root
# Country code -> prefix of the output file names (as in the other interim tables).
FILE_PREFIX = {"DE": "germany", "IT": "italy", "FR": "france", "ES": "spain"}

# Set in main() from the command line (--country); used by the functions below.
EVENTS_FILE: Path
INTERIM_DIR: Path

DATE_COLS = ["announced_date", "active_from", "active_to", "application_open_date"]
# Column in the events table -> column name in the monthly output.
AMOUNT_COLS = {
    "bev_public_max_eur": "incentive_amount_eur",
    "bev_total_max_eur": "incentive_total_eur",
    "phev_public_max_eur": "incentive_amount_phev_eur",
}


def load_events() -> pd.DataFrame:
    """Read the events table, close open-ended regimes and check they don't overlap."""
    ev = pd.read_csv(EVENTS_FILE, parse_dates=DATE_COLS)

    # A regime still in force (empty active_to) runs to the end of the study window.
    open_ended = ev["active_to"].isna()
    ev.loc[open_ended, "active_to"] = pd.Timestamp(END_DATE) + pd.offsets.MonthEnd(0)

    # Regimes must not overlap, otherwise a day would have two amounts.
    # After sorting, each regime must start after the previous one ends.
    ev = ev.sort_values("active_from").reset_index(drop=True)
    overlap = ev["active_from"].iloc[1:].to_numpy() <= ev["active_to"].iloc[:-1].to_numpy()
    if overlap.any():
        raise ValueError(f"Overlapping regimes in {EVENTS_FILE.name}:\n{ev.loc[1:][overlap]}")
    return ev


def daily_amounts(ev: pd.DataFrame, days: pd.DatetimeIndex) -> pd.DataFrame:
    """One row per calendar day with the amounts of the regime active on that day (0 if none)."""
    daily = pd.DataFrame(index=days, columns=list(AMOUNT_COLS) + ["regime_id"])
    daily[list(AMOUNT_COLS)] = 0.0
    daily["regime_id"] = "none"
    for _, r in ev.iterrows():
        mask = (days >= r["active_from"]) & (days <= r["active_to"])
        for col in AMOUNT_COLS:
            daily.loc[mask, col] = float(r[col])
        daily.loc[mask, "regime_id"] = r["regime_id"]
    return daily


def window_flags(days: pd.DatetimeIndex, windows: list[tuple]) -> pd.Series:
    """1 on each day inside any [start, end) window, 0 elsewhere.

    Windows with a missing date or with end <= start (e.g. retroactive
    incentives, active the day after the announcement) are ignored.
    """
    flag = pd.Series(0, index=days)
    for start, end in windows:
        if pd.notna(start) and pd.notna(end) and end > start:
            flag[(days >= start) & (days < end)] = 1
    return flag


def build():
    ev = load_events()

    # Work day by day, then average per month: this handles regimes that
    # start or stop in the middle of a month.
    days = pd.date_range(START_DATE, pd.Timestamp(END_DATE) + pd.offsets.MonthEnd(0), freq="D")
    month = days.to_period("M").to_timestamp()  # the month (1st day) each day belongs to

    # --- amounts --------------------------------------------------------------
    daily = daily_amounts(ev, days)
    # Day-weighted mean: the average of the daily amounts over the month.
    amounts = daily[list(AMOUNT_COLS)].astype(float).groupby(month).mean().round(0)
    amounts = amounts.rename(columns=AMOUNT_COLS).astype("int64")
    # Label each month with the regime that was active for most of its days.
    amounts["incentive_regime"] = daily["regime_id"].groupby(month).agg(lambda s: s.value_counts().idxmax())
    amounts = amounts.rename_axis("date").reset_index()

    # --- dummies --------------------------------------------------------------
    # Split regimes by direction: new/higher incentives make buyers WAIT,
    # cuts/ends make them BUY EARLIER, so they get separate dummies.
    raising = ev[ev["change_type"].isin(["new", "increase"])]
    cutting = ev[ev["change_type"].isin(["cut", "end"])]
    daily_flags = pd.DataFrame({
        # announced -> active (only when activation comes after the announcement)
        "incentive_announced_dummy": window_flags(
            days, list(zip(raising["announced_date"], raising["active_from"]))),
        "incentive_cut_announced_dummy": window_flags(
            days, list(zip(cutting["announced_date"], cutting["active_from"]))),
        # cars already qualify (active_from) but applications not open yet
        "incentive_application_pending_dummy": window_flags(
            days, list(zip(ev["active_from"], ev["application_open_date"]))),
    }, index=days)
    # Monthly mean of a 0/1 daily flag = share of the month's days covered;
    # the month gets 1 if that share is at least DUMMY_MIN_SHARE.
    dummies = (daily_flags.groupby(month).mean() >= DUMMY_MIN_SHARE).astype("int64")
    dummies = dummies.rename_axis("date").reset_index()

    # --- lag reference table --------------------------------------------------
    # Keeps the announcement -> activation information that the monthly
    # features summarise, so lags can be checked or used to build other features.
    lags = ev[["regime_id", "name", "change_type"] + DATE_COLS].copy()
    lags["lag_announce_to_active_days"] = (lags["active_from"] - lags["announced_date"]).dt.days
    lags["lag_announce_to_application_days"] = (
        lags["application_open_date"] - lags["announced_date"]).dt.days
    # Retroactive = cars qualified before buyers could apply.
    lags["retroactive"] = lags["application_open_date"] > lags["active_from"]

    return amounts, dummies, lags


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build monthly incentive features for one country.")
    parser.add_argument("--country", required=True, choices=sorted(FILE_PREFIX), help="country code, e.g. DE")
    parser.add_argument("--end", default=END_DATE, help=f"last month, YYYY-MM-01 (default {END_DATE})")
    args = parser.parse_args()

    END_DATE = args.end
    EVENTS_FILE = REPO_DIR / args.country / "raw_data" / "incentives" / f"incentive_events_{args.country}.csv"
    INTERIM_DIR = REPO_DIR / args.country / "interim"
    if not EVENTS_FILE.exists():
        raise FileNotFoundError(
            f"{EVENTS_FILE} not found: copy common/templates/incentive_events_TEMPLATE.csv there and fill it in")
    INTERIM_DIR.mkdir(parents=True, exist_ok=True)
    prefix = FILE_PREFIX[args.country]

    amounts, dummies, lags = build()
    # Parquet for code, CSV for people and git diffs.
    amounts.to_parquet(INTERIM_DIR / f"{prefix}_incentive_amount.parquet", index=False)
    amounts.to_csv(INTERIM_DIR / f"{prefix}_incentive_amount.csv", index=False)
    dummies.to_parquet(INTERIM_DIR / f"{prefix}_incentive_dummy.parquet", index=False)
    dummies.to_csv(INTERIM_DIR / f"{prefix}_incentive_dummy.csv", index=False)
    lags.to_csv(INTERIM_DIR / f"{prefix}_incentive_lags.csv", index=False)

    print(lags.drop(columns=["name"]).to_string(index=False))
    # Print only the months where some value changes, for a quick visual check.
    both = amounts.merge(dummies, on="date")
    changed = both.drop(columns="date").ne(both.drop(columns="date").shift()).any(axis=1)
    print("\nMonths where something changes:")
    print(both[changed].to_string(index=False))
