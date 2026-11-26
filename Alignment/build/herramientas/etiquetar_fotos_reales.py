"""
ETIQUETAR FOTOS REALES SIN CSV - SOFIA (diagnóstico de alineación)

Arma una sesión para afinar el modelo (entrenar.py --desde) a partir de
fotos REALES del módulo cuando NO se tienen los ángulos (se perdió el CSV
del Monitor Serie). Los ángulos se ESTIMAN de las mismas fotos:

    1. Cada foto se endereza con los 4 ArUco (igual que la app).
    2. Se mide dónde quedó cada placa (comparación de plantillas contra la
       mediana de esa placa en todas las fotos, con precisión subpíxel).
    3. Se quita el movimiento de la cámara de cada foto (un ajuste afín
       robusto con las placas que no se movieron).
    4. Lo que queda es cuánto se corrió cada placa respecto a su posición
       de reposo -> ángulo con la cinemática del panel (brazo de 37 mm),
       igual que el método geométrico.
    5. Las placas que se movieron menos de UMBRAL_QUIETA se etiquetan 0,0
       (ese movimiento es ruido de la medición).

SUPOSICIONES (por eso son etiquetas aproximadas):
    - La posición de REPOSO de cada placa (la mediana de todas las fotos)
      es 0,0: sirve si en la mayoría de las fotos cada unidad estaba en 0,0
      (como en la prueba 'd' de sofia_desalineo_azar.ino) y si el módulo
      estaba alineado. Si una unidad estaba chueca en reposo, su chueco
      queda como "0".
    - El brazo eje -> cara de la placa es de 37 mm (geometria.BRAZO_GDL1/2).
    - Ruido de la medición: ~1° (fotos de WhatsApp, cámara en mano).

Con los ángulos verdaderos (línea CSV del Monitor Serie) siempre es mejor.

Sale en Alignment/build/datos/reales/<nombre>/ (no en datos/webots, para
que no se tome como "la última sesión de Webots"):
    imagenes/       fotos renombradas 00000.jpg ...
    recortes/       recortes de 128x128 (como los hace la app)
    revision/       fotos enderezadas con una flecha por placa (ángulo estimado x8):
                    revísalas para ver si las etiquetas tienen sentido
    recortes.csv    lo que lee entrenar.py
    etiquetas.csv   ángulo estimado, medido y calidad de cada placa
    resumen.json

Uso (desde la carpeta SOFIA):
    python Alignment/build/herramientas/etiquetar_fotos_reales.py <carpeta con fotos>
    python Alignment/build/herramientas/etiquetar_fotos_reales.py <carpeta> --nombre sesion_real_20261125
"""

import argparse
import csv
import glob
import json
import os
import re
import shutil
import sys

import cv2
import numpy as np

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(AQUI)), "app", "nucleo"))

import geometria as g  # noqa: E402
import preprocesamiento as pp  # noqa: E402
import rutas  # noqa: E402


UMBRAL_QUIETA = 2.5         # ° : menos que esto se etiqueta 0,0
CALIDAD_MIN = 0.80          # correlación mínima para confiar en la medición
BUSQUEDA_PX = 62            # mitad de la ventana de búsqueda (px = mm)
PLANTILLA_PX = 32           # mitad de la plantilla
VAL_FOTOS, TEST_FOTOS = 0.15, 0.15
EXTENSIONES = (".jpg", ".jpeg", ".png")


def ordenar(rutas_fotos):
    """Por nombre, respetando números (WhatsApp: '... 5.18.12 PM (3).jpeg')."""
    def clave(ruta):
        return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", os.path.basename(ruta))]
    return sorted(rutas_fotos, key=clave)


def parche(imagen, cx, cy, mitad):
    matriz = np.float32([[1, 0, mitad - cx], [0, 1, mitad - cy]])
    return cv2.warpAffine(imagen, matriz, (2 * mitad, 2 * mitad), flags=cv2.INTER_LINEAR)


def pico_subpixel(respuesta):
    _, valor, _, (x, y) = cv2.minMaxLoc(respuesta)

    def parabola(a, b, c):
        d = a - 2 * b + c
        return 0.0 if d == 0 else 0.5 * (a - c) / d

    dx = parabola(*respuesta[y, x - 1:x + 2]) if 0 < x < respuesta.shape[1] - 1 else 0.0
    dy = parabola(*respuesta[y - 1:y + 2, x]) if 0 < y < respuesta.shape[0] - 1 else 0.0
    corrimiento = BUSQUEDA_PX - PLANTILLA_PX
    return x + dx - corrimiento, y + dy - corrimiento, valor


def medir(enderezadas, centros):
    """Corrimiento (px) de cada placa en cada foto y la calidad de la medición."""
    n = len(enderezadas)
    corr = np.zeros((n, 16, 2))
    calidad = np.zeros((n, 16))
    for paso in range(3):
        # Plantilla: mediana de la placa en todas las fotos (centrada donde se encontró)
        plantillas = [
            np.median(np.stack([parche(e, *(centros[u] + corr[i, u]), PLANTILLA_PX)
                                for i, e in enumerate(enderezadas)]), 0).astype(np.float32)
            for u in range(16)
        ]
        for i, e in enumerate(enderezadas):
            for u in range(16):
                ventana = parche(e, *centros[u], BUSQUEDA_PX)
                dx, dy, v = pico_subpixel(cv2.matchTemplate(ventana, plantillas[u], cv2.TM_CCOEFF_NORMED))
                corr[i, u] = (dx, dy)
                calidad[i, u] = v
    return corr, calidad


def quitar_camara(corr, centros):
    """Separa: movimiento de la cámara (afín por foto) + reposo de cada placa + inclinación."""
    n = len(corr)
    X = np.c_[(centros - centros.mean(0)) / 100.0, np.ones(16)]
    reposo = np.median(corr, 0)
    camara = np.zeros_like(corr)
    for _ in range(10):
        for i in range(n):
            y = corr[i] - reposo
            usar = np.ones(16, bool)
            for _ in range(4):        # robusto: sin las placas que se movieron
                A, *_ = np.linalg.lstsq(X[usar], y[usar], rcond=None)
                residuo = np.linalg.norm(y - X @ A, axis=1)
                usar = residuo < max(1.5, np.percentile(residuo, 70))
            camara[i] = X @ A
        camara -= camara.mean(0, keepdims=True)
        reposo = np.median(corr - camara, 0)
    return corr - camara - reposo


def a_angulos(inclinacion_px):
    du = inclinacion_px[..., 0] / g.PIXELES_POR_METRO
    dv = -inclinacion_px[..., 1] / g.PIXELES_POR_METRO     # las filas crecen hacia abajo
    theta2 = np.degrees(np.arcsin(np.clip(dv / g.BRAZO_GDL2, -1, 1)))
    theta1 = np.degrees(np.arcsin(np.clip(du / (g.BRAZO_GDL1 * np.cos(np.radians(theta2))), -1, 1)))
    return theta1, theta2


def main():
    parser = argparse.ArgumentParser(description="Etiqueta fotos reales sin CSV (ángulos estimados)")
    parser.add_argument("carpeta", help="carpeta con las fotos del módulo")
    parser.add_argument("--nombre", help="nombre de la sesión (por defecto sesion_real_<carpeta>)")
    parser.add_argument("--umbral", type=float, default=UMBRAL_QUIETA,
                        help=f"° por debajo de los cuales la placa se toma como 0,0 ({UMBRAL_QUIETA})")
    args = parser.parse_args()

    fotos = ordenar([f for f in glob.glob(os.path.join(args.carpeta, "*"))
                     if f.lower().endswith(EXTENSIONES)])
    if len(fotos) < 10:
        sys.exit(f"Hay {len(fotos)} fotos: se necesitan al menos 10 (la mediana de reposo sale de todas)")

    nombre = args.nombre or f"sesion_real_{os.path.basename(os.path.normpath(args.carpeta))}"
    salida = os.path.join(rutas.BUILD, "datos", "reales", nombre)
    shutil.rmtree(salida, ignore_errors=True)
    for sub in ("imagenes", "recortes", "revision"):
        os.makedirs(os.path.join(salida, sub))

    # 1. Enderezar
    usadas, enderezadas, recortes, vistas = [], [], [], []
    for ruta in fotos:
        imagen = cv2.imread(ruta)
        r = pp.procesar(imagen) if imagen is not None else None
        if r is None or not r.ok:
            print(f"  descartada (no se ven los 4 ArUco): {os.path.basename(ruta)}")
            continue
        i = len(usadas)
        destino = os.path.join(salida, "imagenes", f"{i:05d}.jpg")
        if ruta.lower().endswith((".jpg", ".jpeg")):
            shutil.copyfile(ruta, destino)          # sin volver a comprimir
        else:
            cv2.imwrite(destino, imagen, [cv2.IMWRITE_JPEG_QUALITY, 95])
        gris = r.enderezada if r.enderezada.ndim == 2 else cv2.cvtColor(r.enderezada, cv2.COLOR_BGR2GRAY)
        usadas.append(ruta)
        enderezadas.append(gris.astype(np.float32))
        recortes.append(r.recortes)
        vistas.append(pp.dibujar_guia(r.enderezada))
    print(f"{len(usadas)} de {len(fotos)} fotos con los 4 ArUco")

    # 2-4. Medir, quitar la cámara, ángulos
    centros = np.array([pp.centro_panel_px(f, c) for _, f, c, _ in g.paneles()])
    corr, calidad = medir(enderezadas, centros)
    theta1, theta2 = a_angulos(quitar_camara(corr, centros))
    magnitud = np.hypot(theta1, theta2)

    # Revisión: flecha = inclinación estimada (x8), roja si cuenta como inclinada
    for i, vista in enumerate(vistas):
        vista = vista if vista.ndim == 3 else cv2.cvtColor(vista, cv2.COLOR_GRAY2BGR)
        for u, fila, columna, _ in g.paneles():
            x, y = centros[u]
            color = (0, 0, 255) if magnitud[i, u] >= args.umbral else (0, 200, 0)
            punta = (int(x + theta1[i, u] * 8), int(y - theta2[i, u] * 8))
            cv2.arrowedLine(vista, (int(x), int(y)), punta, color, 3, tipLength=0.3)
            cv2.putText(vista, f"{g.numero_panel(fila, columna)}: {magnitud[i, u]:.1f}",
                        (int(x) - 35, int(y) + 70), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
        cv2.imwrite(os.path.join(salida, "revision", f"{i:05d}.jpg"), vista, [cv2.IMWRITE_JPEG_QUALITY, 85])

    # División por foto
    rng = np.random.default_rng(2026)
    orden = rng.permutation(len(usadas))
    n_test = max(1, round(TEST_FOTOS * len(usadas)))
    n_val = max(1, round(VAL_FOTOS * len(usadas)))
    conjunto = {}
    for j, i in enumerate(orden):
        conjunto[i] = "test" if j < n_test else ("val" if j < n_test + n_val else "train")

    # 5. Guardar
    filas, etiquetas, descartados = [], [], 0
    for i in range(len(usadas)):
        for u, fila, columna, _ in g.paneles():
            if calidad[i, u] < CALIDAD_MIN:
                descartados += 1
                continue
            t1, t2 = (0.0, 0.0) if magnitud[i, u] < args.umbral else (float(theta1[i, u]), float(theta2[i, u]))
            mag, porcentaje, estado = g.desalineacion(t1, t2)
            archivo = f"{i:05d}_{u:02d}.png"
            cv2.imwrite(os.path.join(salida, "recortes", archivo), recortes[i][u])
            filas.append({
                "archivo": archivo, "muestra": i, "panel": u, "fila": fila, "columna": columna,
                "theta1_deg": f"{t1:.4f}", "theta2_deg": f"{t2:.4f}", "magnitud_deg": f"{mag:.4f}",
                "porcentaje": f"{porcentaje:.2f}", "estado": estado, "conjunto": conjunto[i],
            })
            etiquetas.append({
                "muestra": i, "imagen": f"{i:05d}.jpg", "panel": u, "fila": fila, "columna": columna,
                "numero_app": g.numero_panel(fila, columna),
                "theta1_deg": f"{t1:.4f}", "theta2_deg": f"{t2:.4f}",
                "medido_theta1": f"{theta1[i, u]:.3f}", "medido_theta2": f"{theta2[i, u]:.3f}",
                "calidad": f"{calidad[i, u]:.3f}", "foto_original": os.path.basename(usadas[i]),
            })

    for archivo, datos in (("recortes.csv", filas), ("etiquetas.csv", etiquetas)):
        with open(os.path.join(salida, archivo), "w", newline="") as f:
            escritor = csv.DictWriter(f, fieldnames=list(datos[0]))
            escritor.writeheader()
            escritor.writerows(datos)

    quietas = np.sort(magnitud, 1)[:, :10]
    resumen = {
        "fotos": len(usadas),
        "recortes": len(filas),
        "conjuntos": {c: sum(f["conjunto"] == c for f in filas) for c in ("train", "val", "test")},
        "inclinados": sum(float(f["magnitud_deg"]) > 0 for f in filas),
        "descartados_por_calidad": descartados,
        "ruido_estimado_deg": round(float(np.median(quietas)), 2),
        "umbral_quieta_deg": args.umbral,
        "nota": "Ángulos ESTIMADOS de las fotos (sin CSV). Ver el encabezado de etiquetar_fotos_reales.py",
    }
    with open(os.path.join(salida, "resumen.json"), "w") as f:
        json.dump(resumen, f, indent=2, ensure_ascii=False)

    print(json.dumps(resumen, indent=2, ensure_ascii=False))
    print(f"\nSesión: {salida}")
    print("Afinar:  python Alignment/build/entrenar.py --desde Alignment/results/modelo/cnn.pt "
          f"{os.path.relpath(salida, rutas.RAIZ)} --epocas 20 --lote 64")


if __name__ == "__main__":
    main()
