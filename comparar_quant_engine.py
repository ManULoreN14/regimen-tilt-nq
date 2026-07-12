#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
comparar_quant_engine.py — genera quant_engine_comparativa.json comparando
Quant Engine contra nuestro sistema Régimen+Tilt.

Actualiza estos 3 ficheros en quant_engine/ cuando quieras refrescar la
comparación (mismos nombres exactos) y vuelve a correr este script:
  - quant_engine/output_backtest_quant_engine.csv
  - quant_engine/output_backtest_quant_engine_por_ano.csv
  - quant_engine/output_backtest_quant_engine.json

No hace falta tocar nada más — index.html detecta el fichero de salida
solo. Si borras la carpeta quant_engine/, la comparación desaparece de la
web sin romper nada del sistema principal.
"""
from pathlib import Path
from comparativa_lib import generar_comparativa

BASE = Path(__file__).resolve().parent
DIR = BASE / "quant_engine"

if __name__ == "__main__":
    generar_comparativa(
        nombre="Quant Engine",
        clave_json="quant_engine",
        csv_diario=DIR / "output_backtest_quant_engine.csv",
        csv_anual=DIR / "output_backtest_quant_engine_por_ano.csv",
        json_meta=DIR / "output_backtest_quant_engine.json",
        sistema_json=BASE / "sistema_regimen_tilt.json",
        out_path=BASE / "quant_engine_comparativa.json",
        col_fecha="date",
    )
