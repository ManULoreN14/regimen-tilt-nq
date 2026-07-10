#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generar_datos.py — construye y mantiene historico_maestro.csv

Fuentes (todas públicas, sin API key):
  - yfinance: ^NDX ^VIX ^VIX3M ^VVIX ^VIX9D ^IRX
  - FRED CSV: WALCL (balance Fed), DFF (fed funds)

Columnas del maestro:
  fecha, NDX_close, VIX_close, VIX3M_close, VIX9D_close, VVIX_close,
  IRX_close, WALCL, DFF

Comportamiento:
  - Primera ejecución (no existe historico_maestro.csv): SIEMBRA el
    histórico largo desde los CSV semilla que vienen en el repo
    (historico_maestro_semilla.csv + *_History.csv de CBOE + FRED),
    y luego intenta traer lo más reciente por internet.
  - Ejecuciones siguientes: carga incremental — solo pide fechas nuevas
    desde la última guardada.
  - VIX3M/VIX9D/VVIX son POCO FIABLES vía yfinance (a veces "delisted").
    Si un ticker falla, NO se rompe el script: se mantiene el último
    valor conocido (forward-fill hasta 10 días hábiles) y se sigue.
"""
import sys
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd

BASE = Path(__file__).resolve().parent
MAESTRO = BASE / "historico_maestro.csv"
FFILL_LIMIT = 10  # días hábiles que aguantamos un ticker caído

TICKERS = {
    "NDX_close": "^NDX",
    "VIX_close": "^VIX",
    "VIX3M_close": "^VIX3M",
    "VIX9D_close": "^VIX9D",
    "VVIX_close": "^VVIX",
    "IRX_close": "^IRX",
}
FRED = {"WALCL": "WALCL", "DFF": "DFF"}
COLS = ["NDX_close", "VIX_close", "VIX3M_close", "VIX9D_close",
        "VVIX_close", "IRX_close", "WALCL", "DFF"]


def log(m):
    print(f"[DATOS] {m}", flush=True)


# ------------------------------------------------------------------ semilla
def _read_cboe(path, col_out):
    """Lee un *_History.csv de CBOE (DATE MM/DD/YYYY, CLOSE)."""
    if not path.exists():
        return pd.Series(dtype=float, name=col_out)
    d = pd.read_csv(path)
    d["DATE"] = pd.to_datetime(d["DATE"], format="%m/%d/%Y", errors="coerce")
    val = "CLOSE" if "CLOSE" in d.columns else d.columns[-1]
    d[val] = pd.to_numeric(d[val], errors="coerce")
    s = d.dropna(subset=["DATE", val]).set_index("DATE")[val].sort_index()
    s.name = col_out
    return s


def _read_fred_csv(path, col_out):
    if not path.exists():
        return pd.Series(dtype=float, name=col_out)
    d = pd.read_csv(path)
    dcol = "date" if "date" in d.columns else d.columns[0]
    vcol = "value" if "value" in d.columns else d.columns[-1]
    d[dcol] = pd.to_datetime(d[dcol], errors="coerce")
    d[vcol] = pd.to_numeric(d[vcol], errors="coerce")
    s = d.dropna(subset=[dcol, vcol]).set_index(dcol)[vcol].sort_index()
    s.name = col_out
    return s


def sembrar():
    """Une los CSV semilla del repo en un maestro inicial (una vez)."""
    log("historico_maestro.csv no existe -> sembrando desde CSV del repo")
    sem = BASE / "historico_maestro_semilla.csv"
    if sem.exists():
        base = pd.read_csv(sem, parse_dates=["fecha"]).set_index("fecha").sort_index()
        base.index.name = "fecha"
    else:
        base = pd.DataFrame()
    # calendario = fechas del NDX si las hay; si no, unión de todo
    frames = {}
    if not base.empty:
        for c in ["NDX_close", "VIX_close", "VIX3M_close", "IRX_close"]:
            if c in base.columns:
                frames[c] = base[c]
    frames["VVIX_close"] = _read_cboe(BASE / "VVIX_History.csv", "VVIX_close") \
        if (BASE / "VVIX_History.csv").exists() else _read_cboe_vvix()
    frames["VIX9D_close"] = _read_cboe(BASE / "VIX9D_History.csv", "VIX9D_close")
    # VIX3M largo de CBOE como respaldo si la semilla no lo trae completo
    v3_cboe = _read_cboe(BASE / "VIX3M_History.csv", "VIX3M_close")
    if "VIX3M_close" in frames:
        frames["VIX3M_close"] = frames["VIX3M_close"].combine_first(v3_cboe)
    elif len(v3_cboe):
        frames["VIX3M_close"] = v3_cboe
    frames["WALCL"] = _read_fred_csv(BASE / "fred_WALCL_fed_balance_sheet.csv", "WALCL")
    frames["DFF"] = _read_fred_csv(BASE / "fred_DFF_fed_funds_rate.csv", "DFF")

    df = pd.DataFrame(frames).sort_index()
    df.index.name = "fecha"
    return df


def _read_cboe_vvix():
    return _read_cboe(BASE / "VVIX_History.csv", "VVIX_close")


# ------------------------------------------------------------------ internet
def bajar_yf(desde):
    """Descarga tickers de yfinance desde `desde`. Devuelve DataFrame
    (puede tener columnas faltantes si algún ticker falla)."""
    try:
        import yfinance as yf
    except Exception as e:
        log(f"yfinance no disponible ({e}); se omite descarga de mercado")
        return pd.DataFrame()
    out = {}
    start = (desde - timedelta(days=5)).strftime("%Y-%m-%d")
    for col, tk in TICKERS.items():
        try:
            h = yf.Ticker(tk).history(start=start, auto_adjust=False)
            if h is None or h.empty or "Close" not in h:
                raise ValueError("respuesta vacía")
            s = h["Close"].copy()
            s.index = pd.to_datetime(s.index).tz_localize(None).normalize()
            out[col] = s[~s.index.duplicated(keep="last")]
            log(f"  {tk}: {len(s)} filas nuevas hasta {s.index.max().date()}")
        except Exception as e:
            log(f"  AVISO {tk} falló ({e}); se hará forward-fill")
    return pd.DataFrame(out).sort_index() if out else pd.DataFrame()


def bajar_fred(desde):
    try:
        import requests
    except Exception as e:
        log(f"requests no disponible ({e}); se omite FRED")
        return pd.DataFrame()
    from io import StringIO
    out = {}
    for col, sid in FRED.items():
        url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}"
        try:
            r = requests.get(url, timeout=30)
            r.raise_for_status()
            d = pd.read_csv(StringIO(r.text))
            d.columns = ["date", col]
            d["date"] = pd.to_datetime(d["date"], errors="coerce")
            d[col] = pd.to_numeric(d[col], errors="coerce")
            s = d.dropna().set_index("date")[col].sort_index()
            out[col] = s[s.index >= (desde - timedelta(days=90))]
            log(f"  FRED {sid}: hasta {s.index.max().date()}")
        except Exception as e:
            log(f"  AVISO FRED {sid} falló ({e})")
    return pd.DataFrame(out).sort_index() if out else pd.DataFrame()


# ------------------------------------------------------------------ merge
def ffill_flaky(df):
    """Forward-fill limitado para tickers de volatilidad poco fiables."""
    for c in ["VIX3M_close", "VIX9D_close", "VVIX_close"]:
        if c in df.columns:
            df[c] = df[c].ffill(limit=FFILL_LIMIT)
    # FRED (semanal/diario con huecos) tolera ffill más largo
    for c in ["WALCL", "DFF"]:
        if c in df.columns:
            df[c] = df[c].ffill(limit=20)
    return df


def main():
    if MAESTRO.exists():
        maestro = pd.read_csv(MAESTRO, parse_dates=["fecha"]).set_index("fecha").sort_index()
        desde = maestro.index.max() + timedelta(days=1)
        log(f"maestro existente: {len(maestro)} filas, última {maestro.index.max().date()}")
    else:
        maestro = sembrar()
        # tras sembrar, pedimos solo lo posterior a la última fecha sembrada
        desde = (maestro.index.max() + timedelta(days=1)) if len(maestro) else datetime(2000, 1, 1)
        # aseguramos las columnas
        for c in COLS:
            if c not in maestro.columns:
                maestro[c] = pd.NA

    log(f"pidiendo datos nuevos desde {desde.date()}")
    nuevo_mkt = bajar_yf(desde)
    nuevo_fred = bajar_fred(desde)

    # el calendario lo manda el NDX; si no hay NDX nuevo, no añadimos filas
    combinado = maestro.copy()
    if not nuevo_mkt.empty:
        # unimos por fecha; el NDX define qué días son de trading
        idx_new = nuevo_mkt.index
        for col in nuevo_mkt.columns:
            for dt, v in nuevo_mkt[col].dropna().items():
                combinado.loc[dt, col] = v
    if not nuevo_fred.empty:
        for col in nuevo_fred.columns:
            for dt, v in nuevo_fred[col].dropna().items():
                combinado.loc[dt, col] = v

    combinado = combinado.sort_index()
    # nos quedamos solo con días que tienen NDX (calendario de trading)
    combinado = combinado[combinado["NDX_close"].notna()]
    combinado = ffill_flaky(combinado)

    for c in COLS:
        if c not in combinado.columns:
            combinado[c] = pd.NA
    combinado = combinado[COLS]
    combinado.index.name = "fecha"
    combinado.to_csv(MAESTRO)
    log(f"escrito {MAESTRO.name}: {len(combinado)} filas, "
        f"{combinado.index.min().date()} -> {combinado.index.max().date()}")


if __name__ == "__main__":
    main()
