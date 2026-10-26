"""
EVALUAR EL MÉTODO GEOMÉTRICO - SOFIA (diagnóstico de alineación)

Corre el método geométrico (línea base) sobre las fotos de una sesión
ya preparada (preparar_dataset.py) y guarda métricas, gráficas y reporte en:

    Alignment/resultados/geometrico_<sesión>_<conjunto>/

La foto 0 (todo en 0,0) se usa como referencia del cero.

Uso (desde la carpeta SOFIA):
    python Alignment/geometrico/evaluar_geometrico.py                 (última sesión, test)
    python Alignment/geometrico/evaluar_geometrico.py --conjunto val
    python Alignment/geometrico/evaluar_geometrico.py <carpeta de la sesión> --conjunto todos
"""

import argparse
import csv
import os
import sys
import time

import cv2
import numpy as np

AQUI = os.path.dirname(os.path.abspath(__file__))
ALIGNMENT = os.path.dirname(AQUI)
sys.path.insert(0, os.path.join(ALIGNMENT, "herramientas"))
sys.path.insert(0, ALIGNMENT)
sys.path.insert(0, AQUI)

import evaluacion  # noqa: E402
import preprocesamiento as pp  # noqa: E402
from metodo_geometrico import MetodoGeometrico  # noqa: E402
from preparar_dataset import ultima_sesion  # noqa: E402


def main():

    parser = argparse.ArgumentParser(description="Evalúa el método geométrico")
    parser.add_argument("sesion", nargs="?", help="carpeta de la sesión (por defecto, la última)")
    parser.add_argument("--conjunto", default="test", choices=["train", "val", "test", "todos"])
    args = parser.parse_args()

    sesion = os.path.abspath(args.sesion) if args.sesion else ultima_sesion()
    ruta_csv = os.path.join(sesion, "recortes.csv")

    if not os.path.isfile(ruta_csv):
        sys.exit(f"Falta {ruta_csv}: corre primero preparar_dataset.py")

    with open(ruta_csv, newline="") as archivo:
        filas = list(csv.DictReader(archivo))

    # Ángulos reales por foto
    por_foto = {}
    for f in filas:
        if args.conjunto != "todos" and f["conjunto"] != args.conjunto:
            continue
        if f["conjunto"] == "referencia":
            continue
        por_foto.setdefault(int(f["muestra"]), np.zeros((16, 2)))[int(f["panel"])] = (
            float(f["theta1_deg"]), float(f["theta2_deg"]))

    # Referencia (foto 0)
    referencia = pp.procesar(cv2.imread(os.path.join(sesion, "imagenes", "00000.jpg")))
    if not referencia.ok:
        sys.exit("No se pudo procesar la foto de referencia 00000.jpg")
    metodo = MetodoGeometrico(referencia.enderezada)

    print(f"Sesión {os.path.basename(sesion)} · conjunto {args.conjunto} · {len(por_foto)} fotos")

    reales, estimados, tiempos = [], [], []

    for k, (muestra, angulos) in enumerate(sorted(por_foto.items())):
        imagen = cv2.imread(os.path.join(sesion, "imagenes", f"{muestra:05d}.jpg"))

        inicio = time.perf_counter()
        resultado = pp.procesar(imagen)
        if not resultado.ok:
            print(f"  foto {muestra}: {resultado.motivo}")
            continue
        theta1, theta2 = metodo.estimar(resultado.enderezada)
        tiempos.append((time.perf_counter() - inicio) * 1000)

        reales.append(angulos)
        estimados.append(np.c_[theta1, theta2])

        if (k + 1) % 100 == 0:
            print(f"  {k + 1}/{len(por_foto)}")

    reales = np.concatenate(reales)
    estimados = np.concatenate(estimados)

    metricas = evaluacion.calcular(reales, estimados, tiempos)

    nombre = f"geometrico_{os.path.basename(sesion)}_{args.conjunto}"
    carpeta = os.path.join(ALIGNMENT, "resultados", nombre)
    titulo = "Método geométrico"

    evaluacion.graficas(reales, estimados, carpeta, titulo)
    evaluacion.guardar(metricas, carpeta, titulo, {
        "sesión": os.path.basename(sesion),
        "conjunto": args.conjunto,
        "fotos": len(tiempos),
    })

    c = metricas["clasificacion"]
    print(f"\nMAE global {metricas['mae_global']}° · RMSE {metricas['rmse_global']}° · "
          f"θ1 {metricas['theta1']['mae']}° · θ2 {metricas['theta2']['mae']}°")
    print("MAE por rango: " + ", ".join(
        f"{k}°: {v['mae']}" for k, v in metricas["por_rango"].items()))
    print(f"Estados: exactitud {c['exactitud']} · F1 macro {c['f1_macro']} · "
          f"atención: precisión {c['atencion']['precision']}, recall {c['atencion']['recall']}")
    print(f"Tiempo: {metricas['tiempo_ms_por_foto']['promedio']} ms por foto")
    print(f"\nReporte: {carpeta}")


if __name__ == "__main__":
    main()
