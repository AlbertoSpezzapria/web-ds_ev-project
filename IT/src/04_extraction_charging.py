from pathlib import Path
import pandas as pd

# ==============================================================================
# 1. CONFIGURAZIONE PERCORSI
# ==============================================================================
BASE_DIR = (
    Path(__file__).resolve().parent.parent
    if "__file__" in globals()
    else Path.cwd()
)

RAW_DIR = BASE_DIR / "raw_data" / "charging_points"
OUTPUT_DIR = BASE_DIR / "interim"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def find_file(directory: Path, stem_name: str, extensions: tuple) -> Path:
  """Cerca il file nella cartella provando le estensioni più comuni."""
  for ext in extensions:
    candidate = directory / f"{stem_name}{ext}"
    if candidate.exists():
      return candidate
  raise FileNotFoundError(
      f"File '{stem_name}' non trovato in {directory} con estensioni"
      f" {extensions}"
  )


file_18_19 = find_file(RAW_DIR, "CP_18-19", (".xlsx", ".xls"))
file_20_26 = find_file(RAW_DIR, "CP_20-26", (".csv", ".txt"))


# ==============================================================================
# 2. ESTRAZIONE DATI ANNUALI 2018-2019 (IEA - EXCEL)
# ==============================================================================
xls_iea = pd.ExcelFile(file_18_19)
sheet_iea = (
    "GEVO_EV_2026" if "GEVO_EV_2026" in xls_iea.sheet_names else xls_iea.sheet_names[0]
)
df_iea_raw = pd.read_excel(file_18_19, sheet_name=sheet_iea)

# Filtriamo per Italia, parametro 'EV charging points' e anni 2018-2019
mask_iea = (
    (df_iea_raw["region_country"].astype(str).str.strip() == "Italy")
    & (
        df_iea_raw["parameter"].astype(str).str.strip()
        == "EV charging points"
    )
    & (pd.to_numeric(df_iea_raw["year"], errors="coerce").isin([2018, 2019]))
)
df_iea_it = df_iea_raw.loc[mask_iea].copy()

if df_iea_it.empty:
  raise ValueError(
      "Nessun dato trovato per Italy (2018-2019) in CP_18-19. Verifica i filtri"
      " o il nome del foglio."
  )

# Mappiamo 'Publicly available slow' -> AC, 'fast' / 'ultra-fast' -> DC
def map_powertrain(val: str) -> str:
  v = str(val).lower()
  if "slow" in v:
    return "ac"
  elif "fast" in v:  # cattura sia 'fast' sia 'ultra-fast'
    return "dc"
  return "other"


df_iea_it["type"] = df_iea_it["powertrain"].apply(map_powertrain)
df_iea_it["value"] = pd.to_numeric(df_iea_it["value"], errors="coerce")

# Aggreghiamo per anno e tipo (AC vs DC)
df_iea_piv = (
    df_iea_it[df_iea_it["type"].isin(["ac", "dc"])]
    .pivot_table(index="year", columns="type", values="value", aggfunc="sum")
    .fillna(0)
    .reset_index()
)

# I consuntivi IEA sono al 31 dicembre -> associamo al mese di dicembre ('YYYY-12-01')
df_iea_piv["date"] = pd.to_datetime(
    df_iea_piv["year"].astype(int).astype(str) + "-12-01"
)
df_iea_clean = pd.DataFrame({
    "date": df_iea_piv["date"],
    "charging_points_ac": df_iea_piv["ac"],
    "charging_points_dc": df_iea_piv["dc"],
    "source": "IEA",
})


# ==============================================================================
# 3. ESTRAZIONE DATI TRIMESTRALI 2020-2026 (EAFO - CSV)
# ==============================================================================
# Rileviamo automaticamente il separatore del CSV (, oppure ;)
with open(file_20_26, "r", encoding="utf-8-sig") as f:
  first_line = f.readline()
sep = ";" if ";" in first_line and "," not in first_line else ","

df_eafo_raw = pd.read_csv(file_20_26, sep=sep)
df_eafo_raw.columns = [str(c).strip() for c in df_eafo_raw.columns]

# Identifichiamo la colonna delle etichette trimestrali (es. '2020 Q1' o 'Category')
quarter_col = None
for col in df_eafo_raw.columns:
  if df_eafo_raw[col].astype(str).str.contains(r"20\d{2}\s*Q[1-4]", regex=True).any():
    quarter_col = col
    break

if quarter_col is None:
  raise ValueError(
      f"Impossibile trovare la colonna con i trimestri (es. '2020 Q1') in {file_20_26}."
      f" Colonne presenti: {df_eafo_raw.columns.tolist()}"
  )

# Mappiamo ogni trimestre al suo mese di chiusura (Q1->03, Q2->06, Q3->09, Q4->12)
quarter_to_month = {"Q1": "03", "Q2": "06", "Q3": "09", "Q4": "12"}


def parse_eafo_quarter(q_str: str):
  s = str(q_str).strip()
  parts = s.replace("-", " ").split()
  if len(parts) == 2 and parts[1] in quarter_to_month:
    return pd.to_datetime(f"{parts[0]}-{quarter_to_month[parts[1]]}-01")
  return pd.NaT


df_eafo_clean = pd.DataFrame()
df_eafo_clean["date"] = df_eafo_raw[quarter_col].apply(parse_eafo_quarter)
df_eafo_clean = df_eafo_clean.dropna(subset=["date"]).copy()

# Troviamo le colonne AC e DC nel CSV EAFO
ac_cols = [c for c in df_eafo_raw.columns if c.upper() == "AC" or "AC" in c.upper().split()]
dc_cols = [c for c in df_eafo_raw.columns if c.upper() == "DC" or "DC" in c.upper().split()]

if not ac_cols or not dc_cols:
  raise ValueError(
      f"Colonne AC e/o DC non trovate in {file_20_26}."
      f" Colonne presenti: {df_eafo_raw.columns.tolist()}"
  )

df_eafo_clean["charging_points_ac"] = pd.to_numeric(
    df_eafo_raw.loc[df_eafo_clean.index, ac_cols[0]], errors="coerce"
)
df_eafo_clean["charging_points_dc"] = pd.to_numeric(
    df_eafo_raw.loc[df_eafo_clean.index, dc_cols[0]], errors="coerce"
)
df_eafo_clean["source"] = "EAFO"


# ==============================================================================
# 4. UNIONE DEI RILEVAMENTI NATIVI E INTERPOLAZIONE LINEARE MENSILE
# ==============================================================================
df_anchors = (
    pd.concat([df_iea_clean, df_eafo_clean], ignore_index=True)
    .sort_values("date")
    .drop_duplicates(subset=["date"], keep="last")
    .reset_index(drop=True)
)

df_anchors["charging_points_total"] = (
    df_anchors["charging_points_ac"] + df_anchors["charging_points_dc"]
)

# Salviamo anche la serie nativa non interpolata (utile per il robustness check)
native_parquet = OUTPUT_DIR / "italy_charging_points_native.parquet"
native_csv = OUTPUT_DIR / "italy_charging_points_native.csv"
df_anchors.to_parquet(native_parquet, index=False)
df_anchors.to_csv(native_csv, index=False)

# Creiamo l'indice mensile continuo dall'ancora 2018-12-01 fino all'ultimo mese disponibile
start_anchor = df_anchors["date"].min()
end_anchor = df_anchors["date"].max()
full_monthly_idx = pd.date_range(start=start_anchor, end=end_anchor, freq="MS")

df_monthly = df_anchors.set_index("date").reindex(full_monthly_idx)
df_monthly.index.name = "date"

# Segnaliamo quali mesi sono rilevamenti reali e quali sono interpolati
df_monthly["is_interpolated"] = df_monthly["charging_points_total"].isna()

# Interpolazione lineare sui mesi intermedi (stock lento)
cols_to_interp = ["charging_points_ac", "charging_points_dc"]
df_monthly[cols_to_interp] = (
    df_monthly[cols_to_interp].interpolate(method="linear").round(0)
)

# Ricalcoliamo il totale come somma esatta di AC e DC interpolati
df_monthly["charging_points_total"] = (
    df_monthly["charging_points_ac"] + df_monthly["charging_points_dc"]
)
df_monthly["source"] = df_monthly["source"].fillna("Linear_Interpolation")

df_monthly = df_monthly.reset_index()

# Filtriamo dal 2019-01-01 (scartando dicembre 2018 che serviva solo come punto di ancoraggio)
# Tronchiamo eventualmente a 2026-10-01 per evitare il Q4 2026 incompleto; rimuovi il filtro superiore se vuoi tenerlo
df_monthly = df_monthly[
    (df_monthly["date"] >= "2019-01-01") & (df_monthly["date"] <= "2026-10-01")
].reset_index(drop=True)

# Conversione finale a interi per pulizia
for col in ["charging_points_ac", "charging_points_dc", "charging_points_total"]:
  df_monthly[col] = df_monthly[col].astype("Int64")


# ==============================================================================
# 5. CONTROLLI DI QUALITÀ E SALVATAGGIO SU DISCO
# ==============================================================================
if df_monthly[["charging_points_ac", "charging_points_dc", "charging_points_total"]].isna().any().any():
  print("ATTENZIONE: Sono presenti valori NaN nella serie mensile delle colonnine!")

parquet_path = OUTPUT_DIR / "italy_charging_points.parquet"
csv_path = OUTPUT_DIR / "italy_charging_points.csv"
df_monthly.to_parquet(parquet_path, index=False)
df_monthly.to_csv(csv_path, index=False)

print("Primi 15 mesi (incluso raccordo 2019-2020):")
print(df_monthly.head(15).to_string(index=False))
print("\nUltimi 10 mesi:")
print(df_monthly.tail(10).to_string(index=False))