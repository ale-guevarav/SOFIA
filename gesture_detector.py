import time

from geometry_utils import normalized_distance, angle


class GestureDetector:

    def __init__(self):

        # -----------------------------
        # CONFIGURACIÓN DE ESCUDO
        # -----------------------------

        # Distancia máxima entre cada muñeca
        # y el hombro contrario
        self.shield_distance_threshold = 1.0

        # Diferencia vertical máxima permitida entre
        # cada muñeca y el hombro contrario.
        # Se normaliza utilizando la altura del torso.
        self.shield_vertical_threshold = 0.35

        # Los codos deben estar por debajo
        # de la línea de los hombros
        self.shield_elbow_min_height = 0.15


        # -----------------------------
        # CONFIGURACIÓN DE ATAQUE
        # -----------------------------

        # Rango válido del ángulo proyectado del codo.
        # En nuestras pruebas, ATAQUE estuvo
        # aproximadamente en 48 grados.
        self.attack_elbow_angle_min = 30
        self.attack_elbow_angle_max = 70

        # Distancia horizontal máxima del codo
        # respecto al hombro.
        # Se normaliza utilizando el ancho de hombros.
        #
        # ATAQUE correcto: ~0.12 - 0.14
        # Codos abiertos: ~0.35
        self.attack_elbow_horizontal_max = 0.25

        # Diferencia máxima de profundidad
        # entre muñeca y codo.
        #
        # ATAQUE correcto: ~-0.47 / -0.48
        # Brazos normales: ~-0.15 / -0.16
        self.attack_depth_threshold = -0.30


        # -----------------------------
        # CONFIGURACIÓN DE RECARGAR
        # -----------------------------

        # Posición inicial:
        # ambas manos deben estar cerca de las caderas
        self.reload_start_threshold = 0.90

        # Posición final:
        # ambas manos deben llegar cerca de los hombros
        self.reload_end_threshold = 0.30

        # Estado interno del gesto dinámico
        self.reload_started = False

        # Guardar la posición donde comenzó el movimiento
        self.reload_start_left = None
        self.reload_start_right = None

        # Movimiento mínimo que debe recorrer cada mano
        # hacia arriba para aceptar RECARGAR
        self.reload_min_movement = 0.60

        # Tiempo máximo permitido para completar
        # el movimiento de recarga
        self.reload_max_time = 2.0

        # Momento en que comenzó la recarga
        self.reload_start_time = None

        # -----------------------------
        # CONFIGURACIÓN DE INICIO
        # -----------------------------

        # Distancia máxima para considerar
        # que las manos tocaron los muslos
        self.start_contact_threshold = 0.35

        # Distancia mínima para considerar
        # que las manos volvieron a separarse
        self.start_release_threshold = 0.42

        # Número de palmadas detectadas
        self.start_tap_count = 0

        # Indica si actualmente las manos
        # están en contacto con los muslos
        self.start_in_contact = False

        # Tiempo máximo para completar
        # las tres palmadas
        self.start_max_time = 3.0

        # Momento en que se detectó
        # la primera palmada
        self.start_first_tap_time = None

        # -----------------------------
        # CONFIGURACIÓN DE FIN
        # -----------------------------

        # Una mano debe estar por encima
        # de esta posición para poder saludar
        self.end_hand_height_threshold = 0.35

        # Desplazamiento horizontal mínimo
        # para considerar movimiento real
        self.end_min_horizontal_movement = 0.12

        # Mano que actualmente está realizando
        # el saludo: "left", "right" o None
        self.end_active_hand = None

        # Posición horizontal anterior
        self.end_previous_x = None

        # Dirección actual del movimiento
        self.end_direction = None

        # Número de cambios de dirección
        self.end_direction_changes = 0

        # Cambios de dirección necesarios
        # para reconocer la despedida
        self.end_required_direction_changes = 2


    # =============================================
    # ESCUDO
    # =============================================

    def detect_shield(self, pose_result):

        # Comprobar que exista una persona detectada
        if not pose_result.pose_landmarks:
            return False

        landmarks = pose_result.pose_landmarks[0]

        # -----------------------------
        # LANDMARKS NECESARIOS
        # -----------------------------

        left_shoulder = landmarks[11]
        right_shoulder = landmarks[12]

        left_elbow = landmarks[13]
        right_elbow = landmarks[14]

        left_wrist = landmarks[15]
        right_wrist = landmarks[16]

        left_hip = landmarks[23]
        right_hip = landmarks[24]

        # -----------------------------
        # DISTANCIA A HOMBRO CONTRARIO
        # -----------------------------

        # Muñeca izquierda hacia hombro derecho
        left_wrist_to_right_shoulder = normalized_distance(
            left_wrist,
            right_shoulder,
            left_shoulder,
            right_shoulder
        )

        # Muñeca derecha hacia hombro izquierdo
        right_wrist_to_left_shoulder = normalized_distance(
            right_wrist,
            left_shoulder,
            left_shoulder,
            right_shoulder
        )

        # -----------------------------
        # ALTURA DEL TORSO
        # -----------------------------

        shoulder_y = (
            left_shoulder.y
            + right_shoulder.y
        ) / 2

        hip_y = (
            left_hip.y
            + right_hip.y
        ) / 2

        torso_height = hip_y - shoulder_y

        # Evitar divisiones inválidas
        if torso_height <= 0:
            return False

        # -----------------------------
        # POSICIÓN VERTICAL DE CODOS
        # -----------------------------

        left_elbow_position = (
            left_elbow.y - left_shoulder.y
        ) / torso_height

        right_elbow_position = (
            right_elbow.y - right_shoulder.y
        ) / torso_height

        # -----------------------------
        # DIFERENCIA VERTICAL
        # -----------------------------

        # Diferencia vertical entre muñeca izquierda
        # y hombro derecho
        left_vertical_difference = abs(
            left_wrist.y - right_shoulder.y
        ) / torso_height

        # Diferencia vertical entre muñeca derecha
        # y hombro izquierdo
        right_vertical_difference = abs(
            right_wrist.y - left_shoulder.y
        ) / torso_height

        # -----------------------------
        # REGLA DE ESCUDO
        # -----------------------------

        # Cada muñeca debe estar cerca
        # del hombro contrario
        wrists_near_opposite_shoulders = (
            left_wrist_to_right_shoulder
            < self.shield_distance_threshold
            and
            right_wrist_to_left_shoulder
            < self.shield_distance_threshold
        )

        # Cada muñeca debe estar aproximadamente
        # a la altura del hombro contrario
        wrists_at_shoulder_height = (
            left_vertical_difference
            < self.shield_vertical_threshold
            and
            right_vertical_difference
            < self.shield_vertical_threshold
        )

        # Los codos deben estar claramente
        # por debajo de los hombros
        elbows_below_shoulders = (
            left_elbow_position
            > self.shield_elbow_min_height
            and
            right_elbow_position
            > self.shield_elbow_min_height
        )

        # -----------------------------
        # RESULTADO
        # -----------------------------

        return (
            wrists_near_opposite_shoulders
            and wrists_at_shoulder_height
            and elbows_below_shoulders
        )


    # =============================================
    # ATAQUE - GEOMETRÍA CORPORAL
    # =============================================

    def detect_attack_body(self, pose_result):

        # Comprobar que exista una persona detectada
        if not pose_result.pose_landmarks:
            return False

        landmarks = pose_result.pose_landmarks[0]

        # -----------------------------
        # LANDMARKS NECESARIOS
        # -----------------------------

        left_shoulder = landmarks[11]
        right_shoulder = landmarks[12]

        left_elbow = landmarks[13]
        right_elbow = landmarks[14]

        left_wrist = landmarks[15]
        right_wrist = landmarks[16]

        # -----------------------------
        # ÁNGULOS DE LOS CODOS
        # -----------------------------

        left_elbow_angle = angle(
            left_shoulder,
            left_elbow,
            left_wrist
        )

        right_elbow_angle = angle(
            right_shoulder,
            right_elbow,
            right_wrist
        )

        elbows_in_angle_range = (
            self.attack_elbow_angle_min
            < left_elbow_angle
            < self.attack_elbow_angle_max
            and
            self.attack_elbow_angle_min
            < right_elbow_angle
            < self.attack_elbow_angle_max
        )

        # -----------------------------
        # CODOS CERCA DEL TORSO
        # -----------------------------

        shoulder_width = abs(
            left_shoulder.x - right_shoulder.x
        )

        # Evitar división entre cero
        if shoulder_width <= 0:
            return False

        left_elbow_horizontal = abs(
            left_elbow.x - left_shoulder.x
        ) / shoulder_width

        right_elbow_horizontal = abs(
            right_elbow.x - right_shoulder.x
        ) / shoulder_width

        elbows_near_torso = (
            left_elbow_horizontal
            < self.attack_elbow_horizontal_max
            and
            right_elbow_horizontal
            < self.attack_elbow_horizontal_max
        )

        # -----------------------------
        # PROFUNDIDAD DE LAS MUÑECAS
        # -----------------------------

        left_depth_difference = (
            left_wrist.z - left_elbow.z
        )

        right_depth_difference = (
            right_wrist.z - right_elbow.z
        )

        wrists_forward = (
            left_depth_difference
            < self.attack_depth_threshold
            and
            right_depth_difference
            < self.attack_depth_threshold
        )

        # -----------------------------
        # RESULTADO
        # -----------------------------

        return (
            elbows_in_angle_range
            and elbows_near_torso
            and wrists_forward
        )

    # =============================================
    # RECARGAR - GESTO DINÁMICO
    # =============================================

    def detect_reload(self, pose_result):

        # Comprobar que exista una persona detectada
        if not pose_result.pose_landmarks:
            return False

        landmarks = pose_result.pose_landmarks[0]

        # -----------------------------
        # LANDMARKS NECESARIOS
        # -----------------------------

        left_shoulder = landmarks[11]
        right_shoulder = landmarks[12]

        left_wrist = landmarks[15]
        right_wrist = landmarks[16]

        left_hip = landmarks[23]
        right_hip = landmarks[24]

        # -----------------------------
        # ALTURA DEL TORSO
        # -----------------------------

        shoulder_y = (
            left_shoulder.y
            + right_shoulder.y
        ) / 2

        hip_y = (
            left_hip.y
            + right_hip.y
        ) / 2

        torso_height = (
            hip_y - shoulder_y
        )

        if torso_height <= 0:
            return False

        # -----------------------------
        # POSICIÓN DE LAS MUÑECAS
        # -----------------------------

        left_wrist_position = (
            left_wrist.y - shoulder_y
        ) / torso_height

        right_wrist_position = (
            right_wrist.y - shoulder_y
        ) / torso_height

        # -----------------------------
        # ZONA INICIAL
        # -----------------------------

        hands_down = (
            left_wrist_position
            > self.reload_start_threshold
            and
            right_wrist_position
            > self.reload_start_threshold
        )

        # Si todavía no ha comenzado una recarga,
        # esperar a que ambas manos estén abajo
        if not self.reload_started:

            if hands_down:
                self.reload_started = True

                self.reload_start_left = (
                    left_wrist_position
                )

                self.reload_start_right = (
                    right_wrist_position
                )

                self.reload_start_time = time.time()

            return False

        # -----------------------------
        # LÍMITE DE TIEMPO
        # -----------------------------

        elapsed_time = (
            time.time()
            - self.reload_start_time
        )

        if elapsed_time > self.reload_max_time:

            self.reload_started = False

            self.reload_start_left = None
            self.reload_start_right = None
            self.reload_start_time = None

            return False

        # -----------------------------
        # MOVIMIENTO REALIZADO
        # -----------------------------

        left_movement = (
            self.reload_start_left
            - left_wrist_position
        )

        right_movement = (
            self.reload_start_right
            - right_wrist_position
        )

        enough_movement = (
            left_movement
            > self.reload_min_movement
            and
            right_movement
            > self.reload_min_movement
        )

        # -----------------------------
        # ZONA FINAL
        # -----------------------------

        hands_up = (
            left_wrist_position
            < self.reload_end_threshold
            and
            right_wrist_position
            < self.reload_end_threshold
        )

        # -----------------------------
        # RECARGA COMPLETA
        # -----------------------------

        if (
            hands_up
            and enough_movement
        ):

            # Reiniciar estado para permitir
            # una nueva recarga posteriormente
            self.reload_started = False

            self.reload_start_left = None
            self.reload_start_right = None

            return True

        return False

    # =============================================
    # INICIO - TRES PALMADAS
    # =============================================

    def detect_start(self, pose_result):

        if not pose_result.pose_landmarks:
            return False

        landmarks = pose_result.pose_landmarks[0]

        # -----------------------------
        # LANDMARKS NECESARIOS
        # -----------------------------

        left_shoulder = landmarks[11]
        right_shoulder = landmarks[12]

        left_wrist = landmarks[15]
        right_wrist = landmarks[16]

        left_hip = landmarks[23]
        right_hip = landmarks[24]

        # -----------------------------
        # ANCHO DE HOMBROS
        # -----------------------------

        shoulder_width = abs(
            left_shoulder.x - right_shoulder.x
        )

        if shoulder_width <= 0:
            return False

        # -----------------------------
        # DISTANCIA MANO - CADERA
        # -----------------------------

        left_distance = (
            (
                (left_wrist.x - left_hip.x) ** 2
                + (left_wrist.y - left_hip.y) ** 2
            ) ** 0.5
        ) / shoulder_width

        right_distance = (
            (
                (right_wrist.x - right_hip.x) ** 2
                + (right_wrist.y - right_hip.y) ** 2
            ) ** 0.5
        ) / shoulder_width

        # -----------------------------
        # CONTACTO CON LOS MUSLOS
        # -----------------------------

        hands_in_contact = (
            left_distance
            < self.start_contact_threshold
            and
            right_distance
            < self.start_contact_threshold
        )

        # -----------------------------
        # MANOS SEPARADAS
        # -----------------------------

        hands_released = (
            left_distance
            > self.start_release_threshold
            and
            right_distance
            > self.start_release_threshold
        )

        # -----------------------------
        # LÍMITE DE TIEMPO
        # -----------------------------

        if self.start_first_tap_time is not None:

            elapsed_time = (
                time.time()
                - self.start_first_tap_time
            )

            if elapsed_time > self.start_max_time:

                self.start_tap_count = 0
                self.start_first_tap_time = None
                self.start_in_contact = False

        # -----------------------------
        # CONTAR PALMADA
        # -----------------------------

        if (
            hands_in_contact
            and not self.start_in_contact
        ):

            # Primera palmada:
            # iniciar el temporizador
            if self.start_tap_count == 0:

                self.start_first_tap_time = (
                    time.time()
                )

            self.start_tap_count += 1
            self.start_in_contact = True

            print(
                f"Palmada detectada: "
                f"{self.start_tap_count}"
            )

            # -----------------------------
            # TRES PALMADAS COMPLETADAS
            # -----------------------------

            if self.start_tap_count >= 3:

                self.start_tap_count = 0
                self.start_first_tap_time = None

                return True

        # Las manos deben separarse antes
        # de permitir una nueva palmada
        elif (
            hands_released
            and self.start_in_contact
        ):

            self.start_in_contact = False

        # Todavía no declaramos INICIO
        return False

    # =============================================
    # FIN - DESPEDIDA
    # =============================================

    def detect_end(self, pose_result):

        if not pose_result.pose_landmarks:
            return False

        landmarks = pose_result.pose_landmarks[0]

        # -----------------------------
        # LANDMARKS NECESARIOS
        # -----------------------------

        left_shoulder = landmarks[11]
        right_shoulder = landmarks[12]

        left_wrist = landmarks[15]
        right_wrist = landmarks[16]

        left_hip = landmarks[23]
        right_hip = landmarks[24]

        # -----------------------------
        # REFERENCIAS CORPORALES
        # -----------------------------

        shoulder_y = (
            left_shoulder.y
            + right_shoulder.y
        ) / 2

        hip_y = (
            left_hip.y
            + right_hip.y
        ) / 2

        torso_height = (
            hip_y - shoulder_y
        )

        shoulder_width = abs(
            left_shoulder.x
            - right_shoulder.x
        )

        if (
            torso_height <= 0
            or shoulder_width <= 0
        ):
            return False

        # -----------------------------
        # ALTURA DE LAS MANOS
        # -----------------------------

        left_height = (
            left_wrist.y - shoulder_y
        ) / torso_height

        right_height = (
            right_wrist.y - shoulder_y
        ) / torso_height

        left_raised = (
            left_height
            < self.end_hand_height_threshold
        )

        right_raised = (
            right_height
            < self.end_hand_height_threshold
        )

        # -----------------------------
        # ELEGIR MANO ACTIVA
        # -----------------------------

        if self.end_active_hand is None:

            if right_raised and not left_raised:

                self.end_active_hand = "right"

                self.end_previous_x = (
                    right_wrist.x
                    - right_shoulder.x
                ) / shoulder_width

                return False

            elif left_raised and not right_raised:

                self.end_active_hand = "left"

                self.end_previous_x = (
                    left_wrist.x
                    - left_shoulder.x
                ) / shoulder_width

                return False

            else:
                return False

        # -----------------------------
        # MANO DERECHA
        # -----------------------------

        if self.end_active_hand == "right":

            # Si baja la mano, cancelar saludo
            if not right_raised:

                self.end_active_hand = None
                self.end_previous_x = None
                self.end_direction = None
                self.end_direction_changes = 0

                return False

            current_x = (
                right_wrist.x
                - right_shoulder.x
            ) / shoulder_width

        # -----------------------------
        # MANO IZQUIERDA
        # -----------------------------

        else:

            # Si baja la mano, cancelar saludo
            if not left_raised:

                self.end_active_hand = None
                self.end_previous_x = None
                self.end_direction = None
                self.end_direction_changes = 0

                return False

            current_x = (
                left_wrist.x
                - left_shoulder.x
            ) / shoulder_width

        # -----------------------------
        # MOVIMIENTO HORIZONTAL
        # -----------------------------

        movement = (
            current_x
            - self.end_previous_x
        )

        # Ignorar movimientos pequeños
        if abs(movement) < self.end_min_horizontal_movement:
            return False

        if movement > 0:
            new_direction = "right"
        else:
            new_direction = "left"

        # -----------------------------
        # CAMBIO DE DIRECCIÓN
        # -----------------------------

        if self.end_direction is None:

            self.end_direction = new_direction

            print(
                f"Direccion inicial FIN: "
                f"{new_direction}"
            )

        elif new_direction != self.end_direction:

            self.end_direction = new_direction
            self.end_direction_changes += 1

            print(
                f"Cambio de direccion FIN: "
                f"{self.end_direction_changes}"
            )

            # -----------------------------
            # DESPEDIDA COMPLETADA
            # -----------------------------

            if (
                self.end_direction_changes
                >= self.end_required_direction_changes
            ):

                self.end_active_hand = None
                self.end_previous_x = None
                self.end_direction = None
                self.end_direction_changes = 0

                return True

        # Actualizar punto de referencia
        self.end_previous_x = current_x

        # Todavía no declaramos FIN
        return False