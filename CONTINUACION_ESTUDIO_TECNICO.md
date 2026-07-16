# CONTINUACIÓN — Régimen+Tilt NQ / Estudio Técnico
Actualizado tras encontrar y corregir el bug real de los dibujos (verificado
en vivo con Claude en Chrome contra la web publicada). Pega este archivo
como primer mensaje (o adjúntalo) en la conversación nueva.

## 0. Cómo usar este documento
Si sigues en el MISMO Project de Claude: la memoria y los archivos del
proyecto ya deberían acompañar la conversación nueva automáticamente. Este
documento cubre igualmente lo que la memoria podría no haber asimilado aún
(resúmenes de memoria se generan con retraso), y sirve de referencia exacta
del estado técnico real del código — más fiable que un resumen narrativo.

**Actualiza los archivos del Project** a las versiones actuales (lista en
§7) — varios de los que ya están subidos (`generar_sistema_json.py`,
`PROMPT_INICIO.md`) son BORRADORES ANTIGUOS de antes de crear el repo
`regimen-tilt-nq`; ya no reflejan el código en producción.

## 1. Qué es esto (para quien no tenga contexto previo)
Sistema de trading sistemático sobre Nasdaq-100 (NDX), decisión de exposición
0-100% (sin apalancar), objetivo CAGR sobre Sharpe (horizonte muy largo).
Repo: `github.com/ManULoreN14/regimen-tilt-nq`, publicado en
`manuloren14.github.io/regimen-tilt-nq/` vía GitHub Pages. Automatizado con
GitHub Actions (cron L-V noche) + `actualizar_todo.bat` local para los otros
dos sistemas (NRA-DAS, Quant Engine, que viven fuera de este repo, en
`C:\projects\nra_das` y `C:\PROYECTO\quant_engine`).

**El cron nocturno de GitHub Actions BASTA por sí solo** para regenerar
precios + patrones cada noche (`generar_precios.py` ya está en
`actualizar.yml`). El `.bat` local solo hace falta para refrescar NRA-DAS/
Quant Engine, que GitHub no puede tocar.

Cuatro/cinco sistemas cuantitativos con validación IC/Stability/walk-forward
ya cerrada (ver `CONSOLIDACION_SISTEMA.md`, `RESULTADO_EXPERIMENTO_1/2.md` en
el Project — vigentes, no tocados esta sesión). Todo el trabajo reciente ha
sido front-end: el dashboard y la pestaña de análisis técnico. El motor de
exposición y la validación cuantitativa no se han tocado.

## 2. Pestaña "Estudio técnico" — arquitectura
Añadida dentro de `index.html` (mismo archivo que el dashboard, pestañas
Panel / Estudio técnico, sin backend nuevo). **KLineChart v9.8.12** vía CDN
(`cdn.jsdelivr.net/npm/klinecharts@9.8.12`) para el Estudio Técnico;
Chart.js (también CDN) sigue para el Panel original.

### 2.1 Los 4 paneles
- 4 "slots" fijos: Mensual / Semanal / Diario / 4 horas, temporalidad de
  cada hueco intercambiable de forma independiente.
- 3 plantillas de distribución (2×2 por defecto, 1 grande+2 apiladas, 2
  mitades). Botón ⛶ por panel → pantalla completa.
- Selector de curva: NDX, VIX (velas reales OHLC) + equity de todos los
  sistemas (Régimen+Tilt, Nasdaq B&H, NRA-DAS, Quant Engine, Ensemble,
  Crecimiento) como líneas, leídas en memoria del propio dashboard.
- Indicadores: EMA/SMA, Bollinger, RSI, Estocástico, MACD, Williams %R,
  Volume Profile (custom, cae a "tiempo-en-precio" sin volumen real).
- Vela Normal / Heikin Ashi (transformación cliente).
- Precio "spot" best-effort (QQQ vía Stooq, cliente, 30s) — sigue sin
  confirmar en un navegador real por el usuario.
- Tema claro/oscuro persistente, afecta Panel + Estudio Técnico.
- Reconocimiento de patrones (§2.3).

### 2.2 Sistema de dibujo — compartido entre las 4 temporalidades
- Herramientas: Tendencia (`segment`), Rectángulo (`areaBox`, overlay
  custom — `'rect'` NO es un nombre válido de KLineChart, solo existe como
  figura interna), Fibonacci (`fibonacciLine`), Horizontal
  (`horizontalStraightLine`).
- Un mismo trazo (mismo id de KLineChart reutilizado a propósito en las 4
  instancias de chart) se crea/mueve/borra en los 4 paneles a la vez.
  Guardado en `localStorage` bajo `estudio:<serieKey>` (compartido entre
  temporalidades, no por separado).
- Auto-encuadre (`ensureOverlayVisible`): al replicar un dibujo, si sus
  fechas caen fuera de la ventana visible del panel (típico en Diario/4H
  con miles de velas), se ajusta scroll/zoom para que se vea.
- Clic derecho sobre cualquier dibujo → menú con color, grosor,
  **transparencia** (independiente, el relleno del rectángulo respeta
  alpha sin perder el borde opaco), y "eliminar este dibujo" (solo ese).

### 2.3 Reconocimiento de patrones (PENDIENTE DE RETOMAR)
`patrones_tecnicos.py`: detecta velas (Doji, Martillo, Envolvente
alcista/bajista — reglas deterministas) y figuras gráficas (Doble
techo/suelo, H-C-H y H-C-H invertido, Triángulo asc/desc/simétrico, Bandera
alcista/bajista — heurística sobre swings/fractales). Umbrales configurables
como constantes al principio del archivo. **Decisión acordada y ya
implementada**: solo inspección visual, nunca alimenta el motor de
exposición (mismo principio que ya rechazó RSI/MACD/Fibonacci por falta de
edge). Integrado en `generar_precios.py`, corre solo cada noche. Botón
"Mostrar patrones" en el Estudio Técnico, apagado por defecto, capa aislada
de los dibujos del usuario (verificado con tests).

**Esto quedó implementado y entregado, pero la sesión se desvió hacia el
bug de dibujo (§3) antes de que el usuario confirmara que los patrones
funcionan bien en su navegador real.** Si retomas, pregunta primero si ya
lo probó.

## 3. El bug real de los dibujos — encontrado y corregido esta sesión
El usuario reportó: dibujos desincronizados entre temporalidades (pendiente
invertida, fechas "atrasadas"), y que nunca aparecían en 4H. **Se investigó
en vivo con Claude en Chrome contra la web publicada real** (no solo en el
sandbox de pruebas) — metodología clave a repetir si reaparecen síntomas
parecidos.

### 3.1 Diagnóstico
Con conversión exacta de coordenadas (`chart.convertToPixel`), se descartó
que fuera un problema de sincronización: los datos guardados eran idénticos
y correctamente ordenados en los 4 paneles. **La causa real**: cuando un
clic de dibujo cae en el margen en blanco que KLineChart reserva a la
derecha de la última vela (para "ver hacia el futuro"), el punto se guarda
**sin `timestamp`** (solo `value`, el precio). Verificado con precisión en
vivo: en el panel Diario, x=620px (dentro de las velas) resolvía bien;
x=650px (ya en el margen) fallaba, de forma consistente. El margen ocupa
aproximadamente el último cuarto del ancho de un panel.

Un punto sin timestamp no tiene dónde colocarse al replicarse en los demás
paneles — de ahí pendientes invertidas, fechas desplazadas, o ausencia total
en el panel con menos histórico disponible (4H).

### 3.2 La corrección (`resolveMissingTimestamps` en `index.html`)
Cuando un punto llega sin `timestamp`, se extrapola usando:
- La posición en píxeles **de página** del clic (`evt.pageX`), NO
  `evt.x`/`evt.y` del propio evento de KLineChart — **verificado
  empíricamente que `evt.x` NO comparte sistema de coordenadas con
  `chart.convertToPixel()`** (un desajuste real que costó una ronda extra
  de instrumentación para detectar: la primera versión del fix invertía el
  orden cronológico de los puntos por este motivo).
- El rectángulo real del `<canvas>` de la vela (`getBoundingClientRect()`)
  como referencia común entre `pageX` y `convertToPixel`.
- El intervalo entre las dos últimas velas, para saber cuántas barras
  "hacia el futuro" cayó el clic.

Si por lo que sea no se puede calcular (chart sin datos, error), hay un
último recurso que nunca deja un punto sin fecha (ancla al último dato +
1 intervalo por posición). Verificado con tests que YA NO invierte el
orden cronológico y que el resto de funcionalidad (rectángulo, menú
contextual, cambios de temporalidad/serie) sigue intacta.

### 3.3 Estado de esta corrección
**Entregada al usuario, pendiente de que la suba a GitHub y la confirme en
su navegador real.** Comandos que se le dieron:
```cmd
cd /d C:\Users\m21lo\regimen-tilt-nq
python -m http.server 8000
REM probar: tendencia con el 2º punto arrastrado cerca del borde derecho
git add index.html
git commit -m "Fix: puntos de dibujo en el margen derecho perdian la fecha (afectaba sincronizacion entre temporalidades)"
git push origin main
```
**Si retomas y no sabes si esto se subió**: pregunta al usuario, o comprueba
tú mismo con Claude en Chrome (ver §4) visitando la web publicada con un
parámetro anti-caché y repitiendo la prueba de §3.1.

## 4. Cómo verificar cambios en este proyecto (dos vías, ambas usadas)

### 4.1 Playwright en el sandbox de Claude (rápido, para iterar)
KLineChart/Chart.js vía CDN NO son accesibles desde el sandbox de pruebas
(red restringida). Instalar en local con npm (`npm install klinecharts
chart.js` en `/home/claude`) y servir el HTML apuntando a esas copias
locales en vez del CDN, con `python -m http.server`. Interactuar con
Playwright (`chromium.launch()`), verificando con datos objetivos
(`localStorage`, conteos de overlays vía un pequeño `window.__probe`
inyectado) — nunca fiarse solo de capturas de pantalla para verificar
lógica. **Importante**: KLineChart necesita eventos de `mousemove`
graduales para completar dibujos de 2 clics de forma fiable en
automatización (`page.mouse.move(x,y,{steps:10})`, no `.click()` a secas)
— un ratón real siempre genera ese movimiento, así que esto nunca fue un
problema para el usuario, solo para clics sintéticos instantáneos.

### 4.2 Claude en Chrome contra la web real (esta sesión, primera vez)
Usado quirúrgicamente cuando el usuario pidió verificación en directo.
Aprendizajes:
- **GitHub Pages cachea agresivamente**: la primera visita sirvió una
  versión de días atrás. Añadir `?nocache=<numero>` a la URL fuerza la
  versión actual. Si la web se ve "vieja" sin razón aparente, probar esto
  antes de sospechar del código o del deploy.
- **Cuidado al clicar botones pequeños**: un clic en la esquina superior
  izquierda exacta de un botón (coordenada de `getBoundingClientRect`, no
  el centro) puede no registrar como clic real en este entorno de
  automatización — usar siempre el CENTRO del elemento (`x+w/2, y+h/2`).
- **No llamar a `klinecharts.init(id)` de nuevo sobre un contenedor ya
  inicializado para "inspeccionar" un chart existente** — su idempotencia
  está rota (compara por una clave que nunca coincide) y crea una instancia
  duplicada en el mismo DOM en vez de devolver la existente, rompiendo la
  verificación. Si hace falta inspeccionar un overlay ya creado sin tocar
  el chart, instrumentar temporalmente el propio código fuente (variables
  en `window`) en una copia de prueba, no contra la página ya cargada.
- El puente de Chrome puede quedarse colgado (timeout de 4 min); si pasa,
  no insistir en bucle — pedir al usuario que reinicie la extensión/MCP y
  continuar con `tabs_context_mcp` cuando confirme.

## 5. Estado de git/repo
- Un vídeo de 53MB (`INSTITUCIONAL/FUND_FLOWS.mp4`) se coló por accidente
  (probablemente vía `git add .` del `actualizar_todo.bat`) y causó un
  timeout de push (HTTP 408). Eliminado del repo hacia adelante +
  `.gitignore` con `*.mp4`, `*.mov`, `INSTITUCIONAL/`. Sigue en el
  historial antiguo de git (no purgado, no urgente).
- El resto de git limpio a fecha de cierre de la sesión anterior
  (`main` en `753fafa`, patrones + doc de continuación). **El commit del
  fix de dibujo (§3.3) puede o no estar ya subido** — comprobar.

## 6. Ideas propuestas y aún NO implementadas (pendientes, no urgentes)
- Alertas de cambio de régimen (email/Telegram) — mayor valor práctico.
- Diario de decisiones (cuándo te desviaste del sistema y por qué).
- Exportar PNG del panel enfocado del Estudio Técnico.
- Backup periódico de `historico_maestro.csv` fuera de GitHub.
- Revisar DIX en 6-12 meses (recordatorio antiguo, sigue pendiente).
- Purga del vídeo del historial de git (opcional, no urgente).

## 7. Archivos actuales (adjuntar estos, no los antiguos del Project)
- `index.html` — dashboard completo (Panel + Estudio Técnico), incluye el
  fix de §3
- `generar_precios.py` — genera `precios.json` (OHLC + patrones)
- `patrones_tecnicos.py` — motor de detección de patrones
- `construir_sistema.py` — sin cambios esta sesión
- `actualizar.yml` — Action de GitHub (incluye ya `generar_precios.py`)
- `actualizar_todo.bat` — script local (incluye ya `generar_precios.py`)

No hace falta re-subir `CONSOLIDACION_SISTEMA.md`, `RESULTADO_EXPERIMENTO_*`,
`base.py` — siguen vigentes tal cual están en el Project.

## 8. Qué NO cambiar sin datos (recordatorios ya existentes, siguen vigentes)
- El motor es la regla SMA200 (con confirmación de 3 días); tilt+switch son
  extra marginal.
- Sin apalancamiento: banda 0.50x-1.00x, restricción dura del usuario.
- No añadir más indicadores técnicos "por si acaso" al motor — ya validado
  que no aportan edge en NDX (mismo principio aplica a los patrones §2.3).
