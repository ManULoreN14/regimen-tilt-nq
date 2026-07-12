#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sistema_trend_voltarget.py — sistema long-only NDX, modo "crecimiento" REVISADO.

Revisión 12/07/2026: se corrigió la convención de retraso de ejecución para
que refleje el proceso REAL de traspaso entre fondos:
    señal (cierre lunes) -> orden (martes, antes de 13:00) ->
    valoración de ambas patas (miércoles) -> liquidación visible (jueves)
  = 3 días de trading de retraso efectivo entre señal y ejecución
  (antes se usaba una aproximación de 2 días, más optimista de lo real).

Con el lag correcto, el sistema 100%-dentro-o-fuera (SMA pura) sufre más
el retraso que un blend con un núcleo siempre invertido (ese núcleo no
tiene riesgo de timing porque nunca se traspasa). Por eso el ganador en
CAGR ahora es el BLEND, no la SMA pura -> es el modo por defecto.

  MODO "crecimiento" (por defecto, recomendado)
      30% del capital SIEMPRE en el Nasdaq (núcleo, sin traspasos) +
      70% sigue precio>=SMA300 (satélite, entra/sale con la tendencia).
      Resultado (conv. real ~3d lag): CAGR 13.6% / MaxDD -30.2% / Sharpe 0.82
      Domina en las 3 métricas al SMA puro (12.6/-31.5/0.78).

  MODO "puro" (alternativa, más simple de operar: 1 solo fondo cada vez)
      Regla: precio >= SMA320 -> 100% dentro; si no -> 100% fuera.
      Resultado (conv. real ~3d lag): CAGR 12.6% / MaxDD -31.5% / Sharpe 0.78
      Se deja disponible porque operar el blend implica mantener SIEMPRE
      una posición del 30% en el Nasdaq (nunca se traspasa esa parte),
      mientras que el modo puro es un único traspaso de fondo completo
      cada vez que cambia el régimen -- más simple de ejecutar a mano.

Descartado con datos (no aportan, ver conversación): cruces EMA/SMA rápida-
lenta, MACD, RSI, dip-buy/Fibonacci, mean-reversion Connors, gate y tilt
por estructura VIX, filtros de confirmación/histéresis (empeoran el global
aunque arreglen tramos concretos como 2015-2017).

Pendiente: sustituir el proxy de "tasa libre de riesgo" (IRX) por el
rendimiento real esperado de los fondos Mutuactivos (Fortaleza A FI /
Flex Bond A EUR) que se usan de facto cuando el dinero sale del Nasdaq.
"""
import numpy as np
import pandas as pd

MODO = "crecimiento"        # "crecimiento" (blend, recomendado) | "puro" (un solo fondo)
SMA_BLEND = 300
PESO_NUCLEO_BH = 0.30       # % siempre dentro del Nasdaq, sin traspasos
SMA_PURO = 320


def calcular_exposicion(ndx: pd.Series) -> pd.Series:
    ndx = ndx.sort_index().astype(float)
    if MODO == "crecimiento":
        t = (ndx >= ndx.rolling(SMA_BLEND).mean()).astype(float)
        return (PESO_NUCLEO_BH + (1 - PESO_NUCLEO_BH) * t).clip(0, 1)
    return (ndx >= ndx.rolling(SMA_PURO).mean()).astype(float)


if __name__ == "__main__":
    hm = pd.read_csv("historico_maestro.csv", parse_dates=["fecha"]).set_index("fecha")
    exp = calcular_exposicion(hm["NDX_close"])
    print(f"Modo {MODO} · {exp.index[-1].date()} · exposición hoy: {round(float(exp.iloc[-1])*100)}%")
