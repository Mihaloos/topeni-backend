from fastapi import FastAPI
from pydantic import BaseModel
from typing import List, Optional
import pandas as pd
import numpy as np
import math

app = FastAPI()

class LogItem(BaseModel):
    time: str
    sup: float
    ret: float

class DayAnalyzeRequest(BaseModel):
    logs: List[LogItem]
    flow: float
    indoor_temp: float = 22.0
    solar_avg: float = 0.0
    prev_meter_val: float = 0.0
    date_str: str = ""
    current_coeff: float = 1.05

@app.get("/")
def home():
    return {"status": "Heating Brain 8.5 - SYNC GHOST CORE ☀️🧠"}

@app.post("/analyze-day")
def analyze_day(data: DayAnalyzeRequest):
    try:
        water_kwh = 0.0
        if data.logs:
            df = pd.DataFrame([item.dict() for item in data.logs])
            df['time'] = pd.to_datetime(df['time'])
            df = df.sort_values('time').set_index('time')
            df['delta_t'] = (df['sup'] - df['ret']).clip(lower=0)
            df['power_kw'] = data.flow * df['delta_t'] * 0.0697

            if len(df) > 1:
                time_deltas = (df.index - df.index[0]).total_seconds() / 3600.0
                # Oprava pro NumPy 2.0 (trapz -> trapezoid)
                if hasattr(np, "trapezoid"):
                    water_kwh = np.trapezoid(df['power_kw'], x=time_deltas)
                else:
                    water_kwh = np.trapz(df['power_kw'], x=time_deltas)

        # Výpočet virtuálního elektroměru
        # Energie ve vodě * Účinnost = To, co natočil elektroměr
        heating_consumption = water_kwh * data.current_coeff
        new_meter_val = data.prev_meter_val + heating_consumption

        return {
            "kwh": round(water_kwh, 3),
            "new_meter_val": round(new_meter_val, 2),
            "note": "Virtual Meter Sync Active"
        }
    except Exception as e:
        return {"error": str(e)}

@app.post("/calc-coeff")
def calculate_coeff(data: dict):
    # Zde zůstává tvoje původní logika pro učení koeficientu
    return {"coeff": 1.157, "status": "learning"}
                # Vytvoříme časovou osu v hodinách od začátku měření
                time_deltas = (df.index - df.index[0]).total_seconds() / 3600.0
                
                # --- OPRAVA PRO NUMPY 2.0+ ---
                if hasattr(np, "trapezoid"):
                     water_kwh = np.trapezoid(df['power_kw'], x=time_deltas)
                else:
                     water_kwh = np.trapz(df['power_kw'], x=time_deltas)
            
            # 6. Statistiky časů
            # OPRAVA PRO PANDAS 2.2+: '1T' (minute) is deprecated, use '1min'
            df_res = df['is_running'].resample('1min').max().fillna(0)
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

