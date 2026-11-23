"""
VENTANA DE ALINEACIÓN - SOFIA

Ventana emergente del menú "Alineación" de la GUI:

    1. CÁMARA EN VIVO: para apuntar la cámara al SOFIA (marca los ArUco
       que ve). Cuando esté bien, se pica "Comenzar".
    2. PROCESO: la foto analizada, lo que va haciendo y la barra de
       progreso. Al terminar muestra el resumen.

"Cancelar" detiene todo en cualquier momento.
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
)


class AlineacionVentana(QDialog):

    cancelar = Signal()
    comenzar = Signal()

    def __init__(self, titulo, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"SOFIA - {titulo}")
        self.setModal(True)
        self.resize(560, 700)
        self._terminada = False
        self._pixmap = None

        box = QVBoxLayout(self)
        box.setSpacing(10)

        encabezado = QLabel(titulo.upper())
        encabezado.setObjectName("alignTitle")
        encabezado.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.addWidget(encabezado)

        self.foto = QLabel("Buscando al SOFIA...")
        self.foto.setObjectName("video")
        self.foto.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.foto.setMinimumSize(420, 420)
        self.foto.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        box.addWidget(self.foto, stretch=1)

        self.estado = QLabel("Empezando...")
        self.estado.setObjectName("alignStatus")
        self.estado.setWordWrap(True)
        self.estado.setTextFormat(Qt.TextFormat.RichText)
        box.addWidget(self.estado)

        self.barra = QProgressBar()
        self.barra.setObjectName("align")
        self.barra.setRange(0, 0)
        self.barra.setFormat("%p%")
        box.addWidget(self.barra)

        botones = QHBoxLayout()
        botones.addStretch(1)
        self.boton = QPushButton("Cancelar")
        self.boton.setObjectName("danger")
        self.boton.clicked.connect(self._boton)
        botones.addWidget(self.boton)
        self.boton_comenzar = QPushButton("▶  Comenzar")
        self.boton_comenzar.setObjectName("alignMenu")
        self.boton_comenzar.clicked.connect(self._comenzar)
        self.boton_comenzar.hide()
        botones.addWidget(self.boton_comenzar)
        box.addLayout(botones)

    # -----------------------------
    # 1. CÁMARA EN VIVO
    # -----------------------------

    def modo_vista(self, camara):
        self.foto.setText(f"Abriendo la cámara {camara}...")
        self.barra.hide()
        self.boton_comenzar.show()
        self.boton_comenzar.setDefault(True)
        self.marcadores(0)

    def marcadores(self, cuantos):
        if cuantos == 4:
            texto = ("<span style='color:#7ee787'><b>✔ Se ven los 4 ArUco.</b></span> "
                     "Cuando esté bien acomodada, pica <b>Comenzar</b>.")
        else:
            texto = (f"<span style='color:#e0b341'><b>Se ven {cuantos} de 4 ArUco.</b></span> "
                     "Mueve la cámara hasta que se vean los 4 (marcados en verde).")
        self.estado.setText(texto)

    def _comenzar(self):
        self.boton_comenzar.hide()
        self.barra.show()
        self.barra.setRange(0, 0)
        self.estado.setText("Empezando...")
        self.comenzar.emit()

    # -----------------------------
    # 2. PROCESO
    # -----------------------------

    def progreso(self, valor, maximo, texto):
        if maximo <= 0:
            self.barra.setRange(0, 0)      # "ocupada"
        else:
            self.barra.setRange(0, maximo)
            self.barra.setValue(valor)
        self.estado.setText(texto)

    def imagen(self, qimage):
        self._pixmap = QPixmap.fromImage(qimage)
        self._mostrar_foto()

    def fallar(self, texto):
        """Se queda abierta (con la foto) para ver qué vio la cámara."""
        self._terminada = True
        self.barra.setRange(0, 1)
        self.barra.setValue(0)
        self.estado.setText(f"<span style='color:#ff7b72; font-size:16px'><b>{texto}</b></span>")
        self.boton.setText("Cerrar")

    def terminar(self, resumen_html):
        self._terminada = True
        self.barra.setRange(0, 1)
        self.barra.setValue(1)
        self.estado.setText(resumen_html)
        self.boton.setText("Cerrar")
        self.boton.setObjectName("primary")
        self.boton.style().unpolish(self.boton)
        self.boton.style().polish(self.boton)

    # -----------------------------

    def _mostrar_foto(self):
        if self._pixmap is not None:
            self.foto.setPixmap(self._pixmap.scaled(
                self.foto.size(), Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, evento):
        super().resizeEvent(evento)
        self._mostrar_foto()

    def _boton(self):
        if not self._terminada:
            self.cancelar.emit()
        self.close()

    def closeEvent(self, evento):
        if not self._terminada:
            self.cancelar.emit()
        super().closeEvent(evento)

    def reject(self):      # Esc
        if not self._terminada:
            self.cancelar.emit()
        super().reject()


# =============================================
# CÁMARAS DISPONIBLES
# =============================================

class CamarasVentana(QDialog):
    """Una foto de cada cámara conectada; 'Usar esta' elige la del módulo."""

    elegida = Signal(int)

    def __init__(self, camaras, actual, parent=None):
        from PySide6.QtWidgets import QGridLayout, QWidget

        super().__init__(parent)
        self.setWindowTitle("SOFIA - Cámaras disponibles")
        self.setModal(True)

        box = QVBoxLayout(self)
        titulo = QLabel("¿CUÁL VE AL SOFIA?")
        titulo.setObjectName("alignTitle")
        titulo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.addWidget(titulo)

        if not camaras:
            aviso = QLabel("No se encontró ninguna cámara. Conecta la cámara del módulo y vuelve a buscar.")
            aviso.setObjectName("alignStatus")
            aviso.setWordWrap(True)
            box.addWidget(aviso)

        rejilla = QGridLayout()
        rejilla.setSpacing(12)
        for k, (indice, qimage, texto) in enumerate(camaras):
            celda = QVBoxLayout()
            foto = QLabel()
            foto.setObjectName("video")
            foto.setAlignment(Qt.AlignmentFlag.AlignCenter)
            foto.setFixedSize(300, 200)
            if qimage is not None:
                foto.setPixmap(QPixmap.fromImage(qimage).scaled(
                    foto.size(), Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation))
            else:
                foto.setText("Sin imagen")
            marca = "  ✔ (la elegida)" if indice == actual else ""
            nombre = QLabel(f"<b>Cámara {indice}</b>{marca}<br><small>{texto}</small>")
            nombre.setTextFormat(Qt.TextFormat.RichText)
            boton = QPushButton("Usar esta")
            boton.setObjectName("primary")
            boton.setEnabled(qimage is not None)
            boton.clicked.connect(lambda _=False, i=indice: self._elegir(i))
            celda.addWidget(foto)
            celda.addWidget(nombre)
            celda.addWidget(boton)
            contenedor = QWidget()
            contenedor.setLayout(celda)
            rejilla.addWidget(contenedor, k // 2, k % 2)
        box.addLayout(rejilla)

        cerrar = QPushButton("Cerrar")
        cerrar.clicked.connect(self.close)
        fila = QHBoxLayout()
        fila.addStretch(1)
        fila.addWidget(cerrar)
        box.addLayout(fila)

    def _elegir(self, indice):
        self.elegida.emit(indice)
        self.close()
