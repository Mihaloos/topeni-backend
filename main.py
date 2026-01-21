from fastapi import FastAPI
from pydantic import BaseModel
from typing import List
import pandas as pd
import numpy as np

app = FastAPI()

# Definice dat, která nám pošle PHP
class DayRecord(BaseModel):
    date: str
    water: float
    ele: float

class InputData(BaseModel):
    history: List[DayRecord]

@app.get("/")
def home():
    return {"status": "Heating Brain is Online 🧠"}

@app.post("/calculate")
def calculate_coeff(data: InputData):
    try:
        # 1. Převod dat z PHP do chytré tabulky (Pandas DataFrame)
        df = pd.DataFrame([vars(d) for d in data.history])
        
        # Seřazení podle data
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date')
        
        # 2. Výpočet denní spotřeby elektřiny (rozdíl stavů elektroměru)
        df['ele_delta'] = df['ele'].diff().fillna(0)
        
        # 3. FILTRACE: Bereme jen dny, kde se topilo a data dávají smysl
        # (Voda > 0.5 kWh a Elektřina > 0.5 kWh)
        valid = df[(df['water'] > 0.5) & (df['ele_delta'] > 0.5)].copy()
        
        # Pokud máme málo dat, vracíme bezpečný standard
        if len(valid) < 3:
            return {"coeff": 1.157, "reason": "Malo platnych dat (<3)"}
            
        # 4. EXTRÉMNÍ MATEMATIKA: Klouzavý součet za posledních 7 aktivních dní
        # Tím se vyhladí výkyvy (slunce, setrvačnost)
        last_n = valid.tail(7)
        sum_ele = last_n['ele_delta'].sum()
        sum_water = last_n['water'].sum()
        
        if sum_water == 0:
             return {"coeff": 1.157, "reason": "Deleni nulou"}
             
        raw_coeff = sum_ele / sum_water
        
        # 5. Bezpečnostní pojistka (0.7 - 1.5)
        # Aby nám chyba měření nerozbila systém
        safe_coeff = float(np.clip(raw_coeff, 0.7, 1.5))
        
        return {
            "coeff": round(safe_coeff, 3),
            "reason": f"Vypocteno z {len(last_n)} dni (RAW: {raw_coeff:.3f})"
        }
    except Exception as e:
        return {"coeff": 1.157, "reason": f"Error: {str(e)}"}
