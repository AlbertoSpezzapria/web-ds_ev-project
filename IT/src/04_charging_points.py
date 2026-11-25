from pathlib import Path
import pandas as pd

# ==============================================================================
# PERCORSI
# ==============================================================================
BASE_DIR = (
    Path(__file__).resolve().parent.parent
    if "__file__" in globals()
    else Path.cwd()
)

RAW_DIR = BASE_DIR / "raw_data" / "charging_points"
OUTPUT_DIR = BASE_DIR / "interim"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
file_18_19 = RAW_DIR/ "CP_18-19.xlsx"
file_20_26 = RAW_DIR/ "CP_20-26.csv"





# ==============================================================================
# ESTRAZIONE DATI ANNUALI 2018-2019 (IEA - EXCEL)
# ==============================================================================

sheet_iea = "GEVO_EV_2026"
# il file excel scaricato ha diverse pagine, sheet_iea nome della pagina in cui guardare

df_iea_raw = pd.read_excel(file_18_19, sheet_name=sheet_iea)
# df_iea_raw = DF del file excel file_18_19


mask_iea = (
    (df_iea_raw["region_country"].astype(str).str.strip() == "Italy")
    & (
        df_iea_raw["parameter"].astype(str).str.strip()
        == "EV charging points"
    )
    & (pd.to_numeric(df_iea_raw["year"], errors="coerce").isin([2018, 2019]))
)
# mask_iea = maschera = lista di valori booleani con tante righe quante sono le righe nel file excel file_18_19 
# una certa riga del file excel non viene "oscurata" da mask_iea se e solo se quella riga è sull'italia + la riga riporta dai sui charging points + l'anno di riferimento è 2018 o 2019


df_iea_it = df_iea_raw.loc[mask_iea].copy()
# df_iea_it = DF uguale a df_iea_raw mascherato-> df_iea_it = DF con solo righe sull'italia nel 2018 e 2019 riguardanti diversi tipi di colonnine (veloci, lente....)



def map_powertrain(val: str) -> str:
  v = str(val).lower()
  if "slow" in v:
    return "ac"
  elif "fast" in v:  # cattura sia 'fast' sia 'ultra-fast'
    return "dc"
  return "other"
# il dataset IEA classifica le colonnine in fast e slow mentre l'EAFO in AC e DC. Questa funzione riceve una riga del dataset IEA e restituisce la corrispondente classe in termini EAFO



df_iea_it["type"] = df_iea_it["powertrain"].apply(map_powertrain)
# .apply(ƒ) -> applica la funzione in input d ogni riga del DF in reference 
# ora df_iea_it ha una riga in più che indica il tipo di colonnina 

df_iea_it["value"] = pd.to_numeric(df_iea_it["value"], errors="coerce")
# la colonna value era salvata come string, ora è un int/float (a seconda dei casi)
# errors="coerce" -> se un valore non è convertibile da str a int, lo sostituisce con NaN


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
# la colonna date era un str, ora è un datatime nel formato YYYY-MM-DD

df_iea_clean = pd.DataFrame({
    "date": df_iea_piv["date"],
    "charging_points_ac": df_iea_piv["ac"],
    "charging_points_dc": df_iea_piv["dc"],
    "source": "IEA",
})
# df_iea_clean = df_iea_piv selezionando e rinominando le colonne 




# ==============================================================================
# ESTRAZIONE DATI TRIMESTRALI 2020-2026 (EAFO - CSV)
# ==============================================================================
sep = ","
# in genere il CSV separa le colonne con una virgola, però a volte può capitare che siano separate da un punto e virgola. 

df_eafo_raw = pd.read_csv(file_20_26, sep=sep)
df_eafo_raw.columns = [str(c).strip() for c in df_eafo_raw.columns]
# df_eafo_raw = DF del file csv file_20_26 con i nomi delle colonne puliti (con strip)


quarter_to_month = {"Q1": "03", "Q2": "06", "Q3": "09", "Q4": "12"}
# Mappiamo ogni trimestre al suo mese di chiusura (Q1->03, Q2->06, Q3->09, Q4->12)


def parse_eafo_quarter(q_str: str):
  s = str(q_str).strip()
  parts = s.split()
  if len(parts) == 2 and parts[1] in quarter_to_month:
    return pd.to_datetime(f"{parts[0]}-{quarter_to_month[parts[1]]}-01")
  return pd.NaT
# nel file EAFO la colonna data è scritta "2021 Q2". Questa funzione prende in ingresso una riga e la converte nel formato datetime a seconda del semestre


df_eafo_clean = pd.DataFrame()
df_eafo_clean["date"] = df_eafo_raw[df_eafo_raw.columns[0]].apply(parse_eafo_quarter)
df_eafo_clean = df_eafo_clean.dropna(subset=["date"]).copy()
# df_eafo_clean = DF con una sola colonna contenente le date che c'erano in df_eafo_raw  nel formato datetime eliminando eventuali righe in cui c'è NaT



ac_cols = [c for c in df_eafo_raw.columns if c.upper() == "AC" or "AC" in c.upper().split()]
dc_cols = [c for c in df_eafo_raw.columns if c.upper() == "DC" or "DC" in c.upper().split()]
if not ac_cols or not dc_cols:
  raise ValueError(
      f"Colonne AC e/o DC non trovate in {file_20_26}."
      f" Colonne presenti: {df_eafo_raw.columns.tolist()}"
  )
# Troviamo le colonne AC e DC nel CSV EAFO


df_eafo_clean["charging_points_ac"] = pd.to_numeric(
    df_eafo_raw.loc[df_eafo_clean.index, ac_cols[0]], errors="coerce"
)
df_eafo_clean["charging_points_dc"] = pd.to_numeric(
    df_eafo_raw.loc[df_eafo_clean.index, dc_cols[0]], errors="coerce"
)
df_eafo_clean["source"] = "EAFO"
# ora df_eafo_clean = DF con le colonne date, colonnine AC, colonnine DC, fonte del dato (che può essere EAFO, IEA o interpolazione)


# ==============================================================================
# UNIONE DEI RILEVAMENTI NATIVI E INTERPOLAZIONE LINEARE MENSILE
# ==============================================================================
# ricordiamo che sia df_iea_clean che df_eafo_clean = = DF con le colonne date, colonnine AC, colonnine DC, fonte del dato (che può essere EAFO, IEA o interpolazione)


df_anchors = (
    pd.concat([df_iea_clean, df_eafo_clean], ignore_index=True)
    .sort_values("date")
    .drop_duplicates(subset=["date"], keep="last")
    .reset_index(drop=True)
)
# drop_duplicates -> nel caso i 2 dataset si sovrappongano, teniamo solo l'ocorrenza di df_eafo_clean (keep=last)
# df_anchors = DF dato dall'unione di df_iea_clean e df_eafo_clean con le colonne date, colonnine AC, colonnine DC, fonte del dato



df_anchors["charging_points_total"] = (
    df_anchors["charging_points_ac"] + df_anchors["charging_points_dc"]
)
# aggiungiamo la colonna charging_points_total data dalla somma di ac e dc



# CODICE PER SALVARE LA SERIE NATIVA NON INTERPOLATA (utile per il robustness check)

#native_parquet = OUTPUT_DIR / "italy_charging_points_native.parquet"
#native_csv = OUTPUT_DIR / "italy_charging_points_native.csv"
#df_anchors.to_parquet(native_parquet, index=False)
#df_anchors.to_csv(native_csv, index=False)



start_anchor = df_anchors["date"].min()
end_anchor = df_anchors["date"].max()
full_monthly_idx = pd.date_range(start=start_anchor, end=end_anchor, freq="MS")
# full_monthly_idx = serie di date con frequenza mensile da start_anchor a end_anchor

df_monthly = df_anchors.set_index("date").reindex(full_monthly_idx)
# set_index fa diventare date l'indice del DF df_anchors
# reindex -> forza gli indici di df_anchors a essere uguali agli indici in full_monthly_idx.
# Il risultato è che se l'indice corrente è già presente in df_anchors allora la riga rimane invariata, altrimenti si aggiunge una riga con la data in questione e il resto NaN

df_monthly.index.name = "date"
# con set_index la colonna delle data non si chiama più date ma index, con questa riga torna a chiamarsi date



# Segnaliamo quali mesi sono rilevamenti reali e quali sono interpolati
df_monthly["is_interpolated"] = df_monthly["charging_points_total"].isna()
# creazione nuova colonna is_interpolated che ci dice quando un dato è interpolato 


cols_to_interp = ["charging_points_ac", "charging_points_dc"]
df_monthly[cols_to_interp] = (
    df_monthly[cols_to_interp].interpolate(method="linear").round(0)
)
# interpolate prende le due colonne selezionate e (singolarmente) sostituisce ogni blocco di valori mancanti (NaN) tracciando una retta a incremento costante tra il valore 
# reale precedente e quello successivo (cioè fa l'interpolazione)



df_monthly["charging_points_total"] = (
    df_monthly["charging_points_ac"] + df_monthly["charging_points_dc"]
)
# aggiorniamo la colonna charging_points_total


df_monthly["source"] = df_monthly["source"].fillna("Linear_Interpolation")
# nella colonna source sostituisce tutti i valori NaN con "Linear_Interpolation"


df_monthly = df_monthly.reset_index()
# fa si che l'indice di df_monthly non sia più la colonna date ma un'indice progressivo costruito ad hoc. 
# Questo è necessario perchè per esemprimere condizioni sull'indice (come di seguito) e per poter stampare nel file CSV finale l'indice ci vuole del codice ad hoc.
# per semplicità, riportiamo date ad essere una colonna normale.


df_monthly = df_monthly[
    (df_monthly["date"] >= "2019-01-01") & (df_monthly["date"] <= "2026-10-01")
].reset_index(drop=True)
# Filtriamo dal 2019-01-01 (scartando dicembre 2018 che serviva solo come punto di ancoraggio)
# Tronchiamo eventualmente a 2026-10-01 per evitare il Q4 2026 incompleto; rimuovi il filtro superiore se vuoi tenerlo



for col in ["charging_points_ac", "charging_points_dc", "charging_points_total"]:
  df_monthly[col] = df_monthly[col].astype("Int64")
# Conversione finale a interi per pulizia (il numero di colonnine è sicuramente intero)


# ==============================================================================
# NORMALIZZAZIONE SULLA POPOLAZIONE (COLONNINE PER 100.000 ABITANTI)
# ==============================================================================
pop_path = OUTPUT_DIR / "italy_population.csv"
if not pop_path.exists():
  raise FileNotFoundError(
      f"File {pop_path} non trovato. Esegui prima 05_extraction_population.py!"
  )

df_pop = pd.read_csv(pop_path, parse_dates=["date"])
# Leggiamo la serie mensile della popolazione italiana e convertiamo 'date' in datetime

df_monthly = pd.merge(
    df_monthly,
    df_pop[["date", "population"]],
    on="date",
    how="left",
)
# Uniamo la colonna 'population' a df_monthly allineando le righe tramite la colonna 'date'



df_monthly["charging_points_per_100k"] = (
    (df_monthly["charging_points_total"] / df_monthly["population"]) * 100_000
).round(2)

df_monthly["charging_points_ac_per_100k"] = (
    (df_monthly["charging_points_ac"] / df_monthly["population"]) * 100_000
).round(2)

df_monthly["charging_points_dc_per_100k"] = (
    (df_monthly["charging_points_dc"] / df_monthly["population"]) * 100_000
).round(2)

# Calcolo le colonnine ogni 100.000 abitanti (totali, AC e DC) arrotondate a 2 decimali





# ==============================================================================
# CONTROLLI DI QUALITÀ E SALVATAGGIO 
# ==============================================================================

if (
    df_monthly[[
        "charging_points_ac",
        "charging_points_dc",
        "charging_points_total",
        "population",
        "charging_points_per_100k",
    ]]
    .isna()
    .any()
    .any()
):
  print("ATTENZIONE: Sono presenti valori NaN nella serie mensile delle colonnine!")




parquet_path = OUTPUT_DIR / "italy_charging_points.parquet"
csv_path = OUTPUT_DIR / "italy_charging_points.csv"
#df_monthly.to_parquet(parquet_path, index=False)
#df_monthly.to_csv(csv_path, index=False)

print("Primi 15 mesi:")
print(df_monthly.head(15).to_string(index=False))
print("\nUltimi 10 mesi:")
print(df_monthly.tail(10).to_string(index=False))