"""
APP DE DIAGNÓSTICO DE ALINEACIÓN - SOFIA

Ventana para PROBAR el diagnóstico con la cámara o con fotos:

    - Foto enderezada con una flecha por hexágono (color = estado,
      "?" = el geométrico y la CNN no coinciden).
    - Mapa 4x4 con theta1 / theta2 y el estado de cada hexágono,
      en la misma posición que en la foto.
    - Elegir método: geométrico, CNN o híbrido.
    - Tomar la foto de referencia (todo en 0,0).
    - Con una sesión de Webots muestra también el error contra el valor real.
    - Guardar el reporte (imagen + CSV).

Todo el procesamiento corre en DiagnosticoWorker (QThread).

Uso (desde la carpeta SOFIA, con el entorno activado):
    python Alignment/app/app_diagnostico.py
"""

import csv
import datetime
import os
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QGridLayout, QGroupBox,
    QHBoxLayout, QHeaderView, QLabel, QMainWindow, QPlainTextEdit, QPushButton,
    QSizePolicy, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

AQUI = os.path.dirname(os.path.abspath(__file__))
ALIGNMENT = os.path.dirname(AQUI)
sys.path.insert(0, ALIGNMENT)
sys.path.insert(0, AQUI)

import geometria as g  # noqa: E402
from diagnostico_worker import DiagnosticoWorker  # noqa: E402

METODOS = [("hibrido", "Híbrido (geométrico + CNN)"), ("cnn", "CNN pequeña"), ("geometrico", "Geométrico")]

COLOR_ESTADO = {
    "OK": QColor(200, 240, 200),
    "REVISAR": QColor(255, 225, 150),
    "DESALINEADO": QColor(250, 180, 180),
}


def celda_en_tabla(fila, columna):
    """
    Fila y columna de la tabla para que el mapa se vea igual que la foto
    enderezada: la fila 0 de paneles queda abajo y la columna 0 a la derecha
    (ver geometria.mundo_a_imagen).
    """
    return g.FILAS - 1 - fila, g.COLUMNAS - 1 - columna


class VentanaDiagnostico(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("SOFIA - Diagnóstico de alineación")
        self.resize(1400, 900)

        self.ultimo = None          # (Diagnostico, QImage, info)

        self._armar()

        self.worker = DiagnosticoWorker(METODOS[0][0])
        self.worker.vista_camara.connect(self.mostrar_camara)
        self.worker.diagnostico_listo.connect(self.mostrar_diagnostico)
        self.worker.mensaje.connect(self.registrar)
        self.worker.metodo_listo.connect(self.on_metodo)
        self.worker.foto_actual.connect(self.on_foto)
        self.worker.referencia_lista.connect(self.on_referencia)
        self.worker.start()

    # =============================================
    # INTERFAZ
    # =============================================

    def _armar(self):
        central = QWidget()
        principal = QHBoxLayout(central)

        # Izquierda: foto enderezada con el diagnóstico
        self.imagen = QLabel("Abre la cámara o unas fotos")
        self.imagen.setAlignment(Qt.AlignCenter)
        self.imagen.setMinimumSize(640, 640)
        self.imagen.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.imagen.setStyleSheet("background:#202020; color:#ddd;")
        principal.addWidget(self.imagen, 3)

        # Derecha: controles
        derecha = QVBoxLayout()
        principal.addLayout(derecha, 2)

        # --- Fuente
        fuente = QGroupBox("Fuente")
        rejilla = QGridLayout(fuente)
        self.spin_camara = QSpinBox()
        self.spin_camara.setRange(0, 9)
        btn_camara = QPushButton("Abrir cámara")
        btn_camara.clicked.connect(lambda: self.worker.abrir_camara(self.spin_camara.value()))
        btn_foto = QPushButton("Abrir foto...")
        btn_foto.clicked.connect(self.abrir_foto)
        btn_carpeta = QPushButton("Abrir carpeta / sesión...")
        btn_carpeta.clicked.connect(self.abrir_carpeta)
        self.btn_anterior = QPushButton("◀ Anterior")
        self.btn_anterior.clicked.connect(lambda: self.worker.mover(-1))
        self.btn_siguiente = QPushButton("Siguiente ▶")
        self.btn_siguiente.clicked.connect(lambda: self.worker.mover(1))
        self.lbl_foto = QLabel("-")
        self.vista_camara = QLabel()
        self.vista_camara.setFixedHeight(170)
        self.vista_camara.setAlignment(Qt.AlignCenter)
        self.vista_camara.hide()

        rejilla.addWidget(QLabel("Cámara"), 0, 0)
        rejilla.addWidget(self.spin_camara, 0, 1)
        rejilla.addWidget(btn_camara, 0, 2)
        rejilla.addWidget(btn_foto, 1, 0, 1, 2)
        rejilla.addWidget(btn_carpeta, 1, 2)
        rejilla.addWidget(self.btn_anterior, 2, 0, 1, 2)
        rejilla.addWidget(self.btn_siguiente, 2, 2)
        rejilla.addWidget(self.lbl_foto, 3, 0, 1, 3)
        rejilla.addWidget(self.vista_camara, 4, 0, 1, 3)
        derecha.addWidget(fuente)

        # --- Método y análisis
        analisis = QGroupBox("Análisis")
        rejilla = QGridLayout(analisis)
        self.combo_metodo = QComboBox()
        for clave, nombre in METODOS:
            self.combo_metodo.addItem(nombre, clave)
        self.combo_metodo.currentIndexChanged.connect(
            lambda: self.worker.cambiar_metodo(self.combo_metodo.currentData()))
        self.lbl_metodo = QLabel("Cargando...")
        self.lbl_metodo.setWordWrap(True)
        btn_analizar = QPushButton("Analizar")
        btn_analizar.clicked.connect(self.worker_analizar)
        self.chk_continuo = QCheckBox("Continuo (cámara)")
        self.chk_continuo.toggled.connect(lambda v: self.worker.continuo(v))
        btn_ref = QPushButton("Tomar referencia 0,0")
        btn_ref.setToolTip("Usa la imagen actual (todos los hexágonos en 0,0) como cero del método geométrico")
        btn_ref.clicked.connect(lambda: self.worker.tomar_referencia())
        btn_sin_ref = QPushButton("Quitar referencia")
        btn_sin_ref.clicked.connect(lambda: self.worker.quitar_referencia())
        self.lbl_ref = QLabel("Referencia: teórica")
        btn_guardar = QPushButton("Guardar reporte")
        btn_guardar.clicked.connect(self.guardar)

        rejilla.addWidget(QLabel("Método"), 0, 0)
        rejilla.addWidget(self.combo_metodo, 0, 1, 1, 2)
        rejilla.addWidget(self.lbl_metodo, 1, 0, 1, 3)
        rejilla.addWidget(btn_analizar, 2, 0)
        rejilla.addWidget(self.chk_continuo, 2, 1, 1, 2)
        rejilla.addWidget(btn_ref, 3, 0, 1, 2)
        rejilla.addWidget(btn_sin_ref, 3, 2)
        rejilla.addWidget(self.lbl_ref, 4, 0, 1, 2)
        rejilla.addWidget(btn_guardar, 4, 2)
        derecha.addWidget(analisis)

        # --- Resultado
        resultado = QGroupBox("Resultado (θ1 / θ2 en grados; igual que la foto)")
        caja = QVBoxLayout(resultado)
        self.lbl_resumen = QLabel("-")
        self.lbl_resumen.setWordWrap(True)
        self.lbl_resumen.setStyleSheet("font-size:14px;")
        self.tabla = QTableWidget(g.FILAS, g.COLUMNAS)
        self.tabla.horizontalHeader().setVisible(False)
        self.tabla.verticalHeader().setVisible(False)
        self.tabla.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.tabla.verticalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.tabla.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tabla.setMinimumHeight(260)
        caja.addWidget(self.lbl_resumen)
        caja.addWidget(self.tabla)
        derecha.addWidget(resultado, 1)

        # --- Bitácora
        self.bitacora = QPlainTextEdit()
        self.bitacora.setReadOnly(True)
        self.bitacora.setMaximumHeight(130)
        derecha.addWidget(self.bitacora)

        self.setCentralWidget(central)

    def worker_analizar(self):
        self.worker.analizar()

    # =============================================
    # ACCIONES
    # =============================================

    def abrir_foto(self):
        ruta, _ = QFileDialog.getOpenFileName(self, "Foto del módulo", ALIGNMENT,
                                              "Imágenes (*.jpg *.jpeg *.png *.bmp)")
        if ruta:
            self.vista_camara.hide()
            self.worker.abrir_fotos(ruta)

    def abrir_carpeta(self):
        inicio = os.path.join(ALIGNMENT, "datos", "webots")
        ruta = QFileDialog.getExistingDirectory(self, "Carpeta de fotos o sesión de Webots",
                                                inicio if os.path.isdir(inicio) else ALIGNMENT)
        if ruta:
            self.vista_camara.hide()
            self.worker.abrir_fotos(ruta)

    def guardar(self):
        if self.ultimo is None or not self.ultimo[0].ok:
            self.registrar("No hay un diagnóstico válido para guardar")
            return

        d, imagen, info = self.ultimo
        marca = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        carpeta = os.path.join(ALIGNMENT, "resultados", "diagnosticos", marca)
        os.makedirs(carpeta, exist_ok=True)
        imagen.save(os.path.join(carpeta, "diagnostico.png"))

        with open(os.path.join(carpeta, "diagnostico.csv"), "w", newline="", encoding="utf-8") as archivo:
            escritor = csv.writer(archivo)
            encabezado = ["panel", "fila", "columna", "theta1_deg", "theta2_deg", "magnitud_deg",
                          "porcentaje", "estado", "fuente", "desacuerdo"]
            if info["reales"] is not None:
                encabezado += ["theta1_real", "theta2_real", "error_deg"]
            escritor.writerow(encabezado)
            for indice, fila, columna, _ in g.paneles():
                renglon = [indice, fila, columna, round(float(d.theta1[indice]), 3),
                           round(float(d.theta2[indice]), 3), round(d.magnitud[indice], 3),
                           round(d.porcentaje[indice], 1), d.estado[indice], d.fuente[indice],
                           bool(d.desacuerdo[indice])]
                if info["reales"] is not None:
                    renglon += [*info["reales"][indice], round(float(info["error"][indice]), 3)]
                escritor.writerow(renglon)

        self.registrar(f"Reporte guardado en {carpeta}")

    # =============================================
    # SEÑALES DEL HILO
    # =============================================

    def registrar(self, texto):
        self.bitacora.appendPlainText(texto)
        self.statusBar().showMessage(texto, 6000)

    def on_metodo(self, metodo, dispositivo, aviso):
        texto = f"Usando: {dict(METODOS)[metodo]} ({dispositivo})"
        if aviso:
            texto += f"\n⚠ {aviso}"
        self.lbl_metodo.setText(texto)

    def on_foto(self, posicion, total, nombre):
        self.lbl_foto.setText(f"{nombre}" + (f"  ({posicion}/{total})" if total else ""))
        es_camara = total == 0
        self.btn_anterior.setEnabled(not es_camara and total > 1)
        self.btn_siguiente.setEnabled(not es_camara and total > 1)
        self.vista_camara.setVisible(es_camara)

    def on_referencia(self, hay):
        self.lbl_ref.setText("Referencia: foto 0,0 ✔" if hay else "Referencia: teórica")

    def mostrar_camara(self, qimage):
        self.vista_camara.setPixmap(QPixmap.fromImage(qimage).scaled(
            self.vista_camara.width(), self.vista_camara.height(), Qt.KeepAspectRatio,
            Qt.SmoothTransformation))

    def _pintar(self, qimage):
        self.imagen.setPixmap(QPixmap.fromImage(qimage).scaled(
            self.imagen.width(), self.imagen.height(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def resizeEvent(self, evento):
        super().resizeEvent(evento)
        if self.ultimo is not None:
            self._pintar(self.ultimo[1])

    def mostrar_diagnostico(self, d, qimage, info):
        self.ultimo = (d, qimage, info)
        self._pintar(qimage)

        if not d.ok:
            self.lbl_resumen.setText(f"<b>No se pudo analizar:</b> {d.motivo}")
            self.tabla.clearContents()
            return

        conteo = d.conteo()
        t = d.tiempos_ms
        partes = [
            f"<b>OK {conteo['OK']}</b> · <b>REVISAR {conteo['REVISAR']}</b> · "
            f"<b>DESALINEADO {conteo['DESALINEADO']}</b>",
            f"Tiempo {t.get('total', 0):.0f} ms (preprocesado {t.get('preprocesado', 0):.0f}"
            + (f", geométrico {t['geometrico']:.0f}" if "geometrico" in t else "")
            + (f", CNN {t['cnn']:.0f}" if "cnn" in t else "") + ")",
        ]
        if d.metodo == "hibrido":
            partes.append(f"Geométrico en {d.fuente.count('geo')} de 16 · "
                          f"desacuerdos (?): {int(d.desacuerdo.sum())}")
        if info["error"] is not None:
            partes.append(f"Error contra Webots: promedio {info['error'].mean():.2f}° · "
                          f"máx {info['error'].max():.2f}°")
        self.lbl_resumen.setText("<br>".join(partes))

        for indice, fila, columna, _ in g.paneles():
            texto = (f"#{indice}  {d.estado[indice]}\n"
                     f"{d.theta1[indice]:+.1f} / {d.theta2[indice]:+.1f}")
            if info["error"] is not None:
                real = info["reales"][indice]
                texto += f"\nreal {real[0]:+.1f} / {real[1]:+.1f}"
            if d.desacuerdo is not None and d.desacuerdo[indice]:
                texto += "  ?"
            celda = QTableWidgetItem(texto)
            celda.setTextAlignment(Qt.AlignCenter)
            celda.setBackground(COLOR_ESTADO[d.estado[indice]])
            celda.setForeground(QColor(20, 20, 20))
            self.tabla.setItem(*celda_en_tabla(fila, columna), celda)

    def closeEvent(self, evento):
        self.worker.detener()
        self.worker.wait(3000)
        super().closeEvent(evento)


def main():
    app = QApplication(sys.argv)
    ventana = VentanaDiagnostico()
    ventana.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
