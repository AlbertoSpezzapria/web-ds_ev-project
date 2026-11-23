from pathlib import Path
import pandas as pd

# CONFIGURAZIONE PERCORSI
BASE_DIR = (
    Path(__file__).resolve().parent.parent
    if "__file__" in globals()
    else Path.cwd()
)
# BASE_DIR = percorso al genitore del genitore dello sript corrente, quindi punta alla cartella DS_project

RAW_DIR = BASE_DIR / "raw_data"
OUTPUT_DIR = BASE_DIR / "interim"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)   #se la cartella che accoglierà l'output (interim) non esiste, la crea





input_file = RAW_DIR / "ember_dataset.csv"  
if not input_file.exists():
  raise FileNotFoundError(
      f"File non trovato nella cartella: {input_file}"
  )
# input_file = percorso al file csv contenente il dataset ember



df = pd.read_csv(input_file)    #df = versione dataframe del dataset ember
df_it = df[
    (df["Area"] == "Italy") & (df["Data frequency"] == "Monthly")
].copy()
#df_it = df filtrato, cioè contenente solo informazioni mesili riguardanti l'italia
# è necessario fare copy perchè filtrare un dataframe usando le quadre restituisce una vista che punta alla stessa area di memoria 
# del dataframe originale ma tale vista non è autorizzata a modificare tale dataframe. 
# Per risolvere si crea un nuovo dataframe che accoglie i dati filtrati del primo dataframe 

if df_it.empty:
  raise ValueError(
      "Nessun dato trovato per 'Italy'. Verifica il valore nella colonna"
      " 'Area'."
  )



df_pivot = df_it.pivot_table(
    index="Date",
    columns="Drivetrain",
    values=["Registrations", "Share of registrations (%)"],
    aggfunc="sum",
    fill_value=0,
)
# Il pivot_table è un'operazione che permette di ruotare una tabella, cioè partendo da un certo dataframe permette di creare un nuovo dataframe dove le colonne sono i 
# diversi valori di una certa colonna del datafrmae iniziale. 
# Per esempio nel nostro caso nel dataset ember abbiamo che ciascun mese è ripetuto su 8 righe (una volta per ciascun tipo di drivetrain), 
# è più utile avere i diversi valori di drivetrain nelle colonne. 

# Nel nostro caso il pivot che stiamo creando è basato sul dataframe df_it = dataset originale filtrato per l'italia, risulta:
# - index="Date" -> ora abbiamo una riga per ciascun valore distinto della colonna date (quindi ora il numero di righe è fissato)
# - columns="Drivetrain" -> ora abbiamo una colonna per ciascun valore distinto della colonna drivetrain (diesel, petrol, battery ...)
# - values=["Registrations", "Share of registrations (%)"] -> i valori all'incrocio tra un certo valore di drivetrain e un certo valore di date 
# sono dati da una tupla (Registrations, Share of registrations) i cui valori sono estratti da df_it, all'incrocio tra la stessa data e lo stesso drivetrain.
# Ora ciascuna colonna ha una tupla come valore e per accedere a uno solo di quei valori dobbiamo esplicitare 2 parametri. 
# Per esempio df_pivt[22-10-2021][Registration, Battery] -> alla riga 22-10-2021 e sotto la colonna Battery troviamo una tupla con 2 elementi, vogliamo solo l'elemento sotto registration
# 
# Gli altri parametri sono:
# # fill_value=0 -> se manca un valore metti 0
# - aggfunc="sum" -> se all'incrocio tra una data e un drivetrain corrispondono più valori, fanne la somma



df_out = pd.DataFrame(index=df_pivot.index) 
#ora df_out è un dataframe con lo stesso tipolgia di riga di df_pivot, cioè df_out = dataframe con una sola colonna chiamata date
df_out["date"] = pd.to_datetime(df_pivot.index)
# questa riga impone che qualsiasi cosa venga salvata nella colonna date debba essere convertita in un oggetto datetime


df_out["bev_registrations"] = df_pivot[
    ("Registrations", "Battery electric")
].astype("int64")
# data una certa data di df_pivot e la colonna battery electri, troviamo una tupla. con questo codice stimao dicendo che vogliamo solo l'elemento Registration di quella tuple
# con questo codice abbiamo aggiunto  a dt_out la colonna bev_registrations i cui valori sono uguali ai valori che troviamo in df_pivot sotto la colonna Battery electric nella sezione Registration



df_out["phev_registrations"] = (
    df_pivot[("Registrations", "Plug-in hybrid")]
    + df_pivot[("Registrations", "Hybrid")]
).astype("int64")
# come sopra ma qui il valore finale è dato da hybrid è plug in hybrid


df_out["total_registrations"] = df_pivot[
    ("Registrations", "All drivetrains")
].astype("int64")
# Numero registrazioni totali nel mese (All drivetrains)



df_out["bev_share"] = df_pivot[
    ("Share of registrations (%)", "Battery electric")
].astype("float64")
# Quota BEV direttamente dalla colonna 'Share of registrations (%)' di Ember


df_out["phev_share"] = (
    df_pivot[("Share of registrations (%)", "Plug-in hybrid")]
    + df_pivot[("Share of registrations (%)", "Hybrid")]
).astype("float64")
#  Quota PHEV (somma della colonna 'Share of registrations (%)' di Plug-in hybrid + Hybrid)



df_out = df_out.sort_values("date").reset_index(drop=True)
# ordinamento del df dalla data più piccola alla più grande


expected_months = len(
    pd.date_range(start=df_out["date"].min(), end=df_out["date"].max(), freq="MS")
)
if len(df_out) != expected_months:
  print(
      f"ATTENZIONE: Trovate {len(df_out)} righe su {expected_months} mesi"
      " attesi. Controlla eventuali buchi temporali!"
  )
# expected_months = numero di mesi dalla prima data in df_out fino alla data massima , questo valore dovrebbe essere uguale alle righe in df_out




parquet_path = OUTPUT_DIR / "italy_ev_monthly.parquet"
csv_path = OUTPUT_DIR / "italy_ev_monthly.csv"
df_out.to_parquet(parquet_path, index=False)
df_out.to_csv(csv_path, index=False)
# salva in memoria df_out in formato csv e parquet



print(df_out.tail(10))