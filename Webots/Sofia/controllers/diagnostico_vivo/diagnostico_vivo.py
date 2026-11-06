"""
DIAGNÓSTICO EN VIVO - SOFIA (Webots)

Supervisor de sofia_diagnostico_vivo.wbt (el mismo mundo del dataset).
En lugar de generar fotos, conecta la cámara con la app de diagnóstico
para probarla en vivo, sin el módulo físico:

    app (Alignment/app) <──TCP :5557──> este controlador ──> 16 paneles (panel_dataset)

    - Manda la imagen de la cámara (~5 por segundo) y el estado de los
      paneles: ángulos MEDIDOS por sus sensores (la "verdad").
    - Recibe órdenes de la app: todo a 0,0, desalinear al azar, mover un
      panel, cambiar la escena (cámara y luces) al azar o regresarla.

PROTOCOLO
---------
App -> Webots: una orden JSON por línea, por ejemplo
    {"orden": "cero"}
    {"orden": "azar", "paneles": 3, "grados": 10}
    {"orden": "panel", "panel": 5, "theta1": 8.0, "theta2": -3.5}
    {"orden": "escena", "azar": true}

Webots -> App: paquetes  tipo (4 bytes) | largo u32 | datos
    "ESTA"  JSON: version, quieto, medidos [[θ1, θ2] x16] en grados, comandados, escena
    "IMGN"  ancho u16 | alto u16 | version u32 | píxeles BGRA

`version` cambia con cada orden. Una imagen trae la versión solo si se
tomó con los paneles ya quietos (si no, trae 0): así la app sabe qué
imagen corresponde a qué ángulos medidos.

Solo usa la biblioteca estándar de Python.
"""

import json
import math
import os
import random
import socket
import struct
import sys

from controller import Supervisor

# Funciones de escena del generador del dataset (misma cámara y luces)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dataset_generator"))

import dataset_generator as dg  # noqa: E402  (también carga geometria de Alignment/app/nucleo)

g = dg.g

HOST = "127.0.0.1"
PORT = 5557

PERIODO_IMAGEN_S = 0.2        # ~5 imágenes por segundo
PERIODO_ESTADO_S = 0.5
PASOS_QUIETO = 3              # pasos con los paneles quietos antes de dar la imagen por buena
LIMITE_GRADOS = 27.0          # dentro del tope seguro de los paneles (27.5°)

ENCABEZADO = struct.Struct("<4sI")
ENCABEZADO_IMAGEN = struct.Struct("<HHI")


class DiagnosticoVivo:

    def __init__(self):
        self.robot = Supervisor()
        self.paso = int(self.robot.getBasicTimeStep())
        self.rng = random.Random()

        self.camara = self.robot.getDevice("camara")
        self.camara.enable(self.paso)
        self.ancho = self.camara.getWidth()
        self.alto = self.camara.getHeight()

        def nodo(nombre):
            n = self.robot.getFromDef(nombre)
            if n is None:
                print(f"[VIVO] ERROR: no existe DEF {nombre} en el mundo")
                sys.exit(1)
            return n

        # Mismos nombres que usa dg.Generador.escena()
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

        self.servidor = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.servidor.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.servidor.bind((HOST, PORT))
        self.servidor.listen(1)
        self.servidor.setblocking(False)

        self.cliente = None
        self.entrada = b""
        self.salida = bytearray()

        self.muestra = 0
        self.version = 1
        self.comandados = [[0.0, 0.0] for _ in range(16)]
        self.medidos = [[0.0, 0.0] for _ in range(16)]
        self.escena_azar = False
        self.pasos_quieto = 0
        self.ultima_imagen = -1.0
        self.ultimo_estado = -1.0
        self.imagen_pendiente = True

        print(f"[VIVO] Esperando la app en {HOST}:{PORT} (cámara {self.ancho}x{self.alto})")

    # =============================================
    # PANELES Y ESCENA
    # =============================================

    def mandar_angulos(self):
        self.muestra += 1
        self.version += 1
        self.pasos_quieto = 0
        planos = [a for par in self.comandados for a in par]
        self.robot.setCustomData("S %d %s" % (self.muestra, " ".join(f"{math.radians(a):.6f}" for a in planos)))

    def cambiar_escena(self, azar):
        self.escena_azar = bool(azar)
        dg.Generador.escena(self, por_defecto=not azar)     # usa rng, cam_*, luz_* y suelo de este objeto
        self.version += 1
        self.pasos_quieto = 0

    def leer_paneles(self):
        """True si los 16 paneles ya llegaron a la última orden."""
        listos = 0
        for indice, campo in self.reportes.items():
            partes = campo.getSFString().split()
            if len(partes) == 5 and partes[0] == "P":
                self.medidos[indice] = [math.degrees(float(partes[2])), math.degrees(float(partes[3]))]
                if int(partes[1]) == self.muestra and partes[4] == "1":
                    listos += 1
        return listos == 16

    # =============================================
    # ÓRDENES DE LA APP
    # =============================================

    @staticmethod
    def _limitar(valor):
        return max(-LIMITE_GRADOS, min(LIMITE_GRADOS, float(valor)))

    def atender(self, orden):
        tipo = orden.get("orden")

        if tipo == "cero":
            self.comandados = [[0.0, 0.0] for _ in range(16)]
            self.mandar_angulos()

        elif tipo == "azar":
            n = max(1, min(16, int(orden.get("paneles", 3))))
            grados = abs(self._limitar(orden.get("grados", 10)))
            self.comandados = [[0.0, 0.0] for _ in range(16)]
            for indice in self.rng.sample(range(16), n):
                self.comandados[indice] = [self.rng.uniform(-grados, grados), self.rng.uniform(-grados, grados)]
            self.mandar_angulos()

        elif tipo == "panel":
            indice = int(orden["panel"])
            if 0 <= indice < 16:
                self.comandados[indice] = [self._limitar(orden.get("theta1", 0)),
                                           self._limitar(orden.get("theta2", 0))]
                self.mandar_angulos()

        elif tipo == "escena":
            self.cambiar_escena(orden.get("azar", False))

        else:
            print(f"[VIVO] Orden desconocida: {orden}")
            return

        print(f"[VIVO] {tipo} -> versión {self.version}")

    # =============================================
    # RED
    # =============================================

    def aceptar(self):
        try:
            cliente, direccion = self.servidor.accept()
        except BlockingIOError:
            return
        if self.cliente is not None:
            self.cerrar_cliente()
        cliente.setblocking(False)
        cliente.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.cliente = cliente
        self.entrada = b""
        self.salida = bytearray()
        self.imagen_pendiente = True
        self.ultimo_estado = -1.0
        print(f"[VIVO] App conectada desde {direccion[0]}:{direccion[1]}")

    def cerrar_cliente(self):
        try:
            self.cliente.close()
        except OSError:
            pass
        self.cliente = None
        print("[VIVO] App desconectada")

    def recibir(self):
        try:
            datos = self.cliente.recv(65536)
        except BlockingIOError:
            return
        except OSError:
            self.cerrar_cliente()
            return
        if not datos:
            self.cerrar_cliente()
            return
        self.entrada += datos
        while b"\n" in self.entrada:
            linea, self.entrada = self.entrada.split(b"\n", 1)
            if linea.strip():
                try:
                    self.atender(json.loads(linea))
                except (ValueError, KeyError, TypeError) as error:
                    print(f"[VIVO] Orden inválida ({error}): {linea[:80]!r}")

    def encolar(self, tipo, datos):
        self.salida += ENCABEZADO.pack(tipo, len(datos)) + datos

    def enviar(self):
        if not self.salida:
            return
        try:
            enviados = self.cliente.send(self.salida)
            del self.salida[:enviados]
        except BlockingIOError:
            pass
        except OSError:
            self.cerrar_cliente()

    # =============================================
    # BUCLE
    # =============================================

    def run(self):
        for _ in range(10):                # dejar que los paneles arranquen
            self.robot.step(self.paso)
        self.cambiar_escena(False)
        self.mandar_angulos()

        while self.robot.step(self.paso) != -1:
            ahora = self.robot.getTime()

            quieto = self.leer_paneles()
            antes = self.pasos_quieto
            self.pasos_quieto = self.pasos_quieto + 1 if quieto else 0
            estable = self.pasos_quieto >= PASOS_QUIETO
            if estable and antes == PASOS_QUIETO - 1:
                self.imagen_pendiente = True           # recién se quedaron quietos
                self.ultimo_estado = -1.0

            if self.cliente is None:
                self.aceptar()
                continue

            self.recibir()
            if self.cliente is None:
                continue

            if ahora - self.ultimo_estado >= PERIODO_ESTADO_S:
                self.ultimo_estado = ahora
                estado = {
                    "version": self.version, "quieto": estable,
                    "medidos": [[round(a, 4) for a in par] for par in self.medidos],
                    "comandados": [[round(a, 4) for a in par] for par in self.comandados],
                    "escena": "azar" if self.escena_azar else "normal",
                }
                self.encolar(b"ESTA", json.dumps(estado).encode())

            # Una imagen nueva solo cuando ya se mandó la anterior (no se acumulan)
            if not self.salida and (self.imagen_pendiente or ahora - self.ultima_imagen >= PERIODO_IMAGEN_S):
                imagen = self.camara.getImage()
                if imagen:
                    version = self.version if estable else 0
                    self.encolar(b"IMGN", ENCABEZADO_IMAGEN.pack(self.ancho, self.alto, version) + imagen)
                    self.ultima_imagen = ahora
                    if estable:
                        self.imagen_pendiente = False

            self.enviar()


if __name__ == "__main__":
    DiagnosticoVivo().run()
