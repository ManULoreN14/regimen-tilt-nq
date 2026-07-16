import pandas as pd, numpy as np

full = pd.read_csv("master_full.csv", parse_dates=["date"]).sort_values("date").reset_index(drop=True)

LAG = 3  # tu restricción estructural: 3 días de ejecución hasta que el cambio se refleja
HORIZONS = [5, 10, 20, 60]

price = full["price"].values
n = len(full)

# forward return desde t+LAG hasta t+LAG+h (nunca desde t, para respetar tu lag real)
fwd = {}
for h in HORIZONS:
    r = np.full(n, np.nan)
    for i in range(n - LAG - h):
        p0 = price[i+LAG]
        p1 = price[i+LAG+h]
        r[i] = (p1/p0 - 1) * 100
    fwd[h] = r
    full[f"fwd_{h}"] = r

def event_study(cond_mask, label, min_n=25):
    rows = []
    for h in HORIZONS:
        sub = full.loc[cond_mask, f"fwd_{h}"].dropna()
        base = full[f"fwd_{h}"].dropna()
        if len(sub) < min_n:
            rows.append((h, len(sub), None, None, None, None))
            continue
        mean_c, med_c = sub.mean(), sub.median()
        mean_b = base.mean()
        winrate = (sub > 0).mean() * 100
        rows.append((h, len(sub), mean_c, med_c, mean_b, winrate))
    print(f"\n=== {label} ===  (n total días elegibles: {cond_mask.sum()})")
    print(f"{'h(d)':>5} {'n':>6} {'media_cond%':>12} {'mediana%':>10} {'media_base%':>12} {'winrate%':>9}")
    for h, n_, mc, md, mb, wr in rows:
        if mc is None:
            print(f"{h:>5} {n_:>6}   (insuficiente, min {min_n})")
        else:
            print(f"{h:>5} {n_:>6} {mc:>12.2f} {md:>10.2f} {mb:>12.2f} {wr:>9.1f}")

# ---------- 1. Flujos: outflow extremo 20d (z < -1.5) ----------
event_study(full["z_flow_20d"] < -1.5, "Flujo 20d MUY negativo (z<-1.5) — ¿'distribución' anticipa caída?")
event_study(full["z_flow_20d"] > 1.5,  "Flujo 20d MUY positivo (z>1.5) — ¿entrada masiva anticipa subida?")

# ---------- 2. COT Leveraged Money extremo corto/largo ----------
event_study(full["z_lev_net"] < -1.5, "Leveraged Money muy corto (z<-1.5) — ¿fuel de short squeeze?")
event_study(full["z_lev_net"] > 1.5,  "Leveraged Money muy largo (z>1.5) — ¿sobreextendido, riesgo de liquidación?")

# ---------- 3. COT Asset Managers extremo ----------
event_study(full["z_am_net"] < -1.5, "Asset Managers reduciendo fuerte (z<-1.5) — ¿dinero real saliendo?")
event_study(full["z_am_net"] > 1.5,  "Asset Managers muy largos (z>1.5) — ¿sobre-convicción institucional?")

# ---------- 4. PCR equity extremo (miedo / euforia minorista) ----------
event_study(full["z_pcr_equity"] > 1.5, "PCR equity muy alto (z>1.5) — pánico Put-buying minorista, ¿suelo?")
event_study(full["z_pcr_equity"] < -1.5, "PCR equity muy bajo (z<-1.5) — euforia Call-buying minorista, ¿techo?")

# ---------- 5. VVIX-VIX spread (miedo oculto) ----------
event_study(full["z_vvix_spread"] > 1.5, "VVIX-VIX spread muy alto (z>1.5) — estrés oculto en vol de vol")

# ---------- 6. Divergencia: precio en máximos de 60d PERO flujo negativo (patrón A de Gemini) ----------
price_s = pd.Series(price)
roll_max = price_s.rolling(60, min_periods=30).max()
near_high = (price_s >= roll_max * 0.98).values
divergence = near_high & (full["z_flow_20d"] < -0.75).values
event_study(pd.Series(divergence), "Patrón 'distribución': precio cerca de máx 60d + flujo 20d débil (z<-0.75)")

# ---------- 7. Capitulación clásica: VIX pico + flujo entrando fuerte ----------
vix_pctile = full["vix"].rolling(252, min_periods=60).apply(lambda x: (x.iloc[-1] > x).mean()*100, raw=False)
capitulation = (vix_pctile > 90) & (full["z_flow_20d"] > 0.5)
event_study(capitulation, "Patrón 'capitulación': VIX en percentil >90 (1y) + flujo 20d positivo")
