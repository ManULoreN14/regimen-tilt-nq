#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
patrones_tecnicos.py — detección de patrones de vela y de gráfico sobre OHLC,
pensada EXCLUSIVAMENTE como capa de inspección visual para el Estudio Técnico.

IMPORTANTE (para que quede escrito y no se te olvide en 6 meses): esto NO
alimenta ni debe alimentar nunca el motor de exposición. Tu propio historial
de validación (CONSOLIDACION_SISTEMA.md, RESULTADO_EXPERIMENTO_1/2.md) ya
descartó indicadores técnicos similares (RSI, MACD, Fibonacci) por falta de
edge sistemático en NDX vía el arnés IC/Stability/walk-forward. No hay razón
estructural para que el reconocimiento de patrones de velas o gráficos se
comporte distinto. Si algún día quieres probarlo como señal, pasa por el
mismo arnés de validación (base.py) antes de tocar construir_sistema.py.

Qué detecta:
  Velas (regla determinista sobre el bar):
    - doji, martillo, envolvente_alcista, envolvente_bajista
  Gráficos (heurística sobre puntos de swing / fractales):
    - doble_techo, doble_suelo
    - hch (hombro-cabeza-hombro), hch_inv (invertido)
    - triangulo_asc, triangulo_desc, triangulo_sim
    - bandera_alcista, bandera_bajista

Todo lo de "gráficos" es heurístico y aproximado por naturaleza (igual que
cualquier scanner de patrones retail) — se etiqueta así en el propio dato
('confianza': 'heuristica') para que el dashboard lo deje claro.

Uso: se llama desde generar_precios.py con las listas OHLC ya construidas
(mismas velas que ve el usuario, para que lo que se anota coincida 1:1 con
lo que se dibuja). No lee archivos por su cuenta.
"""
from __future__ import annotations
import math

# ---------------------------------------------------------------- parámetros
SWING_K = 3            # velas a cada lado para confirmar un fractal (swing)
TOL_DOBLE = 0.015       # tolerancia relativa entre picos/valles de doble techo/suelo
TOL_HOMBROS = 0.03      # tolerancia relativa entre hombros del H-C-H
LOOKBACK_TRIANGULO = 60 # velas hacia atrás para buscar triángulo
MIN_SWINGS_TRIANGULO = 3
IMPULSO_PCT = 0.08      # movimiento mínimo (8%) para considerar "impulso" de bandera
IMPULSO_MAX_BARRAS = 10
CONSOLIDACION_MAX_BARRAS = 15


def _rows_to_ohlc(rows):
    """rows: [[ts,o,h,l,c,(vol)], ...] -> listas paralelas."""
    ts = [r[0] for r in rows]
    o = [r[1] for r in rows]
    h = [r[2] for r in rows]
    l = [r[3] for r in rows]
    c = [r[4] for r in rows]
    return ts, o, h, l, c


# ---------------------------------------------------------------- velas
def _cuerpo(o, c):
    return abs(c - o)


def _rango(h, l):
    return max(h - l, 1e-9)


def patrones_vela(rows):
    """Devuelve anotaciones puntuales: doji, martillo, envolventes."""
    ts, o, h, l, c = _rows_to_ohlc(rows)
    out = []
    n = len(rows)
    for i in range(n):
        rng = _rango(h[i], l[i])
        cuerpo = _cuerpo(o[i], c[i])
        # Doji: cuerpo minúsculo frente al rango total de la vela
        if cuerpo / rng < 0.08:
            out.append({"t": ts[i], "tipo": "doji", "texto": "Doji", "clase": "vela",
                        "lado": "arriba" if c[i] >= o[i] else "abajo"})
            continue
        # Martillo: cuerpo pequeño arriba, sombra inferior larga (>=2x cuerpo), poca sombra superior
        cuerpo_top = max(o[i], c[i])
        cuerpo_bot = min(o[i], c[i])
        sombra_inf = cuerpo_bot - l[i]
        sombra_sup = h[i] - cuerpo_top
        if cuerpo > 0 and sombra_inf >= 2 * cuerpo and sombra_sup <= 0.3 * cuerpo:
            out.append({"t": ts[i], "tipo": "martillo", "texto": "Martillo", "clase": "vela",
                        "lado": "abajo"})
        # Envolvente (necesita la vela anterior)
        if i > 0:
            cuerpo_prev = _cuerpo(o[i - 1], c[i - 1])
            alcista_prev = c[i - 1] < o[i - 1]
            alcista_act = c[i] > o[i]
            if alcista_prev and alcista_act and o[i] <= c[i - 1] and c[i] >= o[i - 1] and cuerpo > cuerpo_prev:
                out.append({"t": ts[i], "tipo": "envolvente_alcista", "texto": "Envolvente alcista",
                            "clase": "vela", "lado": "abajo"})
            bajista_prev = c[i - 1] > o[i - 1]
            bajista_act = c[i] < o[i]
            if bajista_prev and bajista_act and o[i] >= c[i - 1] and c[i] <= o[i - 1] and cuerpo > cuerpo_prev:
                out.append({"t": ts[i], "tipo": "envolvente_bajista", "texto": "Envolvente bajista",
                            "clase": "vela", "lado": "arriba"})
    return out


# ---------------------------------------------------------------- swings
def _swings(h, l, k=SWING_K):
    """Fractales: (idx, precio, 'alto'|'bajo'). Requiere k velas de confirmación
    a cada lado, así que los últimos k valores nunca se marcan (aún no
    confirmados) — comportamiento correcto, no un bug."""
    n = len(h)
    out = []
    for i in range(k, n - k):
        ventana_h = h[i - k:i + k + 1]
        ventana_l = l[i - k:i + k + 1]
        if h[i] == max(ventana_h) and ventana_h.count(h[i]) == 1:
            out.append((i, h[i], "alto"))
        if l[i] == min(ventana_l) and ventana_l.count(l[i]) == 1:
            out.append((i, l[i], "bajo"))
    out.sort(key=lambda x: x[0])
    return out


def _cerca(a, b, tol):
    return abs(a - b) / max(abs(a), abs(b), 1e-9) <= tol


def _regresion(xs, ys):
    """Pendiente e intersección de mínimos cuadrados; devuelve (m, b, r2)."""
    n = len(xs)
    if n < 2:
        return 0.0, (ys[0] if ys else 0.0), 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    if sxx == 0:
        return 0.0, my, 0.0
    m = sxy / sxx
    b = my - m * mx
    ss_tot = sum((y - my) ** 2 for y in ys) or 1e-9
    ss_res = sum((y - (m * x + b)) ** 2 for x, y in zip(xs, ys))
    r2 = 1 - ss_res / ss_tot
    return m, b, r2


# ---------------------------------------------------------------- dobles techos/suelos
def _dobles(swings, ts, tipo_swing, tag, texto):
    out = []
    puntos = [s for s in swings if s[2] == tipo_swing]
    for j in range(1, len(puntos)):
        i1, v1, _ = puntos[j - 1]
        i2, v2, _ = puntos[j]
        if i2 - i1 < SWING_K * 2:
            continue
        if _cerca(v1, v2, TOL_DOBLE):
            out.append({
                "tipo": tag, "texto": texto, "clase": "grafico", "confianza": "heuristica",
                "t": ts[i2],
                "puntos": [{"t": ts[i1], "v": v1}, {"t": ts[i2], "v": v2}],
            })
    return out


# ---------------------------------------------------------------- H-C-H
def _hch(swings, ts, tipo_swing, tag, texto, invertido):
    out = []
    picos = [s for s in swings if s[2] == tipo_swing]
    for j in range(2, len(picos)):
        (i1, v1, _), (i2, v2, _), (i3, v3, _) = picos[j - 2], picos[j - 1], picos[j]
        cabeza_mayor = (v2 > v1 and v2 > v3) if not invertido else (v2 < v1 and v2 < v3)
        hombros_parejos = _cerca(v1, v3, TOL_HOMBROS)
        if cabeza_mayor and hombros_parejos:
            out.append({
                "tipo": tag, "texto": texto, "clase": "grafico", "confianza": "heuristica",
                "t": ts[i3],
                "puntos": [{"t": ts[i1], "v": v1}, {"t": ts[i2], "v": v2}, {"t": ts[i3], "v": v3}],
            })
    return out


# ---------------------------------------------------------------- triángulos
def _triangulos(swings, ts, h, l, n):
    out = []
    if n < LOOKBACK_TRIANGULO:
        return out
    ini = n - LOOKBACK_TRIANGULO
    altos = [(i, v) for i, v, t in swings if t == "alto" and i >= ini]
    bajos = [(i, v) for i, v, t in swings if t == "bajo" and i >= ini]
    if len(altos) < MIN_SWINGS_TRIANGULO or len(bajos) < MIN_SWINGS_TRIANGULO:
        return out
    xs_a, ys_a = [p[0] for p in altos], [p[1] for p in altos]
    xs_b, ys_b = [p[0] for p in bajos], [p[1] for p in bajos]
    m_a, b_a, r2_a = _regresion(xs_a, ys_a)
    m_b, b_b, r2_b = _regresion(xs_b, ys_b)
    if r2_a < 0.5 or r2_b < 0.5:
        return out   # las rectas no ajustan bien -> no hay figura clara, se descarta
    ancho_ini = (m_a * ini + b_a) - (m_b * ini + b_b)
    ancho_fin = (m_a * (n - 1) + b_a) - (m_b * (n - 1) + b_b)
    if ancho_ini <= 0 or ancho_fin >= ancho_ini * 0.85:
        return out   # no converge lo suficiente
    plano = lambda m, ref: abs(m) < ref * 0.0015   # pendiente casi nula, relativa al precio
    ref_precio = (ys_a[-1] + ys_b[-1]) / 2
    if plano(m_a, ref_precio) and m_b > 0:
        tipo, texto = "triangulo_asc", "Triángulo ascendente"
    elif plano(m_b, ref_precio) and m_a < 0:
        tipo, texto = "triangulo_desc", "Triángulo descendente"
    elif m_a < 0 and m_b > 0:
        tipo, texto = "triangulo_sim", "Triángulo simétrico"
    else:
        return out
    out.append({
        "tipo": tipo, "texto": texto, "clase": "grafico", "confianza": "heuristica",
        "t": ts[n - 1],
        "linea_superior": [{"t": ts[ini], "v": m_a * ini + b_a}, {"t": ts[n - 1], "v": m_a * (n - 1) + b_a}],
        "linea_inferior": [{"t": ts[ini], "v": m_b * ini + b_b}, {"t": ts[n - 1], "v": m_b * (n - 1) + b_b}],
    })
    return out


# ---------------------------------------------------------------- banderas
def _banderas(ts, o, h, l, c, n):
    out = []
    i = SWING_K
    while i < n - 1:
        encontrado = False
        for dur in range(3, IMPULSO_MAX_BARRAS + 1):
            j = i + dur
            if j >= n:
                break
            var = (c[j] - c[i]) / max(abs(c[i]), 1e-9)
            if abs(var) < IMPULSO_PCT:
                continue
            alcista = var > 0
            # consolidación tras el impulso: rango estrecho, pendiente suave contraria
            fin_cons = min(n - 1, j + CONSOLIDACION_MAX_BARRAS)
            if fin_cons - j < 4:
                continue
            tramo_c = c[j:fin_cons + 1]
            rango_cons = (max(tramo_c) - min(tramo_c)) / max(abs(tramo_c[0]), 1e-9)
            impulso_rango = abs(var)
            if rango_cons < impulso_rango * 0.5:
                tipo = "bandera_alcista" if alcista else "bandera_bajista"
                texto = "Bandera alcista" if alcista else "Bandera bajista"
                out.append({
                    "tipo": tipo, "texto": texto, "clase": "grafico", "confianza": "heuristica",
                    "t": ts[fin_cons],
                    "puntos": [{"t": ts[i], "v": c[i]}, {"t": ts[j], "v": c[j]}, {"t": ts[fin_cons], "v": c[fin_cons]}],
                })
                i = fin_cons
                encontrado = True
                break
        if not encontrado:
            i += 1
    return out


# ---------------------------------------------------------------- entrada única
def detectar(rows):
    """rows: filas OHLC [[ts,o,h,l,c,(vol)], ...] de UNA temporalidad de UNA
    serie (tal cual las consume el gráfico). Devuelve lista de anotaciones."""
    if not rows or len(rows) < SWING_K * 4:
        return []
    ts, o, h, l, c = _rows_to_ohlc(rows)
    n = len(rows)
    anotaciones = list(patrones_vela(rows))
    sw = _swings(h, l)
    anotaciones += _dobles(sw, ts, "alto", "doble_techo", "Doble techo")
    anotaciones += _dobles(sw, ts, "bajo", "doble_suelo", "Doble suelo")
    anotaciones += _hch(sw, ts, "alto", "hch", "Hombro-Cabeza-Hombro", invertido=False)
    anotaciones += _hch(sw, ts, "bajo", "hch_inv", "H-C-H invertido", invertido=True)
    anotaciones += _triangulos(sw, ts, h, l, n)
    anotaciones += _banderas(ts, o, h, l, c, n)
    return anotaciones
