#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generar_precios.py — genera precios.json para la pestaña "Estudio técnico"
del dashboard (gráfico multi-temporalidad con velas reales).

Produce, por cada serie de PRECIO, velas OHLC en 4 temporalidades:
    1M (mensual), 1W (semanal), 1D (diario)  -> histórico completo (yfinance)
    4H (4 horas)                             -> ~2 años (intradía 1h resampleado)

Las curvas de equity de tus sistemas NO se generan aquí: la pestaña las lee
directamente de los JSON que el dashboard ya carga en memoria
(sistema_regimen_tilt.json y los *_comparativa.json). Así no se duplican.

Degradación elegante: si una serie o una temporalidad falla (típico en el
intradía de índices), se omite ESA pieza y el resto sigue. Nunca rompe el
pipeline ni sobrescribe con vacío.

Uso:
    python generar_precios.py            # escribe ./precios.json
Se integra como un paso más en actualizar.yml / actualizar_todo.bat,
después de construir_sistema.py.
"""
import json, sys, datetime as dt
from pathlib import Path
import pandas as pd

try:
    import yfinance as yf
except Exception:
    yf = None

try:
    from patrones_tecnicos import detectar as _detectar_patrones
except Exception:
    _detectar_patrones = None

BASE = Path(__file__).resolve().parent

# Series de precio. Para intradía, un índice (^NDX) suele venir vacío en
# Yahoo, así que se usa el ETF equivalente como proxy (campo "intradia").
PRECIO_CFG = [
    {"key": "NDX", "nombre": "Nasdaq-100",        "ticker": "^NDX", "intradia": "QQQ"},
    {"key": "VIX", "nombre": "VIX (volatilidad)", "ticker": "^VIX", "intradia": None},
]


def _log(m): print(f"[PRECIOS] {m}")


def _ms(ts) -> int:
    t = pd.Timestamp(ts)
    if t.tz is None:
        t = t.tz_localize("UTC")
    return int(t.timestamp() * 1000)


def _rows(df) -> list:
    out = []
    for ts, r in df.iterrows():
        try:
            v = float(r["Volume"]) if "Volume" in r and pd.notna(r["Volume"]) else 0.0
            out.append([_ms(ts), round(float(r["Open"]), 2), round(float(r["High"]), 2),
                        round(float(r["Low"]), 2), round(float(r["Close"]), 2), round(v)])
        except Exception:
            continue
    return out


def _daily(ticker):
    h = yf.Ticker(ticker).history(period="max", interval="1d", auto_adjust=False)
    cols = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in h.columns]
    return h[cols].dropna(subset=["Open", "High", "Low", "Close"])


def _resample(daily, rule):
    agg = {"Open": "first", "High": "max", "Low": "min", "Close": "last"}
    if "Volume" in daily.columns:
        agg["Volume"] = "sum"
    return daily.resample(rule).agg(agg).dropna(subset=["Open", "High", "Low", "Close"])


def _intraday_4h(ticker):
    """1h de los últimos ~729 días -> resampleado a 4h. Puede venir vacío."""
    start = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=729)).date()
    h = yf.Ticker(ticker).history(start=str(start), interval="1h", auto_adjust=False)
    if h is None or h.empty:
        return pd.DataFrame()
    agg = {"Open": "first", "High": "max", "Low": "min", "Close": "last"}
    cols = ["Open", "High", "Low", "Close"]
    if "Volume" in h.columns:
        agg["Volume"] = "sum"; cols = cols + ["Volume"]
    return h[cols].resample("4h").agg(agg).dropna(subset=["Open", "High", "Low", "Close"])


def _serie(cfg):
    tf = {}
    try:
        d = _daily(cfg["ticker"])
        if d.empty:
            raise RuntimeError("diario vacío")
        tf["1D"] = _rows(d)
        tf["1W"] = _rows(_resample(d, "W-FRI"))
        try:
            tf["1M"] = _rows(_resample(d, "ME"))     # month-end (pandas >= 2.2)
        except Exception:
            tf["1M"] = _rows(_resample(d, "M"))
        _log(f"{cfg['key']}: 1D={len(tf['1D'])} 1W={len(tf['1W'])} 1M={len(tf['1M'])}")
    except Exception as e:
        _log(f"{cfg['key']}: sin diario/semanal/mensual ({e})")
    tkr = cfg.get("intradia")
    if tkr:
        try:
            i = _intraday_4h(tkr)
            if not i.empty:
                tf["4H"] = _rows(i)
                _log(f"{cfg['key']}: 4H={len(tf['4H'])} (vía {tkr}, ~2 años)")
            else:
                _log(f"{cfg['key']}: 4H sin datos intradía (se omite)")
        except Exception as e:
            _log(f"{cfg['key']}: 4H falló ({e}) — se omite")
    return {"nombre": cfg["nombre"], "tipo": "ohlc", "tf": tf,
            "patrones": _patrones_por_tf(tf, cfg["key"])} if tf else None


def _patrones_por_tf(tf_dict, key):
    """Detección de patrones (vela + gráfico), SOLO para inspección visual en
    el Estudio Técnico — nunca se usa como señal del sistema. Ver cabecera
    de patrones_tecnicos.py para el porqué. Tolerante: si falla, se omite
    esa temporalidad sin romper el resto del pipeline."""
    if _detectar_patrones is None:
        _log("patrones_tecnicos.py no disponible: se omiten anotaciones")
        return {}
    out = {}
    for tf, rows in tf_dict.items():
        try:
            out[tf] = _detectar_patrones(rows)
        except Exception as e:
            _log(f"patrones {key}/{tf}: fallo detectando ({e}) — se omite")
    if out:
        resumen = " ".join(f"{tf}={len(v)}" for tf, v in out.items())
        _log(f"{key}: patrones detectados {resumen}")
    return out


def main():
    if yf is None:
        _log("yfinance no disponible: pip install yfinance"); sys.exit(1)
    series = {}
    for cfg in PRECIO_CFG:
        s = _serie(cfg)
        if s:
            series[cfg["key"]] = s
    if not series:
        _log("no se generó ninguna serie — abortando sin sobrescribir"); sys.exit(1)
    out = {"generado": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
           "demo": False, "series": series}
    (BASE / "precios.json").write_text(
        json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    _log(f"escrito precios.json — series: {list(series)}")


if __name__ == "__main__":
    main()
