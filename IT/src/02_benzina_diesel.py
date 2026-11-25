from pathlib import Path
import pandas as pd

# CONFIGURAZIONE PERCORSI
BASE_DIR = (
    Path(__file__).resolve().parent.parent
    if "__file__" in globals()
    else Path.cwd()
)
# BASE_DIR =percorso al genitore del genitore dello sript corrente, quindi punta alla cartella DS_project 

RAW_DIR = BASE_DIR / "raw_data"
OUTPUT_DIR = BASE_DIR / "interim"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)



input_file = RAW_DIR / "Weekly_Oil_Bulletin.xlsx"
if not input_file.exists():
  raise FileNotFoundError(
      f"File Excel non trovato nel percorso: {input_file}"
  )
# input file = percorso al dataset weakly oil bulletin




# Le prime 3 righe contengono: [Codice Paese/Metrica, Nome Carburante, Unità di misura]
df_raw = pd.read_excel(
    input_file,
    sheet_name="Prices with taxes",
    header=[0, 1, 2],
)
# df_raw is not the dataframe version of the excel pointed by input_file
# - sheet_name="Prices with taxes" -> the excel has different pages, this parameter allow to identify which page we are refferring to 
# - header=[0, 1, 2] -> in the excel, the head of the columns is spread in to 3 rows (code of the country, name of the oil/gas, unit of measure). For instance (IT, euro-super95, 1000l). 
# By writing header=[0, 1, 2] we are saying that the dataframe df_raw one row for each combination existent of (code of the country, name of the oil/gas, unit of measure).
# Since the rows 0,1 and 2 are exactly the rows in which there are the columns name also in the excel, it happens that columns in df_raw = columns in the excel.




date_col = df_raw.columns[0]
# date_col = df containing all dates in df_raw


petrol_cols = [
    col
    for col in df_raw.columns
    if str(col[0]).startswith("IT_") and "Euro-super 95" in str(col[1])
]
# petrol_cols = colonna in df_raw dove la colonna ha nel nome "IT" e  "Euro-super 95"

diesel_cols = [
    col
    for col in df_raw.columns
    if str(col[0]).startswith("IT_") and "Automotive gas oil" in str(col[1])
]
# come sopra

if not petrol_cols or not diesel_cols:
  raise ValueError(
      "Impossibile trovare le colonne di benzina o diesel per l'Italia (IT_)."
  )




df_weekly = pd.DataFrame()
df_weekly["date"] = pd.to_datetime(
    df_raw[date_col], format="%d/%m/%y", errors="coerce"
)
# df_weekly= DF con una sola colonna in cui troviamo tutte le date presenti in df_raw convertite in formato datetime 
# errors="coerce"-> se in fondo alla colonna date in df_raw ci sono delle note o delle legende, il codice proverà a convertirle in datetime e andrà in errore. 
# questo codice impone di non sollevare errore ma scrivere semplicemente NaT = not a time

df_weekly = df_weekly.dropna(subset=["date"]).copy()
# toglie da df_weekly gli eventuali NaT
# necessario fare .copy() perchè dropna restituisce una vista che permette la sola lettura




# Conversione da €/1000 litri a €/litro (dividendo per 1000)
df_weekly["petrol_price_eur_l"] = (
    pd.to_numeric(df_raw.loc[df_weekly.index, petrol_cols[0]], errors="coerce")
    / 1000.0
)
# - petrol_cols[0] = ('IT_price_with_tax_euro95', 'Euro-super 95  (I)', '1000 l')
# - df_weekly = all dates in df_raw
# - df_weekly.index = all index of rows in df_weakly, notice that df_weakly = only the raws in df_raw where there are valid dates. 
# Hence df_weekly.index = index of rows in df_raw where we can find valid rows
# - df_raw.loc[ rows, columns] = loc is an extractor, it takes a DF as reference, a set of rows, a set of columns and extract the indicated portion of data from the DF
# - df_raw.loc[df_weekly.index, petrol_cols[0]] = extract all valid rows and only the column that refers to the petrol, namely all weakly values of petrol 
# - pd.to_numeric(df_raw.loc[df_weekly.index, petrol_cols[0]], errors="coerce")-> in df_raw are all values are strings, this code convert such strings in int
# errors="coerce" -> se qualche valore non si riesce a convertire a int, viene sostituito da NaN
# - infine si divide per 1000 perchè nel file i valori indicano il costo in euro ogni 1000 litri, ora indicano il prezzo al litro




df_weekly["diesel_price_eur_l"] = (
    pd.to_numeric(df_raw.loc[df_weekly.index, diesel_cols[0]], errors="coerce")
    / 1000.0
)
# come sopra. Ora df_weekly["diesel_price_eur_l"]= prezzo del diesel settimanale




df_monthly = (
    df_weekly.set_index("date")
    .resample("MS")
    .mean()
    .reset_index()
)
# - .set_index("date") -> Sposta la colonna "date" dal corpo della tabella al margine sinistro, trasformandola nell'indice delle righe. Questo è necessario perchè 
# le funzioni temporali di pandas (come .resample()) funzionano esclusivamente se le date si trovano nell'indice della tabella e non in una normale colonna.
# - resample() è come un groupby() specializzato esclusivamente per le date, e la stringa che gli passi tra parentesi è il codice che stabilisce l'ampiezza del contenitore temporale 
# - .resample("MS") -> prende come riferimento l'indice di un df, da per scontato che gli indici siano date e raggruppa tutti gli indici in base al mese. "MS"=month start
# - .mean() -> nel nostro caso prende come reference df_weakly i cui indici sono date raggruppate per mese, il valore per ciascun gruppo è dato dalla media dei valori 
# - .reset_index() -> fa l'opposto di set_index("date"), cioè prende l'attuale indice (che è date), lo riporta ad essere una normale colonna e ripristina gli indici cardianli (1,2,3,...)

# Alla fine abbiamo che df_monthly ha 3 colonne = date, petrol_price_eur_l e diesel_price_eur_l. in particolare le date sono raggruppate per mese e i prezzi sono la media del mese





df_monthly["petrol_price_eur_l"] = df_monthly["petrol_price_eur_l"].round(4)
df_monthly["diesel_price_eur_l"] = df_monthly["diesel_price_eur_l"].round(4)
# arrontonda a 4 cifre decimali (precisione standard al decimo di millesimo di €/litro)


df_monthly = df_monthly[
    (df_monthly["date"] >= "2019-01-01") & (df_monthly["date"] <= "2026-10-01")
].reset_index(drop=True)
# Filtriamo dal 2019-01-01 a 2026-10-01 per allinearci al periodo di interesse 



if df_monthly[["petrol_price_eur_l", "diesel_price_eur_l"]].isna().any().any():
  print("ATTENZIONE: Sono presenti valori NaN nella serie mensile dei prezzi!")
# Controllo eventuali mesi mancanti



CONS_PETROL = 6.5  # L/100km (consumo medio reale segmento B/C europeo)
df_monthly["cost_petrol_100km"] = (df_monthly["petrol_price_eur_l"] * CONS_PETROL).round(2)

CONS_DIESEL = 5.5  # L/100km (consumo medio reale segmento B/C europeo)
df_monthly["cost_diesel_100km"] = (df_monthly["diesel_price_eur_l"] * CONS_DIESEL).round(2)



parquet_path = OUTPUT_DIR / "italy_fuel_prices.parquet"
csv_path = OUTPUT_DIR / "italy_fuel_prices.csv"
df_monthly.to_parquet(parquet_path, index=False)
df_monthly.to_csv(csv_path, index=False)
# SALVATAGGIO SU DISCO (PARQUET E CSV)


print(df_monthly.tail(10))
