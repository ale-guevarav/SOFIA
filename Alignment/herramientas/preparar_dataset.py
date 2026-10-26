"""
PREPARAR EL DATASET - SOFIA (diagnóstico de alineación)

Toma una sesión generada en Webots (Alignment/datos/webots/<sesión>/)
y produce lo que usan los modelos:

    <sesión>/recortes/00012_05.png   recorte del hexágono 5 de la foto 12
    <sesión>/recortes.csv            una fila por recorte, con sus ángulos
                                     y a qué conjunto pertenece (train/val/test)
    <sesión>/referencia_enderezada.png   foto 0 (todo en 0,0) ya enderezada
    <sesión>/revision/               algunas fotos enderezadas con la guía
                                     dibujada, para revisarlas a ojo
    <sesión>/descartadas.txt         fotos donde no se vieron los 4 marcadores

La división train / val / test (70 / 15 / 15 %) es POR FOTO: los 16
recortes de una misma foto quedan juntos, para no hacer trampa.

Uso (desde la carpeta SOFIA, con el entorno activado):
    python Alignment/herramientas/preparar_dataset.py                (última sesión)
    python Alignment/herramientas/preparar_dataset.py <carpeta de la sesión>
"""

import argparse
import csv
import glob
import os
import random
import sys
import time

import cv2

AQUI = os.path.dirname(os.path.abspath(__file__))
ALIGNMENT = os.path.dirname(AQUI)
sys.path.insert(0, ALIGNMENT)

import geometria as g  # noqa: E402
import preprocesamiento as pp  # noqa: E402


PROPORCION = {"train": 0.70, "val": 0.15, "test": 0.15}
SEMILLA_DIVISION = 2026
FOTOS_REVISION = 8


def ultima_sesion():
    sesiones = sorted(glob.glob(os.path.join(ALIGNMENT, "datos", "webots", "sesion_*")))
    if not sesiones:
        sys.exit("No hay sesiones en Alignment/datos/webots/. Genera una en Webots primero.")
    return sesiones[-1]


def dividir(muestras):
    """Asigna cada foto (salvo la referencia) a train, val o test."""

    fotos = sorted(m for m in muestras if m != 0)
    random.Random(SEMILLA_DIVISION).shuffle(fotos)

    n = len(fotos)
    n_train = round(n * PROPORCION["train"])
    n_val = round(n * PROPORCION["val"])

    conjunto = {0: "referencia"}
    for i, m in enumerate(fotos):
        conjunto[m] = "train" if i < n_train else "val" if i < n_train + n_val else "test"

    return conjunto


def main():

    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("sesion", nargs="?", help="carpeta de la sesión (por defecto, la última)")
    args = parser.parse_args()

    sesion = os.path.abspath(args.sesion) if args.sesion else ultima_sesion()
    print(f"Sesión: {sesion}")

    # -----------------------------
    # ETIQUETAS (agrupadas por foto)
    # -----------------------------

    with open(os.path.join(sesion, "etiquetas.csv"), newline="") as archivo:
        etiquetas = list(csv.DictReader(archivo))

    por_foto = {}
    for fila in etiquetas:
        por_foto.setdefault(int(fila["muestra"]), {})[int(fila["panel"])] = fila

    conjunto = dividir(por_foto)

    carpeta_recortes = os.path.join(sesion, "recortes")
    carpeta_revision = os.path.join(sesion, "revision")
    os.makedirs(carpeta_recortes, exist_ok=True)
    os.makedirs(carpeta_revision, exist_ok=True)

    # -----------------------------
    # PROCESAR CADA FOTO
    # -----------------------------

    salida = []
    descartadas = []
    inicio = time.time()

    for k, (muestra, paneles) in enumerate(sorted(por_foto.items())):

        nombre = next(iter(paneles.values()))["imagen"]
        imagen = cv2.imread(os.path.join(sesion, "imagenes", nombre))

        if imagen is None:
            descartadas.append(f"{nombre}: no se pudo leer")
            continue

        resultado = pp.procesar(imagen)

        if not resultado.ok:
            descartadas.append(f"{nombre}: {resultado.motivo}")
            continue

        if muestra == 0:
            cv2.imwrite(os.path.join(sesion, "referencia_enderezada.png"), resultado.enderezada)

        if k < FOTOS_REVISION:
            cv2.imwrite(os.path.join(carpeta_revision, nombre.replace(".jpg", ".png")),
                        pp.dibujar_guia(resultado.enderezada))

        for panel, recorte in enumerate(resultado.recortes):
            fila = paneles[panel]
            archivo = f"{muestra:05d}_{panel:02d}.png"
            cv2.imwrite(os.path.join(carpeta_recortes, archivo), recorte)

            t1, t2 = float(fila["theta1_deg"]), float(fila["theta2_deg"])
            magnitud, porcentaje, estado = g.desalineacion(t1, t2)

            salida.append({
                "archivo": archivo,
                "muestra": muestra,
                "panel": panel,
                "fila": fila["fila"],
                "columna": fila["columna"],
                "theta1_deg": f"{t1:.4f}",
                "theta2_deg": f"{t2:.4f}",
                "magnitud_deg": f"{magnitud:.4f}",
                "porcentaje": f"{porcentaje:.2f}",
                "estado": estado,
                "conjunto": conjunto[muestra],
            })

        if (k + 1) % 200 == 0:
            print(f"  {k + 1}/{len(por_foto)} fotos ({time.time() - inicio:.0f} s)")

    # -----------------------------
    # GUARDAR
    # -----------------------------

    with open(os.path.join(sesion, "recortes.csv"), "w", newline="") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=list(salida[0]))
        escritor.writeheader()
        escritor.writerows(salida)

    with open(os.path.join(sesion, "descartadas.txt"), "w") as archivo:
        archivo.write("\n".join(descartadas))

    resumen = {}
    for fila in salida:
        clave = (fila["conjunto"], fila["estado"])
        resumen[clave] = resumen.get(clave, 0) + 1

    print(f"\nListo en {time.time() - inicio:.0f} s: {len(salida)} recortes de "
          f"{len(por_foto) - len(descartadas)} fotos ({len(descartadas)} descartadas)")

    for nombre_conjunto in ("train", "val", "test", "referencia"):
        partes = [f"{e} {resumen.get((nombre_conjunto, e), 0)}" for e in ("OK", "REVISAR", "DESALINEADO")]
        total = sum(resumen.get((nombre_conjunto, e), 0) for e in ("OK", "REVISAR", "DESALINEADO"))
        print(f"  {nombre_conjunto:<10} {total:>6} recortes   ({', '.join(partes)})")

    print(f"\nRevisa a ojo las fotos de {carpeta_revision}")


if __name__ == "__main__":
    main()
