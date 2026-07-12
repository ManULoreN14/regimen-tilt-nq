# Régimen + Tilt · Nasdaq-100

Sistema de trading sistemático sobre el Nasdaq-100 (NDX) que decide una
**exposición diaria 0–100% (nunca apalancado)** en tres capas:

1. **Régimen SMA200 (motor), con confirmación de 3 días.** Si el NDX
   cotiza por debajo de su media de 200 sesiones → 0% (flat). Si está por
   encima → sigue a la capa 2. El cambio de régimen no se aplica hasta que
   el precio lleva **3 sesiones seguidas** al mismo lado de la media —
   evita "whipsaw" (entradas/salidas de un día que se deshacen enseguida)
   en tramos laterales, sin tocar la protección ante caídas grandes.
2. **Tilt suave (0.50x–1.00x).** Dentro del alcista, una señal de
   estructura de volatilidad (VTS = VIX3M/VIX invertido, VVIX/VIX
   invertido, VIX9D/VIX **directo**, las tres promediadas) inclina la
   exposición. Rebalanceo **semanal** (cada 5 sesiones).
3. **Switch monetario.** Si el balance de la Fed (WALCL) se contrae 60d
   **y** los tipos (DFF) suben >5pb en 60d → se apaga el tilt y la
   exposición se sienta en el **punto medio (0.75x)** dentro del alcista.

## Qué esperar de verdad (números reales, no ideales)

Backtest realista sobre 2006–2026 con retraso de ejecución de 2 días y
5 bps por rebalanceo — es lo que emite `construir_sistema.py`:

| | CAGR | MaxDD | Sharpe |
|---|---|---|---|
| Estrategia (full) | ~10.2% | ~−24% | ~0.81 |
| Estrategia (IS ≤2018) | ~6.9% | ~−19% | ~0.66 |
| Estrategia (OOS ≥2019) | ~15.9% | ~−24% | ~1.01 |
| Nasdaq Buy&Hold (full) | ~15.8% | ~−54% | ~0.77 |

**El sistema NO bate al Nasdaq en retorno.** Su valor es recortar el
drawdown casi a la mitad con un Sharpe similar. El motor es la regla
SMA200; el tilt y el switch añaden poco (neto de coste). Los Sharpe ~2.0
que aparecen en apuntes antiguos correspondían a 2011–2019 (dinero fácil)
o a mediciones sin coste; el número honesto a llevarse es el de arriba.

## Archivos

```
generar_datos.py          descarga NDX/VIX/VIX3M/VVIX/VIX9D/IRX (yfinance)
                          + WALCL/DFF (FRED CSV público). Carga incremental.
construir_sistema.py      calcula score/exposición/equity -> sistema_regimen_tilt.json
index.html                página única (Chart.js): tarjetas de hoy, gráficos de
                          exposición y equity, selector 1A/5A/10A/Todo,
                          crosshair vertical sincronizado entre ambos gráficos.
historico_maestro.csv     histórico (se genera y crece solo; vive en el repo).
sistema_regimen_tilt.json salida que lee la página.
manifest.json              metadatos de la PWA (nombre, iconos, colores).
service-worker.js          caché offline: app shell + último JSON conocido.
icons/                     iconos de la app (192px y 512px).
.github/workflows/        cron nocturno (L-V) que actualiza y hace push solo.
*_History.csv, fred_*.csv semilla del histórico largo (solo para el primer arranque).
```

## Puesta en marcha local

```bash
pip install pandas numpy yfinance requests
python generar_datos.py       # primera vez: siembra desde los CSV + baja lo reciente
python construir_sistema.py   # genera sistema_regimen_tilt.json
# abre index.html en el navegador (mejor servido, ver abajo)
python -m http.server 8000    # y visita http://localhost:8000
```

`index.html` hace `fetch('./sistema_regimen_tilt.json')`, así que necesita
servirse por HTTP (abrirlo con doble clic puede bloquear el fetch por CORS
en algunos navegadores). En producción lo sirve GitHub Pages sin problema.

## Ver en el móvil (PWA)

La página es una PWA (Progressive Web App): además de verse en cualquier
navegador por su URL normal de GitHub Pages, se puede **instalar como
app** en el móvil:

- **Android (Chrome):** abre la URL → menú (⋮) → "Instalar app" o
  "Añadir a pantalla de inicio".
- **iPhone (Safari):** abre la URL → botón compartir → "Añadir a
  pantalla de inicio".

Queda un icono en la pantalla de inicio, se abre a pantalla completa sin
la barra del navegador, y el último dato descargado se guarda en caché
(`service-worker.js`) para poder abrirla aunque no haya cobertura en ese
momento — mostrará el último `sistema_regimen_tilt.json` que se
descargó con conexión.

No hace falta ninguna configuración extra para esto: en cuanto
`index.html`, `manifest.json`, `service-worker.js` y la carpeta
`icons/` estén en GitHub Pages, la instalación funciona sola.

## Comparativa con otros sistemas (NRA-DAS, Quant Engine, ...)

La web puede mostrar, de forma opcional, una línea de comparación por
cada proyecto externo que tengas, en los dos gráficos, más una tabla de
métricas en igualdad de condiciones (mismo periodo para todos).

Actualmente hay dos comparaciones activas: **NRA-DAS** (rojo) y
**Quant Engine** (azul). Añadir un sistema nuevo es sencillo porque la
lógica está generalizada en `comparativa_lib.py`.

**Cómo actualizar una comparación existente** (según dijiste, algo
esporádico — semanal o mensual):

1. Sustituye los 3 ficheros dentro de la carpeta del sistema
   correspondiente (`nra_das/` o `quant_engine/`), **manteniendo
   exactamente los nombres originales**.
2. Ejecuta el script de ese sistema:
   ```bash
   python comparar_nra_das.py
   # o
   python comparar_quant_engine.py
   ```
3. Sube el cambio (`git add . && git commit -m "..." && git push`).

**Cómo añadir un sistema nuevo** (si en el futuro tienes un tercero):

1. Crea una carpeta `nombre_sistema/` con tus 3 ficheros (CSV diario con
   columnas `equity_sys`, `equity_qqq`, `qqq_weight` + columna de fecha;
   CSV anual opcional; JSON de métricas oficiales).
2. Crea un script `comparar_nombre_sistema.py` copiando
   `comparar_quant_engine.py` como plantilla y ajustando los nombres de
   fichero y la columna de fecha (`"fecha"` o `"date"`, según tu CSV).
3. Añade una línea en `index.html`, dentro de `COMPARACIONES_CFG` (busca
   ese nombre en el fichero), con el nuevo `archivo` y un `color` que se
   distinga bien de los demás.
4. Ejecuta tu script nuevo y haz push. La web se actualiza sola con la
   tercera línea, leyenda y tabla incluidas.

Si borras la carpeta de un sistema o no ejecutas su script, esa
comparación simplemente desaparece de la web — no rompe nada del sistema
principal ni de las demás comparaciones.

Haz clic en cualquier nombre de la leyenda (debajo de cada gráfico) para
mostrar u ocultar esa línea.

## Notas de datos

- **VIX3M / VIX9D / VVIX son poco fiables vía yfinance** (a veces
  "delisted"). Si un ticker falla una noche, el script **no rompe**:
  mantiene el último valor (forward-fill hasta 10 sesiones) y sigue. El
  histórico largo de estas tres series se siembra una vez desde los
  `*_History.csv` de CBOE incluidos.
- WALCL/DFF vienen de FRED por CSV público (sin API key).
- El primer arranque necesita los CSV semilla en la raíz del repo. Tras
  generar `historico_maestro.csv`, ya no son imprescindibles (puedes
  dejarlos como respaldo por si hay que re-sembrar).
