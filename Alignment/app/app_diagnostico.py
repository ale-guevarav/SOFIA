"""
APP DE DIAGNÓSTICO DE ALINEACIÓN - SOFIA

Ventana para PROBAR el diagnóstico:

    - Fuentes: cámara, fotos / sesión de Webots, o Webots EN VIVO.
    - Foto enderezada con una flecha por hexágono (color = estado,
      "?" = el geométrico y la CNN no coinciden; blanco = valor real).
    - Mapa 4x4 con theta1 / theta2 y el estado de cada hexágono,
      en la misma posición que en la foto.
    - Método: CNN (por defecto, la más precisa), híbrido o geométrico.
    - Webots en vivo: mover los paneles desde aquí y ver el diagnóstico
      contra los ángulos medidos en la simulación.
    - Guardar el reporte (imagen + CSV) en results/diagnosticos/.

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
    QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QGridLayout, QGroupBox,
    QHBoxLayout, QHeaderView, QLabel, QMainWindow, QPlainTextEdit, QPushButton, QScrollArea,
    QSizePolicy, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, "nucleo"))
sys.path.insert(0, AQUI)

import geometria as g  # noqa: E402
import rutas  # noqa: E402
from diagnostico_worker import CAMARA, FOTOS, SIN_FUENTE, WEBOTS, DiagnosticoWorker  # noqa: E402

METODOS = [("cnn", "CNN pequeña"), ("hibrido", "Híbrido (geométrico + CNN)"), ("geometrico", "Geométrico")]

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
        self.resize(1450, 940)

        self.ultimo = None          # (Diagnostico, QImage, info)

        self._armar()

        self.worker = DiagnosticoWorker(METODOS[0][0])
        self.worker.vista_en_vivo.connect(self.mostrar_vivo)
        self.worker.diagnostico_listo.connect(self.mostrar_diagnostico)
        self.worker.mensaje.connect(self.registrar)
        self.worker.metodo_listo.connect(self.on_metodo)
        self.worker.fuente_cambiada.connect(self.on_fuente)
        self.worker.foto_actual.connect(self.on_foto)
        self.worker.referencia_lista.connect(self.on_referencia)
        self.worker.estado_webots.connect(lambda t: self.lbl_webots.setText(f"Paneles: {t}"))
        self.worker.start()

        self.on_fuente(SIN_FUENTE)

    # =============================================
    # INTERFAZ
    # =============================================

    def _armar(self):
        central = QWidget()
        principal = QHBoxLayout(central)

        # Izquierda: foto enderezada con el diagnóstico
        self.imagen = QLabel("Abre una fuente: cámara, fotos o Webots en vivo")
        self.imagen.setAlignment(Qt.AlignCenter)
        self.imagen.setMinimumSize(640, 640)
        self.imagen.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.imagen.setStyleSheet("background:#202020; color:#ddd;")
        principal.addWidget(self.imagen, 3)

        # Derecha: controles (con scroll por si la pantalla es chica)
        contenedor = QWidget()
        derecha = QVBoxLayout(contenedor)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(contenedor)
        scroll.setMinimumWidth(470)
        principal.addWidget(scroll, 2)

        derecha.addWidget(self._grupo_fuente())
        derecha.addWidget(self._grupo_webots())
        derecha.addWidget(self._grupo_analisis())
        derecha.addWidget(self._grupo_resultado(), 1)

        self.bitacora = QPlainTextEdit()
        self.bitacora.setReadOnly(True)
        self.bitacora.setMaximumHeight(120)
        derecha.addWidget(self.bitacora)

        self.setCentralWidget(central)

    def _grupo_fuente(self):
        grupo = QGroupBox("Fuente")
        rejilla = QGridLayout(grupo)

        self.spin_camara = QSpinBox()
        self.spin_camara.setRange(0, 9)
        btn_camara = QPushButton("Abrir cámara")
        btn_camara.clicked.connect(lambda: self.worker.abrir_camara(self.spin_camara.value()))
        btn_foto = QPushButton("Abrir foto...")
        btn_foto.clicked.connect(self.abrir_foto)
        btn_carpeta = QPushButton("Abrir carpeta / sesión...")
        btn_carpeta.clicked.connect(self.abrir_carpeta)
        btn_webots = QPushButton("Webots en vivo")
        btn_webots.setToolTip("Conecta con sofia_diagnostico_vivo.wbt (la simulación debe estar corriendo)")
        btn_webots.clicked.connect(lambda: self.worker.conectar_webots())
        self.btn_cerrar = QPushButton("■ Cerrar fuente")
        self.btn_cerrar.clicked.connect(lambda: self.worker.cerrar_fuente())

        self.btn_anterior = QPushButton("◀ Anterior")
        self.btn_anterior.clicked.connect(lambda: self.worker.mover(-1))
        self.btn_siguiente = QPushButton("Siguiente ▶")
        self.btn_siguiente.clicked.connect(lambda: self.worker.mover(1))
        self.lbl_foto = QLabel("-")

        self.vista_vivo = QLabel()
        self.vista_vivo.setFixedHeight(170)
        self.vista_vivo.setAlignment(Qt.AlignCenter)

        rejilla.addWidget(QLabel("Cámara"), 0, 0)
        rejilla.addWidget(self.spin_camara, 0, 1)
        rejilla.addWidget(btn_camara, 0, 2)
        rejilla.addWidget(btn_foto, 1, 0, 1, 2)
        rejilla.addWidget(btn_carpeta, 1, 2)
        rejilla.addWidget(btn_webots, 2, 0, 1, 2)
        rejilla.addWidget(self.btn_cerrar, 2, 2)
        rejilla.addWidget(self.btn_anterior, 3, 0, 1, 2)
        rejilla.addWidget(self.btn_siguiente, 3, 2)
        rejilla.addWidget(self.lbl_foto, 4, 0, 1, 3)
        rejilla.addWidget(self.vista_vivo, 5, 0, 1, 3)
        return grupo

    def _grupo_webots(self):
        self.grupo_webots = QGroupBox("Webots en vivo")
        rejilla = QGridLayout(self.grupo_webots)

        btn_cero = QPushButton("Todo a 0,0")
        btn_cero.setToolTip("Regresa los 16 paneles a 0,0 y toma esa imagen como referencia")
        btn_cero.clicked.connect(lambda: self.worker.ordenar_webots("cero"))

        self.spin_n = QSpinBox()
        self.spin_n.setRange(1, 16)
        self.spin_n.setValue(3)
        self.spin_n.setSuffix(" paneles")
        self.spin_max = QSpinBox()
        self.spin_max.setRange(1, 27)
        self.spin_max.setValue(10)
        self.spin_max.setPrefix("hasta ")
        self.spin_max.setSuffix("°")
        btn_azar = QPushButton("Desalinear al azar")
        btn_azar.clicked.connect(lambda: self.worker.ordenar_webots(
            "azar", paneles=self.spin_n.value(), grados=self.spin_max.value()))

        self.spin_panel = QSpinBox()
        self.spin_panel.setRange(0, 15)
        self.spin_panel.setPrefix("panel ")
        self.spin_t1 = QDoubleSpinBox()
        self.spin_t2 = QDoubleSpinBox()
        for spin, nombre in ((self.spin_t1, "θ1 "), (self.spin_t2, "θ2 ")):
            spin.setRange(-27, 27)
            spin.setSingleStep(0.5)
            spin.setDecimals(1)
            spin.setPrefix(nombre)
            spin.setSuffix("°")
        btn_panel = QPushButton("Mover panel")
        btn_panel.clicked.connect(lambda: self.worker.ordenar_webots(
            "panel", panel=self.spin_panel.value(), theta1=self.spin_t1.value(), theta2=self.spin_t2.value()))

        btn_escena = QPushButton("Cámara y luz al azar")
        btn_escena.setToolTip("Mueve la cámara (±4 cm, ±4°, ±8° de giro) y cambia la luz, como en el dataset")
        btn_escena.clicked.connect(lambda: self.worker.ordenar_webots("escena", azar=True))
        btn_normal = QPushButton("Escena normal")
        btn_normal.clicked.connect(lambda: self.worker.ordenar_webots("escena", azar=False))

        self.lbl_webots = QLabel("Paneles: -")

        rejilla.addWidget(btn_cero, 0, 0)
        rejilla.addWidget(self.lbl_webots, 0, 1, 1, 3)
        rejilla.addWidget(self.spin_n, 1, 0)
        rejilla.addWidget(self.spin_max, 1, 1)
        rejilla.addWidget(btn_azar, 1, 2, 1, 2)
        rejilla.addWidget(self.spin_panel, 2, 0)
        rejilla.addWidget(self.spin_t1, 2, 1)
        rejilla.addWidget(self.spin_t2, 2, 2)
        rejilla.addWidget(btn_panel, 2, 3)
        rejilla.addWidget(btn_escena, 3, 0, 1, 2)
        rejilla.addWidget(btn_normal, 3, 2, 1, 2)
        return self.grupo_webots

    def _grupo_analisis(self):
        grupo = QGroupBox("Análisis")
        rejilla = QGridLayout(grupo)

        self.combo_metodo = QComboBox()
        for clave, nombre in METODOS:
            self.combo_metodo.addItem(nombre, clave)
        self.combo_metodo.currentIndexChanged.connect(
            lambda: self.worker.cambiar_metodo(self.combo_metodo.currentData()))
        self.lbl_metodo = QLabel("Cargando...")
        self.lbl_metodo.setWordWrap(True)

        btn_analizar = QPushButton("Analizar")
        btn_analizar.clicked.connect(lambda: self.worker.analizar())
        self.chk_continuo = QCheckBox("Continuo (cámara / Webots)")
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
        return grupo

    def _grupo_resultado(self):
        grupo = QGroupBox("Resultado (θ1 / θ2 en grados; igual que la foto)")
        caja = QVBoxLayout(grupo)
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
        return grupo

    # =============================================
    # ACCIONES
    # =============================================

    def abrir_foto(self):
        ruta, _ = QFileDialog.getOpenFileName(self, "Foto del módulo", rutas.ALIGNMENT,
                                              "Imágenes (*.jpg *.jpeg *.png *.bmp)")
        if ruta:
            self.worker.abrir_fotos(ruta)

    def abrir_carpeta(self):
        inicio = rutas.DATOS_WEBOTS if os.path.isdir(rutas.DATOS_WEBOTS) else rutas.ALIGNMENT
        ruta = QFileDialog.getExistingDirectory(self, "Carpeta de fotos o sesión de Webots", inicio)
        if ruta:
            self.worker.abrir_fotos(ruta)

    def guardar(self):
        if self.ultimo is None or not self.ultimo[0].ok:
            self.registrar("No hay un diagnóstico válido para guardar")
            return

        d, imagen, info = self.ultimo
        marca = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        carpeta = os.path.join(rutas.DIAGNOSTICOS, marca)
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
                    renglon += [round(float(v), 3) for v in info["reales"][indice]]
                    renglon.append(round(float(info["error"][indice]), 3))
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

    def on_fuente(self, fuente):
        en_vivo = fuente in (CAMARA, WEBOTS)
        self.vista_vivo.setVisible(en_vivo)
        if not en_vivo:
            self.vista_vivo.clear()
        self.btn_cerrar.setEnabled(fuente != SIN_FUENTE)
        self.btn_anterior.setEnabled(fuente == FOTOS)
        self.btn_siguiente.setEnabled(fuente == FOTOS)
        self.grupo_webots.setEnabled(fuente == WEBOTS)
        if fuente != WEBOTS:
            self.lbl_webots.setText("Paneles: -")
        if fuente == SIN_FUENTE:
            self.ultimo = None
            self.imagen.clear()
            self.imagen.setText("Abre una fuente: cámara, fotos o Webots en vivo")
            self.lbl_resumen.setText("-")
            self.tabla.clearContents()

    def on_foto(self, posicion, total, nombre):
        self.lbl_foto.setText(f"{nombre}" + (f"  ({posicion}/{total})" if total else ""))

    def on_referencia(self, hay):
        self.lbl_ref.setText("Referencia: foto 0,0 ✔" if hay else "Referencia: teórica")

    def mostrar_vivo(self, qimage):
        self.vista_vivo.setPixmap(QPixmap.fromImage(qimage).scaled(
            self.vista_vivo.width(), self.vista_vivo.height(), Qt.KeepAspectRatio,
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
            f"<b>{info['nombre']}</b>",
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
