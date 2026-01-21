from fastapi import FastAPI
from pydantic import BaseModel
from typing import List, Optional
import pandas as pd
import numpy as np

app = FastAPI()

# --- MODELY DAT ---
class LogItem(BaseModel):
    time: str
    sup: float
    ret: float

class LogInput(BaseModel):
    logs: List[LogItem]
    flow: float = 15.0

class DayHistory(BaseModel):
    date: str
    water: float
    ele: float

class HistoryInput(BaseModel):
    history: List[DayHistory]

@app.get("/")
def home():
    return {"status": "Heating Brain 4.0 - Dual Core Ready 🧠"}

# --- 1. ANALÝZA DNE (Fyzika vody a časy) ---
@app.post("/analyze-day")
def analyze_day(data: LogInput):
    try:
        if not data.logs:
            return {"kwh": 0, "run": 0, "off": 0, "error": "No logs"}

        # Načtení do Pandas
        df = pd.DataFrame([vars(l) for l in data.logs])
        df['time'] = pd.to_datetime(df['time'])
        df = df.set_index('time').sort_index()

        # Resampling na minuty (vyhlazení děr)
        df_res = df.resample('1T').mean().interpolate(method='linear')

        # Výpočty
        df_res['delta'] = (df_res['sup'] - df_res['ret']).clip(lower=0)
        df_res['is_running'] = (df_res['delta'] > 0.4) & (df_res['sup'] > 25)
        
        # Výkon (kW) = (Průtok * Delta * 4186) / 60000 ... zjednodušeně / 14.3
        df_res['power'] = 0.0
        df_res.loc[df_res['is_running'], 'power'] = (data.flow * df_res.loc[df_res['is_running'], 'delta']) / 14.3

        total_kwh = df_res['power'].sum() / 60.0
        run_mins = int(df_res['is_running'].sum())
        off_mins = int(len(df_res) - run_mins)

        return {
            "kwh": round(total_kwh, 2),
            "run_mins": run_mins,
            "off_mins": off_mins
        }
    except Exception as e:
        return {"kwh": 0, "run": 0, "off": 0, "error": str(e)}

# --- 2. VÝPOČET KOEFICIENTU (Z historie) ---
@app.post("/calc-coeff")
def calc_coeff(data: HistoryInput):
    try:
        df = pd.DataFrame([vars(d) for d in data.history])
        df['ele_delta'] = df['ele'].diff().fillna(0)
        
        # Filtr validních dní
        valid = df[(df['water'] > 0.5) & (df['ele_delta'] > 0.5)].copy()
        
        if len(valid) < 3: return {"coeff": 1.157, "msg": "Malo dat"}

        # Klouzavý součet (7 dní)
        last = valid.tail(7)
        sum_e = last['ele_delta'].sum()
        sum_w = last['water'].sum()
        
        if sum_w == 0: return {"coeff": 1.157, "msg": "Nula voda"}
        
        calc = sum_e / sum_w
        safe = float(np.clip(calc, 0.7, 1.5))
        
        return {"coeff": round(safe, 3), "msg": "OK"}
    except Exception as e:
        return {"coeff": 1.157, "msg": str(e)}
