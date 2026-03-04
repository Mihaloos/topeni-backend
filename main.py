from fastapi import FastAPI
from pydantic import BaseModel
from typing import List, Optional, Dict
import pandas as pd
import numpy as np

app = FastAPI()

# =============================================================================
# VERZE: 5.0 - CLEAN COEFFICIENT ENGINE
#
# Architektura koeficientů:
#   Ghost = cloud_water_kwh × global_coeff × range_coeff
#
#   global_coeff  = čistý fyzikální poměr ele/voda, očištěný od range efektu
#                   počítá se exponenciálně váženým průměrem přes CELOU historii
#                   (decay=0.97 → den starý 30 dní má stále 40% váhu)
#
#   range_coeff   = opravný faktor per pásmo spotřeby (10-20, 20-30 kWh...)
#                   zachycuje rozdíl účinnosti: krátké cykly vs. dlouhý běh
#                   = avg(real_coeff_v_pásmu) / global_coeff
#
# Výsledek z dat (43 dní, leden-březen 2026):
#   global_coeff ≈ 1.171
#   Stdev po range korekci: 0.0181 (o 47% lepší než bez range)
#   Prediktivní model (delta_T, venkovní teplota) nepřináší zlepšení (r < 0.06)
# =============================================================================

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

class WaterLogItem(BaseModel):
    date: str
    water_kwh: float

class DistributeRequest(BaseModel):
    total_ele_delta: float
    daily_water_logs: List[WaterLogItem]

class RangeCoeffRequest(BaseModel):
    history: List[DayHistory]
    range_breaks: Optional[List[float]] = None


# =============================================================================
# SDÍLENÁ FUNKCE: Výpočet global_coeff
# Používají ji OBOBA endpointy → zaručena konzistence
# =============================================================================

def _get_range_label(water: float, breaks_ext: list) -> str:
    """Vrátí label pásma pro danou spotřebu vody."""
    for i in range(len(breaks_ext) - 1):
        if breaks_ext[i] <= water < breaks_ext[i + 1]:
            lo, hi = breaks_ext[i], breaks_ext[i + 1]
            return f"{int(lo)}+" if hi == float('inf') else f"{int(lo)}-{int(hi)}"
    return f"{int(breaks_ext[-2])}+"


def _compute_global_coeff(df: pd.DataFrame,
                           range_coeffs: dict = None,
                           breaks_ext: list = None,
                           decay: float = 0.97) -> float:
    """
    Exponenciálně vážený global_coeff přes VŠECHNA validní data.

    Parametry:
        df          – DataFrame se sloupci 'water', 'ele', 'real_coeff'
        range_coeffs – pokud zadáno, očistí real_coeff od range efektu
        breaks_ext  – breaks včetně inf na konci
        decay       – faktor stárnutí (0.97 → starší data mají menší, ale nenulovou váhu)

    Matematika:
        Bez range korekce: gc = Σ(real_coeff_i × w_i) / Σ(w_i)
        S range korekcí:   gc = Σ((real_coeff_i / range_coeff_i) × w_i) / Σ(w_i)
        kde w_i = decay^(n-1-i)  ... nejnovější den má váhu 1.0
    """
    n = len(df)
    if n == 0:
        return 1.157

    weights = np.array([decay ** i for i in range(n - 1, -1, -1)])

    if range_coeffs and breaks_ext:
        rc_vals = df['water'].apply(
            lambda w: float(range_coeffs.get(_get_range_label(w, breaks_ext), 1.0))
        ).values
        # Ochrana před dělením nulou
        rc_vals = np.where(rc_vals < 0.1, 1.0, rc_vals)
        clean_coeffs = df['real_coeff'].values / rc_vals
    else:
        clean_coeffs = df['real_coeff'].values

    gc = float(np.average(clean_coeffs, weights=weights))
    return float(np.clip(gc, 0.85, 1.50))


# =============================================================================
# ENDPOINTS
# =============================================================================

@app.get("/")
def home():
    return {"status": "Heating Brain 5.0 - Clean Coefficient Engine 🧠"}

@app.get("/wake-up")
def wake_up():
    return {"status": "I am awake!"}


# --- 1. ANALÝZA DNE (Fyzika vody a časy) ---
@app.post("/analyze-day")
def analyze_day(data: LogInput):
    try:
        if not data.logs:
            return {"kwh": 0, "run": 0, "off": 0, "error": "No logs"}

        df = pd.DataFrame([vars(l) for l in data.logs])
        df['time'] = pd.to_datetime(df['time'])
        df = df.set_index('time').sort_index()
        df_res = df.resample('1min').mean().interpolate(method='linear')

        df_res['delta'] = (df_res['sup'] - df_res['ret']).clip(lower=0)
        df_res['is_running'] = (df_res['delta'] > 0.4) & (df_res['sup'] > 20.0)
        df_res['power'] = 0.0
        df_res.loc[df_res['is_running'], 'power'] = (
            data.flow * df_res.loc[df_res['is_running'], 'delta']
        ) / 14.3

        total_kwh = df_res['power'].sum() / 60.0
        run_mins  = int(df_res['is_running'].sum())
        off_mins  = int(len(df_res) - run_mins)

        return {"kwh": round(total_kwh, 2), "run_mins": run_mins, "off_mins": off_mins}
    except Exception as e:
        return {"kwh": 0, "run": 0, "off": 0, "error": str(e)}


# --- 2. VÝPOČET GLOBAL KOEFICIENTU ---
@app.post("/calc-coeff")
def calc_coeff(data: HistoryInput):
    """
    Vrátí global_coeff jako exponenciálně vážený průměr přes celou historii.
    PHP posílá data již očištěná o coeff_exclude dny a s ele_override.
    Tento endpoint nepoužívá range korekci (range korekce je věc /calc-range-coeffs).
    global_coeff zde = čistý fyzikální základ před range úpravou.
    """
    try:
        df = pd.DataFrame([d.dict() for d in data.history])
        valid = df[(df['water'] > 0.5) & (df['ele'] > 0.5)].copy()

        if len(valid) < 3:
            return {"coeff": 1.157, "msg": "Malo dat", "valid_days": 0}

        valid['real_coeff'] = valid['ele'] / valid['water']
        # Outlier filter
        valid = valid[(valid['real_coeff'] >= 0.85) & (valid['real_coeff'] <= 1.50)].copy()

        if len(valid) < 3:
            return {"coeff": 1.157, "msg": "Malo dat po filtru", "valid_days": 0}

        gc = _compute_global_coeff(valid, decay=0.97)

        return {
            "coeff":      round(gc, 4),
            "valid_days": int(len(valid)),
            "msg":        "OK"
        }
    except Exception as e:
        return {"coeff": 1.157, "msg": str(e)}


# --- 3. RANGE KOEFICIENTY ---
@app.post("/calc-range-coeffs")
def calc_range_coeffs(data: RangeCoeffRequest):
    """
    Dvoufázový výpočet:

    Fáze 1: global_coeff bez range korekce (startovní bod)
    Fáze 2: range_coeffs = avg(real_coeff_v_pásmu) / global_coeff_fáze1
    Fáze 3: global_coeff ČISTÝ = exponenciálně vážený průměr (real_coeff / range_coeff)
             → odstraní systematický bias způsobený tím, v jakých pásmech se právě topí
    Fáze 4: range_coeffs přepočítány vůči čistému global_coeff

    Výsledek: global_coeff a range_coeffs jsou navzájem konzistentní a čisté.
    """
    try:
        df = pd.DataFrame([vars(d) for d in data.history])
        valid = df[(df['water'] > 0.5) & (df['ele'] > 0.5)].copy()

        if len(valid) < 5:
            return {
                "global_coeff": 1.157,
                "range_breaks": [0, 10, 20, 30, 40, 50],
                "range_coeffs": {
                    "0-10": 1.0, "10-20": 1.05, "20-30": 1.01,
                    "30-40": 0.98, "40-50": 0.97, "50+": 0.97
                },
                "msg": "Malo dat – použity výchozí hodnoty"
            }

        # Outlier filter
        valid['real_coeff'] = valid['ele'] / valid['water']
        valid = valid[(valid['real_coeff'] >= 0.85) & (valid['real_coeff'] <= 1.50)].copy()

        # --- Hranice pásem ---
        if data.range_breaks and len(data.range_breaks) >= 2:
            breaks = sorted(data.range_breaks)
        else:
            # Pevné kroky po 10 kWh
            max_w  = float(valid['water'].max())
            strop  = min(100.0, ((max_w // 10) + 1) * 10)
            breaks = [float(x) for x in range(0, int(strop), 10)]
            # Spoj poslední pásmo pokud má méně než 3 vzorky
            if len(breaks) > 2:
                last_data = valid[valid['water'] >= breaks[-1]]
                if len(last_data) < 3:
                    breaks.pop()

        breaks_ext = breaks + [float('inf')]

        valid['range'] = valid['water'].apply(lambda w: _get_range_label(w, breaks_ext))

        # === FÁZE 1: global_coeff bez range korekce ===
        gc_raw = _compute_global_coeff(valid, decay=0.97)

        # === FÁZE 2: range_coeffs vůči gc_raw ===
        range_coeffs_raw = {}
        for lbl, grp in valid.groupby('range', sort=False):
            avg_real = float(grp['real_coeff'].mean())
            range_coeffs_raw[lbl] = float(np.clip(avg_real / gc_raw, 0.70, 1.50))

        # === FÁZE 3: global_coeff ČISTÝ (očištěný od range efektu) ===
        gc_clean = _compute_global_coeff(valid, range_coeffs_raw, breaks_ext, decay=0.97)

        # === FÁZE 4: range_coeffs vůči čistému global_coeff ===
        range_coeffs  = {}
        range_details = {}
        for lbl, grp in valid.groupby('range', sort=False):
            avg_real = float(grp['real_coeff'].mean())
            rc = float(np.clip(avg_real / gc_clean, 0.70, 1.50))
            range_coeffs[lbl] = round(rc, 4)
            range_details[lbl] = {
                "count":          int(len(grp)),
                "avg_real_coeff": round(avg_real, 4),
                "range_coeff":    round(rc, 4),
                "stdev_real":     round(float(grp['real_coeff'].std()), 4) if len(grp) > 1 else 0,
            }

        # Seřazené labely
        ordered_coeffs = {}
        for i in range(len(breaks_ext) - 1):
            lo, hi = breaks_ext[i], breaks_ext[i + 1]
            lbl = f"{int(lo)}+" if hi == float('inf') else f"{int(lo)}-{int(hi)}"
            ordered_coeffs[lbl] = range_coeffs.get(lbl, 1.0)

        return {
            "global_coeff":      round(gc_clean, 4),
            "global_coeff_raw":  round(gc_raw, 4),   # pro debug / porovnání
            "range_breaks":      breaks,
            "range_coeffs":      ordered_coeffs,
            "range_details":     range_details,
            "valid_days":        int(len(valid)),
            "msg":               "OK"
        }

    except Exception as e:
        import traceback
        return {
            "global_coeff": 1.157,
            "range_breaks": [0, 10, 20, 30, 40, 50],
            "range_coeffs": {
                "0-10": 1.0, "10-20": 1.05, "20-30": 1.01,
                "30-40": 0.98, "40-50": 0.97, "50+": 0.97
            },
            "msg":   f"Python Error: {str(e)}",
            "debug": traceback.format_exc()
        }


# --- 4. SMART DELTA (Rozpočítání elektřiny mezi dny) ---
@app.post("/smart-distribute")
def smart_distribute(data: DistributeRequest):
    try:
        daily_water_logs = [vars(item) for item in data.daily_water_logs]
        total_ele_delta  = data.total_ele_delta
        total_water      = sum(d['water_kwh'] for d in daily_water_logs)

        results = []
        if total_water == 0:
            count = len(daily_water_logs)
            even  = total_ele_delta / count if count > 0 else 0
            for d in daily_water_logs:
                results.append({'date': d['date'], 'ele_kwh': round(even, 2)})
            return {"results": results}

        for d in daily_water_logs:
            ratio     = d['water_kwh'] / total_water if d['water_kwh'] > 0 else 0
            daily_ele = total_ele_delta * ratio
            results.append({'date': d['date'], 'ele_kwh': round(daily_ele, 2)})

        return {"results": results}
    except Exception as e:
        return {"results": [], "error": str(e)}
