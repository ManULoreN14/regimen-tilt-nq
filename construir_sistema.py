#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
construir_sistema.py — calcula régimen + tilt + switch monetario sobre
historico_maestro.csv y escribe sistema_regimen_tilt.json (lo que lee index.html).

Diseño (validado, ver CONSOLIDACION_SISTEMA.md):
  1. Régimen SMA200 (MOTOR): NDX < SMA200 -> FLAT (0%). Si >= -> dentro.
     Con FILTRO DE CONFIRMACIÓN: no cambia de régimen hasta que el precio
     lleva CONFIRM_DIAS sesiones seguidas al mismo lado de la SMA200. Evita
     "whipsaw" (entradas/salidas de un solo día que se deshacen enseguida)
     en tramos laterales. Probado con datos reales 2000-2026: mejora CAGR
     y Sharpe manteniendo el mismo nivel de drawdown (ver nota más abajo).
  2. Tilt suave dentro del alcista: exposición 0.50x-1.00x (SIN apalancar,
     restricción dura) según score = pctl(0.06*vol3), con
     vol3 = media(VTS_inv, VVIX/VIX_inv, VIX9D/VIX directo).
  3. Switch monetario: si WALCL cae 60d Y DFF sube >5pb 60d -> se apaga el
     tilt y la exposición se sienta en el PUNTO MEDIO (0.75x) dentro del
     alcista. (En banda sin apalancar, "neutral" = medio, no el techo.)
  4. Rebalanceo semanal (5 días de trading).

Backtest realista: retraso de ejecución 2 días + 5 bps por rebalanceo.
Métricas: full / in-sample <=2018 / out-of-sample >=2019.
Los números son los que produce ESTA pipeline sobre TUS datos, sin adornar.
"""
import json
from pathlib import Path
import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent
MAESTRO = BASE / "historico_maestro.csv"
OUT = BASE / "sistema_regimen_tilt.json"

# --- parámetros del sistema (no tocar sin datos, ver los .md) ---
SMA = 200
CONFIRM_DIAS = 3                          # confirmación anti-whipsaw (probado con datos)
BANDA_LO, BANDA_HI = 0.50, 1.00          # sin apalancamiento
NEUTRAL = (BANDA_LO + BANDA_HI) / 2.0     # 0.75x -> punto medio para el switch
W_VOL = 0.06                              # peso de la señal de volatilidad
REBAL = 5                                 # días de trading por rebalanceo
LAG_EJEC = 2                              # días de retraso de ejecución
COSTE_BPS = 5                             # coste por rebalanceo


def expanding_percentile(s, warmup=60):
    arr = s.values.astype(float)
    out = np.full(len(arr), np.nan)
    seen = []
    for i in range(len(arr)):
        if np.isnan(arr[i]):
            continue
        seen.append(arr[i])
        if len(seen) >= warmup:
            out[i] = (np.array(seen) <= arr[i]).mean() * 100
    return pd.Series(out, index=s.index)


def regimen_confirmado(ndx, sma, n=CONFIRM_DIAS):
    """Régimen SMA200 con confirmación de n días: solo cambia de estado
    (dentro/fuera) cuando el precio lleva n sesiones seguidas al mismo
    lado de la media. Reduce whipsaw en tramos laterales sin tocar la
    protección ante caídas grandes (el régimen sigue siendo el motor)."""
    crudo = (ndx >= sma).fillna(False).astype(int)
    conf = crudo.rolling(n).sum()
    estado = []
    actual = False
    for c, r in zip(conf.values, crudo.values):
        if np.isnan(c):
            estado.append(False)
            continue
        if not actual and c == n:
            actual = True
        elif actual and c == 0:
            actual = False
        estado.append(actual)
    return pd.Series(estado, index=ndx.index)


def stats(r):
    r = r.dropna()
    if len(r) < 2:
        return {"cagr": None, "maxdd": None, "sharpe": None}
    eq = (1 + r).cumprod()
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    return {
        "cagr": round(((eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1) * 100, 1),
        "maxdd": round(((eq / eq.cummax()) - 1).min() * 100, 1),
        "sharpe": round((r.mean() / r.std()) * (252 ** 0.5), 2) if r.std() > 0 else None,
    }


def main():
    hm = pd.read_csv(MAESTRO, parse_dates=["fecha"]).set_index("fecha").sort_index()
    idx = hm["NDX_close"].dropna().index
    ndx = hm["NDX_close"].reindex(idx)
    vix = hm["VIX_close"].reindex(idx)
    vix3m = hm["VIX3M_close"].reindex(idx)
    vix9d = hm["VIX9D_close"].reindex(idx) if "VIX9D_close" in hm else pd.Series(np.nan, index=idx)
    vvix = hm["VVIX_close"].reindex(idx) if "VVIX_close" in hm else pd.Series(np.nan, index=idx)
    irx = hm["IRX_close"].reindex(idx) if "IRX_close" in hm else pd.Series(0.0, index=idx)
    walcl = hm["WALCL"].reindex(idx) if "WALCL" in hm else pd.Series(np.nan, index=idx)
    dff = hm["DFF"].reindex(idx) if "DFF" in hm else pd.Series(np.nan, index=idx)

    pct = expanding_percentile
    # tres estructuras de volatilidad; VIX9D/VIX va DIRECTO (verificado)
    vts = 100 - pct(vix3m / vix)
    vvx = 100 - pct(vvix / vix) if vvix.notna().any() else pd.Series(np.nan, index=idx)
    v9d = pct(vix9d / vix) if vix9d.notna().sum() > 200 else pd.Series(np.nan, index=idx)

    parts = pd.DataFrame({"vts": vts, "vvx": vvx, "v9d": v9d})
    vol3 = parts.mean(axis=1, skipna=True)     # media de las disponibles
    score = pct(vol3)

    # régimen (con confirmación anti-whipsaw) y switch monetario
    sma200 = ndx.rolling(SMA).mean()
    alc = regimen_confirmado(ndx, sma200, CONFIRM_DIAS)
    if walcl.notna().any() and dff.notna().any():
        duro = ((walcl.diff(60) < 0) & (dff.diff(60) > 0.05)).reindex(idx).fillna(False)
    else:
        duro = pd.Series(False, index=idx)

    # mapeo score -> factor de tilt en [0,1] (rampa entre pctl 30 y 70)
    b = score.apply(lambda x: 0.5 if pd.isna(x)
                    else (1.0 if x >= 70 else 0.0 if x <= 30 else (x - 30) / 40.0))
    exp_d = pd.Series((BANDA_LO + b * (BANDA_HI - BANDA_LO)) * np.where(alc, 1.0, 0.0), index=idx)
    # switch: en régimen duro, apaga el tilt -> punto medio (de-riesgo vs techo)
    exp_d[duro & alc] = NEUTRAL

    # rebalanceo semanal (mantiene la última exposición durante 5 días)
    v = exp_d.values.copy()
    last = None
    for i in range(len(v)):
        if last is None or (i - last) >= REBAL:
            last = i
        else:
            v[i] = v[last]
    exp = pd.Series(v, index=idx)

    # equity realista: retraso de ejecución + coste por turno
    exp_ex = exp.shift(LAG_EJEC).bfill()
    ndx_fwd = ndx.pct_change().shift(-1)          # retorno de mañana
    rf = (irx / 100 / 252).fillna(0)              # libre de riesgo cuando exp<1
    turn = exp_ex.diff().abs().fillna(0)
    r_str = exp_ex * ndx_fwd + (1 - exp_ex).clip(lower=0) * rf - turn * COSTE_BPS / 10000

    ini = score.first_valid_index()
    mask = idx >= ini
    r_str = r_str[mask].fillna(0)
    r_bh = ndx_fwd[mask].fillna(0)
    ix = r_str.index
    yr = ix.year

    eq_s = (1 + r_str).cumprod(); eq_s /= eq_s.iloc[0]
    eq_bh = (1 + r_bh).cumprod(); eq_bh /= eq_bh.iloc[0]

    met = {
        "estrategia": {"full": stats(r_str), "is": stats(r_str[yr <= 2018]), "oos": stats(r_str[yr >= 2019])},
        "buyhold": {"full": stats(r_bh), "is": stats(r_bh[yr <= 2018]), "oos": stats(r_bh[yr >= 2019])},
    }

    # submuestreo cada 5 días para aligerar el JSON
    ds = ix[::REBAL]

    def arr(s):
        return [round(float(x), 4) if pd.notna(x) else None for x in s.reindex(ds).values]

    out = {
        "generado": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"),
        "desde": ix[0].strftime("%Y-%m-%d"),
        "hasta": ix[-1].strftime("%Y-%m-%d"),
        "score_hoy": round(float(score.dropna().iloc[-1]), 1) if score.notna().any() else None,
        "regimen_hoy": "ALCISTA" if bool(alc.iloc[-1]) else "BAJISTA (flat)",
        "exposicion_hoy_pct": round(float(exp.iloc[-1]) * 100),
        "switch_monetario": "DURO (tilt off, neutral 0.75x)" if bool(duro.iloc[-1]) else "normal",
        "banda": [BANDA_LO, BANDA_HI],
        "formula": ("Régimen SMA200 con confirmación de 3 días (evita whipsaw) + tilt "
                    "0.50x-1.00x por señal de estructura de volatilidad (VTS, VVIX/VIX, "
                    "VIX9D/VIX) dentro del alcista + switch monetario (neutral 0.75x en "
                    "QT) + rebalanceo semanal."),
        "nota": ("Números REALES de esta pipeline (retraso ejec. 2d + 5bps), no cifras "
                 "ideales. El motor es la regla SMA200 (con confirmación de 3 días para "
                 "reducir cambios de régimen que se deshacen enseguida); el tilt y el "
                 "switch añaden poco. El sistema NO bate al Nasdaq en retorno: su valor "
                 "es recortar el drawdown (~a la mitad). El Sharpe ~2.0 de los apuntes "
                 "viejos era 2011-2019 (dinero fácil) o sin costes; el realista es ~0.8 full."),
        "fechas": [d.strftime("%Y-%m-%d") for d in ds],
        "score": arr(score),
        "exposicion_pct": [None if x is None else round(x * 100, 1) for x in arr(exp)],
        "equity_estrategia": arr(eq_s),
        "equity_nasdaq_bh": arr(eq_bh),
        "metricas": met,
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"[SISTEMA] escrito {OUT.name}: {len(out['fechas'])} pts · "
          f"score_hoy={out['score_hoy']} · exp={out['exposicion_hoy_pct']}% · "
          f"régimen={out['regimen_hoy']}")
    print(f"[SISTEMA] estrategia full: {met['estrategia']['full']}")
    print(f"[SISTEMA] buyhold   full: {met['buyhold']['full']}")


if __name__ == "__main__":
    main()
