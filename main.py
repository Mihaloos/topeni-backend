from fastapi import FastAPI
from pydantic import BaseModel
from typing import List, Optional
import pandas as pd
import numpy as np

app = FastAPI()

# 1. Model pro HISTORII (pro výpočet koeficientu)
class DayRecord(BaseModel):
    date: str
    water: float
    ele: float

class HistoryInput(BaseModel):
    history: List[DayRecord]

# 2. Model pro LOGY (pro přesný výpočet dneška)
class LogItem(BaseModel):
    time: str     # Čas z databáze
    sup: float    # Přívod (t102)
    ret: float    # Zpátečka (t104)

class LogInput(BaseModel):
    logs: List[LogItem]
    flow: float = 15.0  # Průtok (default 15 l/min)

@app.get("/")
def home():
    return {"status": "Heating Brain 3.0 (Pandas Powered) 🐍"}

# --- A. Výpočet KOEFICIENTU (Z historie) ---
@app.post("/calculate-coeff")
def calculate_coeff(data: HistoryInput):
    try:
        df = pd.DataFrame([vars(d) for d in data.history])
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date')
        
        df['ele_delta'] = df['ele'].diff().fillna(0)
        valid = df[(df['water'] > 0.5) & (df['ele_delta'] > 0.5)].copy()
        
        if len(valid) < 3:
            return {"coeff": 1.157, "reason": "Malo dat (<3)"}
            
        last_n = valid.tail(7) # Klouzavý průměr 7 dní
        sum_ele = last_n['ele_delta'].sum()
        sum_water = last_n['water'].sum()
        
        if sum_water == 0: return {"coeff": 1.157, "reason": "Nula voda"}
        
        raw = sum_ele / sum_water
        safe = float(np.clip(raw, 0.7, 1.5))
        
        return {"coeff": round(safe, 3), "reason": f"Vypocet z {len(last_n)} dni"}
    except Exception as e:
        return {"coeff": 1.157, "reason": str(e)}

# --- B. Výpočet DNEŠNÍ ENERGIE (Z logů) ---
@app.post("/analyze-log")
def analyze_log(data: LogInput):
    try:
        if not data.logs:
            return {"kwh": 0.0, "run_hours": 0.0, "off_hours": 0.0}

        # 1. Načtení do Pandas
        df = pd.DataFrame([vars(l) for l in data.logs])
        df['time'] = pd.to_datetime(df['time'])
        df = df.set_index('time').sort_index()

        # 2. Resampling (Srovnání času na minuty a dopočítání děr)
        # Toto je ta "Magie", kterou PHP neumí. 
        # I když Shelly vynechá 5 minut, my si to domyslíme lineárně.
        df_res = df.resample('1T').mean().interpolate(method='linear')

        # 3. Výpočet Delta T
        df_res['delta_t'] = (df_res['sup'] - df_res['ret']).clip(lower=0)
        
        # 4. Detekce běhu (Delta T > 0.4 a Přívod > 25)
        # Filtrujeme šum čidel
        df_res['is_running'] = (df_res['delta_t'] > 0.4) & (df_res['sup'] > 25)

        # 5. Výpočet výkonu (kW) pro každou minutu
        # Vzorec: (Průtok * DeltaT) / 14.3
        # flow je l/min, výsledek kW
        df_res['power_kw'] = 0.0
        df_res.loc[df_res['is_running'], 'power_kw'] = (data.flow * df_res.loc[df_res['is_running'], 'delta_t']) / 14.3

        # 6. Integrace (Sečtení energie)
        # Máme výkon v kW každou minutu -> dělíme 60, abychom měli kWh
        total_kwh = df_res['power_kw'].sum() / 60.0

        # 7. Časy
        total_mins = len(df_res)
        run_mins = df_res['is_running'].sum()
        off_mins = total_mins - run_mins

        return {
            "kwh": round(total_kwh, 2),
            "run_hours": round(run_mins / 60, 1),
            "off_hours": round(off_mins / 60, 1),
            "avg_delta": round(df_res[df_res['is_running']]['delta_t'].mean(), 1) if run_mins > 0 else 0
        }

    except Exception as e:
        return {"error": str(e)}
