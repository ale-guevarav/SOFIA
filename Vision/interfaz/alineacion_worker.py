"""
ALINEACIÓN - SOFIA (une la GUI de visión con el diagnóstico de alineación)

Lo que hace el menú "Alineación" de la GUI, en un hilo aparte para no
congelar la ventana. Todo el diagnóstico sigue viviendo en
Alignment/app/nucleo; aquí solo se usa.

    TOMAR CEROS  mide las 16 unidades, calcula el cero de cada servo,
                 lo guarda en Alignment/results/ceros_esp32.json y se
                 lo manda al ESP32.
    ALINEAR      mide, y corrige UNA POR UNA las unidades que no están
                 OK, de la menos a la más desalineada (cada una se
                 reacomoda con su cero nuevo). Guarda los ceros nuevos y
                 al final toma otra foto para revisar.

En los dos casos:
    - La GUI manda STOP antes (todas en 0,0) y deja de mandar posturas /
      TRACK mientras dura.
    - Si no se ven los 4 ArUco: "¡No hay un SOFIA a la vista!".
"""

import os
import sys
import time

import cv2
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage


# Núcleo de Alignment (SOFIA/Alignment/app/nucleo)
RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
NUCLEO_ALIGNMENT = os.path.join(RAIZ, "Alignment", "app", "nucleo")

if NUCLEO_ALIGNMENT not in sys.path:
    sys.path.append(NUCLEO_ALIGNMENT)


# -----------------------------
# CONFIGURACIÓN
# -----------------------------

TOMAR_CEROS = "ceros"
ALINEAR = "alinear"

METODO = "cnn"                  # el que usa la app de alineación por defecto
ESPERA_INICIAL_S = 2.0          # tras el STOP, para que todas lleguen a 0,0
ESPERA_POR_UNIDAD_S = 1.5       # ALINEAR: lo que tarda una unidad en reacomodarse
ESPERA_CEROS_S = 0.15           # TOMAR CEROS: entre unidad y unidad
ESPERA_REVISION_S = 1.0         # antes de la foto de revisión
FOTOS_CALENTAR = 15             # la cámara tarda unos cuadros en ajustar la luz
PASOS_BARRA = 100               # resolución de la barra por unidad

# Colores (BGR) del dibujo, iguales a la app de alineación
COLOR_ESTADO = {
    "OK": (80, 185, 63),
    "REVISAR": (65, 179, 224),
    "DESALINEADO": (51, 54, 218),
}

_diagnosticador = None          # se carga una vez (PyTorch tarda)


def cargar_diagnosticador():
    global _diagnosticador
    if _diagnosticador is None:
        from diagnosticador import Diagnosticador   # importa PyTorch solo aquí
        _diagnosticador = Diagnosticador(METODO)
    return _diagnosticador


def a_qimage(imagen_bgr):
    rgb = cv2.cvtColor(imagen_bgr, cv2.COLOR_BGR2RGB)
    alto, ancho, _ = rgb.shape
    return QImage(rgb.data, ancho, alto, 3 * ancho, QImage.Format.Format_RGB888).copy()


def dibujar(d, resaltar=()):
    """Foto enderezada con un círculo por unidad (color = estado)."""

    import geometria as g
    import preprocesamiento as pp

    vista = cv2.cvtColor(d.enderezada, cv2.COLOR_GRAY2BGR) if d.enderezada.ndim == 2 else d.enderezada.copy()

    for indice, fila, columna, _ in g.paneles():
        numero = g.numero_panel(fila, columna)
        cx, cy = (int(round(v)) for v in pp.centro_panel_px(fila, columna))
        color = COLOR_ESTADO[d.estado[indice]]
        cv2.circle(vista, (cx, cy), 52, color, 8 if numero in resaltar else 4, cv2.LINE_AA)
        texto = f"{numero}: {d.magnitud[indice]:.1f}"
        for borde, ancho in (((0, 0, 0), 6), (color, 2)):
            cv2.putText(vista, texto, (cx - 42, cy + 82), cv2.FONT_HERSHEY_SIMPLEX,
                        0.8, borde, ancho, cv2.LINE_AA)

    return vista


def por_numero(d):
    """{numero (0-15): (theta1, theta2, magnitud, estado)} de un diagnóstico."""
    import geometria as g
    return {
        g.numero_panel(fila, columna): (float(d.theta1[i]), float(d.theta2[i]), d.magnitud[i], d.estado[i])
        for i, fila, columna, _ in g.paneles()
    }


# =============================================
# HILO
# =============================================

class AlineacionWorker(QThread):

    # valor, máximo, texto  (máximo = 0 -> barra "ocupada")
    progreso = Signal(int, int, str)
    # No se ven los ArUco: no hay módulo a la vista (motivo)
    sin_sofia = Signal(str)
    # Cualquier otro error (cámara, Alignment, etc.)
    error = Signal(str)
    # numero (0-15), cero X, cero Y, reacomodar -> la GUI manda AJUSTE al ESP32
    ajustar = Signal(int, float, float, bool)
    # Foto analizada, para mostrarla en la ventana
    imagen = Signal(QImage)
    # Resumen al terminar: texto
    terminado = Signal(str)
    log = Signal(str)

    def __init__(self, accion, indice_camara, parent=None):
        """accion: TOMAR_CEROS o ALINEAR. indice_camara: la que ve al módulo."""
        super().__init__(parent)
        self.accion = accion
        self.indice_camara = indice_camara
        self._detener = False

    def detener(self):
        self._detener = True

    def run(self):
        try:
            self._correr()
        except Exception as error:   # que un error no cierre la GUI
            self.error.emit(f"Error inesperado: {error}")

    # -----------------------------
    # UTILIDADES
    # -----------------------------

    def _esperar(self, segundos, base, maximo, texto):
        """Espera moviendo la barra de base a base + PASOS_BARRA."""
        pasos = max(1, int(segundos / 0.05))
        for k in range(1, pasos + 1):
            if self._detener:
                return
            time.sleep(segundos / pasos)
            if maximo:
                self.progreso.emit(base + k * PASOS_BARRA // pasos, maximo, texto)

    def _foto(self, camara):
        foto = None
        for _ in range(FOTOS_CALENTAR):
            ok, cuadro = camara.read()
            if ok:
                foto = cuadro
        return foto

    def _analizar(self, diag, camara):
        """Diagnóstico de una foto nueva, o None (y avisa) si no se puede."""
        foto = self._foto(camara)
        if foto is None:
            self.error.emit(f"La cámara del módulo ({self.indice_camara}) no manda imagen")
            return None
        d = diag.analizar(foto)
        if not d.ok:
            self.imagen.emit(a_qimage(foto))
            self.sin_sofia.emit(d.motivo)
            return None
        return d

    # -----------------------------
    # PRINCIPAL
    # -----------------------------

    def _correr(self):

        self.progreso.emit(0, 0, "Cargando el modelo de alineación...")
        try:
            diag = cargar_diagnosticador()
            import ceros as cz
        except ImportError as error:
            self.error.emit(f"No se encontró el diagnóstico de Alignment ({error})")
            return
        if diag.aviso:
            self.log.emit(f"Alineación: {diag.aviso}")

        self.progreso.emit(0, 0, f"Abriendo la cámara del módulo ({self.indice_camara})...")
        camara = cv2.VideoCapture(self.indice_camara)
        if not camara.isOpened():
            self.error.emit(f"No se pudo abrir la cámara del módulo ({self.indice_camara})")
            return
        camara.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
        camara.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)

        try:
            self._esperar(ESPERA_INICIAL_S, 0, 0, "Mandando todo a 0,0...")
            self.progreso.emit(0, 0, "Buscando al SOFIA...")
            d = self._analizar(diag, camara)
            if d is None:
                return

            medidos = por_numero(d)
            conteo = d.conteo()
            self.log.emit(f"Alineación ({d.metodo}): OK {conteo['OK']} · REVISAR {conteo['REVISAR']}"
                          f" · DESALINEADO {conteo['DESALINEADO']}")

            ceros = cz.cargar()      # los que tiene el ESP32 (se mandan al conectar)

            if self.accion == TOMAR_CEROS:
                unidades = list(range(cz.NUM_UNIDADES))
                reacomodar, espera = False, ESPERA_CEROS_S
            else:
                # Las que no están OK, de la menos a la más desalineada
                unidades = sorted((n for n, m in medidos.items() if m[3] != "OK"),
                                  key=lambda n: medidos[n][2])
                reacomodar, espera = True, ESPERA_POR_UNIDAD_S

            self.imagen.emit(a_qimage(dibujar(d, unidades if self.accion == ALINEAR else ())))

            if not unidades:
                self.progreso.emit(1, 1, "¡Todo alineado!")
                self.terminado.emit("¡Todo alineado! Ninguna unidad necesita corrección.")
                return

            # Una por una
            total = len(unidades)
            maximo = (total + 1) * PASOS_BARRA          # +1: la revisión final
            hechas = []
            for i, numero in enumerate(unidades):
                if self._detener:
                    break
                theta1, theta2, magnitud, _ = medidos[numero]
                nuevo = cz.corregir(ceros[numero], theta1, theta2)
                if self.accion == ALINEAR:
                    texto = f"Alineando #{numero}: {magnitud:.1f}°  ({i + 1} de {total})"
                else:
                    texto = f"Tomando el cero de #{numero}  ({i + 1} de {total})"
                self.progreso.emit(i * PASOS_BARRA, maximo, texto)
                self.ajustar.emit(numero, nuevo[0], nuevo[1], reacomodar)
                self.log.emit(f"  #{numero}: midió {theta1:+.1f} / {theta2:+.1f} -> cero "
                              f"{ceros[numero][0]:+.1f},{ceros[numero][1]:+.1f} -> {nuevo[0]:+.1f},{nuevo[1]:+.1f}")
                ceros[numero] = nuevo
                hechas.append(numero)
                self._esperar(espera, i * PASOS_BARRA, maximo, texto)

            if hechas:
                ruta = cz.guardar(ceros, d.metodo)
                self.log.emit(f"Ceros guardados en {ruta}")

            # Revisión
            self.progreso.emit(total * PASOS_BARRA, maximo, "Revisando cómo quedó...")
            self._esperar(ESPERA_REVISION_S, total * PASOS_BARRA, maximo, "Revisando cómo quedó...")
            d2 = self._analizar(diag, camara)
            self.progreso.emit(maximo, maximo, "Listo")
            if d2 is None:
                return
            self.imagen.emit(a_qimage(dibujar(d2)))
            self.terminado.emit(self._resumen(hechas, medidos, por_numero(d2), d2.conteo()))

        finally:
            camara.release()

    def _resumen(self, hechas, antes, despues, conteo):
        accion = "Ceros tomados" if self.accion == TOMAR_CEROS else "Alineadas"
        lineas = [
            f"<b>{accion}: {len(hechas)} unidades</b>",
            f"Ahora: OK {conteo['OK']} · REVISAR {conteo['REVISAR']} · DESALINEADO {conteo['DESALINEADO']}",
            "",
        ]
        empeoraron = []
        for n in hechas:
            a, b = antes[n][2], despues[n][2]
            lineas.append(f"#{n}: {a:.1f}° → {b:.1f}°")
            if b > a + 1.0:
                empeoraron.append(n)
        if empeoraron:
            lineas += ["", f"<span style='color:#ff7b72'><b>Empeoraron: "
                       f"{', '.join(f'#{n}' for n in empeoraron)}</b> — revisa los signos en "
                       "Alignment/app/nucleo/ceros.py</span>"]
        return "<br>".join(lineas)


def ceros_guardados():
    """Ceros de Alignment/results/ceros_esp32.json, o None si no hay archivo."""
    import ceros as cz
    return cz.cargar() if cz.existe() else None


# =============================================
# BUSCAR CÁMARAS (menú Alineación -> Cámara del módulo)
# =============================================

MAX_CAMARAS = 5


class BuscarCamarasWorker(QThread):
    """Prueba las cámaras 0..MAX_CAMARAS-1 y regresa una foto de cada una."""

    # lista de (indice, QImage o None, texto)
    listas = Signal(list)

    def __init__(self, ocupadas=(), parent=None):
        super().__init__(parent)
        self.ocupadas = set(ocupadas)

    def run(self):
        resultado = []
        for indice in range(MAX_CAMARAS):
            if indice in self.ocupadas:
                resultado.append((indice, None, "en uso por la detección (ve a la persona)"))
                continue
            camara = cv2.VideoCapture(indice)
            try:
                if not camara.isOpened():
                    continue                       # no existe: no se muestra
                foto = None
                for _ in range(10):                # unos cuadros para que ajuste la luz
                    ok, cuadro = camara.read()
                    if ok:
                        foto = cuadro
                if foto is None:
                    resultado.append((indice, None, "abre pero no manda imagen"))
                else:
                    resultado.append((indice, a_qimage(foto), f"{foto.shape[1]}x{foto.shape[0]}"))
            finally:
                camara.release()
        self.listas.emit(resultado)
