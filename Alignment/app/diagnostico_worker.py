"""
HILO DE DIAGNÓSTICO - SOFIA (diagnóstico de alineación)

QThread que hace todo el trabajo pesado FUERA del hilo de la interfaz:
leer la cámara o las fotos, cargar el modelo (PyTorch / CUDA), analizar
y dibujar el resultado. La ventana solo muestra lo que llega por señales.

    GUI -> hilo:  métodos que encolan una orden (protegida con QMutex)
                  y despiertan al hilo (QWaitCondition):
                  abrir_camara, abrir_fotos, mover, analizar, continuo,
                  tomar_referencia, quitar_referencia, cambiar_metodo, detener

    hilo -> GUI:  señales de Qt (vista_camara, diagnostico_listo, ...)

Está hecho igual que Vision/interfaz/vision_worker.py para que después
se pueda meter tal cual en la GUI principal como un modo más.

FUENTES
-------
    Cámara       se ve en vivo; se analiza con "Analizar" o en continuo.
    Fotos        una foto, una carpeta, o una SESIÓN de Webots
                 (carpeta con imagenes/ y recortes.csv): en ese caso
                 también se muestran los ángulos reales y el error.
"""

import csv
import glob
import os
import sys
import time

import cv2
import numpy as np
from PySide6.QtCore import QMutex, QMutexLocker, QThread, QWaitCondition, Signal
from PySide6.QtGui import QImage

AQUI = os.path.dirname(os.path.abspath(__file__))
ALIGNMENT = os.path.dirname(AQUI)
sys.path.insert(0, os.path.join(ALIGNMENT, "hibrido"))
sys.path.insert(0, ALIGNMENT)

import geometria as g  # noqa: E402
import preprocesamiento as pp  # noqa: E402


EXTENSIONES = (".jpg", ".jpeg", ".png", ".bmp")
PERIODO_CONTINUO_S = 0.5           # análisis en continuo: 2 por segundo
PERIODO_VISTA_S = 1 / 15           # vista de la cámara a ~15 FPS
PIXELES_POR_GRADO = 4.0            # largo de la flecha en la imagen (30° = 120 px)

COLORES = {                        # BGR
    "OK": (80, 200, 60),
    "REVISAR": (0, 190, 255),
    "DESALINEADO": (50, 50, 230),
}


def a_qimage(imagen):
    """BGR o gris (numpy) -> QImage (copia, segura para mandar entre hilos)."""
    if imagen.ndim == 2:
        h, w = imagen.shape
        return QImage(imagen.data, w, h, w, QImage.Format_Grayscale8).copy()
    rgb = cv2.cvtColor(imagen, cv2.COLOR_BGR2RGB)
    h, w, _ = rgb.shape
    return QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888).copy()


def dibujar(d, reales=None):
    """Foto enderezada con una flecha por hexágono (color = estado)."""

    vista = cv2.cvtColor(d.enderezada, cv2.COLOR_GRAY2BGR)
    vista = (vista * 0.75).astype(np.uint8)          # un poco más oscura para que resalten

    for indice, fila, columna, _ in g.paneles():
        cx, cy = pp.centro_panel_px(fila, columna)
        centro = (int(round(cx)), int(round(cy)))
        color = COLORES[d.estado[indice]]

        # Real (si se conoce): flecha blanca delgada
        if reales is not None:
            punta = (int(round(cx + reales[indice, 0] * PIXELES_POR_GRADO)),
                     int(round(cy - reales[indice, 1] * PIXELES_POR_GRADO)))
            cv2.arrowedLine(vista, centro, punta, (255, 255, 255), 1, cv2.LINE_AA, tipLength=0.2)

        # Estimado: theta1 -> derecha, theta2 -> arriba
        punta = (int(round(cx + d.theta1[indice] * PIXELES_POR_GRADO)),
                 int(round(cy - d.theta2[indice] * PIXELES_POR_GRADO)))
        cv2.circle(vista, centro, 34, color, 3, cv2.LINE_AA)
        cv2.arrowedLine(vista, centro, punta, color, 3, cv2.LINE_AA, tipLength=0.25)

        if d.desacuerdo is not None and d.desacuerdo[indice]:
            cv2.circle(vista, centro, 42, (0, 255, 255), 2, cv2.LINE_AA)
            cv2.putText(vista, "?", (centro[0] + 30, centro[1] - 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 255), 2, cv2.LINE_AA)

        texto = f"{indice}: {d.magnitud[indice]:.1f}"
        cv2.putText(vista, texto, (centro[0] - 40, centro[1] + 62),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 4, cv2.LINE_AA)
        cv2.putText(vista, texto, (centro[0] - 40, centro[1] + 62),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2, cv2.LINE_AA)

    return vista


def leer_sesion(carpeta):
    """Si la carpeta es una sesión de Webots, {muestra: (16, 2)} con los ángulos reales."""
    ruta = os.path.join(carpeta, "recortes.csv")
    if not os.path.isfile(ruta):
        return {}
    reales = {}
    with open(ruta, newline="") as archivo:
        for f in csv.DictReader(archivo):
            reales.setdefault(int(f["muestra"]), np.zeros((16, 2)))[int(f["panel"])] = (
                float(f["theta1_deg"]), float(f["theta2_deg"]))
    return reales


class DiagnosticoWorker(QThread):

    # Vista en vivo de la cámara (sin analizar)
    vista_camara = Signal(QImage)

    # (Diagnostico, QImage dibujada, info dict: nombre, reales, error)
    diagnostico_listo = Signal(object, QImage, object)

    # Texto para la barra de estado / bitácora
    mensaje = Signal(str)

    # (metodo efectivo, dispositivo, aviso)
    metodo_listo = Signal(str, str, str)

    # (posición, total, nombre) de la foto actual
    foto_actual = Signal(int, int, str)

    # True / False: hay referencia 0,0
    referencia_lista = Signal(bool)

    def __init__(self, metodo="hibrido", parent=None):
        super().__init__(parent)
        self._mutex = QMutex()
        self._condicion = QWaitCondition()
        self._ordenes = []
        self._corriendo = True

        self._metodo = metodo
        self._diag = None
        self._camara = None
        self._fotos = []
        self._posicion = 0
        self._reales = {}
        self._continuo = False
        self._ultima_imagen = None
        self._ultimo_nombre = ""

    # =============================================
    # ÓRDENES (se llaman desde la GUI)
    # =============================================

    def _orden(self, *orden):
        with QMutexLocker(self._mutex):
            self._ordenes.append(orden)
            self._condicion.wakeAll()

    def abrir_camara(self, indice):
        self._orden("camara", indice)

    def abrir_fotos(self, ruta):
        self._orden("fotos", ruta)

    def mover(self, paso):
        self._orden("mover", paso)

    def analizar(self):
        self._orden("analizar")

    def continuo(self, activo):
        self._orden("continuo", activo)

    def tomar_referencia(self):
        self._orden("referencia")

    def quitar_referencia(self):
        self._orden("sin_referencia")

    def cambiar_metodo(self, metodo):
        self._orden("metodo", metodo)

    def detener(self):
        with QMutexLocker(self._mutex):
            self._corriendo = False
            self._condicion.wakeAll()

    # =============================================
    # HILO
    # =============================================

    def run(self):
        self._cargar_metodo(self._metodo)
        ultima_vista = ultimo_analisis = 0.0

        while True:
            with QMutexLocker(self._mutex):
                # Sin cámara no hay nada que hacer hasta la siguiente orden
                if self._corriendo and not self._ordenes and self._camara is None:
                    self._condicion.wait(self._mutex)
                if not self._corriendo:
                    break
                ordenes, self._ordenes = self._ordenes, []

            for orden in ordenes:
                try:
                    self._atender(*orden)
                except Exception as error:   # que un error no tumbe el hilo
                    self.mensaje.emit(f"Error en '{orden[0]}': {error}")

            if self._camara is None:
                continue

            ok, frame = self._camara.read()
            if not ok:
                self.mensaje.emit("La cámara dejó de responder")
                self._cerrar_camara()
                continue

            self._ultima_imagen = frame
            ahora = time.monotonic()

            if ahora - ultima_vista >= PERIODO_VISTA_S:
                ultima_vista = ahora
                self.vista_camara.emit(a_qimage(frame))

            if self._continuo and ahora - ultimo_analisis >= PERIODO_CONTINUO_S:
                ultimo_analisis = ahora
                self._analizar_actual()

        self._cerrar_camara()

    def _atender(self, tipo, *datos):
        if tipo == "camara":
            self._abrir_camara(datos[0])
        elif tipo == "fotos":
            self._abrir_fotos(datos[0])
        elif tipo == "mover":
            self._mover(datos[0])
        elif tipo == "analizar":
            self._analizar_actual()
        elif tipo == "continuo":
            self._continuo = bool(datos[0])
        elif tipo == "referencia":
            self._tomar_referencia()
        elif tipo == "sin_referencia":
            self._diag.quitar_referencia()
            self.referencia_lista.emit(False)
            self.mensaje.emit("Referencia quitada: el geométrico mide desde la posición teórica")
        elif tipo == "metodo":
            self._cargar_metodo(datos[0])
            self._analizar_actual()

    # =============================================
    # MÉTODO
    # =============================================

    def _cargar_metodo(self, metodo):
        from metodo_hibrido import Diagnosticador   # importa PyTorch solo si hace falta

        self.mensaje.emit(f"Cargando método {metodo}...")
        anterior = self._diag
        self._diag = Diagnosticador(metodo)

        # Conservar la referencia 0,0 al cambiar de método
        if anterior is not None and anterior.referencia:
            self._diag.geometrico = anterior.geometrico
            self._diag.referencia = True

        self.metodo_listo.emit(self._diag.metodo, self._diag.dispositivo, self._diag.aviso)
        if self._diag.aviso:
            self.mensaje.emit(self._diag.aviso)

    # =============================================
    # FUENTES
    # =============================================

    def _abrir_camara(self, indice):
        self._fotos = []
        self._cerrar_camara()
        camara = cv2.VideoCapture(indice)
        if not camara.isOpened():
            self.mensaje.emit(f"No se pudo abrir la cámara {indice}")
            return
        # Mientras más resolución, mejor se ven los marcadores y las placas
        camara.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
        camara.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
        self._camara = camara
        self._ultimo_nombre = f"cámara {indice}"
        self.mensaje.emit(
            f"Cámara {indice}: {int(camara.get(cv2.CAP_PROP_FRAME_WIDTH))}x"
            f"{int(camara.get(cv2.CAP_PROP_FRAME_HEIGHT))}")
        self.foto_actual.emit(0, 0, self._ultimo_nombre)

    def _cerrar_camara(self):
        if self._camara is not None:
            self._camara.release()
            self._camara = None

    def _abrir_fotos(self, ruta):
        self._cerrar_camara()
        self._reales = {}

        if os.path.isfile(ruta):
            self._fotos = [ruta]
        else:
            carpeta = ruta
            if os.path.isdir(os.path.join(ruta, "imagenes")):     # sesión de Webots
                self._reales = leer_sesion(ruta)
                carpeta = os.path.join(ruta, "imagenes")
            self._fotos = sorted(f for f in glob.glob(os.path.join(carpeta, "*"))
                                 if f.lower().endswith(EXTENSIONES))

        if not self._fotos:
            self.mensaje.emit(f"No hay fotos en {ruta}")
            return

        extra = f" · sesión de Webots con ángulos reales" if self._reales else ""
        self.mensaje.emit(f"{len(self._fotos)} fotos{extra}")
        self._posicion = 0
        self._mover(0)

    def _mover(self, paso):
        if not self._fotos:
            return
        self._posicion = (self._posicion + paso) % len(self._fotos)
        ruta = self._fotos[self._posicion]
        imagen = cv2.imread(ruta)
        if imagen is None:
            self.mensaje.emit(f"No se pudo leer {ruta}")
            return
        self._ultima_imagen = imagen
        self._ultimo_nombre = os.path.basename(ruta)
        self.foto_actual.emit(self._posicion + 1, len(self._fotos), self._ultimo_nombre)
        self._analizar_actual()

    # =============================================
    # ANÁLISIS
    # =============================================

    def _tomar_referencia(self):
        if self._ultima_imagen is None:
            self.mensaje.emit("No hay imagen para usar como referencia")
            return
        ok, motivo = self._diag.fijar_referencia(self._ultima_imagen)
        self.referencia_lista.emit(ok)
        self.mensaje.emit(f"Referencia 0,0 tomada de {self._ultimo_nombre}" if ok
                          else f"No sirve como referencia: {motivo}")

    def _reales_actuales(self):
        if not self._reales or not self._fotos:
            return None
        nombre = os.path.splitext(os.path.basename(self._fotos[self._posicion]))[0]
        return self._reales.get(int(nombre)) if nombre.isdigit() else None

    def _analizar_actual(self):
        if self._ultima_imagen is None or self._diag is None:
            return

        d = self._diag.analizar(self._ultima_imagen)
        info = {"nombre": self._ultimo_nombre, "reales": None, "error": None}

        if not d.ok:
            vista = self._ultima_imagen.copy()
            cv2.putText(vista, d.motivo, (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 3)
            self.diagnostico_listo.emit(d, a_qimage(vista), info)
            return

        reales = self._reales_actuales() if self._camara is None else None
        if reales is not None:
            estimado = np.c_[d.theta1, d.theta2]
            info["reales"] = reales
            info["error"] = np.abs(estimado - reales).max(axis=1)

        self.diagnostico_listo.emit(d, a_qimage(dibujar(d, reales)), info)
