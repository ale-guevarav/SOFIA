"""
CREA EL MUNDO DE WEBOTS PARA EL DATASET - SOFIA

Toma el mundo normal (Webots/Sofia/worlds/sofia.wbt) y genera
sofia_dataset.wbt con lo necesario para el diagnóstico de alineación:

    - Los 16 paneles con un controlador propio (panel_dataset) que pone
      ángulos EXACTOS y reporta lo que mide un PositionSensor.
    - Marco con 4 marcadores ArUco en las esquinas, a la altura de las placas.
    - Cámara de alta resolución (supervisor dataset_generator) que cambia
      la luz y su propia posición, toma las fotos y guarda los ángulos.
    - Sin esfera ni cámara cenital (no se usan aquí).

El mundo normal NO se modifica.

Uso (desde la carpeta SOFIA):
    python Alignment/herramientas/generar_marcadores.py   (texturas)
    python Alignment/herramientas/crear_mundo_dataset.py
"""

import os
import re
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
DIAGNOSTICO = os.path.dirname(AQUI)
RAIZ = os.path.dirname(DIAGNOSTICO)
sys.path.insert(0, DIAGNOSTICO)

import geometria as g  # noqa: E402


MUNDOS = os.path.join(RAIZ, "Webots", "Sofia", "worlds")
ORIGEN = os.path.join(MUNDOS, "sofia.wbt")
DESTINO = os.path.join(MUNDOS, "sofia_dataset.wbt")

# Cámara del dataset (se mueve un poco en cada foto)
CAMARA_ALTURA = 1.35        # m sobre el piso
CAMARA_RESOLUCION = 1280    # px por lado
CAMARA_FOV = 1.0            # rad


def modificar_paneles(texto):

    # DEF PANEL_<fila>_<columna> para que el supervisor los encuentre
    texto, n = re.subn(
        r'Robot \{(\s+translation\s+[-\d. ]+\s+name\s+"Panel_(\d)_(\d)")',
        r'DEF PANEL_\2_\3 Robot {\1',
        texto,
    )
    assert n == 16, f"Se esperaban 16 paneles y hay {n}"

    # Controlador del dataset en lugar del de seguimiento
    texto, n = re.subn(r'controller "tracker_esfera_cpp"', 'controller "panel_dataset"', texto)
    assert n == 16, n

    # Un sensor de posición junto a cada motor (la "verdad" de los ángulos)
    texto, n = re.subn(
        r'(RotationalMotor\s*\{\s*name\s*"motor_(gdl\d)"[^}]*\})',
        r'\1 PositionSensor { name "sensor_\2" }',
        texto,
    )
    assert n == 32, n

    # Placas claras (contraste con el piso oscuro). DEF por si se quiere
    # cambiar su color desde el supervisor.
    texto, n = re.subn(
        r'appearance PBRAppearance \{ baseColor 0\.8 0\.8 0\.8 roughness 0\.6 \}',
        'appearance DEF PLACA_APARIENCIA PBRAppearance { baseColor 0.92 0.92 0.92 roughness 0.6 }',
        texto,
    )
    assert n == 1, n

    return texto


def modificar_suelo(texto):
    texto, n = re.subn(
        r'appearance PBRAppearance \{ baseColor 0\.7 0\.7 0\.7 roughness 1 \}',
        'appearance DEF SUELO_APARIENCIA PBRAppearance { baseColor 0.25 0.25 0.27 roughness 1 }',
        texto,
    )
    assert n == 1, n
    return texto


def quitar_esfera_y_luces(texto):
    """Todo lo que va después de los paneles (esfera, cámara, luces) se reemplaza."""
    inicio = texto.index("DEF ESFERA_TARGET Robot")
    return texto[:inicio]


def marcadores():

    bloques = []
    lado = g.LADO_CUADRO_BLANCO
    z = g.ALTURA_PLACAS - 0.001

    for id_, (x, y) in g.esquinas_mundo().items():
        bloques.append(f'''Solid {{
  translation {x:.4f} {y:.4f} {z:.4f}
  children [
    Shape {{
      appearance PBRAppearance {{
        baseColorMap ImageTexture {{ url [ "textures/aruco_{id_}.png" ] filtering 0 }}
        roughness 1
        metalness 0
      }}
      geometry Box {{ size {lado:.3f} {lado:.3f} 0.002 }}
    }}
    Transform {{
      translation 0 0 {-(z / 2):.4f}
      children [
        Shape {{
          appearance PBRAppearance {{ baseColor 0.3 0.3 0.3 roughness 1 metalness 0 }}
          geometry Box {{ size 0.02 0.02 {z - 0.002:.4f} }}
        }}
      ]
    }}
  ]
  name "aruco_{id_}"
}}
''')

    return "\n".join(bloques)


def resto_del_mundo():

    cx, cy = g.CENTRO_X, g.CENTRO_Y

    return f'''
# =============================================
# DATASET DEL DIAGNÓSTICO DE ALINEACIÓN
# (generado por Alignment/herramientas/crear_mundo_dataset.py)
# =============================================

DEF LUZ_DIRECCIONAL DirectionalLight {{
  direction -1 -1 -1
  intensity 1
  castShadows TRUE
}}

DEF LUZ_PUNTUAL PointLight {{
  location 0.3 0.3 0.5
  intensity 2
  attenuation 0 0 1
}}

# Marco: 4 marcadores ArUco a la altura de las placas
{marcadores()}
# Cámara del dataset + supervisor que genera las fotos.
# Mira hacia abajo: arriba de la imagen = +X del mundo, derecha = -Y.
DEF GENERADOR Robot {{
  translation {cx} {cy} {CAMARA_ALTURA}
  rotation 0 1 0 1.5708
  name "generador_dataset"
  controller "dataset_generator"
  supervisor TRUE
  children [
    Camera {{
      name "camara"
      fieldOfView {CAMARA_FOV}
      width {CAMARA_RESOLUCION}
      height {CAMARA_RESOLUCION}
    }}
  ]
}}
'''


def main():

    with open(ORIGEN, encoding="utf-8") as archivo:
        texto = archivo.read().replace("\r\n", "\n")

    texto = modificar_paneles(texto)
    texto = modificar_suelo(texto)
    texto = quitar_esfera_y_luces(texto)
    texto = texto.replace(
        'Viewpoint {\n  position 0.6 0.6 0.5',
        'Viewpoint {\n  position 0.9 0.9 0.9',
    )
    texto += resto_del_mundo()

    with open(DESTINO, "w", encoding="utf-8", newline="\n") as archivo:
        archivo.write(texto)

    print(f"Mundo creado: {DESTINO}")


if __name__ == "__main__":
    main()
