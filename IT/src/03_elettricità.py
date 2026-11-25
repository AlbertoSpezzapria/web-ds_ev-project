from pathlib import Path
import pandas as pd
import numpy as np

# ==============================================================================
# PERCORSI
# ==============================================================================
BASE_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = BASE_DIR / "raw_data" / "electricity"
INTERIM_DIR = BASE_DIR / "interim"
INTERIM_DIR.mkdir(parents=True, exist_ok=True)

FILE_ISTAT_2019_2025 = RAW_DIR / "prezzo_al_consumo_corrente_elettrica_2019_2025.csv"
FILE_ISTAT_2026 = RAW_DIR / "prezzo_al_consumo_corrente_elettrica_2026.csv"
FILE_EUROSTAT = RAW_DIR / "prezzi_semestrali_corrente.csv"
FILE_PETROL = INTERIM_DIR / "italy_fuel_prices.csv"





def load_istat(filepath: Path) -> pd.DataFrame:
    "prende in input il percorso a uno dei due file istat contenenti gli indici a-dimensioali e restituisce un DF contenente 2 colonne: "
    "mese - coefficiente (che nel file è chiamato 'osservazione' "
    
    df = pd.read_csv(filepath, usecols=["TIME_PERIOD", "Osservazione"])
    # ora df = DF dove ogni riga = mese , coefficiente 

    df["date"] = pd.to_datetime(df["TIME_PERIOD"] + "-01")
    # aggiunge una nuova colonna chiamata date i cui valori sono uguali ai valori della colonna TIME_PERIOD convertiti in formato datetime 
    # e a cui vi concatena anche il giorno (per esempio 2026-01 diventa 2026-01-01)
    
    return df[["date", "Osservazione"]].rename(columns={"Osservazione": "index_val"})
    # restituisce un DF composto dalle 2 colonne ["date", "Osservazione"] in df e rinomina le 2 colonne come sopra





def load_eurostat(filepath: Path) -> pd.DataFrame:
    " legge il file CSV semestrale scaricato da Eurostat, isola esclusivamente le righe relative alla fascia di consumo domestico standard "
    "(band DC, da 2.500 a 4.999 kWh annui) e restituisce una tabella essenziale composta da due sole colonne rinominate: semester ed eurostat_eur_kwh "
    "(il prezzo medio semestrale in €/kWh tasse incluse) "

    df = pd.read_csv(filepath, usecols=["nrg_cons", "TIME_PERIOD", "OBS_VALUE"])
    # df = DF con solo le colonne di interesse
    df = df[df["nrg_cons"] == "Consumption from 2 500 kWh to 4 999 kWh - band DC"]
    # filtra solo le righe che riferiscono i prezzi relativi a consumi civili 
    return df[["TIME_PERIOD", "OBS_VALUE"]].rename(
        columns={"TIME_PERIOD": "semester", "OBS_VALUE": "eurostat_eur_kwh"}
    )
# restituisce un df con solo le colonne di interesse rinominate 






def build_monthly_electricity_prices() -> pd.DataFrame:
    "prende i due file mensili dell'ISTAT (espressi con due basi diverse) e il file semestrale di Eurostat (espresso in €/kWh), "
    "riporta tutto su un'unica base temporale continua, "
    "calcola per ciascun semestre il coefficiente di conversione proporzionale tra indice ISTAT e prezzo reale Eurostat, "
    "e moltiplica ogni singolo mese per il fattore del proprio semestre. Il risultato è una serie storica mensile continua in €/kWh (tasse incluse)."


    df_19_25 = load_istat(FILE_ISTAT_2019_2025)
    df_26 = load_istat(FILE_ISTAT_2026)
    # df_19_25 = DF dove ciascuna riga è una data + il coefficiente tra il prezzo medio nel mese considerato e il prezzo medio del 2015
    # df_26 = come sopra ma rapportato al prezzo medio della corrente nel 2025



    mean_2025 = df_19_25.loc[df_19_25["date"].dt.year == 2025, "index_val"].mean()
    # - df_19_25["date"] -> i valori di questa colonna sono di tipo datetime 
    # - df_19_25["date"].dt.year -> dt.year permette di estrarre solo l'anno da ciascun elemento di df_19_25["date"]. Quindi df_19_25["date"].dt.year  = colonna di annate presenti in df_19_25
    # - df_19_25.loc[df_19_25["date"].dt.year == 2025, "index_val"] -> restituisce tutti quei valori della colonna index_val laddove la riga contiene una data con un anno 2025
    # - .mean -> fa la media di tutti gli index_val ricavati 

    # mean_2025 -> essendo che index_val = "quanto costa la corrente nel mese corrente rispetto al prezzo medio del 2015", ora abbiamo che 
    # mean_2025 = prezzo medio della corrente nel 2025 rispetto al 2015


    df_26["index_val"] = df_26["index_val"] * (mean_2025 / 100.0)
    # df_26 = coefficienti che dicono quanto costa la corrente nel mese indicato rispetto al 2025
    # moltiplicando per la media del 2025 facciamo si che ora f_26["index_val"]  = prezzo medio della corrente nel mese indicato rispetto al 2015 
    # (proprio come tutti i mesi in df_19_25)



    df_istat = pd.concat([df_19_25, df_26], ignore_index=True).sort_values("date")
    # concatena i due DF, crea un nuovo indice di riga che parte da 0 (ignore_index=True) e ordina i valori per data


    df_istat["semester"] = (
        df_istat["date"].dt.year.astype(str)
        + "-S"
        + np.where(df_istat["date"].dt.month <= 6, "1", "2")
    )
    # Nell'altro df derivato dal csv dell'eurostat abbiamo 2 colonne: semester e eurostat_eur_kwh = semestre e relativo prezzo medio della corrente euro/kW.
    # Il problema è che la colonna semester è indicata così: 2021-S2 per indicare il seconod semestre del 2021. 
    # Per poter combinare i 2 DF dobbiamo aggiungere a df_istat una colonna che indica anno e semestre ed è esattamente ciò che fa il codice.
    # viene aggiunta la colonna df_istat["semester"] dove prende l'anno dalla riga in questione, concatena S e poi concatena 1 se il mese <6 oppure 2

    # Adesso df_istat = date , semester , indice = rapporto del prezzo della corrente tra il mese corrente e il prezzo medio del 2015



    df_eurostat = load_eurostat(FILE_EUROSTAT)
    # df_eurostat = DF con le colonne (semester , eurostat_eur_kwh)

    sem_mean = df_istat.groupby("semester", as_index=False)["index_val"].mean()
    # sem_mean = df dove ciascuna riga è data da un semestre e dalla media degli indici di quel semestre presente in df_istat
    

    anchor = sem_mean.merge(df_eurostat, on="semester", how="left")
    # anchor = DF dato da sem_mean left join df_eurostat su semester. 
    # In altre parole ogni riga di anchor è un semestre, media sul semestre dei coefficienti di rapporto con il 2015, prezzo medio corrente euro/kW nel semestre

    

    anchor["k_factor"] = (anchor["eurostat_eur_kwh"] / anchor["index_val"]).ffill()
    # aggiunge ad anchor la colonna k_factor data dal rapporto tra prezzo medio semestrale euro/kW e i vari coefficienti medi. 
    # Questo è esattamente il coefficiente che ci permette di passare da: (coefficiente di rapporto tra un certo mese e la media del 2015) a / (prezzo euro/kW nello stesso mese)
    


   
    df_final = df_istat.merge(anchor[["semester", "k_factor", "eurostat_eur_kwh"]], on="semester", how="left")
    # ogni riga di df_final = date , semester , k_factor , prezzo semestrale euro/kW, coefficiente di rapporto tra il mese corrente e il prezzo medio nel 2015
    # in altre parole tutti i dati definiti sin ora stanno in df_final
    



    df_final["elec_domestic_price_eur_kwh"] = (
        df_final["index_val"] * df_final["k_factor"]
    ).round(5)
    # la colonna elec_domestic_price_eur_kwh = prezzo mensile domestico euro/kWh nel mese considerato

    df_final["elec_public_price_eur_kwh"] = (
        df_final["elec_domestic_price_eur_kwh"] * 2.1
    ).round(5)
    # la colonna elec_public_price_eur_kwh = prezzo stimato alla colonnina pubblica (2.1x il prezzo domestico)


    elec_blended_price = (
        0.80 * df_final["elec_domestic_price_eur_kwh"]
        + 0.20 * df_final["elec_public_price_eur_kwh"]
    )
    # Prezzo medio ponderato per ricarica un'auto ev al kWh (80% ricarica domestica + 20% ricarica pubblica)



    df_final["cost_ev_100km"] = (elec_blended_price * 18.0).round(2)
    # Costo medio per 100 km in elettrico (consumo fatturato = 18.0 kWh/100km, perdite di ricarica incluse)
    # i valori di questa colonna sono espressi in euro ogni 100km
    
    
    
    CONS_UF = 0.5  # % di percorrenza in elettrico delle auto plug-in
    CONS_CONSUME_ELECTRIC = 19.0  # kWh/100km in modalità elettrica (perdite incluse)
    CONS_CONSUME_PETROL = 6.0  # L/100km in modalità benzina (a batteria scarica)

    # 1. Carichiamo anche 'date' dal file carburanti e facciamo merge su 'date'
    df_petrol = pd.read_csv(
        FILE_PETROL, usecols=["date", "petrol_price_eur_l", "cost_petrol_100km"], parse_dates=["date"]
    )
    df_final = df_final.merge(df_petrol, on="date", how="left")

    # 2. Calcoliamo il costo PHEV usando la Series df_final["petrol_price_eur_l"]
    df_final["cost_phev_100km"] = (
        (CONS_UF * elec_blended_price * CONS_CONSUME_ELECTRIC)
        + ((1 - CONS_UF) * df_final["petrol_price_eur_l"] * CONS_CONSUME_PETROL)
    ).round(2)





    # Costo medio per 100 km con auto ibrida non ricaricabile (HEV / Full Hybrid)
    # Consumo medio reale su strada = 5.0 L/100km di benzina (nessun prelievo dalla rete elettrica)
    CONS_HEV_PETROL = 5.0
    df_final["cost_hev_100km"] = (
        df_final["petrol_price_eur_l"] * CONS_HEV_PETROL
    ).round(2)



    df_final["petrol_ev_cost_ratio"] = (
        df_final["cost_petrol_100km"] / df_final["cost_ev_100km"]
    ).round(3)
    # Rapporto di convenienza adimensionale: quanto costa percorrere 100 km a benzina rispetto all'elettrico puro
    # Un valore > 1 indica che l'elettrico è più conveniente della benzina

    df_final["petrol_phev_cost_ratio"] = (
        df_final["cost_petrol_100km"] / df_final["cost_phev_100km"]
    ).round(3)
    # Rapporto di convenienza adimensionale: quanto costa percorrere 100 km a benzina rispetto al plug-in
    # Un valore > 1 indica che l'elettrico è più conveniente della benzina


    df_final["petrol_hev_cost_ratio"] = (
        df_final["cost_petrol_100km"] / df_final["cost_hev_100km"]
    ).round(3)
    # Rapporto di convenienza adimensionale: quanto costa percorrere 100 km a benzina rispetto al plug-in
    # Un valore > 1 indica che l'elettrico è più conveniente della benzina

    return df_final[[
        "date",
        "elec_domestic_price_eur_kwh",
        "elec_public_price_eur_kwh",
        "cost_ev_100km",
        "cost_phev_100km",
        "cost_hev_100km",
        "eurostat_eur_kwh",
        "petrol_ev_cost_ratio",
        "petrol_phev_cost_ratio",
        "petrol_hev_cost_ratio"
    ]].rename(
        columns={
            "eurostat_eur_kwh": "eurostat_sem_anchor_eur_kwh",
        }
    )



















if __name__ == "__main__":
    df_elec = build_monthly_electricity_prices()
    df_elec.to_parquet(INTERIM_DIR / "italy_electricity_prices.parquet", index=False)
    df_elec.to_csv(INTERIM_DIR / "italy_electricity_prices.csv", index=False)
    print(df_elec.to_string(index=False))
    #g