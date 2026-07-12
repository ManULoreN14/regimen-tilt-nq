#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
comparar_crecimiento.py — genera crecimiento_comparativa.json, con el MISMO
esquema que usan nra_das_comparativa.json / quant_engine_comparativa.json /
ensemble_comparativa.json, así que index.html lo detecta y lo pinta solo.

Sistema "Crecimiento" (revisado 12/07/2026, ver sistema_trend_voltarget.py):
  30% del capital SIEMPRE en el Nasdaq (núcleo, nunca se traspasa) +
  70% sigue precio NDX >= SMA300 (satélite, entra/sale con la tendencia).
Long-only, sin apalancamiento.

Retraso de ejecución: 3 días de trading (no 2), porque así es el proceso
REAL de traspaso entre fondos: señal con el cierre del lunes -> orden el
martes antes de las 13:00 -> valoración de ambas patas el miércoles ->
liquidación visible el jueves. Se modela con exp.shift(2) sobre la señal
+ retorno "forward" (.shift(-1)) -- la misma convención que ya usa
generar_sistema_json.py / generar_ensemble.py, verificada contra el
proceso real de traspasos del usuario.

Uso: correr DESPUÉS de construir_sistema.py (necesita sistema_regimen_tilt.json
para tomar el mismo eje de fechas que usa el resto de comparativas — el
front-end alinea los arrays por POSICIÓN, no por fecha, así que hay que
usar exactamente el mismo grid de 'fechas').

Integración en actualizar_todo.bat: añadir esta línea junto a las otras
comparaciones (paso 4/5), justo después de generar_ensemble.py:
    python comparar_crecimiento.py
    if errorlevel 1 (
        echo ERROR: fallo comparar_crecimiento.py
        goto :error
    )

Integración en index.html: añadir una línea a COMPARACIONES_CFG:
    {archivo:"crecimiento_comparativa.json", color:"#8b5cf6"},
"""
import json
from pathlib import Path
import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent
SISTEMA_JSON = BASE / "sistema_regimen_tilt.json"
MAESTRO = BASE / "historico_maestro.csv"
OUT = BASE / "crecimiento_comparativa.json"

SMA_BLEND = 300
PESO_NUCLEO_BH = 0.30
LAG_EJEC = 2          # + el forward-shift(-1) del retorno = 3d efectivos reales
COSTE_BPS = 5
DIV_ANUAL = 0.0065     # dividendo proxy QQQ, para CAGR comparable con B&H


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


def ret_periodo(eq, d1, d2):
    s = eq[(eq.index >= d1) & (eq.index <= d2)]
    if len(s) < 2:
        return None
    return round(float(s.iloc[-1] / s.iloc[0] - 1) * 100, 2)


def main():
    faltan = [p.name for p in (SISTEMA_JSON, MAESTRO) if not p.exists()]
    if faltan:
        print(f"[CRECIMIENTO-CMP] faltan ficheros ({', '.join(faltan)}) -> no se genera. "
              f"Corre construir_sistema.py primero.")
        if OUT.exists():
            OUT.unlink()
        return

    sistema = json.loads(SISTEMA_JSON.read_text(encoding="utf-8"))
    fechas = pd.to_datetime(sistema["fechas"])  # eje maestro compartido (cada 5d)

    hm = pd.read_csv(MAESTRO, parse_dates=["fecha"]).set_index("fecha").sort_index()
    idxd = hm["NDX_close"].dropna().index
    ndx_d = hm["NDX_close"].reindex(idxd)
    irx_d = hm["IRX_close"].reindex(idxd) if "IRX_close" in hm else pd.Series(0.0, index=idxd)

    sma = ndx_d.rolling(SMA_BLEND).mean()
    t = (ndx_d >= sma).astype(float)
    exp_d = (PESO_NUCLEO_BH + (1 - PESO_NUCLEO_BH) * t).clip(0, 1)
    exp_ex = exp_d.shift(LAG_EJEC).bfill()
    ndx_fwd = ndx_d.pct_change().shift(-1) + DIV_ANUAL / 252
    rf = (irx_d / 100 / 252).fillna(0)
    turn = exp_ex.diff().abs().fillna(0)
    r_diario = exp_ex * ndx_fwd + (1 - exp_ex).clip(lower=0) * rf - turn * COSTE_BPS / 10000

    # ventana COMÚN con sistema_regimen_tilt.json (igual que generar_ensemble.py:
    # ini = fechas.min()), para que "mismo periodo" compare de verdad lo mismo.
    # La SMA300 ya está bien calentada muchísimo antes de 2006, así que esto no
    # recorta warm-up real, solo iguala la ventana de comparación.
    ini = fechas.min()
    r_diario = r_diario[idxd >= ini].fillna(0)
    eq_diaria = (1 + r_diario).cumprod()
    yr = r_diario.index.year

    met_full = stats(r_diario)
    met_is = stats(r_diario[yr <= 2018])
    met_oos = stats(r_diario[yr >= 2019])

    # muestrear en el MISMO eje de fechas que sistema_regimen_tilt.json
    # (index-aligned con DATA.fechas en el front-end; no importa si algún
    # punto queda ligeramente ffill-eado, es el mismo criterio que ensemble)
    eq_5d = eq_diaria.reindex(idxd.union(fechas)).sort_index().ffill().reindex(fechas)
    eq_5d = eq_5d / eq_5d.dropna().iloc[0]
    exp_5d = exp_d.reindex(idxd.union(fechas)).sort_index().ffill().reindex(fechas)
    exp_pct_5d = (exp_5d * 100).round(1)

    turn_anual = round(float(turn[idxd >= ini].sum() / ((idxd[-1] - ini).days / 365.25) * 100), 1)

    correlacion = None
    ret_diario_ours = pd.Series(sistema["equity_estrategia"], index=fechas).pct_change().dropna()
    ret_diario_sma = eq_5d.pct_change().dropna()
    comunes = ret_diario_ours.index.intersection(ret_diario_sma.index)
    if len(comunes) > 30:
        correlacion = round(float(np.corrcoef(
            ret_diario_ours.reindex(comunes), ret_diario_sma.reindex(comunes))[0, 1]), 2)

    crisis = {
        "2008 (ene-dic) [Crecimiento]": ret_periodo(eq_diaria, "2008-01-01", "2008-12-31"),
        "2020 Covid (feb-mar) [Crecimiento]": ret_periodo(eq_diaria, "2020-02-01", "2020-03-31"),
        "2022 bajista (ene-dic) [Crecimiento]": ret_periodo(eq_diaria, "2022-01-01", "2022-12-31"),
        "2025 aranceles (abr) [Crecimiento]": ret_periodo(eq_diaria, "2025-04-01", "2025-04-30"),
    }

    out = {
        "nombre": "Crecimiento",
        "generado": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"),
        "periodo_oficial": f"{fechas[0].strftime('%Y-%m-%d')} / {fechas[-1].strftime('%Y-%m-%d')} "
                            "(calculado, no es un backtest externo)",
        "nuestro_periodo": f"{sistema['desde']} / {sistema['hasta']}",
        "fechas": [d.strftime("%Y-%m-%d") for d in fechas],
        "exposicion_pct": [None if pd.isna(x) else float(x) for x in exp_pct_5d.values],
        "equity": [None if pd.isna(x) else round(float(x), 4) for x in eq_5d.values],
        "equity_bh": sistema["equity_nasdaq_bh"],
        "metricas_oficiales": {"sistema": "crecimiento", "periodo": f"{fechas[0].strftime('%Y-%m-%d')} / {fechas[-1].strftime('%Y-%m-%d')}",
                                "cagr_pct": met_full["cagr"], "max_dd_pct": met_full["maxdd"], "sharpe": met_full["sharpe"]},
        "metricas_oficiales_bh": {},
        "turnover_oficial_anual_pct": turn_anual,
        "turnover_nuestro_anual_pct": None,
        "mismo_periodo": {
            "ventana": f"{ini.strftime('%Y-%m-%d')} / {sistema['hasta']}",
            "otro_sistema": met_full,
            "otro_qqq_bh": sistema["metricas"]["buyhold"]["full"],
            "nuestro_sistema": sistema["metricas"]["estrategia"]["full"],
        },
        "correlacion_retornos_5d": correlacion,
        "crisis": crisis,
        "por_año": [],
        "formula": "30% del capital siempre en el Nasdaq (núcleo, sin traspasos) + 70% sigue "
                   "precio NDX >= SMA300 (satélite). Long-only, sin apalancamiento, "
                   "retraso ejecución real ~3d (traspaso de fondos), coste 5bps.",
        "metricas_is_oos": {"is_2018": met_is, "oos_2019": met_oos},
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"[CRECIMIENTO-CMP] escrito {OUT.name}: {len(out['fechas'])} pts · "
          f"full={met_full} · IS={met_is} · OOS={met_oos}")


if __name__ == "__main__":
    main()
