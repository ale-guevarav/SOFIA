"""
CEROS DEL ESP32 - SOFIA (diagnóstico de alineación)

El "cero" de cada unidad son los grados que el ESP32 le suma a cada servo
(X, Y) para que la placa quede derecha en 0,0. Se miden con el
diagnóstico de alineación y se guardan en:

    Alignment/results/ceros_esp32.json

La GUI de visión (menú "Alineación"):
    - "Tomar ceros": mide las 16 unidades, guarda sus ceros y se los manda.
    - "Alinear": corrige una por una las que no están OK (de menor a mayor
      desalineación) y guarda sus ceros nuevos.
    - Cada vez que se conecta al ESP32 por BLE le manda los ceros guardados
      (si existe el archivo), en lugar de los de fábrica del firmware.

Los ceros están en grados DEL SERVO (lo que suma el firmware), no en los
ángulos de la app; corregir() hace la conversión.

SIGNOS POR UNIDAD: si un servo está montado o conectado al revés, corregir
lo empujaría para el lado contrario (cada "Alinear" lo deja peor). Alinear
lo detecta (el eje empeora en vez de mejorar), invierte el signo de ese eje
SOLO para esa unidad y lo guarda en el mismo JSON (signo_x / signo_y).
"""

import json
import os
from datetime import datetime

import rutas


NUM_UNIDADES = 16
CERO_MAX = 20.0                 # ° por eje (el ESP32 rechaza más)

# Servo -> ángulos de la app (theta1 + = derecha, theta2 + = arriba).
# Comprobado con el TRACKING del módulo real: +X del servo inclina la
# placa a la DERECHA y +Y la inclina hacia ABAJO. Si al alinear un eje
# empeora en vez de mejorar, cambia su signo aquí.
SERVO_X_POR_THETA1 = +1.0
SERVO_Y_POR_THETA2 = -1.0

# Qué tanto de la desalineación medida se corrige de una vez
# (1 = todo; si se pasa y "rebota", bájalo a 0.7)
GANANCIA = 1.0

# Lo más que se mueve el cero de una vez, por eje (si el diagnóstico se
# equivoca feo, el servo no se va hasta el tope; con otra pasada termina)
PASO_MAX = 8.0


def ceros_vacios():
    return [[0.0, 0.0] for _ in range(NUM_UNIDADES)]


def signos_vacios():
    return [[1, 1] for _ in range(NUM_UNIDADES)]


def _leer(ruta):
    try:
        with open(ruta, encoding="utf-8") as archivo:
            return json.load(archivo).get("unidades", [])
    except (OSError, ValueError, AttributeError):
        return []


def existe(ruta=rutas.CEROS_ESP32):
    return os.path.isfile(ruta)


def cargar(ruta=rutas.CEROS_ESP32):
    """Lista de 16 [x, y] (grados del servo). Sin archivo o dañado: ceros."""
    ceros = ceros_vacios()
    for unidad in _leer(ruta):
        try:
            numero = int(unidad["numero"])
            if 0 <= numero < NUM_UNIDADES:
                ceros[numero] = [float(unidad["x"]), float(unidad["y"])]
        except (ValueError, KeyError, TypeError):
            pass
    return ceros


def cargar_signos(ruta=rutas.CEROS_ESP32):
    """Lista de 16 [signo_x, signo_y] (1 o -1). Sin archivo: todos 1."""
    signos = signos_vacios()
    for unidad in _leer(ruta):
        try:
            numero = int(unidad["numero"])
            if 0 <= numero < NUM_UNIDADES:
                signos[numero] = [-1 if unidad.get("signo_x", 1) < 0 else 1,
                                  -1 if unidad.get("signo_y", 1) < 0 else 1]
        except (ValueError, KeyError, TypeError):
            pass
    return signos


def guardar(ceros, metodo="", ruta=rutas.CEROS_ESP32, signos=None):
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    datos = {
        "descripcion": "Ceros de los servos (grados que suma el ESP32 a X, Y). "
                       "Los mide la GUI de visión (menú Alineación).",
        "fecha": datetime.now().isoformat(timespec="seconds"),
        "metodo": metodo,
        "unidades": [
            {"numero": n, "x": round(x, 1), "y": round(y, 1),
             "signo_x": sx, "signo_y": sy}
            for n, ((x, y), (sx, sy)) in enumerate(zip(ceros, signos or signos_vacios()))
        ],
    }
    with open(ruta, "w", encoding="utf-8") as archivo:
        json.dump(datos, archivo, indent=2, ensure_ascii=False)
    return ruta


def corregir(cero, theta1, theta2, signos=(1, 1)):
    """
    Cero nuevo de una unidad a partir de su cero actual y de lo que midió
    el diagnóstico (theta1, theta2 en grados de la app). signos: los de
    esa unidad (cargar_signos), por si tiene un servo al revés.
    """
    def limitar(v):
        return max(-CERO_MAX, min(CERO_MAX, v))

    def paso(v):
        return max(-PASO_MAX, min(PASO_MAX, v))

    x = cero[0] - paso(GANANCIA * SERVO_X_POR_THETA1 * signos[0] * theta1)
    y = cero[1] - paso(GANANCIA * SERVO_Y_POR_THETA2 * signos[1] * theta2)
    return [round(limitar(x), 1), round(limitar(y), 1)]
