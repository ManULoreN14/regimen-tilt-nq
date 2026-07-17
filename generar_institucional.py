#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generar_institucional.py — genera institucional.json para la pestaña
"Institucional" del dashboard (huella institucional: flujos, COT, PCR,
complejo de volatilidad, SKEW y GEX/muros de opciones).

Lee todos sus insumos de la carpeta INSTITUCIONAL/ (misma ruta que ya usas:
C:\\Users\\m21lo\\regimen-tilt-nq\\INSTITUCIONAL).

Desde julio 2026, DOS bloques se auto-descargan de una fuente pública
estable (ver refrescar_cboe/refrescar_cot) y ya NO hace falta bajarlos a
mano nunca más:
  - VIX / VIX9D / VIX3M / VVIX / SKEW  -> CBOE (cdn.cboe.com)
  - COT NASDAQ-100 (código 209742)     -> CFTC (API Socrata pública)
Estas dos fuentes bastan para el score IC-validado del composite, así que
esa parte del dashboard se mantiene fresca SOLA, incluso corriendo en la
nube (GitHub Actions) sin ningún CSV manual presente.

El resto sigue siendo estrictamente manual porque no existe fuente
gratuita/API pública estable conocida: fund flows (ETF.com), PCR (CBOE,
sin API), cadena de opciones de QQQ (Nasdaq, snapshot del día). Sigue
dejando esos CSV en INSTITUCIONAL/ cuando quieras refrescarlos.

Degradación elegante: si una pieza falta (auto o manual) o cambia de
formato, ESA pieza se omite (se loguea) y el resto del payload se genera
igual. resultado_flujos.csv YA NO es obligatorio: si falta, se usa VIX
como eje temporal y el composite score se genera igual (solo flujos/AUM
quedan vacíos hasta que corras el script en local con ese CSV puesto).

Uso:
    python generar_institucional.py                    # auto-descarga CBOE/CFTC + escribe ./institucional.json
    python generar_institucional.py --dir OTRA/RUTA
    python generar_institucional.py --no-download       # solo con lo que ya haya en --dir (sin tocar la red)

Se integra como un paso más en actualizar.yml (nightly, solo el bloque
auto) y en actualizar_todo.bat (local, auto + manual combinados).
"""
import argparse
import json
import sys
import urllib.request
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

# ---------------------------------------------------------------------
# AUTO-DESCARGA (fuentes con URL/API pública estable, sin necesidad de
# descarga manual). Cubren VIX/VIX9D/VIX3M/VVIX/SKEW (CBOE) y COT (CFTC).
# PCR, cadena de opciones y flujos ETF siguen siendo manuales: no existe
# fuente gratuita estable conocida para ellas -> se quedan en INSTITUCIONAL/
# esperando la descarga manual de siempre. Si una descarga automática falla
# (red caída, CBOE/CFTC cambian el formato, etc.) se deja el fichero local
# existente tal cual -- nunca rompe el pipeline.
# ---------------------------------------------------------------------
CBOE_BASE = "https://cdn.cboe.com/api/global/us_indices/daily_prices"
CBOE_AUTO = {"vix": "VIX", "vix9d": "VIX9D", "vix3m": "VIX3M", "vvix": "VVIX", "skew": "SKEW"}

CFTC_TFF_FUTURES_ONLY = "https://publicreporting.cftc.gov/resource/gpe5-46if.json"
CFTC_NDX_CODE = "209742"  # NASDAQ-100, TFF Futures Only

COT_RENAME = {
    "report_date_as_yyyy_mm_dd": "Report_Date_as_YYYY-MM-DD",
    "asset_mgr_positions_long_all": "Asset_Mgr_Positions_Long_All",
    "asset_mgr_positions_short_all": "Asset_Mgr_Positions_Short_All",
    "lev_money_positions_long_all": "Lev_Money_Positions_Long_All",
    "lev_money_positions_short_all": "Lev_Money_Positions_Short_All",
    "dealer_positions_long_all": "Dealer_Positions_Long_All",
    "dealer_positions_short_all": "Dealer_Positions_Short_All",
    "open_interest_all": "Open_Interest_All",
}


def _http_get(url: str, timeout=20) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "regimen-tilt-nq/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def refrescar_cboe(base: Path):
    """Descarga VIX/VIX9D/VIX3M/VVIX/SKEW desde la URL pública estable de CBOE
    y sobrescribe el CSV local correspondiente en `base`. Mismo formato exacto
    que ya usan load_vixlike/load_skew, así que no hace falta tocar nada más."""
    for key, name in CBOE_AUTO.items():
        fname = FILES[key]
        url = f"{CBOE_BASE}/{name}_History.csv"
        try:
            data = _http_get(url)
            (base / fname).write_bytes(data)
            _log(f"CBOE {name}: descargado OK ({len(data)} bytes) -> {fname}")
        except Exception as e:
            _log(f"AVISO — no se pudo descargar {name} de CBOE, uso el CSV local existente: {e}")


def refrescar_cot(base: Path, cftc_code: str = CFTC_NDX_CODE):
    """Descarga el informe TFF Futures Only (CFTC, API Socrata pública) para el
    código NASDAQ-100 y lo guarda con las mismas columnas que espera load_cot().
    Si falla, deja el fichero local existente igual (nunca rompe el pipeline)."""
    url = (f"{CFTC_TFF_FUTURES_ONLY}?$where=cftc_contract_market_code='{cftc_code}'"
           "&$order=report_date_as_yyyy_mm_dd DESC&$limit=1000")
    try:
        rows = json.loads(_http_get(url))
        if not rows:
            raise ValueError("respuesta vacía de la API de la CFTC")
        df = pd.DataFrame(rows).rename(columns=COT_RENAME)
        keep = list(COT_RENAME.values())
        df = df[[c for c in keep if c in df.columns]]
        df.to_csv(base / FILES["cot"], index=False)
        _log(f"CFTC COT ({cftc_code}): descargado OK ({len(df)} filas) -> {FILES['cot']}")
    except Exception as e:
        _log(f"AVISO — no se pudo descargar COT de la CFTC, uso el fichero local existente: {e}")


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

    # Eje temporal: preferimos flujos (mas historia real y trae precio/AUM),
    # pero ya NO es obligatorio. Si no esta disponible -- p.ej. una corrida
    # automatica en la nube, sin los CSV manuales -- usamos VIX como eje
    # (se descarga solo via refrescar_cboe). Esto permite que el score
    # IC-validado (que solo depende de VIX/VIX9D/VIX3M/VVIX) se genere cada
    # noche sin intervencion manual; flujos/PCR/GEX simplemente quedan en
    # blanco hasta la proxima corrida local con los CSV actualizados.
    if flujos is not None:
        m = flujos
    elif vix is not None:
        _log("AVISO — resultado_flujos.csv no disponible; uso VIX como eje temporal "
             "(flujos/AUM quedaran vacios hasta la proxima corrida local).")
        m = vix[["date"]].copy()
        m["flow_usd"] = np.nan
        m["price"] = np.nan
        m["aum"] = np.nan
    else:
        _log("ERROR — ni flujos.csv ni VIX (local o descargado) disponibles; "
             "no hay eje temporal posible. Abortando.")
        sys.exit(1)

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
                   ("flow_usd_20d", "z_flow_20d"),
                   ("vix9d_vix_ratio", "z_vix9d_vix_ratio"), ("vix_vix3m_ratio", "z_vix_vix3m_ratio")]:
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
    # --- Score compuesto: SOLO señales que pasan el harness real de validación
    # (IC Spearman forward, walk-forward de 3 tramos, estabilidad >=66.7%,
    # |IC|>0.03, p<0.05 -- ver ic_harness.py). Flujos, COT y PCR NO pasaron
    # el harness (ver ic_harness_results.csv) y por tanto quedan FUERA del
    # score -- se muestran igualmente en el dashboard como contexto de
    # posicionamiento, pero sin pretender que aporten poder predictivo
    # demostrado. Pesos derivados del propio |IC| de cada señal en su mejor
    # horizonte encontrado, no inventados por intuición:
    #   VIX/VIX3M ratio  (IC=0.230, h=20d, p=0.0007, estabilidad 100%) -> peso 0.522
    #   VIX9D/VIX ratio  (IC=0.132, h=10d, p=0.008,  estabilidad 100%) -> peso 0.300
    #   VVIX-VIX spread  (IC=0.078, h=5d,  p=0.012,  estabilidad 100%) -> peso 0.178
    # Las 3 tienen IC de signo positivo: valor alto -> retorno futuro esperado
    # positivo (tensión en la parte corta de la curva de vol -> rebote).
    IC_WEIGHTS = {"z_vix_vix3m_ratio": 0.522, "z_vix9d_vix_ratio": 0.300, "z_vvix_spread": 0.178}
    composite = sum(w * clip(last.get(k)) for k, w in IC_WEIGHTS.items())

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
        "z_vix9d_vix_ratio": series("z_vix9d_vix_ratio"), "z_vix_vix3m_ratio": series("z_vix_vix3m_ratio"),
        "vix_curve": vix_curve or {},
        "gex": gex or {},
        "composite_score": round(float(composite), 3),
        "validation": {
            "metodo": "IC Spearman forward (con lag de 3 sesiones), walk-forward de 3 tramos cronológicos, estabilidad >=66.7%, |IC|>0.03, p<0.05. Ver ic_harness.py / ic_harness_results.csv.",
            "señales_en_el_score": [
                {"metric":"vix_vix3m_ratio","horizonte_dias":20,"IC":0.230,"p":0.0007,"estabilidad_%":100,"peso":0.522},
                {"metric":"vix9d_vix_ratio","horizonte_dias":10,"IC":0.132,"p":0.008,"estabilidad_%":100,"peso":0.300},
                {"metric":"vvix_vix_spread","horizonte_dias":5,"IC":0.078,"p":0.012,"estabilidad_%":100,"peso":0.178},
            ],
            "señales_fuera_del_score_no_pasan_harness": [
                "flow_usd_20d (flujo ETF)", "am_net (COT Asset Managers)",
                "lev_net (COT Leveraged Money)", "pcr_equity (Put/Call Ratio)"
            ],
        },
    }
    return payload, m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=str(Path(r"INSTITUCIONAL")),
                     help="Carpeta con los CSV/TXT institucionales")
    ap.add_argument("--out", default="institucional.json")
    ap.add_argument("--dump-merged", default=None,
                     help="Si se indica, también escribe el DataFrame combinado completo "
                          "(todas las fechas, sin redondear/recortar) a este CSV -- lo usan "
                          "ic_harness.py y event_study.py como 'master_full.csv'.")
    ap.add_argument("--no-download", action="store_true",
                     help="No intentar descargar CBOE/CFTC; usa solo lo que ya haya en --dir.")
    args = ap.parse_args()

    base = Path(args.dir)
    base.mkdir(parents=True, exist_ok=True)  # en un runner en la nube esta carpeta no existe aun

    if not args.no_download:
        refrescar_cboe(base)
        refrescar_cot(base)

    payload, merged = build(base)
    Path(args.out).write_text(json.dumps(payload), encoding="utf-8")
    _log(f"Escrito {args.out} — asof {payload['asof']}, {len(payload['dates'])} fechas, "
         f"composite_score={payload['composite_score']}")

    if args.dump_merged:
        merged.to_csv(args.dump_merged, index=False)
        _log(f"Escrito {args.dump_merged} ({len(merged)} filas) para ic_harness.py / event_study.py")


if __name__ == "__main__":
    main()
