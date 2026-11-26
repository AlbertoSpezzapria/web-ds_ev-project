# Data schema (shared by all countries)

Every country folder (`IT/`, `DE/`, ...) must produce tables with **the same names, columns,
units and definitions** described here. This way the datasets can be stacked into one panel
for the model. Column names follow the Italian pipeline. If you change a column, update this
file in the same commit.

## Conventions

| Topic | Rule |
|---|---|
| Time | One row per calendar month. `date` = first day of the month (`2026-10-01` = October 2026). |
| Window | From `2019-01-01` to the last month covered by **all** sources (inner join in the final dataset). |
| Shares | Percent, 0–100 (not 0–1). |
| Money | EUR, all taxes included. Prices per unit: `_eur_l`, `_eur_kwh`. Costs per 100 km: `_100km`. |
| Stocks | Charging points are measured on the **1st day** of the month. |
| Files | Every table is saved as `.parquet` (read by code, keeps types) **and** `.csv` (for people and git diffs). |
| Names | `<CC>/interim/<country>_<table>.(parquet\|csv)`, for example `DE/interim/germany_fuel_prices.parquet`. Final dataset: `<CC>/processed/<country>_dataset.(parquet\|csv)`. |
| Folders | `<CC>/raw_data/` = downloaded files, never edited by hand (except the incentive events table). `<CC>/interim/` = cleaned monthly tables. `<CC>/processed/` = final dataset. `common/` = shared scripts, templates and this file. |

## Interim tables

### `<country>_ev_monthly`: new car registrations (source: Ember, all countries)

| Column | Unit | Definition |
|---|---|---|
| `date` | date | Month |
| `bev_registrations` | cars | Battery electric cars registered (Ember "Battery electric") |
| `hybrid_registrations` | cars | Full hybrids that **cannot** be plugged in (HEV, Ember "Hybrid") |
| `plug-in_registrations` | cars | Plug-in hybrids (PHEV, Ember "Plug-in hybrid") |
| `total_registrations` | cars | All new cars (Ember "All drivetrains") |
| `bev_share` | % | BEV / total. **Target** |
| `plug-in_share` | % | PHEV / total. **Target** |
| `hybrid_share` | % | HEV / total |

HEVs are not EVs: they must never be added to `plug-in_*`.
Note: names with a hyphen (`plug-in_share`) need `df["plug-in_share"]`, because `df.plug-in_share` does not work.

### `<country>_fuel_prices`: pump prices (source: EU Weekly Oil Bulletin, "Prices with taxes")

| Column | Unit | Definition |
|---|---|---|
| `petrol_price_eur_l` | EUR/l | Euro-super 95, monthly mean of the weekly prices |
| `diesel_price_eur_l` | EUR/l | Automotive gas oil, same method |
| `cost_petrol_100km` | EUR | `petrol_price_eur_l × 6.5` |
| `cost_diesel_100km` | EUR | `diesel_price_eur_l × 5.5` |

### `<country>_electricity_prices`: electricity and running costs

The household price is a half-yearly Eurostat price (`nrg_pc_204`, band DC 2,500–4,999 kWh/year,
all taxes), spread over the months with the national consumer price index for electricity:
`price = index × k`, where `k = Eurostat price / half-year mean of the index`.

| Column | Unit | Definition |
|---|---|---|
| `elec_domestic_price_eur_kwh` | EUR/kWh | Household electricity price |
| `elec_public_price_eur_kwh` | EUR/kWh | Public charging price = domestic × `PUBLIC_TO_DOMESTIC_RATIO` (country-specific) |
| `cost_ev_100km` | EUR | BEV: blended price × 18 kWh. Blended price = `HOME_CHARGING_SHARE × domestic + (1 − HOME_CHARGING_SHARE) × public` |
| `cost_phev_100km` | EUR | PHEV: 0.5 × blended × 19 kWh + 0.5 × petrol × 6.0 l (half of the km electric) |
| `cost_hev_100km` | EUR | HEV: petrol × 5.0 l |
| `eurostat_sem_anchor_eur_kwh` | EUR/kWh | Eurostat half-year price used as the anchor. Empty when not yet published (that half-year reuses the last `k`) |
| `petrol_ev_cost_ratio` | ratio | `cost_petrol_100km / cost_ev_100km` (> 1: electric is cheaper) |
| `petrol_phev_cost_ratio` | ratio | `cost_petrol_100km / cost_phev_100km` |
| `petrol_hev_cost_ratio` | ratio | `cost_petrol_100km / cost_hev_100km` |

### `<country>_population`

| Column | Unit | Definition |
|---|---|---|
| `population` | people | Resident population. Months without official data are interpolated linearly between known values, and the latest months are **extrapolated linearly** using the latest trend |
| `source` | text | `ISTAT` / `Eurostat` (official), `Linear_Interpolation`, `Linear_Extrapolation` |

### `<country>_charging_points`: public charging points

| Column | Unit | Definition |
|---|---|---|
| `charging_points_normal` | points | Normal points (AC, ≤ 22 kW) |
| `charging_points_fast` | points | Fast points (> 22 kW, mostly DC) |
| `source` | text | Where the month's value comes from |
| `charging_points_total` | points | normal + fast |
| `is_interpolated` | bool | True if the month is not an official data point |
| `population` | people | From `<country>_population` |
| `charging_points_per_100k` | points | total / population × 100,000 |
| `charging_points_normal_per_100k` | points | normal / population × 100,000 |
| `charging_points_fast_per_100k` | points | fast / population × 100,000 |

Points are counted, not stations: a station with 2 sockets counts as 2.

### `<country>_incentive_amount` / `_incentive_dummy` / `_incentive_lags`

These come from the shared script `common/src/build_incentives.py --country <CC>`. Its input is a
hand-curated table `<CC>/raw_data/incentives/incentive_events_<CC>.csv`, with one row per
regime (a period with constant rules). The empty template is
`common/templates/incentive_events_TEMPLATE.csv`.

Events table:

| Column | Definition |
|---|---|
| `regime_id`, `name` | Short id (`R0`, `R1`, ...) and name |
| `change_type` | `new` / `increase` (buyers expected to **wait**) or `cut` / `end` (buyers expected to **buy earlier**) |
| `eligible_buyers` | e.g. `all`, `private`, `private_income_tested` |
| `announced_date` | First official announcement |
| `active_from`, `active_to` | Registration dates the regime applies to, both inclusive. Leave `active_to` empty if the regime is still in force. Regimes must not overlap |
| `application_open_date` | When buyers could actually apply (later than `active_from` = retroactive) |
| `bev_public_max_eur`, `phev_public_max_eur` | Maximum **public** grant per car |
| `bev_total_max_eur`, `phev_total_max_eur` | Same, including any mandatory manufacturer/dealer discount |
| `notes`, `source_1`, `source_2` | Rules and official sources (URLs) |

Monthly outputs (amounts are day-weighted means over the month; a dummy is 1 when at least 50% of the month's days are covered):

| Column | Unit | Definition |
|---|---|---|
| `incentive_amount_eur` | EUR | Maximum public grant for a BEV |
| `incentive_total_eur` | EUR | Same, including the manufacturer share |
| `incentive_amount_phev_eur` | EUR | Maximum public grant for a PHEV |
| `incentive_regime` | text | Regime in force for most of the month (label only, not a feature) |
| `incentive_announced_dummy` | 0/1 | A new or higher incentive is announced but not active yet |
| `incentive_cut_announced_dummy` | 0/1 | A cut or end is announced but not in force yet |
| `incentive_application_pending_dummy` | 0/1 | Cars already qualify but applications are not open yet |

`_incentive_lags.csv` has one row per regime with `lag_announce_to_active_days`, `lag_announce_to_application_days` and `retroactive`.

## Final dataset: `<CC>/processed/<country>_dataset`

It is the inner join on `date` of all the interim tables. The bookkeeping columns are removed:
`eurostat_sem_anchor_eur_kwh`, and `source`/`is_interpolated` of the charging points table.
The following columns are added:

| Column | Definition |
|---|---|
| `country` | ISO code (`IT`, `DE`, ...) |
| `elec_price_estimated` | 1 if the month's half-year has no Eurostat price yet |
| `ev_share` | 100 × (BEV + PHEV) / total. Aggregate **target** |
| `diesel_ev_cost_ratio` | `cost_diesel_100km / cost_ev_100km` |
| `petrol_ev_saving_100km`, `diesel_ev_saving_100km` | Cost per 100 km of petrol/diesel minus electric (EUR saved) |
| `charging_points_per_1k_cars` | total points / monthly registrations × 1000 (PDF formula, very seasonal) |
| `charging_points_per_1k_cars_12m` | Same with the registrations of the last 12 months (empty in the first 11 months) |
| `month_sin`, `month_cos` | sin/cos(2π · month / 12) |
| `d_<col>` | Change from the previous month, for: `bev_share`, `plug-in_share`, `ev_share`, `petrol_price_eur_l`, `diesel_price_eur_l`, `elec_domestic_price_eur_kwh`, `petrol_ev_cost_ratio`, `diesel_ev_cost_ratio`, `incentive_amount_eur`, `charging_points_total` |
| `<col>_lag<k>` | Value k = 1..12 months earlier, for: the three shares, the three prices, `petrol_ev_cost_ratio`, `petrol_phev_cost_ratio`, `diesel_ev_cost_ratio`, the two savings, `incentive_amount_eur`, `incentive_amount_phev_eur` and the three incentive dummies |

Leakage warning: to predict month t, do not use the same-month registrations or shares, their
`d_`, or `charging_points_per_1k_cars*` (they divide by the same-month registrations). Use the
`_lag` versions.

## Assumptions

Vehicle assumptions are the **same for every country**, so costs can be compared:

| Parameter | Value |
|---|---|
| Petrol car | 6.5 l/100 km |
| Diesel car | 5.5 l/100 km |
| BEV | 18 kWh/100 km (charging losses included) |
| PHEV | 50% of the km electric at 19 kWh/100 km, 50% on petrol at 6.0 l/100 km |
| HEV | 5.0 l/100 km |

Country-specific charging parameters (constant over time):

| Country | `PUBLIC_TO_DOMESTIC_RATIO` | `HOME_CHARGING_SHARE` | Sources |
|---|---|---|---|
| IT | 2.1 | 0.80 | *to be documented* |
| DE | 1.77 | 0.72 | **Ratio:** vzbv position paper, 26.05.2025, p. 5: mid-2024 public price 67 ct/kWh AC and 75 ct/kWh DC (Edison Media Charging Radar) vs a household price of 40.22 ct/kWh (BDEW). Mean (67 + 75) / 2 = 71 ct, and 71 / 40.22 = 1.77. A cross-check, LichtBlick Ladesäulencheck 2024, gives 1.44. **Share:** Nationale Leitstelle Ladeinfrastruktur, *Ladeinfrastruktur nach 2025/2030*, Neuauflage 2024, p. 26: home-charging share in 2023 = 70–74%, mid-point 72% |

## Status by country

| Table | IT | DE |
|---|---|---|
| ev_monthly | ✅ (`it-pipeline`) | ✅ |
| fuel_prices | ✅ | ✅ |
| electricity_prices | ✅ | ✅ |
| population | ✅ | ✅ (Eurostat on 1 January, interpolated and extrapolated) |
| charging_points | ⚠️ uses `charging_points_ac/dc`: rename to `normal/fast` | ✅ (BNetzA) |
| incentives | ❌ needs `IT/raw_data/incentives/incentive_events_IT.csv` | ✅ |
| final dataset | ❌ | ✅ (`DE/src/06_build_dataset.py`) |
