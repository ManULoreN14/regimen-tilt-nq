#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
comparar_nra_das.py — genera nra_das_comparativa.json a partir de:
  - nra_das/output_backtest_nradas.csv       (equity diaria del otro sistema)
  - nra_das/output_backtest_nradas_por_año.csv (retornos anuales, informativo)
  - nra_das/output_backtest_nradas.json      (métricas oficiales del otro sistema)
  - sistema_regimen_tilt.json                (nuestro propio sistema, ya generado)

No toca nada del sistema Régimen+Tilt; si esta carpeta o estos ficheros no
existen, index.html simplemente no muestra la comparativa (degradación
elegante). Actualiza estos 3 CSV/JSON en nra_das/ cuando quieras refrescar
la comparación y vuelve a correr este script — no hace falta tocar nada más.

Metodología de la comparación (para que sea justa, "mismo periodo"):
  - Se usa como ventana común el rango de fechas de NUESTRO sistema (empieza
    más tarde que NRA-DAS porque el score de volatilidad necesita historial
    para calentar). Las métricas "mismo periodo" recalculan ambos sistemas
    SOLO en esa ventana común, para comparar manzanas con manzanas.
  - Las métricas "oficiales" son las que cada proyecto reporta con su propio
    periodo completo (más largo en el caso de NRA-DAS, que arranca en 2002).
"""
import json
from pathlib import Path
import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent
NRA_DIR = BASE / "nra_das"
NRA_CSV = NRA_DIR / "output_backtest_nradas.csv"
NRA_ANUAL = NRA_DIR / "output_backtest_nradas_por_año.csv"
NRA_JSON = NRA_DIR / "output_backtest_nradas.json"
SISTEMA_JSON = BASE / "sistema_regimen_tilt.json"
OUT = BASE / "nra_das_comparativa.json"

REBAL = 5  # mismo submuestreo que construir_sistema.py, para que las fechas casen


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
    if not (NRA_CSV.exists() and SISTEMA_JSON.exists()):
        print("[COMPARATIVA] faltan ficheros de nra_das/ o sistema_regimen_tilt.json "
              "-> no se genera comparativa (esto no rompe el sistema principal).")
        if OUT.exists():
            OUT.unlink()  # si antes existía y ahora ya no hay datos, la retiramos
        return

    sistema = json.loads(SISTEMA_JSON.read_text(encoding="utf-8"))
    fechas_sistema = pd.to_datetime(sistema["fechas"])

    nra = pd.read_csv(NRA_CSV, parse_dates=["fecha"]).set_index("fecha").sort_index()
    nra_meta = json.loads(NRA_JSON.read_text(encoding="utf-8")) if NRA_JSON.exists() else {}
    nra_anual = pd.read_csv(NRA_ANUAL) if NRA_ANUAL.exists() else None

    # --- serie diaria de NRA-DAS reindexada a las fechas (submuestreadas) de nuestro sistema ---
    nra_exp = nra["qqq_weight"].reindex(fechas_sistema.union(nra.index)).sort_index() \
        .ffill(limit=5).reindex(fechas_sistema)
    nra_eq = nra["equity_sys"].reindex(fechas_sistema.union(nra.index)).sort_index() \
        .ffill(limit=5).reindex(fechas_sistema)
    nra_eq_bh = nra["equity_qqq"].reindex(fechas_sistema.union(nra.index)).sort_index() \
        .ffill(limit=5).reindex(fechas_sistema)

    # rebase a 1.0 en el primer punto donde ambas series tienen dato
    primero_comun = nra_eq.first_valid_index()
    if primero_comun is not None:
        base_nra = nra_eq.loc[primero_comun]
        base_bh = nra_eq_bh.loc[primero_comun]
        nra_eq = nra_eq / base_nra
        nra_eq_bh = nra_eq_bh / base_bh

    def arr(s):
        return [round(float(x), 4) if pd.notna(x) else None for x in s.values]

    # --- métricas "mismo periodo" (ventana = nuestro sistema, la más corta) ---
    ini = fechas_sistema.min()
    r_nra_mismo = nra["equity_sys"].pct_change()[nra.index >= ini].dropna()
    r_nuestro_mismo = pd.Series(sistema["equity_estrategia"], index=fechas_sistema).pct_change().dropna()
    r_bh_mismo = nra["equity_qqq"].pct_change()[nra.index >= ini].dropna()

    # correlación de retornos diarios en la ventana común (submuestreados a 5d, igual que el resto)
    r_nra_5d = nra["equity_sys"].pct_change(REBAL)[nra.index >= ini]
    ret_nuestro = pd.Series(sistema["equity_estrategia"], index=fechas_sistema)
    r_nuestro_5d = ret_nuestro.pct_change()
    comunes = r_nra_5d.reindex(fechas_sistema).dropna().index.intersection(r_nuestro_5d.dropna().index)
    correlacion = None
    if len(comunes) > 30:
        correlacion = round(float(np.corrcoef(
            r_nra_5d.reindex(comunes).values, r_nuestro_5d.reindex(comunes).values)[0, 1]), 2)

    # turnover propio (para comparar con el 516.3%/año que reporta NRA-DAS)
    exp_nuestro = pd.Series(sistema["exposicion_pct"], index=fechas_sistema) / 100
    turn_nuestro_anual = round(
        float(exp_nuestro.diff().abs().sum() / ((fechas_sistema.max() - fechas_sistema.min()).days / 365.25) * 100), 1)

    out = {
        "generado": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"),
        "nra_das_periodo_oficial": nra_meta.get("nra_das", {}).get("periodo"),
        "nuestro_periodo": f"{sistema['desde']} / {sistema['hasta']}",
        "fechas": [d.strftime("%Y-%m-%d") for d in fechas_sistema],
        "exposicion_pct_nra": [None if x is None else round(x * 100, 1) for x in arr(nra_exp)],
        "equity_nra": arr(nra_eq),
        "equity_nra_bh_qqq": arr(nra_eq_bh),
        "metricas_oficiales_nra": nra_meta.get("nra_das", {}),
        "metricas_oficiales_nra_qqq_bh": nra_meta.get("qqq_bh", {}),
        "turnover_oficial_nra_anual_pct": nra_meta.get("turnover", {}).get("turnover_anual_pct"),
        "turnover_nuestro_anual_pct": turn_nuestro_anual,
        "mismo_periodo": {
            "ventana": f"{ini.strftime('%Y-%m-%d')} / {sistema['hasta']}",
            "nra_das": stats(r_nra_mismo),
            "nra_qqq_bh": stats(r_bh_mismo),
            "nuestro_sistema": sistema["metricas"]["estrategia"]["full"],
        },
        "correlacion_retornos_5d": correlacion,
        "crisis_nra": nra_meta.get("crisis", {}),
        "por_año_nra": nra_anual.to_dict(orient="records") if nra_anual is not None else [],
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"[COMPARATIVA] escrito {OUT.name}: {len(out['fechas'])} pts · "
          f"correlación 5d={correlacion} · turnover nuestro={turn_nuestro_anual}%/año "
          f"vs NRA-DAS={out['turnover_oficial_nra_anual_pct']}%/año")


if __name__ == "__main__":
    main()
