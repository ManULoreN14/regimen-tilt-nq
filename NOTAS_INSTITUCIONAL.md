# Notas — Pestaña "Institucional"

Ideas propias añadidas al análisis inicial de Gemini sobre la huella
institucional (flujos, COT, PCR, complejo de volatilidad, SKEW, GEX).
Estado a fecha de esta sesión: los 5 puntos están implementados en
`generar_institucional.py` + la pestaña de `index.html`, salvo donde se
indica lo contrario.

## 1. COT: separar Asset Managers vs. Leveraged Money — IMPLEMENTADO
Gemini trataba el COT como un bloque monolítico ("compromiso
institucional"). Son dos actores con motivaciones opuestas:
- **Asset Managers** = dinero real (fondos, aseguradoras, pensiones) →
  "buy and hold" institucional.
- **Leveraged Money** = fondos macro/CTA/hedge funds apalancados →
  táctico, rota rápido.
Cuando divergen (real money largo, apalancados muy cortos, o viceversa)
es la señal más rica del dataset. Se muestran como dos series separadas
en el gráfico COT vs. precio, con z-scores independientes
(`z_am_net`, `z_lev_net`) y mensajes de card distintos según cuál es el
que está en extremo.

## 2. Zero-gamma flip level — IMPLEMENTADO
No basta con Call Wall / Put Wall. El strike donde el GEX acumulado
(ordenado por strike ascendente) cruza cero marca el punto donde el
régimen cambia de "pegajoso" (gamma positivo, dealers amortiguan) a
"explosivo" (gamma negativo, dealers amplifican). Se calcula en
`generar_institucional.py::load_options_gex` (campo
`gex.summary.zero_gamma_strike`) y se muestra en la card de GEX.

## 3. Divergencia flujo vs. precio como serie, no snapshot — IMPLEMENTADO (versión básica)
En vez de mirar un solo día de flujo, se compara la variación de precio
en 20 sesiones (`price_20d_chg_pct`) contra el signo del flujo
acumulado de 20 sesiones (`flow_usd_20d`). Se muestra como card
("Divergencia flujo vs. precio") con lectura explícita de si convergen
o divergen. **Pendiente de refinar**: esto es una comparación de signos
en el último punto, no una serie histórica de divergencia con su propio
z-score. Si quieres ese nivel de detalle, el siguiente paso natural es
correlación rolling (63 días) entre `flow_usd_20d` y el retorno de
precio de la misma ventana, y marcar visualmente los tramos donde la
correlación cae o se invierte.

## 4. Term structure del VIX (contango/backwardation) — IMPLEMENTADO (snapshot)
`VIX_FUTURES_CURVE.csv` solo te da un corte del día (no serie
histórica), así que el régimen (`vix_curve.regime`,
`vix_curve.front_slope`) se calcula comparando el vencimiento más
cercano contra el más lejano disponible ese día. Se muestra en la card
de COT. Backwardation = señal de estrés más limpia que el nivel de VIX
en sí. **Si en algún momento guardas el snapshot de cada día**, esto se
podría convertir en serie histórica real y testarse con el mismo
harness IC que usas para el resto de señales.

## 5. Ratio Volumen/Open Interest como proxy de liquidez — IMPLEMENTADO
El bid-ask spread real no es viable (no tienes tick data ni NBBO
histórico). En su lugar: volumen del día / open interest acumulado en
los vencimientos ≤45 días (`gex.summary.vol_oi_ratio_near`). Un ratio
bajo = libro fino = movimientos más violentos ante cualquier orden
grande. Se muestra en la card de GEX con un aviso cuando cae por
debajo de 0.3 (umbral inicial, ajustar con más historia una vez
acumules varios cortes de la cadena de opciones).

## Limitación conocida y pendiente
`SKEW_History.csv` solo tiene ~3 meses de historia (abril-julio 2026).
El z-score de SKEW no es fiable todavía y no se usa en el score
compuesto. Se irá corrigiendo solo según acumules el archivo cada
noche. Si consigues el histórico completo del CBOE SKEW, avisa para
recalcular.

## Siguiente paso recomendado (no implementado aquí)
Antes de dar por buena cualquiera de estas señales como algo accionable,
pasarlas por tu harness real de validación (IC Spearman forward,
Stability ≥70%, walk-forward ≥3 periodos, |IC|>0.03, p<0.05) — igual
que ya hiciste con RSI/MACD/Fibonacci. El event study exploratorio
(`event_study.py`) ya deja ver que, por ejemplo, "flujo de salida
extremo → sube" es robusta IS/OOS, pero "flujo de entrada extremo →
baja" no lo es tras 2018. Ese es el tipo de filtro que hay que aplicar
a todo lo de esta pestaña antes de que influya en decisiones reales.
