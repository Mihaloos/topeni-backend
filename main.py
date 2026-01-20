from fastapi import FastAPI
from pydantic import BaseModel
import datetime

app = FastAPI()

class HeatingData(BaseModel):
    date: str
    ele: float

@app.get("/")
def home():
    return {"message": "Ahoj! Python Server pro Topení běží.", "time": str(datetime.datetime.now())}

@app.post("/calculate-coeff")
def calculate(data: HeatingData):
    # Tady později bude ta chytrá logika s Pandas
    # Zatím uděláme jen testovací výpočet
    fake_coeff = 1.123
    return {
        "status": "ok",
        "received_ele": data.ele,
        "calculated_coeff": fake_coeff,
        "note": "Toto je testovací odpověď z Pythonu"
    }
