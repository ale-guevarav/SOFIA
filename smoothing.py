class SmoothedLandmark:

    def __init__(self, x, y, z, visibility=1.0):

        self.x = x
        self.y = y
        self.z = z
        self.visibility = visibility


class LandmarkSmoother:

    def __init__(self, alpha=0.3):

        # Factor de suavizado
        self.alpha = alpha

        # Coordenadas suavizadas anteriores
        self.previous_landmarks = None


    def smooth(self, landmarks):

        # -----------------------------
        # PRIMER FRAME
        # -----------------------------

        if self.previous_landmarks is None:

            smoothed_landmarks = [
                SmoothedLandmark(
                    landmark.x,
                    landmark.y,
                    landmark.z,
                    getattr(landmark, "visibility", 1.0)
                )
                for landmark in landmarks
            ]

            self.previous_landmarks = (
                smoothed_landmarks
            )

            return smoothed_landmarks

        # -----------------------------
        # EMA
        # -----------------------------

        smoothed_landmarks = []

        for index, landmark in enumerate(landmarks):

            previous = (
                self.previous_landmarks[index]
            )

            smooth_x = (
                self.alpha * landmark.x
                + (1 - self.alpha) * previous.x
            )

            smooth_y = (
                self.alpha * landmark.y
                + (1 - self.alpha) * previous.y
            )

            smooth_z = (
                self.alpha * landmark.z
                + (1 - self.alpha) * previous.z
            )

            smoothed_landmarks.append(
                SmoothedLandmark(
                    smooth_x,
                    smooth_y,
                    smooth_z,
                    getattr(
                        landmark,
                        "visibility",
                        1.0
                    )
                )
            )

        self.previous_landmarks = (
            smoothed_landmarks
        )

        return smoothed_landmarks


    def reset(self):

        self.previous_landmarks = None