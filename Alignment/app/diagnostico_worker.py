"""
HILO DE DIAGNÓSTICO - SOFIA (diagnóstico de alineación)

QThread que hace todo el trabajo pesado FUERA del hilo de la interfaz:
leer la fuente de imágenes, cargar el modelo (PyTorch / CUDA), analizar
y dibujar el resultado. La ventana solo muestra lo que llega por señales.

    GUI -> hilo:  métodos que encolan una orden (protegida con QMutex)
                  y despiertan al hilo (QWaitCondition).
    hilo -> GUI:  señales de Qt.

Está hecho igual que Vision/interfaz/vision_worker.py para que después
se pueda meter en la GUI principal como un modo más.

FUENTES
-------
    camara   cámara de la PC; se analiza con "Analizar" o en continuo.
    fotos    una foto, una carpeta o una SESIÓN de Webots (carpeta con
             imagenes/ y recortes.csv): también muestra el valor real.
    webots   Webots en vivo (mundo sofia_diagnostico_vivo.wbt): la app
             mueve los paneles y cada vez que se quedan quietos analiza
             sola y compara contra los ángulos medidos en la simulación.
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
sys.path.insert(0, os.path.join(AQUI, "nucleo"))
sys.path.insert(0, AQUI)

import geometria as g  # noqa: E402
import preprocesamiento as pp  # noqa: E402
from webots_vivo import ClienteWebots  # noqa: E402


EXTENSIONES = (".jpg", ".jpeg", ".png", ".bmp")
PERIODO_CONTINUO_S = 0.5           # análisis en continuo: 2 por segundo
PERIODO_VISTA_S = 1 / 15           # vista en vivo a ~15 FPS
PIXELES_POR_GRADO = 4.0            # largo de la flecha en la imagen (30° = 120 px)

SIN_FUENTE, CAMARA, FOTOS, WEBOTS = "ninguna", "camara", "fotos", "webots"

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

    # Vista en vivo (cámara o Webots), sin analizar
    vista_en_vivo = Signal(QImage)

    # (Diagnostico, QImage dibujada, info dict: nombre, reales, error)
    diagnostico_listo = Signal(object, QImage, object)

    # Texto para la barra de estado / bitácora
    mensaje = Signal(str)

    # (metodo efectivo, dispositivo, aviso)
    metodo_listo = Signal(str, str, str)

    # Fuente activa: "ninguna", "camara", "fotos" o "webots"
    fuente_cambiada = Signal(str)

    # (posición, total, nombre) de la foto actual
    foto_actual = Signal(int, int, str)

    # True / False: hay referencia 0,0
    referencia_lista = Signal(bool)

    # Texto del estado de los paneles en Webots ("Moviendo...", "Quietos")
    estado_webots = Signal(str)

    def __init__(self, metodo="hibrido", parent=None):
        super().__init__(parent)
        self._mutex = QMutex()
        self._condicion = QWaitCondition()
        self._ordenes = []
        self._corriendo = True

        self._metodo = metodo
        self._diag = None
        self._continuo = False

        self._fuente = SIN_FUENTE
        self._camara = None
        self._webots = ClienteWebots()
        self._fotos = []
        self._posicion = 0
        self._reales_sesion = {}

        self._ultima_imagen = None
        self._ultimo_nombre = ""

        # Webots en vivo
        self._estado = None               # último "ESTA"
        self._version_imagen = 0          # versión de la última imagen (0 = paneles moviéndose)
        self._version_analizada = 0
        self._referencia_pendiente = False

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

    def conectar_webots(self):
        self._orden("webots")

    def cerrar_fuente(self):
        self._orden("cerrar")

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

    def ordenar_webots(self, orden, **datos):
        """cero / azar (paneles, grados) / panel (panel, theta1, theta2) / escena (azar)."""
        self._orden("webots_orden", orden, datos)

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
                # Sin fuente en vivo no hay nada que hacer hasta la siguiente orden
                if self._corriendo and not self._ordenes and self._fuente not in (CAMARA, WEBOTS):
                    self._condicion.wait(self._mutex)
                if not self._corriendo:
                    break
                ordenes, self._ordenes = self._ordenes, []

            for orden in ordenes:
                try:
                    self._atender(*orden)
                except Exception as error:   # que un error no tumbe el hilo
                    self.mensaje.emit(f"Error en '{orden[0]}': {error}")

            nueva = False
            if self._fuente == CAMARA:
                nueva = self._leer_camara()
            elif self._fuente == WEBOTS:
                nueva = self._leer_webots()

            if not nueva:
                continue

            ahora = time.monotonic()
            if ahora - ultima_vista >= PERIODO_VISTA_S:
                ultima_vista = ahora
                self.vista_en_vivo.emit(a_qimage(self._ultima_imagen))

            if self._fuente == WEBOTS and self._toca_analisis_automatico():
                ultimo_analisis = ahora
                self._analizar_webots()
            elif self._continuo and ahora - ultimo_analisis >= PERIODO_CONTINUO_S:
                ultimo_analisis = ahora
                self._analizar_actual()

        self._cerrar()

    def _atender(self, tipo, *datos):
        if tipo == "camara":
            self._abrir_camara(datos[0])
        elif tipo == "fotos":
            self._abrir_fotos(datos[0])
        elif tipo == "webots":
            self._conectar_webots()
        elif tipo == "cerrar":
            self._cerrar()
            self.mensaje.emit("Fuente cerrada")
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
        elif tipo == "webots_orden":
            self._ordenar_webots(datos[0], datos[1])

    # =============================================
    # MÉTODO
    # =============================================

    def _cargar_metodo(self, metodo):
        from diagnosticador import Diagnosticador   # importa PyTorch solo si hace falta

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

    def _cerrar(self):
        if self._camara is not None:
            self._camara.release()
            self._camara = None
        self._webots.cerrar()
        self._fotos = []
        self._reales_sesion = {}
        self._estado = None
        self._version_imagen = self._version_analizada = 0
        self._referencia_pendiente = False
        if self._fuente != SIN_FUENTE:
            self._fuente = SIN_FUENTE
            self.fuente_cambiada.emit(SIN_FUENTE)
            self.foto_actual.emit(0, 0, "-")

    def _cambiar_fuente(self, fuente, nombre):
        self._fuente = fuente
        self._ultimo_nombre = nombre
        self.fuente_cambiada.emit(fuente)
        self.foto_actual.emit(0, 0, nombre)

    def _abrir_camara(self, indice):
        self._cerrar()
        camara = cv2.VideoCapture(indice)
        if not camara.isOpened():
            self.mensaje.emit(f"No se pudo abrir la cámara {indice}")
            return
        # Mientras más resolución, mejor se ven los marcadores y las placas
        camara.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
        camara.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
        self._camara = camara
        self._cambiar_fuente(CAMARA, f"cámara {indice}")
        self.mensaje.emit(
            f"Cámara {indice}: {int(camara.get(cv2.CAP_PROP_FRAME_WIDTH))}x"
            f"{int(camara.get(cv2.CAP_PROP_FRAME_HEIGHT))}")

    def _leer_camara(self):
        ok, frame = self._camara.read()
        if not ok:
            self.mensaje.emit("La cámara dejó de responder")
            self._cerrar()
            return False
        self._ultima_imagen = frame
        return True

    def _abrir_fotos(self, ruta):
        self._cerrar()

        if os.path.isfile(ruta):
            fotos = [ruta]
        else:
            carpeta = ruta
            if os.path.isdir(os.path.join(ruta, "imagenes")):     # sesión de Webots
                self._reales_sesion = leer_sesion(ruta)
                carpeta = os.path.join(ruta, "imagenes")
            fotos = sorted(f for f in glob.glob(os.path.join(carpeta, "*"))
                           if f.lower().endswith(EXTENSIONES))

        if not fotos:
            self.mensaje.emit(f"No hay fotos en {ruta}")
            return

        self._fotos = fotos
        self._fuente = FOTOS
        self.fuente_cambiada.emit(FOTOS)
        extra = " · sesión de Webots con ángulos reales" if self._reales_sesion else ""
        self.mensaje.emit(f"{len(fotos)} fotos{extra}")
        self._posicion = 0
        self._mover(0)

    def _mover(self, paso):
        if self._fuente != FOTOS or not self._fotos:
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
    # WEBOTS EN VIVO
    # =============================================

    def _conectar_webots(self):
        self._cerrar()
        self.mensaje.emit(f"Conectando a Webots en {self._webots.host}:{self._webots.port}...")
        try:
            self._webots.conectar()
        except OSError as error:
            self.mensaje.emit(f"No se pudo conectar a Webots ({error}). ¿Está abierto "
                              "sofia_diagnostico_vivo.wbt y corriendo la simulación?")
            return
        self._cambiar_fuente(WEBOTS, "Webots en vivo")
        # Al arrancar, los paneles están en 0,0: esa primera imagen quieta es la referencia
        self._referencia_pendiente = True
        self.mensaje.emit("Conectado a Webots: la primera imagen con todo en 0,0 se toma como referencia")

    def _ordenar_webots(self, orden, datos):
        if self._fuente != WEBOTS:
            self.mensaje.emit("Primero conecta Webots en vivo")
            return
        try:
            self._webots.ordenar(orden, **datos)
        except OSError as error:
            self.mensaje.emit(f"Webots: {error}")
            self._cerrar()
            return
        if orden == "cero":
            self._referencia_pendiente = True
        self.estado_webots.emit("Moviendo...")

    def _leer_webots(self):
        try:
            eventos = self._webots.leer()
        except ConnectionError as error:
            self.mensaje.emit(f"Webots: {error}")
            self._cerrar()
            return False

        nueva = False
        for tipo, dato in eventos:
            if tipo == "estado":
                anterior = self._estado
                self._estado = dato
                if anterior is None or anterior["quieto"] != dato["quieto"] or anterior["version"] != dato["version"]:
                    self.estado_webots.emit(
                        f"Quietos (versión {dato['version']}, escena {dato['escena']})" if dato["quieto"]
                        else "Moviendo...")
            else:
                self._ultima_imagen, self._version_imagen = dato
                nueva = True
        return nueva

    def _toca_analisis_automatico(self):
        """Una vez por cada posición nueva, con la primera imagen ya quieta."""
        return (self._version_imagen != 0 and self._estado is not None and self._estado["quieto"]
                and self._estado["version"] == self._version_imagen
                and self._version_imagen != self._version_analizada)

    def _analizar_webots(self):
        self._version_analizada = self._version_imagen
        comandados = np.array(self._estado["comandados"])
        if self._referencia_pendiente and not comandados.any():
            self._referencia_pendiente = False
            self._tomar_referencia()
        self._ultimo_nombre = f"Webots (versión {self._version_imagen})"
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
        """Ángulos reales de la imagen actual, si se conocen."""
        if self._fuente == WEBOTS:
            # Solo si la imagen se tomó con los paneles quietos en la posición del estado
            if (self._estado is not None and self._version_imagen != 0
                    and self._estado["version"] == self._version_imagen):
                return np.array(self._estado["medidos"], float)
            return None
        if self._fuente == FOTOS and self._reales_sesion:
            nombre = os.path.splitext(os.path.basename(self._fotos[self._posicion]))[0]
            return self._reales_sesion.get(int(nombre)) if nombre.isdigit() else None
        return None

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

        reales = self._reales_actuales()
        if reales is not None:
            estimado = np.c_[d.theta1, d.theta2]
            info["reales"] = reales
            info["error"] = np.abs(estimado - reales).max(axis=1)

        self.diagnostico_listo.emit(d, a_qimage(dibujar(d, reales)), info)
