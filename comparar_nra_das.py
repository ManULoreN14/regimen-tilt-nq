#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
comparar_nra_das.py — genera nra_das_comparativa.json comparando NRA-DAS
contra nuestro sistema Régimen+Tilt.

Actualiza estos 3 ficheros en nra_das/ cuando quieras refrescar la
comparación (mismos nombres exactos) y vuelve a correr este script:
  - nra_das/output_backtest_nradas.csv
  - nra_das/output_backtest_nradas_por_año.csv
  - nra_das/output_backtest_nradas.json

No hace falta tocar nada más — index.html detecta el fichero de salida
solo. Si borras la carpeta nra_das/, la comparación desaparece de la web
sin romper nada del sistema principal.
"""
from pathlib import Path
from comparativa_lib import generar_comparativa

BASE = Path(__file__).resolve().parent
DIR = BASE / "nra_das"

if __name__ == "__main__":
    generar_comparativa(
        nombre="NRA-DAS",
        clave_json="nra_das",
        csv_diario=DIR / "output_backtest_nradas.csv",
        csv_anual=DIR / "output_backtest_nradas_por_año.csv",
        json_meta=DIR / "output_backtest_nradas.json",
        sistema_json=BASE / "sistema_regimen_tilt.json",
        out_path=BASE / "nra_das_comparativa.json",
        col_fecha="fecha",
    )
