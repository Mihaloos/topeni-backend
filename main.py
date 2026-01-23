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

# --- NOVÉ MODELY PRO SMART DELTA ---
class WaterLogItem(BaseModel):
    date: str
    water_kwh: float

class DistributeRequest(BaseModel):
    total_ele_delta: float
    daily_water_logs: List[WaterLogItem]

@app.get("/")
def home():
    return {"status": "Heating Brain 4.4 - Full Logic 🧠"}

# --- 0. WAKE UP CALL ---
@app.get("/wake-up")
def wake_up():
    return {"status": "I am awake!"}

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

        # Resampling na minuty (OPRAVA: '1T' -> '1min')
        df_res = df.resample('1min').mean().interpolate(method='linear')

        # Výpočty
        df_res['delta'] = (df_res['sup'] - df_res['ret']).clip(lower=0)
        
        # LOGIKA BĚHU:
        # Delta > 0.4 (Fyzikální přenos tepla)
        # Sup > 20.0 (Sníženo z 25 kvůli nízkoteplotnímu provozu)
        df_res['is_running'] = (df_res['delta'] > 0.4) & (df_res['sup'] > 20.0)
        
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
        
        # PHP posílá hotovou denní spotřebu (rozpočítanou z "Smart Delta").
        # Takže nepočítáme .diff(), ale bereme hodnotu napřímo.
        df['ele_delta'] = df['ele']
        
        # Filtr validních dní
        valid = df[(df['water'] > 0.5) & (df['ele_delta'] > 0.5)].copy()
        
        if len(valid) < 3: return {"coeff": 1.157, "msg": "Malo dat"}

        # Klouzavý součet (7 dní) pro stabilitu
        last = valid.tail(7)
        sum_e = last['ele_delta'].sum()
        sum_w = last['water'].sum()
        
        if sum_w == 0: return {"coeff": 1.157, "msg": "Nula voda"}
        
        # Koeficient = Realita (Ele) / Minulý Odhad (Water)
        calc = sum_e / sum_w
        safe = float(np.clip(calc, 0.7, 1.5))
        
        return {"coeff": round(safe, 3), "msg": "OK"}
    except Exception as e:
        return {"coeff": 1.157, "msg": str(e)}

# --- 3. SMART DELTA (Rozpočítání elektřiny) ---
# Toto je ta nová logika, kterou jsi chtěl přidat.
@app.post("/smart-distribute")
def smart_distribute(data: DistributeRequest):
    try:
        # Převedeme vstupní data
        daily_water_logs = [vars(item) for item in data.daily_water_logs]
        total_ele_delta = data.total_ele_delta
        
        # 1. Sečteme celkovou energii ve vodě za dané období
        total_water = sum(day['water_kwh'] for day in daily_water_logs)
        
        results = []
        
        # Ošetření dělení nulou (kdyby kotel vůbec neběžel)
        if total_water == 0:
            # Rozdělíme rovnoměrně
            count = len(daily_water_logs)
            if count > 0:
                even_share = total_ele_delta / count
                for day in daily_water_logs:
                    results.append({
                        'date': day['date'],
                        'ele_kwh': round(even_share, 2)
                    })
            return {"results": results}

        # 2. Rozpočítání podle váhy (Trojčlenka)
        for day in daily_water_logs:
            if day['water_kwh'] > 0:
                # Vzorec: (Voda Dne / Voda Celkem) * Elektřina Celkem
                ratio = day['water_kwh'] / total_water
                daily_ele = total_ele_delta * ratio
            else:
                daily_ele = 0.0
                
            results.append({
                'date': day['date'],
                'ele_kwh': round(daily_ele, 2)
            })
            
        return {"results": results}
    except Exception as e:
        return {"results": [], "error": str(e)}
