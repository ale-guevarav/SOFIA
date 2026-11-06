"""
RUTAS - SOFIA (diagnóstico de alineación)

Todas las carpetas del proyecto en un solo lugar:

    Alignment/
    ├── app/       lo que corre la app (este núcleo lo usa también build/)
    ├── build/     generar datos, entrenar, evaluar y publicar
    │   ├── datos/webots/<sesión>/      fotos de Webots (no se suben)
    │   └── entrenados/<modelo>_<sesión>/  pesos (no se suben), historial y curvas
    └── results/   lo que sale del build y usa la app
        ├── modelo/cnn.pt              modelo publicado (sí se sube)
        ├── evaluaciones/<método>_<sesión>_<conjunto>/
        └── diagnosticos/              reportes guardados desde la app (no se suben)
"""

import glob
import os
import sys

NUCLEO = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(NUCLEO)
ALIGNMENT = os.path.dirname(APP)
RAIZ = os.path.dirname(ALIGNMENT)                 # carpeta SOFIA

BUILD = os.path.join(ALIGNMENT, "build")
DATOS_WEBOTS = os.path.join(BUILD, "datos", "webots")
ENTRENADOS = os.path.join(BUILD, "entrenados")

RESULTS = os.path.join(ALIGNMENT, "results")
CARPETA_MODELO = os.path.join(RESULTS, "modelo")
MODELO_PUBLICADO = os.path.join(CARPETA_MODELO, "cnn.pt")
EVALUACIONES = os.path.join(RESULTS, "evaluaciones")
DIAGNOSTICOS = os.path.join(RESULTS, "diagnosticos")


def ultima_sesion():
    """Carpeta de la sesión de Webots más reciente."""
    sesiones = sorted(glob.glob(os.path.join(DATOS_WEBOTS, "sesion_*")))
    if not sesiones:
        sys.exit(f"No hay sesiones en {DATOS_WEBOTS}. Genera una en Webots primero.")
    return sesiones[-1]


def resolver_sesion(ruta):
    """
    Una sesión guardada con su ruta completa (por ejemplo dentro de un
    modelo.pt) puede ya no existir si se movieron las carpetas: se busca
    por nombre en build/datos/webots/.
    """
    if ruta and os.path.isdir(ruta):
        return ruta
    candidata = os.path.join(DATOS_WEBOTS, os.path.basename(os.path.normpath(str(ruta))))
    if os.path.isdir(candidata):
        return candidata
    sys.exit(f"No se encontró la sesión {ruta} (ni en {DATOS_WEBOTS})")


def ultima_cnn_entrenada():
    """modelo.pt de la CNN entrenada más reciente en esta PC, o None."""
    entrenados = sorted(glob.glob(os.path.join(ENTRENADOS, "cnn_*", "modelo.pt")), key=os.path.getmtime)
    return entrenados[-1] if entrenados else None
