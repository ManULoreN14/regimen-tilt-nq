@echo off
setlocal enabledelayedexpansion

REM ============================================================
REM  actualizar_todo.bat
REM  Corre los 3 backtests (NRA-DAS, Quant Engine, Regimen+Tilt),
REM  copia los resultados a las carpetas correctas, regenera las
REM  comparativas, y sube todo a GitHub. Un doble clic y listo.
REM
REM  Si algo falla, el script para en seco en ese paso y te dice
REM  cual fue - no sigue adelante con datos a medias.
REM ============================================================

REM --- RUTAS: ajusta aqui si algo no coincide con tu instalacion ---
set "RTNQ=C:\Users\m21lo\regimen-tilt-nq"

set "NRA_DIR=C:\projects\nra_das"
set "NRA_BACKTESTS=%NRA_DIR%\backtests"

set "QE_DIR=C:\PROYECTO\quant_engine"
set "QE_BACKTESTS=%QE_DIR%\backtests"

echo.
echo ================================================================
echo  1/6 - Generando backtest NRA-DAS
echo ================================================================
cd /d "%NRA_BACKTESTS%"
if errorlevel 1 (
    echo ERROR: no existe la carpeta %NRA_BACKTESTS%
    goto :error
)
python run_backtest_nradas.py
if errorlevel 1 (
    echo ERROR: fallo run_backtest_nradas.py - revisa el mensaje de arriba.
    goto :error
)

echo Copiando resultados de NRA-DAS a regimen-tilt-nq\nra_das\ ...
copy /Y "%NRA_BACKTESTS%\output_backtest_nradas.csv" "%RTNQ%\nra_das\output_backtest_nradas.csv" >nul
copy /Y "%NRA_BACKTESTS%\output_backtest_nradas.json" "%RTNQ%\nra_das\output_backtest_nradas.json" >nul
REM el nombre del CSV anual lleva "n" con tilde; usamos un comodin (a?o) para
REM no tener que escribir esa letra en el script (evita problemas de
REM codificacion). El destino es la carpeta -> conserva el nombre real tal
REM cual esta en disco, sin que nosotros lo tecleemos.
copy /Y "%NRA_BACKTESTS%\output_backtest_nradas_por_a?o.csv" "%RTNQ%\nra_das\" >nul
if errorlevel 1 (
    echo ERROR: fallo copiando algun fichero de NRA-DAS. Revisa que existan
    echo en %NRA_BACKTESTS% con esos nombres exactos.
    goto :error
)
echo OK.

echo.
echo ================================================================
echo  2/6 - Generando backtest Quant Engine
echo ================================================================
cd /d "%QE_BACKTESTS%"
if errorlevel 1 (
    echo ERROR: no existe la carpeta %QE_BACKTESTS%
    goto :error
)
python run_backtest_quant_engine.py
if errorlevel 1 (
    echo ERROR: fallo run_backtest_quant_engine.py - revisa el mensaje de arriba.
    goto :error
)

echo Copiando resultados de Quant Engine a regimen-tilt-nq\quant_engine\ ...
copy /Y "%QE_BACKTESTS%\output_backtest_quant_engine.csv" "%RTNQ%\quant_engine\output_backtest_quant_engine.csv" >nul
copy /Y "%QE_BACKTESTS%\output_backtest_quant_engine.json" "%RTNQ%\quant_engine\output_backtest_quant_engine.json" >nul
copy /Y "%QE_BACKTESTS%\output_backtest_quant_engine_por_ano.csv" "%RTNQ%\quant_engine\output_backtest_quant_engine_por_ano.csv" >nul
if errorlevel 1 (
    echo ERROR: fallo copiando algun fichero de Quant Engine. Revisa que existan
    echo en %QE_BACKTESTS% con esos nombres exactos.
    goto :error
)
echo OK.

echo.
echo ================================================================
echo  3/6 - Actualizando datos de mercado propios (NDX/VIX/FRED...)
echo ================================================================
cd /d "%RTNQ%"
if errorlevel 1 (
    echo ERROR: no existe la carpeta %RTNQ%
    goto :error
)
python generar_datos.py
if errorlevel 1 (
    echo ERROR: fallo generar_datos.py - revisa el mensaje de arriba.
    goto :error
)

echo.
echo ================================================================
echo  4/6 - Regenerando sistema Regimen+Tilt y comparativas
echo ================================================================
python construir_sistema.py
if errorlevel 1 (
    echo ERROR: fallo construir_sistema.py
    goto :error
)

REM velas para la pestaña "Estudio tecnico" (NDX/VIX via yfinance).
REM Tolerante: si falla (p.ej. intradia caido) NO abortamos el push;
REM avisamos y seguimos, porque no debe bloquear la actualizacion real.
python generar_precios.py
if errorlevel 1 (
    echo AVISO: generar_precios.py fallo - se sigue sin actualizar precios.json.
)
python comparar_nra_das.py
if errorlevel 1 (
    echo ERROR: fallo comparar_nra_das.py
    goto :error
)
python comparar_quant_engine.py
if errorlevel 1 (
    echo ERROR: fallo comparar_quant_engine.py
    goto :error
)
python generar_ensemble.py
if errorlevel 1 (
    echo ERROR: fallo generar_ensemble.py
    goto :error
)
python comparar_crecimiento.py
if errorlevel 1 (
    echo ERROR: fallo comparar_crecimiento.py
    goto :error
)

echo.
echo ================================================================
echo  5/6 - Actualizando pestana Institucional (flujos/COT/PCR/vol/GEX)
echo ================================================================
REM Auto-descarga VIX/VIX9D/VIX3M/VVIX/SKEW (CBOE) y COT NASDAQ-100 (CFTC),
REM y ademas usa los CSV manuales (PCR, flujos, cadena de opciones) si los
REM has puesto en INSTITUCIONAL\. Tolerante: si falla, avisa y seguimos sin
REM bloquear el push del resto (igual que generar_precios.py).
python generar_institucional.py
if errorlevel 1 (
    echo AVISO: generar_institucional.py fallo - se sigue sin actualizar institucional.json.
)

echo.
echo ================================================================
echo  6/6 - Subiendo cambios a GitHub
echo ================================================================
git add .
git commit -m "Actualizacion automatica local"
if errorlevel 1 (
    echo AVISO: nada que commitear, o el commit fallo. Continuo con el push
    echo por si hay commits pendientes de antes.
)
git push
if errorlevel 1 (
    echo ERROR: fallo el push. Es posible que haya un conflicto con GitHub
    echo ^(por ejemplo si el cron nocturno actualizo entretanto^).
    echo Prueba manualmente: git pull origin main
    goto :error
)

echo.
echo ================================================================
echo  TODO OK - los 3 sistemas + Institucional actualizados y subidos a GitHub.
echo  La web se refrescara sola en un par de minutos.
echo ================================================================
pause
exit /b 0

:error
echo.
echo ================================================================
echo  PROCESO INTERRUMPIDO - revisa el error de arriba antes de repetir.
echo ================================================================
pause
exit /b 1
@echo off
setlocal enabledelayedexpansion

REM ============================================================
REM  actualizar_todo.bat
REM  Corre los 3 backtests (NRA-DAS, Quant Engine, Regimen+Tilt),
REM  copia los resultados a las carpetas correctas, regenera las
REM  comparativas, y sube todo a GitHub. Un doble clic y listo.
REM
REM  Si algo falla, el script para en seco en ese paso y te dice
REM  cual fue - no sigue adelante con datos a medias.
REM ============================================================

REM --- RUTAS: ajusta aqui si algo no coincide con tu instalacion ---
set "RTNQ=C:\Users\m21lo\regimen-tilt-nq"

set "NRA_DIR=C:\projects\nra_das"
set "NRA_BACKTESTS=%NRA_DIR%\backtests"

set "QE_DIR=C:\PROYECTO\quant_engine"
set "QE_BACKTESTS=%QE_DIR%\backtests"

echo.
echo ================================================================
echo  1/5 - Generando backtest NRA-DAS
echo ================================================================
cd /d "%NRA_BACKTESTS%"
if errorlevel 1 (
    echo ERROR: no existe la carpeta %NRA_BACKTESTS%
    goto :error
)
python run_backtest_nradas.py
if errorlevel 1 (
    echo ERROR: fallo run_backtest_nradas.py - revisa el mensaje de arriba.
    goto :error
)

echo Copiando resultados de NRA-DAS a regimen-tilt-nq\nra_das\ ...
copy /Y "%NRA_BACKTESTS%\output_backtest_nradas.csv" "%RTNQ%\nra_das\output_backtest_nradas.csv" >nul
copy /Y "%NRA_BACKTESTS%\output_backtest_nradas.json" "%RTNQ%\nra_das\output_backtest_nradas.json" >nul
REM el nombre del CSV anual lleva "n" con tilde; usamos un comodin (a?o) para
REM no tener que escribir esa letra en el script (evita problemas de
REM codificacion). El destino es la carpeta -> conserva el nombre real tal
REM cual esta en disco, sin que nosotros lo tecleemos.
copy /Y "%NRA_BACKTESTS%\output_backtest_nradas_por_a?o.csv" "%RTNQ%\nra_das\" >nul
if errorlevel 1 (
    echo ERROR: fallo copiando algun fichero de NRA-DAS. Revisa que existan
    echo en %NRA_BACKTESTS% con esos nombres exactos.
    goto :error
)
echo OK.

echo.
echo ================================================================
echo  2/5 - Generando backtest Quant Engine
echo ================================================================
cd /d "%QE_BACKTESTS%"
if errorlevel 1 (
    echo ERROR: no existe la carpeta %QE_BACKTESTS%
    goto :error
)
python run_backtest_quant_engine.py
if errorlevel 1 (
    echo ERROR: fallo run_backtest_quant_engine.py - revisa el mensaje de arriba.
    goto :error
)

echo Copiando resultados de Quant Engine a regimen-tilt-nq\quant_engine\ ...
copy /Y "%QE_BACKTESTS%\output_backtest_quant_engine.csv" "%RTNQ%\quant_engine\output_backtest_quant_engine.csv" >nul
copy /Y "%QE_BACKTESTS%\output_backtest_quant_engine.json" "%RTNQ%\quant_engine\output_backtest_quant_engine.json" >nul
copy /Y "%QE_BACKTESTS%\output_backtest_quant_engine_por_ano.csv" "%RTNQ%\quant_engine\output_backtest_quant_engine_por_ano.csv" >nul
if errorlevel 1 (
    echo ERROR: fallo copiando algun fichero de Quant Engine. Revisa que existan
    echo en %QE_BACKTESTS% con esos nombres exactos.
    goto :error
)
echo OK.

echo.
echo ================================================================
echo  3/5 - Actualizando datos de mercado propios (NDX/VIX/FRED...)
echo ================================================================
cd /d "%RTNQ%"
if errorlevel 1 (
    echo ERROR: no existe la carpeta %RTNQ%
    goto :error
)
python generar_datos.py
if errorlevel 1 (
    echo ERROR: fallo generar_datos.py - revisa el mensaje de arriba.
    goto :error
)

echo.
echo ================================================================
echo  4/5 - Regenerando sistema Regimen+Tilt y comparativas
echo ================================================================
python construir_sistema.py
if errorlevel 1 (
    echo ERROR: fallo construir_sistema.py
    goto :error
)

REM velas para la pestaña "Estudio tecnico" (NDX/VIX via yfinance).
REM Tolerante: si falla (p.ej. intradia caido) NO abortamos el push;
REM avisamos y seguimos, porque no debe bloquear la actualizacion real.
python generar_precios.py
if errorlevel 1 (
    echo AVISO: generar_precios.py fallo - se sigue sin actualizar precios.json.
)
python comparar_nra_das.py
if errorlevel 1 (
    echo ERROR: fallo comparar_nra_das.py
    goto :error
)
python comparar_quant_engine.py
if errorlevel 1 (
    echo ERROR: fallo comparar_quant_engine.py
    goto :error
)
python generar_ensemble.py
if errorlevel 1 (
    echo ERROR: fallo generar_ensemble.py
    goto :error
)
python comparar_crecimiento.py
if errorlevel 1 (
    echo ERROR: fallo comparar_crecimiento.py
    goto :error
)

echo.
echo ================================================================
echo  5/5 - Subiendo cambios a GitHub
echo ================================================================
git add .
git commit -m "Actualizacion automatica local"
if errorlevel 1 (
    echo AVISO: nada que commitear, o el commit fallo. Continuo con el push
    echo por si hay commits pendientes de antes.
)
git push
if errorlevel 1 (
    echo ERROR: fallo el push. Es posible que haya un conflicto con GitHub
    echo ^(por ejemplo si el cron nocturno actualizo entretanto^).
    echo Prueba manualmente: git pull origin main
    goto :error
)

echo.
echo ================================================================
echo  TODO OK - los 3 sistemas actualizados y subidos a GitHub.
echo  La web se refrescara sola en un par de minutos.
echo ================================================================
pause
exit /b 0

:error
echo.
echo ================================================================
echo  PROCESO INTERRUMPIDO - revisa el error de arriba antes de repetir.
echo ================================================================
pause
exit /b 1
