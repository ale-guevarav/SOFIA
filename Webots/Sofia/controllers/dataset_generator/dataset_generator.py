"""
GENERADOR DEL DATASET - SOFIA (diagnóstico de alineación)

Supervisor de sofia_dataset.wbt. En cada muestra:

    1. Elige ángulos aleatorios para los 16 paneles: la mitad casi
       alineados (±3°) y la otra mitad en todo el rango (±27°).
    2. Cambia la escena al azar: luces, color del piso y posición e
       inclinación de la cámara (el marco ArUco lo endereza después).
    3. Espera a que los 16 paneles lleguen (panel_dataset avisa).
    4. Guarda la foto y los ángulos MEDIDOS por los sensores.

La muestra 0 es la REFERENCIA: todos los paneles en 0,0 con la escena
por defecto (la usa el método geométrico).

Salida (en la carpeta SOFIA):
    Diagnostico/datos/webots/<sesión>/
        imagenes/00000.jpg ...
        etiquetas.csv      una fila por panel y muestra
        escenas.csv        parámetros de la escena de cada muestra
        config.json        geometría y cámara usadas

Cuántas muestras: variable de entorno DATASET_MUESTRAS (por defecto 2000).
"""

import csv
import json
import math
import os
import random
import sys
import time
from datetime import datetime

from controller import Supervisor


# =============================================
# RUTAS Y GEOMETRÍA (Alignment/geometria.py)
# =============================================

def buscar_diagnostico():
    carpeta = os.path.dirname(os.path.abspath(__file__))
    for _ in range(7):
        candidato = os.path.join(carpeta, "Alignment")
        if os.path.isfile(os.path.join(candidato, "geometria.py")):
            return candidato
        carpeta = os.path.dirname(carpeta)
    print("[DATASET] ERROR: no se encontró la carpeta Alignment/ del repositorio")
    sys.exit(1)


DIAGNOSTICO = buscar_diagnostico()
sys.path.insert(0, DIAGNOSTICO)

import geometria as g  # noqa: E402


# =============================================
# CONFIGURACIÓN
# =============================================

MUESTRAS = int(os.environ.get("DATASET_MUESTRAS", "2000"))
SEMILLA = int(os.environ.get("DATASET_SEMILLA", "7"))

PROB_CASI_ALINEADO = 0.5      # paneles con ángulos chicos
CASI_ALINEADO_GRADOS = 3.0
RANGO_GRADOS = 27.0           # dentro del tope seguro de 27.5°
PROB_CERO = 0.05              # paneles exactamente en 0,0

# Cámara (posición por defecto y variación)
CAMARA_CENTRO = (g.CENTRO_X, g.CENTRO_Y, 1.35)
CAMARA_DESPLAZAMIENTO = 0.04  # m en x, y
CAMARA_ALTURA = (1.30, 1.40)  # m
CAMARA_INCLINACION = 4.0      # grados (alrededor de x e y)
CAMARA_GIRO = 8.0             # grados (alrededor de z)
# (con estos rangos el marco completo siempre queda dentro de la foto)

ESPERA_MAXIMA_S = 3.0         # tiempo de simulación para que lleguen los paneles
CALIDAD_JPG = 95


# =============================================
# ROTACIONES (matriz <-> eje-ángulo de Webots)
# =============================================

def rot_x(a):
    c, s = math.cos(a), math.sin(a)
    return [[1, 0, 0], [0, c, -s], [0, s, c]]


def rot_y(a):
    c, s = math.cos(a), math.sin(a)
    return [[c, 0, s], [0, 1, 0], [-s, 0, c]]


def rot_z(a):
    c, s = math.cos(a), math.sin(a)
    return [[c, -s, 0], [s, c, 0], [0, 0, 1]]


def mult(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def eje_angulo(m):
    """Matriz de rotación -> [x, y, z, ángulo] (campo rotation de Webots)."""

    traza = m[0][0] + m[1][1] + m[2][2]
    angulo = math.acos(max(-1.0, min(1.0, (traza - 1) / 2)))

    if angulo < 1e-9:
        return [0, 0, 1, 0]

    if abs(angulo - math.pi) < 1e-6:
        # 180°: el eje sale de la diagonal
        x = math.sqrt(max(0.0, (m[0][0] + 1) / 2))
        y = math.sqrt(max(0.0, (m[1][1] + 1) / 2))
        z = math.sqrt(max(0.0, (m[2][2] + 1) / 2))
        return [x, y, z, angulo]

    s = 2 * math.sin(angulo)
    return [(m[2][1] - m[1][2]) / s, (m[0][2] - m[2][0]) / s, (m[1][0] - m[0][1]) / s, angulo]


# Cámara mirando hacia abajo (como la cámara cenital)
ROTACION_BASE = rot_y(math.pi / 2)


# =============================================
# GENERADOR
# =============================================

class Generador:

    def __init__(self):

        self.robot = Supervisor()
        self.paso = int(self.robot.getBasicTimeStep())
        self.rng = random.Random(SEMILLA)

        self.camara = self.robot.getDevice("camara")
        self.camara.enable(self.paso)

        def nodo(nombre):
            n = self.robot.getFromDef(nombre)
            if n is None:
                print(f"[DATASET] ERROR: no existe DEF {nombre} en el mundo")
                sys.exit(1)
            return n

        generador = nodo("GENERADOR")
        self.cam_traslacion = generador.getField("translation")
        self.cam_rotacion = generador.getField("rotation")

        self.luz_dir = nodo("LUZ_DIRECCIONAL")
        self.luz_punt = nodo("LUZ_PUNTUAL")
        self.suelo = nodo("SUELO_APARIENCIA")

        self.reportes = {
            indice: nodo(f"PANEL_{fila}_{columna}").getField("customData")
            for indice, fila, columna, _ in g.paneles()
        }

        # -----------------------------
        # CARPETA DE SALIDA
        # -----------------------------

        sesion = datetime.now().strftime("sesion_%Y%m%d_%H%M%S")
        self.salida = os.path.join(DIAGNOSTICO, "datos", "webots", sesion)
        os.makedirs(os.path.join(self.salida, "imagenes"), exist_ok=True)

        self._guardar_config()

        self.etiquetas = open(os.path.join(self.salida, "etiquetas.csv"), "w", newline="")
        self.escribir_etiqueta = csv.writer(self.etiquetas)
        self.escribir_etiqueta.writerow([
            "muestra", "imagen", "panel", "fila", "columna",
            "theta1_deg", "theta2_deg", "theta1_cmd_deg", "theta2_cmd_deg",
            "magnitud_deg", "porcentaje", "estado",
        ])

        self.escenas = open(os.path.join(self.salida, "escenas.csv"), "w", newline="")
        self.escribir_escena = csv.writer(self.escenas)
        self.escribir_escena.writerow([
            "muestra", "cam_x", "cam_y", "cam_z", "cam_incl_x_deg", "cam_incl_y_deg",
            "cam_giro_deg", "luz_dir_intensidad", "luz_punt_intensidad", "suelo_gris",
        ])

        print(f"[DATASET] {MUESTRAS} muestras -> {self.salida}")


    def _guardar_config(self):
        config = {
            "muestras": MUESTRAS,
            "semilla": SEMILLA,
            "camara": {
                "resolucion": [self.camara.getWidth(), self.camara.getHeight()],
                "fov_rad": self.camara.getFov(),
            },
            "geometria": {
                nombre: getattr(g, nombre) for nombre in dir(g)
                if nombre.isupper() and isinstance(getattr(g, nombre), (int, float, str, list, dict))
            },
        }
        with open(os.path.join(self.salida, "config.json"), "w", encoding="utf-8") as archivo:
            json.dump(config, archivo, indent=2, ensure_ascii=False, default=str)


    # =============================================
    # ALEATORIZACIÓN
    # =============================================

    def angulos_aleatorios(self):
        """32 ángulos en grados: (theta1, theta2) de cada panel."""

        angulos = []

        for _ in range(16):
            sorteo = self.rng.random()

            if sorteo < PROB_CERO:
                par = (0.0, 0.0)
            elif sorteo < PROB_CERO + PROB_CASI_ALINEADO:
                par = (self.rng.uniform(-CASI_ALINEADO_GRADOS, CASI_ALINEADO_GRADOS),
                       self.rng.uniform(-CASI_ALINEADO_GRADOS, CASI_ALINEADO_GRADOS))
            else:
                par = (self.rng.uniform(-RANGO_GRADOS, RANGO_GRADOS),
                       self.rng.uniform(-RANGO_GRADOS, RANGO_GRADOS))

            angulos.extend(par)

        return angulos


    def escena(self, por_defecto=False):
        """Cambia cámara, luces y piso. Regresa los parámetros usados."""

        r = self.rng

        if por_defecto:
            x, y, z = CAMARA_CENTRO
            incl_x = incl_y = giro = 0.0
            luz_dir, luz_punt, gris = 1.0, 2.0, 0.25
            direccion = [-1, -1, -1]
            ubicacion = [0.3, 0.3, 0.5]
        else:
            x = CAMARA_CENTRO[0] + r.uniform(-CAMARA_DESPLAZAMIENTO, CAMARA_DESPLAZAMIENTO)
            y = CAMARA_CENTRO[1] + r.uniform(-CAMARA_DESPLAZAMIENTO, CAMARA_DESPLAZAMIENTO)
            z = r.uniform(*CAMARA_ALTURA)
            incl_x = r.uniform(-CAMARA_INCLINACION, CAMARA_INCLINACION)
            incl_y = r.uniform(-CAMARA_INCLINACION, CAMARA_INCLINACION)
            giro = r.uniform(-CAMARA_GIRO, CAMARA_GIRO)
            luz_dir = r.uniform(0.3, 1.5)
            luz_punt = r.uniform(0.5, 3.0)
            gris = r.uniform(0.10, 0.45)
            direccion = [r.uniform(-1, 1), r.uniform(-1, 1), -r.uniform(0.5, 1.5)]
            ubicacion = [r.uniform(-0.5, 0.5), r.uniform(-0.5, 0.5), r.uniform(0.4, 1.0)]

        rotacion = mult(
            rot_z(math.radians(giro)),
            mult(rot_x(math.radians(incl_x)), mult(rot_y(math.radians(incl_y)), ROTACION_BASE)),
        )

        self.cam_traslacion.setSFVec3f([x, y, z])
        self.cam_rotacion.setSFRotation(eje_angulo(rotacion))

        self.luz_dir.getField("intensity").setSFFloat(luz_dir)
        self.luz_dir.getField("direction").setSFVec3f(direccion)
        self.luz_punt.getField("intensity").setSFFloat(luz_punt)
        self.luz_punt.getField("location").setSFVec3f(ubicacion)
        self.suelo.getField("baseColor").setSFColor([gris, gris, gris * 1.05])

        return [x, y, z, incl_x, incl_y, giro, luz_dir, luz_punt, gris]


    # =============================================
    # UNA MUESTRA
    # =============================================

    def esperar_paneles(self, muestra):
        """Avanza la simulación hasta que los 16 paneles reportan listo."""

        limite = self.robot.getTime() + ESPERA_MAXIMA_S

        while self.robot.step(self.paso) != -1:

            medidos = {}

            for indice, campo in self.reportes.items():
                partes = campo.getSFString().split()
                if (len(partes) == 5 and partes[0] == "P"
                        and int(partes[1]) == muestra and partes[4] == "1"):
                    medidos[indice] = (float(partes[2]), float(partes[3]))

            if len(medidos) == 16:
                return medidos

            if self.robot.getTime() > limite:
                print(f"[DATASET] Muestra {muestra}: solo {len(medidos)}/16 paneles "
                      "llegaron a tiempo; se descarta")
                return None

        return None


    def muestra(self, numero):

        referencia = numero == 0
        angulos = [0.0] * 32 if referencia else self.angulos_aleatorios()
        parametros = self.escena(por_defecto=referencia)

        orden = "S %d %s" % (numero, " ".join(f"{math.radians(a):.6f}" for a in angulos))
        self.robot.setCustomData(orden)

        medidos = self.esperar_paneles(numero)
        if medidos is None:
            return False

        # Un paso más para que la cámara tenga la imagen ya con todo quieto
        self.robot.step(self.paso)

        nombre = f"{numero:05d}.jpg"
        ruta = os.path.join(self.salida, "imagenes", nombre)

        if self.camara.saveImage(ruta, CALIDAD_JPG) != 0:
            print(f"[DATASET] ERROR al guardar {ruta}")
            return False

        if referencia:
            self.camara.saveImage(os.path.join(self.salida, "referencia.png"), 100)

        for indice, fila, columna, _ in g.paneles():
            t1 = math.degrees(medidos[indice][0])
            t2 = math.degrees(medidos[indice][1])
            magnitud, porcentaje, estado = g.desalineacion(t1, t2)

            self.escribir_etiqueta.writerow([
                numero, nombre, indice, fila, columna,
                f"{t1:.4f}", f"{t2:.4f}",
                f"{angulos[2 * indice]:.4f}", f"{angulos[2 * indice + 1]:.4f}",
                f"{magnitud:.4f}", f"{porcentaje:.2f}", estado,
            ])

        self.escribir_escena.writerow([numero] + [f"{v:.4f}" for v in parametros])
        return True


    # =============================================
    # BUCLE
    # =============================================

    def run(self):

        try:
            self.robot.simulationSetMode(Supervisor.SIMULATION_MODE_FAST)
        except Exception:
            pass

        # Dejar que los paneles arranquen
        for _ in range(10):
            self.robot.step(self.paso)

        inicio = time.time()
        guardadas = 0

        for numero in range(MUESTRAS):

            if self.muestra(numero):
                guardadas += 1

            if numero % 50 == 0 or numero == MUESTRAS - 1:
                self.etiquetas.flush()
                self.escenas.flush()
                transcurrido = time.time() - inicio
                print(f"[DATASET] {numero + 1}/{MUESTRAS} "
                      f"({guardadas} guardadas, {transcurrido:.0f} s)")

        self.etiquetas.close()
        self.escenas.close()

        print(f"[DATASET] Listo: {guardadas} imágenes en {self.salida}")

        try:
            self.robot.simulationSetMode(Supervisor.SIMULATION_MODE_PAUSE)
        except Exception:
            pass


if __name__ == "__main__":
    Generador().run()
