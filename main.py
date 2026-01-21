from fastapi import FastAPI
from pydantic import BaseModel
from typing import List, Optional
import datetime
import pandas as pd
import numpy as np

app = FastAPI()

# --- DATOVÉ MODELY ---

class LogItem(BaseModel):
    time: str   # Čas záznamu
    sup: float  # Teplota přívod (t102)
    ret: float  # Teplota zpátečka (t104)

class DayAnalyzeRequest(BaseModel):
    logs: List[LogItem]
    flow: float # Průtok v l/min (ze SQL sumy)

class HistoryItem(BaseModel):
    date: str
    water: float # water_raw_kwh
    ele: float   # ele_daily_usage

class CoeffRequest(BaseModel):
    history: List[HistoryItem]

# --- ENDPOINTY ---

@app.get("/")
def home():
    return {"message": "Python Heating Brain v1.0 (Pandas Enabled)", "time": str(datetime.datetime.now())}

@app.get("/wake-up")
def wake_up():
    return {"status": "awake"}

@app.post("/analyze-day")
def analyze_day(data: DayAnalyzeRequest):
    """
    PRECIZNÍ VÝPOČET FYZIKY (Integrál)
    Místo hrubého průměru použijeme Pandas a integraci v čase.
    """
    try:
        if not data.logs:
            return {"kwh": 0, "run_mins": 0, "off_mins": 1440, "note": "No logs"}

        # 1. Převod na Pandas DataFrame
        df = pd.DataFrame([item.dict() for item.dict() in data.logs])
        df['time'] = pd.to_datetime(df['time'])
        df = df.sort_values('time').set_index('time')

        # 2. Výpočet Delta T a Výkonu (okamžitého)
        # Vzorec: P[kW] = Průtok[l/min] * DeltaT * 0.0697 (konstanta pro vodu)
        df['delta_t'] = (df['sup'] - df['ret']).clip(lower=0) # Záporné hodnoty na 0
        
        # Filtrace šumu (pokud je delta < 0.2, považujeme za vypnuto)
        df['is_running'] = df['delta_t'] > 0.4
        
        # Okamžitý výkon v kW
        df['power_kw'] = data.flow * df['delta_t'] * 0.0697

        # 3. Integrace energie (kWh) pomocí Lichoběžníkového pravidla
        # Přesně spočítá plochu pod křivkou výkonu
        # Převedeme čas na hodiny od začátku
        time_hours = (df.index - df.index[0]).total_seconds() / 3600.0
        
        # np.trapz(y, x) -> Integruje výkon v čase -> Energie
        total_kwh = np.trapz(df['power_kw'], time_hours)

        # 4. Statistiky běhu
        # Resampling na minuty pro zjištění doby běhu
        # Pokud v dané minutě byl průměrný výkon > 0, počítáme jako běh
        df_resampled = df['is_running'].resample('1T').max()
        run_mins = int(df_resampled.sum())
        off_mins = 1440 - run_mins

        return {
            "kwh": round(total_kwh, 3),
            "run_mins": run_mins,
            "off_mins": off_mins,
            "note": "Calculated using Pandas Trapezoidal Integration"
        }

    except Exception as e:
        return {"error": str(e), "kwh": 0}

@app.post("/calc-coeff")
def calculate_coeff(data: CoeffRequest):
    """
    UČENÍ KOEFICIENTU (Weighted Median)
    Z historie zjistí nejpravděpodobnější koeficient pro převod Raw -> Final.
    """
    try:
        if not data.history:
            return {"status": "empty", "coeff": 1.157}

        df = pd.DataFrame([item.dict() for item.dict() in data.history])
        
        # 1. Filtrace platných dat
        # Zahodíme dny, kde nebyla zadána elektřina nebo byla nulová voda
        valid = df[(df['ele'] > 0.1) & (df['water'] > 0.1)].copy()

        if len(valid) < 3:
            return {"status": "low_data", "coeff": 1.157, "note": "Need at least 3 valid days"}

        # 2. Výpočet denního koeficientu
        valid['daily_coeff'] = valid['ele'] / valid['water']

        # 3. Odstranění extrémů (Outliers)
        # Zahodíme hodnoty, které jsou totálně mimo (např. chyba měření)
        # Povolíme koeficienty mezi 0.8 a 2.5
        clean = valid[(valid['daily_coeff'] > 0.8) & (valid['daily_coeff'] < 2.5)].copy()
        
        if clean.empty:
             return {"status": "outliers_only", "coeff": 1.157}

        # 4. Vážený průměr (Weighted Average)
        # Dny s vyšší spotřebou mají větší váhu (jsou přesnější)
        weighted_coeff = np.average(clean['daily_coeff'], weights=clean['water'])

        return {
            "status": "ok",
            "coeff": round(weighted_coeff, 4),
            "sample_size": len(clean),
            "note": "Weighted average by energy consumption"
        }

    except Exception as e:
        return {"error": str(e), "coeff": 1.157}
