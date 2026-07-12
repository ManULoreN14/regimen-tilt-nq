#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
comparativa_lib.py — lógica común para comparar cualquier sistema externo
contra Régimen+Tilt. La usan comparar_nra_das.py, comparar_quant_engine.py,
y cualquier script comparar_<nombre>.py que añadas en el futuro.

Formato de entrada esperado (igual para todos los sistemas externos):
  - CSV diario con columnas: <col_fecha>, equity_sys, equity_qqq, qqq_weight
  - CSV anual (opcional, solo informativo, se pasa tal cual al JSON)
  - JSON de métricas oficiales con estructura {"<clave_sistema>": {...}, "qqq_bh": {...}, ...}

Salida: un JSON con esquema genérico (mismas claves para cualquier sistema),
para que index.html pueda pintar cualquier número de comparaciones sin
necesitar código específico por sistema.
"""
import json
from pathlib import Path
import numpy as np
import pandas as pd

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


def generar_comparativa(nombre, clave_json, csv_diario, csv_anual, json_meta,
                         sistema_json, out_path, col_fecha="fecha"):
    """
    nombre        : nombre a mostrar ("NRA-DAS", "Quant Engine"...)
    clave_json    : clave del sistema dentro de su propio JSON de métricas
                    (ej. "nra_das", "quant_engine")
    csv_diario    : Path al CSV con equity_sys/equity_qqq/qqq_weight
    csv_anual     : Path al CSV de retornos anuales (o None)
    json_meta     : Path al JSON de métricas oficiales (o None)
    sistema_json  : Path a sistema_regimen_tilt.json (el nuestro)
    out_path      : Path de salida para el JSON de comparativa
    col_fecha     : nombre de la columna de fecha en csv_diario ("fecha" o "date")
    """
    if not (csv_diario.exists() and sistema_json.exists()):
        print(f"[COMPARATIVA {nombre}] faltan ficheros -> no se genera "
              f"(esto no rompe el sistema principal).")
        if out_path.exists():
            out_path.unlink()
        return

    sistema = json.loads(sistema_json.read_text(encoding="utf-8"))
    fechas_sistema = pd.to_datetime(sistema["fechas"])

    otro = pd.read_csv(csv_diario, parse_dates=[col_fecha]).set_index(col_fecha).sort_index()
    meta = json.loads(json_meta.read_text(encoding="utf-8")) if (json_meta and json_meta.exists()) else {}
    anual = pd.read_csv(csv_anual) if (csv_anual and csv_anual.exists()) else None

    # --- serie diaria del otro sistema reindexada a las fechas (submuestreadas) de nuestro sistema ---
    otro_exp = otro["qqq_weight"].reindex(fechas_sistema.union(otro.index)).sort_index() \
        .ffill(limit=5).reindex(fechas_sistema)
    otro_eq = otro["equity_sys"].reindex(fechas_sistema.union(otro.index)).sort_index() \
        .ffill(limit=5).reindex(fechas_sistema)
    otro_eq_bh = otro["equity_qqq"].reindex(fechas_sistema.union(otro.index)).sort_index() \
        .ffill(limit=5).reindex(fechas_sistema)

    # rebase a 1.0 en el primer punto con dato
    primero = otro_eq.first_valid_index()
    if primero is not None:
        otro_eq = otro_eq / otro_eq.loc[primero]
        otro_eq_bh = otro_eq_bh / otro_eq_bh.loc[primero]

    def arr(s):
        return [round(float(x), 4) if pd.notna(x) else None for x in s.values]

    # --- métricas "mismo periodo" (ventana = nuestro sistema, normalmente la más corta) ---
    ini = fechas_sistema.min()
    r_otro_mismo = otro["equity_sys"].pct_change()[otro.index >= ini].dropna()
    r_bh_mismo = otro["equity_qqq"].pct_change()[otro.index >= ini].dropna()

    # correlación de retornos a 5d (mismo horizonte que nuestro rebalanceo)
    r_otro_5d = otro["equity_sys"].pct_change(REBAL)[otro.index >= ini]
    ret_nuestro = pd.Series(sistema["equity_estrategia"], index=fechas_sistema)
    r_nuestro_5d = ret_nuestro.pct_change()
    comunes = r_otro_5d.reindex(fechas_sistema).dropna().index.intersection(r_nuestro_5d.dropna().index)
    correlacion = None
    if len(comunes) > 30:
        correlacion = round(float(np.corrcoef(
            r_otro_5d.reindex(comunes).values, r_nuestro_5d.reindex(comunes).values)[0, 1]), 2)

    exp_nuestro = pd.Series(sistema["exposicion_pct"], index=fechas_sistema) / 100
    turn_nuestro_anual = round(
        float(exp_nuestro.diff().abs().sum() / ((fechas_sistema.max() - fechas_sistema.min()).days / 365.25) * 100), 1)

    out = {
        "nombre": nombre,
        "generado": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"),
        "periodo_oficial": meta.get(clave_json, {}).get("periodo"),
        "nuestro_periodo": f"{sistema['desde']} / {sistema['hasta']}",
        "fechas": [d.strftime("%Y-%m-%d") for d in fechas_sistema],
        "exposicion_pct": [None if x is None else round(x * 100, 1) for x in arr(otro_exp)],
        "equity": arr(otro_eq),
        "equity_bh": arr(otro_eq_bh),
        "metricas_oficiales": meta.get(clave_json, {}),
        "metricas_oficiales_bh": meta.get("qqq_bh", {}),
        "turnover_oficial_anual_pct": meta.get("turnover", {}).get("turnover_anual_pct"),
        "turnover_nuestro_anual_pct": turn_nuestro_anual,
        "mismo_periodo": {
            "ventana": f"{ini.strftime('%Y-%m-%d')} / {sistema['hasta']}",
            "otro_sistema": stats(r_otro_mismo),
            "otro_qqq_bh": stats(r_bh_mismo),
            "nuestro_sistema": sistema["metricas"]["estrategia"]["full"],
        },
        "correlacion_retornos_5d": correlacion,
        "crisis": meta.get("crisis", {}),
        "por_año": anual.to_dict(orient="records") if anual is not None else [],
    }
    out_path.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"[COMPARATIVA {nombre}] escrito {out_path.name}: {len(out['fechas'])} pts · "
          f"correlación 5d={correlacion} · turnover nuestro={turn_nuestro_anual}%/año "
          f"vs {nombre}={out['turnover_oficial_anual_pct']}%/año")
