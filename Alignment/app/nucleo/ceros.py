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


def existe(ruta=rutas.CEROS_ESP32):
    return os.path.isfile(ruta)


def cargar(ruta=rutas.CEROS_ESP32):
    """Lista de 16 [x, y] (grados del servo). Sin archivo o dañado: ceros."""
    ceros = ceros_vacios()
    try:
        with open(ruta, encoding="utf-8") as archivo:
            datos = json.load(archivo)
        for unidad in datos.get("unidades", []):
            numero = int(unidad["numero"])
            if 0 <= numero < NUM_UNIDADES:
                ceros[numero] = [float(unidad["x"]), float(unidad["y"])]
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return ceros


def guardar(ceros, metodo="", ruta=rutas.CEROS_ESP32):
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    datos = {
        "descripcion": "Ceros de los servos (grados que suma el ESP32 a X, Y). "
                       "Los mide la GUI de visión (menú Alineación).",
        "fecha": datetime.now().isoformat(timespec="seconds"),
        "metodo": metodo,
        "unidades": [
            {"numero": n, "x": round(x, 1), "y": round(y, 1)}
            for n, (x, y) in enumerate(ceros)
        ],
    }
    with open(ruta, "w", encoding="utf-8") as archivo:
        json.dump(datos, archivo, indent=2, ensure_ascii=False)
    return ruta


def corregir(cero, theta1, theta2):
    """
    Cero nuevo de una unidad a partir de su cero actual y de lo que midió
    el diagnóstico (theta1, theta2 en grados de la app).
    """
    def limitar(v):
        return max(-CERO_MAX, min(CERO_MAX, v))

    def paso(v):
        return max(-PASO_MAX, min(PASO_MAX, v))

    x = cero[0] - paso(GANANCIA * SERVO_X_POR_THETA1 * theta1)
    y = cero[1] - paso(GANANCIA * SERVO_Y_POR_THETA2 * theta2)
    return [round(limitar(x), 1), round(limitar(y), 1)]
