from fastapi import FastAPI
from pydantic import BaseModel
from typing import List, Optional
import datetime

app = FastAPI()

# Definice datových modelů (aby Python věděl, co mu PHP posílá)
class LogItem(BaseModel):
    time: str
    sup: float
    ret: float

class DayAnalyzeRequest(BaseModel):
    logs: List[LogItem]
    flow: float

class HistoryItem(BaseModel):
    date: str
    water: float
    ele: float

class CoeffRequest(BaseModel):
    history: List[HistoryItem]

@app.get("/")
def home():
    return {"message": "Python Server bezi", "time": str(datetime.datetime.now())}

@app.get("/wake-up")
def wake_up():
    """ Probudí server pro CRON """
    return {"status": "awake", "time": str(datetime.datetime.now())}

@app.post("/analyze-day")
def analyze_day(data: DayAnalyzeRequest):
    """
    Zde bude v budoucnu složitá logika integrálu.
    Zatím vracíme 0, aby PHP nehavarovalo, pokud by to zavolalo.
    Většinu práce teď dělá PHP ve funkci save_day/cron.
    """
    return {
        "kwh": 0, 
        "run_mins": 0, 
        "off_mins": 0,
        "note": "Python calculation logic pending"
    }

@app.post("/calc-coeff")
def calculate_coeff(data: CoeffRequest):
    """
    Vypočítá koeficient účinnosti.
    Zatím vrací fixní hodnotu, dokud nenasadíme Pandas logiku.
    """
    return {
        "status": "ok",
        "coeff": 1.157, 
        "note": "Placeholder coefficient"
    }
