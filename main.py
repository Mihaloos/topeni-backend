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

class HistoryItem(BaseModel):
    date: str
    water: float
    ele: float

class CoeffRequest(BaseModel):
    history: List[HistoryItem]

class SolarPhysics:
    def __init__(self, date_str):
        try:
            self.date_obj = pd.to_datetime(date_str)
            self.day_of_year = self.date_obj.dayofyear
        except:
            self.day_of_year = 1
        
    def get_solar_factor(self):
        rads = 2 * math.pi * (self.day_of_year + 10) / 365
        factor = (math.cos(rads) + 1) / 2 
        return 0.15 + (0.85 * factor)

@app.get("/")
def home():
    return {"status": "Heating Brain 8.6 - FULL BRAIN SYNC ☀️🧠"}

@app.post("/analyze-day")
def analyze_day(data: DayAnalyzeRequest):
    try:
        water_kwh = 0.0
        run_mins = 0
        if data.logs:
            df = pd.DataFrame([item.dict() for item in data.logs])
            df['time'] = pd.to_datetime(df['time'])
            df = df.sort_values('time').set_index('time')
            df['delta_t'] = (df['sup'] - df['ret']).clip(lower=0)
            df['is_running'] = (df['delta_t'] > 0.4) & (df['sup'] > 25.0)
            df['power_kw'] = data.flow * df['delta_t'] * 0.0697

            if len(df) > 1:
                time_deltas = (df.index - df.index[0]).total_seconds() / 3600.0
                if hasattr(np, "trapezoid"):
                    water_kwh = np.trapezoid(df['power_kw'], x=time_deltas)
                else:
                    water_kwh = np.trapz(df['power_kw'], x=time_deltas)
            
            df_res = df['is_running'].resample('1min').max().fillna(0)
            run_mins = int(df_res.sum())

        solar_gain_kwh = 0.0
        if data.date_str and data.indoor_temp > 0:
            physics = SolarPhysics(data.date_str)
            shading_eff = physics.get_solar_factor()
            solar_gain_kwh = (data.solar_avg * 24 * 12 * 0.6 * shading_eff) / 1000.0
            
        heating_consumption = water_kwh * data.current_coeff 
        new_meter_val = data.prev_meter_val + heating_consumption

        return {
            "kwh": round(water_kwh, 3),
            "run_mins": run_mins,
            "new_meter_val": round(new_meter_val, 2),
            "solar_gain": round(solar_gain_kwh, 2),
            "used_coeff": data.current_coeff
        }
    except Exception as e:
        return {"error": str(e)}

@app.post("/calc-coeff")
def calculate_coeff(data: CoeffRequest):
    try:
        if not data.history: return {"coeff": 1.157}
        df = pd.DataFrame([item.dict() for item in data.history])
        valid = df[(df['ele'] > 0.1) & (df['water'] > 0.1)].copy()
        if len(valid) < 3: return {"coeff": 1.157}
        valid['daily_coeff'] = valid['ele'] / valid['water']
        clean = valid[(valid['daily_coeff'] > 0.8) & (valid['daily_coeff'] < 2.5)].copy()
        if clean.empty: return {"coeff": 1.157}
        weighted_coeff = np.average(clean['daily_coeff'], weights=clean['water'])
        return {"coeff": round(weighted_coeff, 4), "status": "ok"}
    except:
        return {"coeff": 1.157}
            solar_gain_kwh = (data.solar_avg * 24 * 12 * 0.6 * shading_eff) / 1000.0
            
            heating_consumption = water_kwh * data.current_coeff 
            simulated_meter += heating_consumption

        return {
            "kwh": round(water_kwh, 3),
            "run_mins": run_mins,
            "off_mins": off_mins,
            "new_meter_val": round(simulated_meter, 2),
            "solar_gain_debug": round(solar_gain_kwh, 2),
            "used_coeff_debug": data.current_coeff,
            "note": "Complete Logic Sync Active"
        }

    except Exception as e:
        return {"kwh": 0, "run_mins": 0, "error": str(e)}

@app.post("/calc-coeff")
def calculate_coeff(data: CoeffRequest):
    """
    UČENÍ KOEFICIENTU (Weighted Average)
    """
    try:
        if not data.history:
            return {"coeff": 1.157, "status": "empty"}

        df = pd.DataFrame([item.dict() for item in data.history])
        valid = df[(df['ele'] > 0.1) & (df['water'] > 0.1)].copy()

        if len(valid) < 3:
            return {"coeff": 1.157, "status": "low_data"}

        valid['daily_coeff'] = valid['ele'] / valid['water']
        clean = valid[(valid['daily_coeff'] > 0.8) & (valid['daily_coeff'] < 2.5)].copy()
        
        if clean.empty:
             return {"coeff": 1.157, "status": "outliers_only"}

        # Vážený průměr
        weighted_coeff = np.average(clean['daily_coeff'], weights=clean['water'])

        return {
            "coeff": round(weighted_coeff, 4),
            "status": "ok",
            "sample_size": len(clean)
        }
    except Exception as e:
        return {"coeff": 1.157, "error": str(e)}
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



