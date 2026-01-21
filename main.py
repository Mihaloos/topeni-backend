from fastapi import FastAPI
from pydantic import BaseModel
from typing import List, Optional
import pandas as pd
import numpy as np
import math
import datetime

app = FastAPI()

# --- DATOVÉ MODELY ---

class LogItem(BaseModel):
    time: str   # Čas záznamu
    sup: float  # Teplota přívod (t102)
    ret: float  # Teplota zpátečka (t104)

class DayAnalyzeRequest(BaseModel):
    logs: List[LogItem]
    flow: float         # Průtok v l/min
    # Solar & Weather Inputs
    indoor_temp: float = 22.0     
    solar_avg: float = 0.0        # W/m2
    prev_meter_val: float = 0.0   # Ghost Meter Start
    date_str: str = ""            # "YYYY-MM-DD"
    current_coeff: float = 1.05   # <--- NOVÝ VSTUP: Naučený koeficient

class HistoryItem(BaseModel):
    date: str
    water: float # water_raw_kwh
    ele: float   # ele_daily_usage

class CoeffRequest(BaseModel):
    history: List[HistoryItem]

# --- POMOCNÁ TŘÍDA: SOLÁRNÍ FYZIKA ---
class SolarPhysics:
    def __init__(self, date_str):
        # Ošetření prázdného data
        if not date_str:
            self.day_of_year = 1
        else:
            try:
                self.date_obj = pd.to_datetime(date_str)
                self.day_of_year = self.date_obj.dayofyear
            except:
                self.day_of_year = 1
        
    def get_solar_factor(self):
        """
        Vypočítá 'účinnost' slunce dopadajícího do oken (Geometrie přesahu).
        Zima (den 0) = 1.0 (slunce jde pod přesahem).
        Léto (den 180) = ~0.15 (stínění).
        """
        # Posun vrcholu zimy na cca 21.12.
        rads = 2 * math.pi * (self.day_of_year + 10) / 365
        factor = (math.cos(rads) + 1) / 2 
        
        # Oříznutí (v létě nikdy není tma, difuzní světlo cca 15%)
        final_factor = 0.15 + (0.85 * factor)
        return final_factor

# --- ENDPOINTY ---

@app.get("/")
def home():
    return {"status": "Heating Brain 6.0 - INTEGRAL + SOLAR CORE ☀️🧠"}

@app.get("/wake-up")
def wake_up():
    return {"status": "awake"}

@app.post("/analyze-day")
def analyze_day(data: DayAnalyzeRequest):
    """
    MASTER ANALÝZA:
    1. Pandas Integrál pro přesnou spotřebu vody.
    2. Solární model pro zisky oken.
    3. Výpočet Ghost Elektroměru.
    """
    try:
        # A) VÝPOČET VODY (Precizní Integrál)
        water_kwh = 0.0
        run_mins = 0
        off_mins = 1440
        
        if data.logs:
            # 1. Převod na Pandas
            df = pd.DataFrame([item.dict() for item in data.logs])
            df['time'] = pd.to_datetime(df['time'])
            df = df.sort_values('time').set_index('time')

            # 2. Výpočet Delta T
            df['delta_t'] = (df['sup'] - df['ret']).clip(lower=0)
            
            # 3. Filtrace běhu (pro statistiku minut)
            # Kotel běží, pokud delta > 0.4 A přívod > 25 (aby nepočítal studený oběh)
            df['is_running'] = (df['delta_t'] > 0.4) & (df['sup'] > 25.0)

            # 4. Okamžitý výkon (kW)
            # Vzorec: Flow * Delta * 0.0697 (konstanta pro vodu 4186/60000)
            df['power_kw'] = data.flow * df['delta_t'] * 0.0697

            # 5. INTEGRACE (Lichoběžníkové pravidlo)
            # Převedeme index na hodiny (float)
            if len(df) > 1:
                # Vytvoříme časovou osu v hodinách od začátku měření
                time_deltas = (df.index - df.index[0]).total_seconds() / 3600.0
                # np.trapz spočítá plochu pod křivkou (kW * h = kWh)
                water_kwh = np.trapz(df['power_kw'], time_deltas)
            
            # 6. Statistiky časů
            df_res = df['is_running'].resample('1T').max().fillna(0)
            run_mins = int(df_res.sum())
            off_mins = 1440 - run_mins

        # B) SOLÁRNÍ FYZIKA & GHOST METER
        simulated_meter = data.prev_meter_val
        solar_gain_kwh = 0.0
        
        if data.date_str and data.indoor_temp > 0:
            # 1. Solární Zisk (12m2 oken * g-value 0.6 * factor)
            physics = SolarPhysics(data.date_str)
            shading_eff = physics.get_solar_factor()
            
            # Vzorec: W/m2 * 24h * 12m2 * 0.6 * stínění / 1000
            solar_gain_kwh = (data.solar_avg * 24 * 12 * 0.6 * shading_eff) / 1000.0
            
           # 2. Bilance domu (Ghost Meter)
            # Protože máš SAMOSTATNÝ elektroměr pro kotel:
            # - Base Load domu (lednice atd.) je 0.
            # - Solární zisk se NEODEČÍTÁ (projevil se už tím, že kotel nesepl).
            
            # Výpočet: (Energie ve vodě kWh * Účinnost/Ztráty trubek)
            heating_consumption = water_kwh * data.current_coeff 
            
            # Ghost Meter simuluje pouze točení elektroměru kotle
            daily_total = heating_consumption
            
            simulated_meter += daily_total

        return {
            "kwh": round(water_kwh, 3),
            "run_mins": run_mins,
            "off_mins": off_mins,
            "new_meter_val": round(simulated_meter, 2),
            "solar_gain_debug": round(solar_gain_kwh, 2),
            "used_coeff_debug": data.current_coeff,
            "note": "Pandas Integral + Solar Physics + Smart Coeff"
        }

    except Exception as e:
        return {"kwh": 0, "run_mins": 0, "off_mins": 1440, "error": str(e)}

@app.post("/calc-coeff")
def calculate_coeff(data: CoeffRequest):
    """
    UČENÍ KOEFICIENTU (Weighted Median - Vylepšeno)
    """
    try:
        if not data.history:
            return {"coeff": 1.157, "status": "empty"}

        df = pd.DataFrame([item.dict() for item in data.history])
        
        # 1. Filtrace platných dat
        valid = df[(df['ele'] > 0.1) & (df['water'] > 0.1)].copy()

        if len(valid) < 3:
            return {"coeff": 1.157, "status": "low_data"}

        # 2. Výpočet denního koeficientu
        valid['daily_coeff'] = valid['ele'] / valid['water']

        # 3. Odstranění extrémů (0.8 až 2.5)
        clean = valid[(valid['daily_coeff'] > 0.8) & (valid['daily_coeff'] < 2.5)].copy()
        
        if clean.empty:
             return {"coeff": 1.157, "status": "outliers_only"}

        # 4. Vážený průměr (Weighted Average)
        # Dny s vyšší spotřebou mají větší váhu
        weighted_coeff = np.average(clean['daily_coeff'], weights=clean['water'])

        return {
            "coeff": round(weighted_coeff, 4),
            "status": "ok",
            "sample_size": len(clean)
        }

    except Exception as e:
        return {"coeff": 1.157, "error": str(e)}

