# Resumen — arquitectura y automatización real del sistema

*Última actualización: sesión del 16 de julio de 2026.*

## 1. Qué hay construido

**4 sistemas cuantitativos** (exposición 0-100% sobre NDX, sin apalancar):

- **Régimen+Tilt** — vive en este mismo repo (`regimen-tilt-nq`)
- **NRA-DAS** — vive fuera, en `C:\projects\nra_das`
- **Quant Engine** — vive fuera, en `C:\PROYECTO\quant_engine`
- **Ensemble** — combina los 3 (más agresivo si momentum 20d positivo, más defensivo si negativo)
- **+ Crecimiento/Blend** — curva adicional (30% B&H + 70% SMA300)

**Dashboard** (`index.html`, GitHub Pages) con 3 pestañas: **Panel** (equity curves, Chart.js), **Estudio técnico** (velas NDX/VIX/QQQ, KLineChart), **Institucional** (flujos, COT, vol, GEX).

## 2. 100% automático — no tienes que tocar nada

**GitHub Actions**, L-V a las 20:30 UTC (~22:30 Madrid en verano), corre en la nube y hace push solo:

```
generar_datos.py → construir_sistema.py → generar_precios.py (tolerante a fallo)
```

Actualiza: `historico_maestro.csv`, `sistema_regimen_tilt.json`, `precios.json`. Esto cubre **Régimen+Tilt y el Estudio Técnico** (NDX/VIX/QQQ vía yfinance). Si `generar_precios.py` falla (p. ej. intradía caído), no bloquea el resto — se sube igual sin ese archivo.

**Esto es lo único que corre solo, sin que tú hagas nada, cada noche laborable.**

## 3. Semi-automático — requiere que TÚ lo dispares (doble clic)

`actualizar_todo.bat`, local, en tu máquina:

```
1/5  NRA-DAS          (corre backtest en C:\projects\nra_das, copia resultados)
2/5  Quant Engine      (corre backtest en C:\PROYECTO\quant_engine, copia resultados)
3/5  generar_datos.py  (refresca NDX/VIX/FRED)
4/5  construir_sistema.py → generar_precios.py → comparar_nra_das.py →
     comparar_quant_engine.py → generar_ensemble.py → comparar_crecimiento.py
5/5  git add . / commit / push
```

Para en seco si algo falla (no sube datos a medias). **Tienes que ejecutarlo tú** porque NRA-DAS y Quant Engine viven fuera del repo, en carpetas que GitHub Actions (en la nube) no puede ver.

**Cadencia recomendada**: cuando quieras refrescar NRA-DAS/Quant Engine/Ensemble/Crecimiento — el cron nocturno ya te mantiene Régimen+Tilt y el Estudio Técnico al día sin esto.

## 4. Totalmente manual — aquí está el riesgo real de desactualización

**La pestaña Institucional NO está enganchada a ninguno de los dos automatismos anteriores.** Nadie la ejecuta por ti. Dos capas de trabajo manual:

### (a) Mantener los archivos de origen actualizados
en `C:\Users\m21lo\regimen-tilt-nq\INSTITUCIONAL\`:

| Archivo | Fuente | Frecuencia sensata |
|---|---|---|
| `resultado_flujos.csv` | ETF.com (a mano) | semanal/mensual |
| `cot_209742_consolidado.txt` | CFTC (se publica los viernes) | semanal |
| `PCR_RATIOS_HISTORICO.csv` | CBOE | semanal/mensual |
| `VIX_History.csv` / `VIX9D` / `VIX3M` / `VVIX` | CBOE | semanal/mensual |
| `SKEW_History.csv` | CBOE | semanal/mensual |
| `VIX_FUTURES_CURVE.csv` | CFE (snapshot del día) | cuando quieras un corte nuevo |
| `qqq_options_chain_*.csv` | Nasdaq (snapshot del día) | cuando quieras recalcular GEX |

### (b) Ejecutar tú mismo el generador
después de actualizar esos archivos:

```cmd
cd /d C:\Users\m21lo\regimen-tilt-nq
python generar_institucional.py --dir INSTITUCIONAL --out institucional.json
git add institucional.json
git commit -m "Actualización institucional"
git push
```

**Si no haces (a) y (b), `institucional.json` se queda congelado en la fecha de la última vez que lo generaste** — no falla, simplemente no avanza. A diferencia del resto del dashboard, esta pestaña no tiene "red de seguridad" automática todavía.

## 5. Lo que sí podría pasar a la columna 2 (automático), si quieres

Confirmado: **VIX/VIX9D/VIX3M/VVIX (CBOE) y COT (CFTC)** tienen URLs/API públicas estables, así que esas dos SÍ se podrían añadir al `actualizar_todo.bat` o incluso al workflow de GitHub Actions sin que tengas que descargarlas a mano nunca más. PCR, cadena de opciones y fund flows de ETF.com seguirían siendo manuales (no hay fuente gratuita estable conocida). Pendiente de decidir si se cablea.

## Checklist mínimo para que nada se desactualice

- [ ] **Nada** — Régimen+Tilt y Estudio Técnico se cuidan solos cada noche laborable.
- [ ] **Doble clic en `actualizar_todo.bat`** — cuando quieras refrescar NRA-DAS/Quant Engine/Ensemble/Crecimiento.
- [ ] **Actualizar CSVs de `INSTITUCIONAL\` + correr `generar_institucional.py` + git push** — manual, sin recordatorio automático, la única pestaña que puede quedarse "vieja" sin que nada te avise.
