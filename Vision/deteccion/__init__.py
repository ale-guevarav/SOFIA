"""
DETECCIÓN - SOFIA

Todo lo que convierte un frame de la cámara en un resultado:

    vision_pipeline.py      Procesa un frame según el modo (punto de entrada)
    gesture_recognition.py  Decide la postura (con confirmación temporal)
    gesture_detector.py     Reglas geométricas de las 5 posturas
    hand_tracker.py         Posición de la mano en el plano cartesiano
    pose_detector.py        MediaPipe Pose Landmarker (cuerpo)
    hand_detector.py        MediaPipe Hand Landmarker (manos)
    pose_connections.py     Conexiones del esqueleto para dibujar
    hand_connections.py     Conexiones de los dedos para dibujar
    geometry_utils.py       Distancias y ángulos
    smoothing.py            Suavizado EMA y confirmación temporal
"""
