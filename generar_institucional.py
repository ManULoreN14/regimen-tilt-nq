#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generar_institucional.py — genera institucional.json para la pestaña
"Institucional" del dashboard (huella institucional: flujos, COT, PCR,
complejo de volatilidad, SKEW y GEX/muros de opciones).

Lee todos sus insumos de la carpeta INSTITUCIONAL/ (misma ruta que ya usas:
C:\\Users\\m21lo\\regimen-tilt-nq\\INSTITUCIONAL), así que basta con seguir
dejando ahí los CSV/TXT que ya descargas manualmente (fund flows, COT,
PCR, VIX/VIX9D/VIX3M/VVIX, SKEW, cadena de opciones de QQQ). No hay
descarga automática: son series que hoy obtienes a mano de fuentes sin
API pública estable (CBOE, CFTC, ETF.com), así que este script solo
consolida lo que ya tienes en disco.

Degradación elegante: si un archivo falta o cambia de formato, ESA pieza
se omite (se loguea) y el resto del payload se genera igual. Nunca rompe
el pipeline.

Uso:
    python generar_institucional.py             # escribe ./institucional.json
    python generar_institucional.py --dir OTRA/RUTA/INSTITUCIONAL

Se integra como un paso más en actualizar.yml / actualizar_todo.bat, justo
después de generar_precios.py. OJO: como estos archivos NO se generan por
API (los actualizas tú a mano descargando de CBOE/ETF.com/CFTC), este
script no falla si la carpeta no ha cambiado desde la última corrida —
simplemente reescribe institucional.json con los mismos datos.
"""
import argparse
import json
import sys
from pathlib import Path

import pandas as pd
import numpy as np


def _log(m):
    print(f"[INSTITUCIONAL] {m}")


# ---------------------------------------------------------------------
# Nombres de archivo esperados dentro de INSTITUCIONAL/. Todos opcionales:
# si falta uno, esa pieza del payload queda vacía y el resto sigue.
# ---------------------------------------------------------------------
FILES = {
    "flujos": "resultado_flujos.csv",          # Fecha,Signo,Cantidad_USD,NAV,Cambio_%,AUM
    "cot": "cot_209742_consolidado.txt",       # COT semanal NASDAQ-100 (código CFTC 209742)
    "pcr": "PCR_RATIOS_HISTORICO.csv",         # Put/Call ratios diarios CBOE
    "vix": "VIX_History.csv",
    "vix9d": "VIX9D_History.csv",
    "vix3m": "VIX3M_History.csv",
    "vvix": "VVIX_History.csv",
    "skew": "SKEW_History.csv",
    "vix_curve": "VIX_FUTURES_CURVE.csv",      # snapshot del día: term structure de futuros VIX
}
# La cadena de opciones cambia de nombre cada día (qqq_options_chain_YYYY-MM-DD.csv).
OPTIONS_GLOB = "qqq_options_chain_*.csv"

ROLL_Z_WINDOW = 756  # ~3 años de sesiones, para z-scores


def _safe(fn):
    def wrapper(*a, **kw):
        try:
            return fn(*a, **kw)
        except Exception as e:
            _log(f"AVISO — {fn.__name__} falló y se omite: {e}")
            return None
    return wrapper


@_safe
def load_flujos(base: Path) -> pd.DataFrame:
    d = pd.read_csv(base / FILES["flujos"], parse_dates=["Fecha"])
    d = d.rename(columns={"Fecha": "date", "Cantidad_USD": "flow_usd", "NAV": "price", "AUM": "aum"})
    d = d[["date", "flow_usd", "price", "aum"]].sort_values("date")
    d["flow_usd"] = d["flow_usd"].fillna(0)
    return d


@_safe
def load_cot(base: Path) -> pd.DataFrame:
    d = pd.read_csv(base / FILES["cot"], parse_dates=["Report_Date_as_YYYY-MM-DD"])
    d = d.rename(columns={"Report_Date_as_YYYY-MM-DD": "date"})
    d["am_net"] = d["Asset_Mgr_Positions_Long_All"] - d["Asset_Mgr_Positions_Short_All"]
    d["lev_net"] = d["Lev_Money_Positions_Long_All"] - d["Lev_Money_Positions_Short_All"]
    d["dealer_net"] = d["Dealer_Positions_Long_All"] - d["Dealer_Positions_Short_All"]
    return d[["date", "am_net", "lev_net", "dealer_net", "Open_Interest_All"]].sort_values("date")


@_safe
def load_pcr(base: Path) -> pd.DataFrame:
    d = pd.read_csv(base / FILES["pcr"], parse_dates=["Fecha"])
    d = d.rename(columns={"Fecha": "date", "TOTAL_PUT_CALL_RATIO": "pcr_total",
                           "EQUITY_PUT_CALL_RATIO": "pcr_equity"})
    return d[["date", "pcr_total", "pcr_equity"]].sort_values("date")


@_safe
def load_vixlike(base: Path, fname: str, valcol: str, newname: str) -> pd.DataFrame:
    d = pd.read_csv(base / fname)
    d["date"] = pd.to_datetime(d["DATE"], format="%m/%d/%Y")
    return d.rename(columns={valcol: newname})[["date", newname]].sort_values("date")


@_safe
def load_skew(base: Path) -> pd.DataFrame:
    d = pd.read_csv(base / FILES["skew"], parse_dates=["DATE"])
    return d.rename(columns={"DATE": "date", "SKEW": "skew"})


@_safe
def load_vix_curve(base: Path) -> dict:
    d = pd.read_csv(base / FILES["vix_curve"], parse_dates=["expiration_date"]).sort_values("expiration_date")
    points = [{"exp": r["expiration_date"].strftime("%Y-%m-%d"), "settlement": float(r["settlement"])}
              for _, r in d.iterrows()]
    regime, front_slope = None, None
    if len(d) >= 2:
        front = float(d.iloc[0]["settlement"])
        back = float(d.iloc[-1]["settlement"])  # extremo más lejano disponible, evita empates del tramo corto
        front_slope = round(back - front, 4)
        regime = "contango" if back > front else ("backwardation" if back < front else "flat")
    return {"points": points, "regime": regime, "front_slope": front_slope}


@_safe
def load_options_gex(base: Path):
    """Toma el CSV de cadena de opciones MÁS RECIENTE en la carpeta (nombre
    qqq_options_chain_YYYY-MM-DD.csv) y calcula GEX por strike.

    Convención estándar (misma que usan la mayoría de trackers gratuitos):
    se asume que el market maker queda largo gamma en las calls que ha
    vendido y corto gamma en las puts que ha vendido (posición contraria
    al cliente neto comprador de opciones). Es una aproximación — sin
    conocer quién es realmente contraparte de cada contrato no hay forma
    de saberlo con certeza, pero es la convención de facto del sector.
    """
    candidates = sorted(base.glob(OPTIONS_GLOB))
    if not candidates:
        return None
    fp = candidates[-1]  # el más reciente por orden de nombre (fecha en el nombre)
    _log(f"Cadena de opciones usada para GEX: {fp.name}")

    # cabecera CBOE/Nasdaq típica: 2 líneas de metadatos + fila de header real
    with open(fp, encoding="utf-8", errors="ignore") as fh:
        head_lines = [fh.readline() for _ in range(4)]
    spot = None
    for ln in head_lines:
        if "Last:" in ln:
            try:
                spot = float(ln.split("Last:")[1].split(",")[0].strip())
            except Exception:
                pass
    df = pd.read_csv(fp, skiprows=3, header=0)
    if spot is None:
        # fallback: punto medio strike con mayor OI total como proxy de spot
        spot = float(df["Strike"].median())

    df["Strike"] = df["Strike"].astype(float)
    for c in ["Gamma", "Gamma.1", "Open Interest", "Open Interest.1"]:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)

    df["call_gex"] = df["Gamma"] * df["Open Interest"] * 100 * spot ** 2 * 0.01
    df["put_gex"] = df["Gamma.1"] * df["Open Interest.1"] * 100 * spot ** 2 * 0.01 * -1

    df["exp"] = pd.to_datetime(df["Expiration Date"])
    asof = df["exp"].min()  # aprox: fecha de la propia cadena
    near = df[df["exp"] <= asof + pd.Timedelta(days=45)]

    def agg(sub):
        g = sub.groupby("Strike").agg(
            call_oi=("Open Interest", "sum"), put_oi=("Open Interest.1", "sum"),
            call_gex=("call_gex", "sum"), put_gex=("put_gex", "sum"),
        ).reset_index()
        g["net_gex"] = g["call_gex"] + g["put_gex"]
        g["total_oi"] = g["call_oi"] + g["put_oi"]
        return g

    g_all = agg(df)
    g_near = agg(near)

    def wall(g, col):
        r = g.loc[g[col].idxmax()]
        return float(r["Strike"]), float(r[col])

    call_wall_s, call_wall_oi = wall(g_near, "call_oi")
    put_wall_s, put_wall_oi = wall(g_near, "put_oi")

    # nivel de "zero gamma flip": strike donde el GEX acumulado (ordenado por
    # strike ascendente) cruza cero. Por debajo de este nivel el régimen tiende
    # a "explosivo" (gamma negativo), por encima a "pegajoso" (gamma positivo).
    bs_sorted = g_near.sort_values("Strike").reset_index(drop=True)
    bs_sorted["cum_gex"] = bs_sorted["net_gex"].cumsum()
    zero_gamma = None
    for i in range(1, len(bs_sorted)):
        prev, cur = bs_sorted.loc[i-1, "cum_gex"], bs_sorted.loc[i, "cum_gex"]
        if (prev < 0 <= cur) or (prev > 0 >= cur):
            zero_gamma = float(bs_sorted.loc[i, "Strike"])
            break

    # proxy de liquidez: volumen del día / open interest acumulado, en el
    # bloque de vencimientos cercanos. Un ratio muy bajo = libro fino,
    # movimientos más violentos ante cualquier orden grande.
    near_vol = near["Volume"].sum() + near["Volume.1"].sum()
    near_oi = near["Open Interest"].sum() + near["Open Interest.1"].sum()
    vol_oi_ratio = float(near_vol / near_oi) if near_oi else None

    window = g_near[(g_near["Strike"] > spot * 0.85) & (g_near["Strike"] < spot * 1.15)]
    by_strike = window[["Strike", "call_oi", "put_oi", "call_gex", "put_gex", "net_gex"]] \
        .round(2).to_dict(orient="records")

    summary = {
        "spot": spot,
        "asof_chain": fp.stem.split("_")[-1] if "_" in fp.stem else None,
        "net_gex_45d": float(g_near["net_gex"].sum()),
        "net_gex_all_expiries": float(g_all["net_gex"].sum()),
        "call_wall_strike": call_wall_s, "call_wall_oi": call_wall_oi,
        "put_wall_strike": put_wall_s, "put_wall_oi": put_wall_oi,
        "zero_gamma_strike": zero_gamma,
        "vol_oi_ratio_near": vol_oi_ratio,
    }
    return {"summary": summary, "by_strike": by_strike}


def zscore(s: pd.Series, window=ROLL_Z_WINDOW) -> pd.Series:
    m = s.rolling(window, min_periods=60).mean()
    sd = s.rolling(window, min_periods=60).std()
    return (s - m) / sd


def clip(v, lo=-3, hi=3):
    if pd.isna(v):
        return 0.0
    return float(max(lo, min(hi, v)))


def build(base: Path) -> dict:
    flujos = load_flujos(base)
    cot = load_cot(base)
    pcr = load_pcr(base)
    vix = load_vixlike(base, FILES["vix"], "CLOSE", "vix")
    vix9d = load_vixlike(base, FILES["vix9d"], "CLOSE", "vix9d")
    vix3m = load_vixlike(base, FILES["vix3m"], "CLOSE", "vix3m")
    vvix = load_vixlike(base, FILES["vvix"], "VVIX", "vvix")
    skew = load_skew(base)
    vix_curve = load_vix_curve(base)
    gex = load_options_gex(base)

    if flujos is None:
        _log("ERROR — resultado_flujos.csv es obligatorio (define el eje temporal). Abortando.")
        sys.exit(1)

    m = flujos
    for extra in [pcr, vix, vix9d, vix3m, vvix, skew]:
        if extra is not None:
            m = m.merge(extra, on="date", how="left")
    if cot is not None:
        m = m.merge(cot, on="date", how="left").sort_values("date")
        for c in ["am_net", "lev_net", "dealer_net", "Open_Interest_All"]:
            if c in m.columns:
                m[c] = m[c].ffill()

    if "vix9d" in m and "vix" in m:
        m["vix9d_vix_ratio"] = m["vix9d"] / m["vix"]
    if "vix" in m and "vix3m" in m:
        m["vix_vix3m_ratio"] = m["vix"] / m["vix3m"]
    if "vvix" in m and "vix" in m:
        m["vvix_vix_spread"] = m["vvix"] - m["vix"]

    m["flow_usd_20d"] = m["flow_usd"].rolling(20, min_periods=5).sum()
    m["flow_usd_60d"] = m["flow_usd"].rolling(60, min_periods=10).sum()
    # variación de precio en la misma ventana de 20 sesiones, para poder leer
    # la divergencia flujo/precio como pendiente relativa (no como snapshot)
    m["price_20d_chg_pct"] = m["price"].pct_change(20) * 100

    for col, z in [("pcr_equity", "z_pcr_equity"), ("vvix_vix_spread", "z_vvix_spread"),
                   ("skew", "z_skew"), ("am_net", "z_am_net"), ("lev_net", "z_lev_net"),
                   ("flow_usd_20d", "z_flow_20d")]:
        if col in m.columns:
            m[z] = zscore(m[col])

    # OJO: NO recortamos el histórico al inicio del PCR (~2019). Flujos, COT
    # y VIX tienen muchos más años de historia real — cada serie simplemente
    # queda a `None` en el JSON antes de que exista esa fuente concreta, y el
    # frontend ya sabe dibujar huecos (spanGaps) sin romper el resto del rango.

    def series(col):
        if col not in m.columns:
            return []
        return [None if pd.isna(v) else round(float(v), 4) for v in m[col]]

    last = m.iloc[-1]
    composite = (
        0.30 * clip(last.get("z_flow_20d")) +
        -0.20 * clip(last.get("z_pcr_equity")) +
        -0.25 * clip(last.get("z_lev_net")) * -1 +  # lev_net muy negativo (cortos extremos) = riesgo de squeeze, no puramente bajista
        0.25 * clip(last.get("z_am_net"))
    )

    payload = {
        "asof": m["date"].max().strftime("%Y-%m-%d"),
        "dates": m["date"].dt.strftime("%Y-%m-%d").tolist(),
        "price": series("price"), "flow_usd": series("flow_usd"),
        "flow_usd_20d": series("flow_usd_20d"), "flow_usd_60d": series("flow_usd_60d"),
        "price_20d_chg_pct": series("price_20d_chg_pct"),
        "pcr_total": series("pcr_total"), "pcr_equity": series("pcr_equity"),
        "vix": series("vix"), "vix9d": series("vix9d"), "vix3m": series("vix3m"), "vvix": series("vvix"),
        "vix9d_vix_ratio": series("vix9d_vix_ratio"), "vix_vix3m_ratio": series("vix_vix3m_ratio"),
        "vvix_vix_spread": series("vvix_vix_spread"), "skew": series("skew"),
        "am_net": series("am_net"), "lev_net": series("lev_net"), "dealer_net": series("dealer_net"),
        "z_pcr_equity": series("z_pcr_equity"), "z_vvix_spread": series("z_vvix_spread"),
        "z_am_net": series("z_am_net"), "z_lev_net": series("z_lev_net"), "z_flow_20d": series("z_flow_20d"),
        "vix_curve": vix_curve or {},
        "gex": gex or {},
        "composite_score": round(float(composite), 3),
    }
    return payload


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=str(Path(r"INSTITUCIONAL")),
                     help="Carpeta con los CSV/TXT institucionales")
    ap.add_argument("--out", default="institucional.json")
    args = ap.parse_args()

    base = Path(args.dir)
    if not base.exists():
        _log(f"ERROR — no existe la carpeta {base.resolve()}")
        sys.exit(1)

    payload = build(base)
    Path(args.out).write_text(json.dumps(payload), encoding="utf-8")
    _log(f"Escrito {args.out} — asof {payload['asof']}, {len(payload['dates'])} fechas, "
         f"composite_score={payload['composite_score']}")


if __name__ == "__main__":
    main()
