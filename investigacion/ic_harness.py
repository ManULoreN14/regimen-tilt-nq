"""
Harness de validación real (IC Spearman forward, walk-forward, estabilidad,
significancia) aplicado a CADA métrica institucional candidata, siguiendo el
mismo criterio ya documentado en el proyecto: |IC|>0.03, p<0.05, Stability
alta, consistente en varios sub-periodos (walk-forward >=3).

A diferencia del event_study.py anterior (que solo miraba "extremos"), este
harness calcula el IC de Spearman de forma CONTINUA (todos los valores de la
señal, no solo los extremos) porque es lo que de verdad determina si un peso
IC-derivado tiene sentido para un score compuesto.
"""
import pandas as pd, numpy as np
from scipy.stats import spearmanr

full = pd.read_csv("master_full.csv", parse_dates=["date"]).sort_values("date").reset_index(drop=True)

LAG = 3
HORIZONS = [5, 10, 20, 60]
price = full["price"].values
n = len(full)
for h in HORIZONS:
    r = np.full(n, np.nan)
    for i in range(n - LAG - h):
        r[i] = (price[i+LAG+h]/price[i+LAG] - 1) * 100
    full[f"fwd_{h}"] = r

CANDIDATES = {
    "z_flow_20d":      "Flujo ETF acumulado 20d (z-score)",
    "z_am_net":        "Asset Managers netos COT (z-score)",
    "z_lev_net":       "Leveraged Money netos COT (z-score)",
    "z_pcr_equity":    "Put/Call Ratio equity (z-score)",
    "z_vvix_spread":   "VVIX-VIX spread (z-score)",
    "vix9d_vix_ratio":  "VIX9D/VIX ratio",
    "vix_vix3m_ratio":  "VIX/VIX3M ratio",
}

def stride_sample(df, cols, stride):
    """Muestreo no solapado para no inflar significancia por autocorrelación."""
    return df.iloc[::stride].dropna(subset=cols)

results = []
for col, label in CANDIDATES.items():
    if col not in full.columns:
        continue
    for h in HORIZONS:
        stride = max(h, 1)  # observaciones separadas >= horizonte -> no solapan
        sub = stride_sample(full, [col, f"fwd_{h}"], stride)
        if len(sub) < 40:
            continue
        ic, p = spearmanr(sub[col], sub[f"fwd_{h}"])

        # walk-forward: 3 tramos cronológicos sobre las fechas DISPONIBLES para esta señal
        valid_dates = full.loc[full[col].notna(), "date"].sort_values().reset_index(drop=True)
        if len(valid_dates) < 300:
            continue
        m = len(valid_dates)
        cuts = [valid_dates.iloc[0], valid_dates.iloc[m//3], valid_dates.iloc[2*m//3], valid_dates.iloc[m-1]]
        fold_ics = []
        for i in range(3):
            if i < 2:
                fmask = (full["date"] >= cuts[i]) & (full["date"] < cuts[i+1])
            else:
                fmask = (full["date"] >= cuts[i]) & (full["date"] <= cuts[i+1])
            fsub = stride_sample(full[fmask], [col, f"fwd_{h}"], stride)
            if len(fsub) < 20:
                fold_ics.append(None); continue
            fic, fp = spearmanr(fsub[col], fsub[f"fwd_{h}"])
            fold_ics.append(fic)
        valid_folds = [f for f in fold_ics if f is not None]
        same_sign = sum(1 for f in valid_folds if np.sign(f) == np.sign(ic))
        stability = 100 * same_sign / len(valid_folds) if valid_folds else 0

        passes = abs(ic) > 0.03 and p < 0.05 and stability >= 66.7
        results.append({
            "metric": col, "label": label, "h": h, "n": len(sub),
            "IC": round(ic,4), "p": round(p,5), "stability_%": round(stability,1),
            "fold_ICs": [round(f,3) if f is not None else None for f in fold_ics],
            "PASA": passes,
        })

res = pd.DataFrame(results).sort_values(["metric","h"])
pd.set_option("display.width", 160)
print(res.to_string(index=False))

print("\n=== SEÑALES QUE PASAN EL HARNESS (al menos un horizonte) ===")
passed = res[res["PASA"]]
print(passed.to_string(index=False))
res.to_csv("ic_harness_results.csv", index=False)
