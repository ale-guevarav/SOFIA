"""
VENTANA DE ALINEACIÓN - SOFIA

Ventana emergente del menú "Alineación" de la GUI: muestra la foto
analizada, lo que va haciendo y la barra de progreso. Al terminar
muestra el resumen; "Cancelar" detiene el proceso.
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
        box.addLayout(botones)

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
