from pathlib import Path
import numpy as np
import pandas as pd

# 1. Configurazione percorsi
# Lo script sta in .../DS_project/IT/src/05_extraction_population.py
# Quindi .parent.parent punta a .../DS_project/IT/ e .parent.parent.parent punta a .../DS_project/
IT_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = IT_DIR.parent

# Cerca population.csv sia in DS_project/raw_data/ sia in DS_project/IT/raw_data/
if (PROJECT_ROOT / "raw_data" / "population.csv").exists():
  RAW_FILE = PROJECT_ROOT / "raw_data" / "population.csv"
elif (IT_DIR / "raw_data" / "population.csv").exists():
  RAW_FILE = IT_DIR / "raw_data" / "population.csv"
else:
  raise FileNotFoundError(
      "File population.csv non trovato né in raw_data/ né in IT/raw_data/"
  )

# Salva in IT/interim/ se esiste IT/, altrimenti nella root
INTERIM_DIR = (
    (IT_DIR / "interim")
    if (IT_DIR / "interim").exists()
    else (PROJECT_ROOT / "interim")
)
INTERIM_DIR.mkdir(parents=True, exist_ok=True)

# 2. Lettura del CSV IstatData
with open(RAW_FILE, "r", encoding="utf-8-sig", errors="replace") as f:
  first_line = f.readline()
sep = ";" if first_line.count(";") > first_line.count(",") else ","

df_raw = pd.read_csv(RAW_FILE, sep=sep, dtype=str)
df_raw.columns = [str(c).strip() for c in df_raw.columns]

# 3. Filtri di sicurezza (solo Italia, solo Totale Sesso, solo frequenza Mensile)
if "REF_AREA" in df_raw.columns:
  df_raw = df_raw[df_raw["REF_AREA"].str.strip().isin(["IT", "ITALIA"])]

if "SEX" in df_raw.columns:
  # In IstatData il totale maschi+femmine è codificato come 'T' o '9'
  tot_codes = [c for c in ["T", "9", "TOT"] if c in df_raw["SEX"].unique()]
  if tot_codes:
    df_raw = df_raw[df_raw["SEX"].isin(tot_codes)]

if "FREQ" in df_raw.columns:
  df_raw = df_raw[df_raw["FREQ"].str.strip() == "M"]

# 4. Estrazione Date ('TIME_PERIOD') e Valori ('Osservazione')
records = []
for _, row in df_raw.iterrows():
  t_str = str(row["TIME_PERIOD"]).strip().upper().replace("M", "-")
  # Accetta solo formati mensili YYYY-MM (scarta eventuali totali annuali)
  if len(t_str) >= 7 and t_str[:4].isdigit() and t_str[5:7].isdigit():
    date_val = pd.to_datetime(f"{t_str[:4]}-{t_str[5:7]}-01", errors="coerce")
    pop_clean = str(row["Osservazione"]).strip().replace(",", ".")
    pop_val = pd.to_numeric(pop_clean, errors="coerce")
    if pd.notna(date_val) and pd.notna(pop_val):
      records.append({"date": date_val, "population": pop_val})

if not records:
  raise ValueError(
      "Nessun record mensile estratto! Controlla i filtri o il contenuto di"
      " TIME_PERIOD / Osservazione."
  )

df_pop = (
    pd.DataFrame(records)
    .sort_values("date")
    .drop_duplicates(subset=["date"], keep="last")
)

# 5. Creazione griglia mensile continua: 2019-01-01 -> 2026-10-01
full_idx = pd.date_range(start="2019-01-01", end="2026-10-01", freq="MS")
df_monthly = df_pop.set_index("date").reindex(full_idx)
df_monthly.index.name = "date"

df_monthly["source"] = np.where(
    df_monthly["population"].notna(), "ISTAT", "Missing"
)

# Interpolazione eventuali buchi interni fino ad agosto 2026
df_monthly.loc[:"2026-08-01", "population"] = df_monthly.loc[
    :"2026-08-01", "population"
].interpolate(method="linear")
df_monthly.loc[
    (df_monthly.index <= "2026-08-01") & (df_monthly["source"] == "Missing"),
    "source",
] = "Linear_Interpolation"

# 6. Previsione Settembre e Ottobre 2026 dal trend Gennaio -> Agosto 2026
if pd.isna(df_monthly.loc["2026-09-01", "population"]) or pd.isna(
    df_monthly.loc["2026-10-01", "population"]
):
  pop_jan26 = df_monthly.loc["2026-01-01", "population"]
  pop_aug26 = df_monthly.loc["2026-08-01", "population"]

  if pd.isna(pop_jan26) or pd.isna(pop_aug26):
    raise ValueError(
        "Mancano i dati di Gennaio o Agosto 2026 per calcolare la proiezione."
    )

  monthly_drift = (pop_aug26 - pop_jan26) / 7.0

  if pd.isna(df_monthly.loc["2026-09-01", "population"]):
    df_monthly.loc["2026-09-01", "population"] = pop_aug26 + monthly_drift
    df_monthly.loc["2026-09-01", "source"] = "Linear_Extrapolation"

  if pd.isna(df_monthly.loc["2026-10-01", "population"]):
    df_monthly.loc["2026-10-01", "population"] = pop_aug26 + 2 * monthly_drift
    df_monthly.loc["2026-10-01", "source"] = "Linear_Extrapolation"

# 7. Formattazione finale e salvataggio
df_monthly["population"] = df_monthly["population"].round(0).astype("Int64")
df_monthly = df_monthly.reset_index()

csv_out = INTERIM_DIR / "italy_population.csv"
parquet_out = INTERIM_DIR / "italy_population.parquet"

df_monthly.to_csv(csv_out, index=False)
df_monthly.to_parquet(parquet_out, index=False)

print(
    f"Completato! Salvati {len(df_monthly)} mesi in {csv_out}"
)
print(df_monthly.tail(6))