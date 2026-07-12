#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generar_ensemble.py — construye la estrategia "lo mejor de los tres mundos":

  En tendencia alcista de corto plazo (momentum 20 días > 0): sigue la
  exposición MÁS ALTA de los tres sistemas (Régimen+Tilt, NRA-DAS, Quant
  Engine) ese día.
  En tendencia bajista de corto plazo (momentum 20 días < 0): sigue la
  exposición MÁS BAJA de los tres.

Validado con datos reales (ver conversación): mejora CAGR, MaxDD y Sharpe
frente a cualquiera de los tres sistemas por separado, y la mejora se
mantiene tanto en el tramo in-sample (≤2018) como en el out-of-sample
(≥2019) — no es un efecto de sobreajuste al periodo fácil.

Requiere que ya existan: sistema_regimen_tilt.json, nra_das_comparativa.json
y quant_engine_comparativa.json (corre construir_sistema.py y los dos
comparar_*.py antes que este). Si falta alguno, este script no genera nada
y no rompe el resto de la web.

Escribe ensemble_comparativa.json con el MISMO esquema que usan las demás
comparativas, así que index.html lo detecta y lo pinta solo — no hace
falta tocar nada del front-end salvo añadir esta entrada a
COMPARACIONES_CFG (ya hecho).
"""
import json
from pathlib import Path
import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent
SISTEMA_JSON = BASE / "sistema_regimen_tilt.json"
NRA_JSON = BASE / "nra_das_comparativa.json"
QE_JSON = BASE / "quant_engine_comparativa.json"
MAESTRO = BASE / "historico_maestro.csv"
OUT = BASE / "ensemble_comparativa.json"

LAG_EJEC = 2
COSTE_BPS = 5
MOM_DIAS = 20  # ventana de momentum que decide "subiendo" vs "bajando"


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
    faltan = [p.name for p in (SISTEMA_JSON, NRA_JSON, QE_JSON, MAESTRO) if not p.exists()]
    if faltan:
        print(f"[ENSEMBLE] faltan ficheros ({', '.join(faltan)}) -> no se genera. "
              f"Corre construir_sistema.py, comparar_nra_das.py y "
              f"comparar_quant_engine.py primero.")
        if OUT.exists():
            OUT.unlink()
        return

    sistema = json.loads(SISTEMA_JSON.read_text(encoding="utf-8"))
    nra = json.loads(NRA_JSON.read_text(encoding="utf-8"))
    qe = json.loads(QE_JSON.read_text(encoding="utf-8"))

    fechas = pd.to_datetime(sistema["fechas"])
    e_ours = pd.Series(sistema["exposicion_pct"], index=fechas) / 100
    e_nra = pd.Series(nra["exposicion_pct"], index=fechas) / 100
    e_qe = pd.Series(qe["exposicion_pct"], index=fechas) / 100

    hm = pd.read_csv(MAESTRO, parse_dates=["fecha"]).set_index("fecha").sort_index()
    idxd = hm["NDX_close"].dropna().index
    ndx_d = hm["NDX_close"].reindex(idxd)
    irx_d = hm["IRX_close"].reindex(idxd) if "IRX_close" in hm else pd.Series(0.0, index=idxd)

    mom = ndx_d.pct_change(MOM_DIAS).reindex(fechas)
    df = pd.DataFrame({"ours": e_ours, "nra": e_nra, "qe": e_qe, "mom": mom}).dropna()
    mx = df[["ours", "nra", "qe"]].max(axis=1)
    mn = df[["ours", "nra", "qe"]].min(axis=1)
    exp_5d = pd.Series(np.where(df["mom"] > 0, mx, mn), index=df.index)

    # a diario (ffill) para meter en el motor realista de ejecución
    exp_d = exp_5d.reindex(idxd.union(exp_5d.index)).sort_index().ffill().reindex(idxd)
    exp_ex = exp_d.shift(LAG_EJEC).bfill()
    ndx_fwd = ndx_d.pct_change().shift(-1)
    rf = (irx_d / 100 / 252).fillna(0)
    turn = exp_ex.diff().abs().fillna(0)
    r_diario = exp_ex * ndx_fwd + (1 - exp_ex).clip(lower=0) * rf - turn * COSTE_BPS / 10000

    ini = fechas.min()
    r_diario = r_diario[idxd >= ini].fillna(0)
    eq_diaria = (1 + r_diario).cumprod()
    yr = r_diario.index.year

    met_full = stats(r_diario)
    met_is = stats(r_diario[yr <= 2018])
    met_oos = stats(r_diario[yr >= 2019])

    # equity y exposición submuestreadas a las mismas fechas que el resto (cada 5d)
    eq_5d = eq_diaria.reindex(fechas).ffill()
    eq_5d = eq_5d / eq_5d.iloc[0]
    exp_pct_5d = (exp_5d.reindex(fechas) * 100).round(1)

    # turnover propio del ensemble
    turn_anual = round(float(turn[idxd >= ini].sum() / ((idxd[-1] - ini).days / 365.25) * 100), 1)

    # correlación con nuestro sistema en solitario (informativo)
    correlacion = None
    ret_diario_ours = pd.Series(sistema["equity_estrategia"], index=fechas).pct_change().dropna()
    ret_diario_ens = eq_5d.pct_change().dropna()
    comunes = ret_diario_ours.index.intersection(ret_diario_ens.index)
    if len(comunes) > 30:
        correlacion = round(float(np.corrcoef(
            ret_diario_ours.reindex(comunes), ret_diario_ens.reindex(comunes))[0, 1]), 2)

    crisis = {
        "2008 (ene-dic) [Ensemble]": ret_periodo(eq_diaria, "2008-01-01", "2008-12-31"),
        "2020 Covid (feb-mar) [Ensemble]": ret_periodo(eq_diaria, "2020-02-01", "2020-03-31"),
        "2022 bajista (ene-dic) [Ensemble]": ret_periodo(eq_diaria, "2022-01-01", "2022-12-31"),
        "2025 aranceles (abr) [Ensemble]": ret_periodo(eq_diaria, "2025-04-01", "2025-04-30"),
    }

    out = {
        "nombre": "Ensemble",
        "generado": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"),
        "periodo_oficial": f"{fechas[0].strftime('%Y-%m-%d')} / {fechas[-1].strftime('%Y-%m-%d')} "
                            "(calculado, no es un backtest externo)",
        "nuestro_periodo": f"{sistema['desde']} / {sistema['hasta']}",
        "fechas": [d.strftime("%Y-%m-%d") for d in fechas],
        "exposicion_pct": [None if pd.isna(x) else float(x) for x in exp_pct_5d.values],
        "equity": [None if pd.isna(x) else round(float(x), 4) for x in eq_5d.values],
        "equity_bh": sistema["equity_nasdaq_bh"],
        "metricas_oficiales": {"sistema": "ensemble", "periodo": f"{fechas[0].strftime('%Y-%m-%d')} / {fechas[-1].strftime('%Y-%m-%d')}",
                                "cagr_pct": met_full["cagr"], "max_dd_pct": met_full["maxdd"], "sharpe": met_full["sharpe"]},
        "metricas_oficiales_bh": {},
        "turnover_oficial_anual_pct": turn_anual,
        "turnover_nuestro_anual_pct": nra.get("turnover_nuestro_anual_pct"),
        "mismo_periodo": {
            "ventana": f"{ini.strftime('%Y-%m-%d')} / {sistema['hasta']}",
            "otro_sistema": met_full,
            "otro_qqq_bh": sistema["metricas"]["buyhold"]["full"],
            "nuestro_sistema": sistema["metricas"]["estrategia"]["full"],
        },
        "correlacion_retornos_5d": correlacion,
        "crisis": crisis,
        "por_año": [],
        "formula": ("Sigue la exposición MÁS ALTA de los 3 sistemas (nuestro, NRA-DAS, "
                    "Quant Engine) cuando el Nasdaq lleva 20 sesiones subiendo en neto; "
                    "sigue la MÁS BAJA de los 3 cuando lleva 20 sesiones bajando en neto."),
        "metricas_is_oos": {"is_2018": met_is, "oos_2019": met_oos},
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"[ENSEMBLE] escrito {OUT.name}: {len(out['fechas'])} pts · "
          f"full={met_full} · IS={met_is} · OOS={met_oos}")


if __name__ == "__main__":
    main()
