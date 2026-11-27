// =============================================
// SOFIA - DESALINEADO AL AZAR (prueba del diagnóstico de alineación)
// =============================================
// Programa aparte (no es el firmware del maestro). Mueve unidades a
// ángulos al azar CONOCIDOS, las deja quietas e imprime los ángulos en
// el Monitor Serie para compararlos con la tabla de la app.
//
// Mismo hardware que sofia_maestro: ESP32-C3, 2 x PCA9685 (0x40 y 0x41),
// SDA = GPIO 0, SCL = GPIO 1, OE = GPIO 5. Unidad k de cada placa:
// canal 2k = X (horizontal), 2k+1 = Y (vertical).
//
// Monitor Serie a 115200, "Sin ajuste de línea":
//   d   4 unidades al azar a ángulos al azar (las demás en 0,0)
//   D   las 16 unidades a ángulos al azar
//   r   vuelve a imprimir los ángulos
//   0   todas al centro
//
// MUESTREO: cada d / D / 0 es una MUESTRA (una foto). Se van guardando y
// al final se saca el CSV de todas de una vez:
//   f   imprime el CSV de todo el muestreo (para copiar y guardar en .csv)
//   x   borra la última muestra (si la foto salió mal o no se tomó)
//   n   empieza un muestreo nuevo (borra todas)
// Toma UNA foto por muestra, en el mismo orden, después del "Listo".
//
// Numeración igual que la app: 0 = abajo-izquierda ... 15 = arriba-derecha
// (unidad física = número + 1).
// Los ángulos que imprime están en la convención de la app:
// theta1 + = derecha de la cámara, theta2 + = arriba.
// Los servos se mueven con EMA, como las figuras del maestro.
// =============================================

#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_PWMServoDriver.h>
#include <math.h>

// -----------------------------
// HARDWARE (igual que movimiento.h del maestro)
// -----------------------------
const int SDA_PIN = 0;
const int SCL_PIN = 1;
const int OE_PIN  = 5;                 // LOW = salidas habilitadas
const uint32_t I2C_HZ = 100000;

const int NUM_PLACAS = 2;
const int UNIDADES_POR_PLACA = 8;
const int NUM_UNIDADES = NUM_PLACAS * UNIDADES_POR_PLACA;   // 16

const float THETA_MIN = -60.0f;
const float THETA_MAX =  60.0f;
const int PWM_EN_THETA_MIN = 385;      // cuentas del PCA9685 en -60°
const int PWM_EN_THETA_MAX = 225;      // cuentas del PCA9685 en +60°

const bool INVERTIR_X = false;
const bool INVERTIR_Y = false;
const float AJUSTE_X[NUM_UNIDADES] = {0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0};
const float AJUSTE_Y[NUM_UNIDADES] = {0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0};

// -----------------------------
// PRUEBA
// -----------------------------
const float DESALINEO_MAX = 10.0f;     // ° por eje, como máximo
const float DESALINEO_MIN = 2.0f;      // ° de inclinación mínima de las elegidas
const int   DESALINEO_N   = 4;         // unidades con 'd' (con 'D' son las 16)

// Servo -> ángulos de la app (igual que Alignment/app/nucleo/ceros.py):
// +X del servo inclina a la DERECHA, +Y inclina hacia ABAJO
const float SERVO_X_POR_THETA1 = +1.0f;
const float SERVO_Y_POR_THETA2 = -1.0f;

// Movimiento: EMA como el maestro (K_SUAVIZADO). Si el ESP32 se reinicia
// por corriente con 'D' (16 a la vez), pon USAR_EMA en false: vuelven los
// turnos de POR_TURNO unidades a VELOCIDAD
const bool  USAR_EMA    = true;
const float K_SUAVIZADO = 0.33f;
const float LLEGADA_EMA = 0.05f;       // ° : más cerca que esto ya "llegó"
const float VELOCIDAD = 60.0f;         // °/s (solo sin EMA)
const int   POR_TURNO = 4;             // unidades por paso (solo sin EMA)
const unsigned long TS_MS = 20;        // paso de control

// -----------------------------
// ESTADO
// -----------------------------
Adafruit_PWMServoDriver* placas[NUM_PLACAS] = {nullptr, nullptr};
int placasEncontradas = 0;

float actualX[NUM_UNIDADES], actualY[NUM_UNIDADES];     // ° del servo, donde está
float objetivoX[NUM_UNIDADES], objetivoY[NUM_UNIDADES]; // ° de la app (theta1, theta2)
int siguienteTurno = 0;
bool avisado = true;
unsigned long ultimoPaso = 0;

// Muestreo (décimas de grado, para que quepan muchas)
const int MAX_MUESTRAS = 400;
int16_t muestraX[MAX_MUESTRAS][NUM_UNIDADES];
int16_t muestraY[MAX_MUESTRAS][NUM_UNIDADES];
char tipoMuestra[MAX_MUESTRAS];        // 'd', 'D' o '0'
int numMuestras = 0;

// =============================================
// SERVOS
// =============================================

int theta_a_pwm(float theta) {
  if (theta < THETA_MIN) theta = THETA_MIN;
  if (theta > THETA_MAX) theta = THETA_MAX;
  float m = (float)(PWM_EN_THETA_MAX - PWM_EN_THETA_MIN) / (THETA_MAX - THETA_MIN);
  return (int)roundf(PWM_EN_THETA_MIN + m * (theta - THETA_MIN));
}

void escribirUnidad(int u) {
  int b = u / UNIDADES_POR_PLACA;
  int k = u % UNIDADES_POR_PLACA;
  if (b >= placasEncontradas) return;
  float tx = (INVERTIR_X ? -actualX[u] : actualX[u]) + AJUSTE_X[u];
  float ty = (INVERTIR_Y ? -actualY[u] : actualY[u]) + AJUSTE_Y[u];
  placas[b]->setPWM(2 * k,     0, theta_a_pwm(tx));
  placas[b]->setPWM(2 * k + 1, 0, theta_a_pwm(ty));
}

void iniciarServos() {
  pinMode(OE_PIN, OUTPUT);
  digitalWrite(OE_PIN, LOW);
  Wire.begin(SDA_PIN, SCL_PIN);
  Wire.setClock(I2C_HZ);

  // Busca PCA9685 (0x70 es "todas las placas" y se salta)
  uint8_t encontradas[NUM_PLACAS];
  int n = 0;
  for (uint8_t dir = 0x40; dir <= 0x7F && n < NUM_PLACAS; dir++) {
    if (dir == 0x70) continue;
    Wire.beginTransmission(dir);
    if (Wire.endTransmission() == 0) encontradas[n++] = dir;
  }

  for (int b = 0; b < n; b++) {
    Adafruit_PWMServoDriver* placa = new Adafruit_PWMServoDriver(encontradas[b]);
    if (!placa->begin()) { delete placa; continue; }
    placa->setOscillatorFrequency(27000000);
    placa->setPWMFreq(50);
    placas[placasEncontradas++] = placa;
    Serial.printf("PCA9685 en 0x%02X -> numeros %d-%d\n", encontradas[b],
                  (placasEncontradas - 1) * UNIDADES_POR_PLACA,
                  placasEncontradas * UNIDADES_POR_PLACA - 1);
  }

  for (int u = 0; u < NUM_UNIDADES; u++) {
    actualX[u] = actualY[u] = objetivoX[u] = objetivoY[u] = 0.0f;
  }

  delay(300);
  // Centrar de una en una (evita el pico de corriente)
  for (int u = 0; u < placasEncontradas * UNIDADES_POR_PLACA; u++) {
    escribirUnidad(u);
    delay(150);
  }
}

// =============================================
// DESALINEADO AL AZAR
// =============================================

float azarEntre(float a, float b) {
  return a + (b - a) * (esp_random() / 4294967295.0f);
}

void imprimirAngulos() {
  Serial.println("[DESALINEO] Angulos (theta1 / theta2 en grados, como la tabla de la app):");
  for (int fila = 3; fila >= 0; fila--) {
    Serial.print("   ");
    for (int col = 0; col < 4; col++) {
      int u = fila * 4 + col;
      Serial.printf("#%-2d %+5.1f / %+5.1f    ", u, objetivoX[u], objetivoY[u]);
    }
    Serial.println();
  }
  Serial.print("[DESALINEO] CSV ");
  for (int u = 0; u < NUM_UNIDADES; u++) {
    Serial.printf("%d,%.1f,%.1f%s", u, objetivoX[u], objetivoY[u], u < NUM_UNIDADES - 1 ? ";" : "\n");
  }
}

void guardarMuestra(char tipo) {
  if (numMuestras >= MAX_MUESTRAS) {
    Serial.printf("[MUESTREO] Ya hay %d muestras (el máximo): pica f para sacar el CSV y n para empezar otro\n",
                  MAX_MUESTRAS);
    return;
  }
  for (int u = 0; u < NUM_UNIDADES; u++) {
    muestraX[numMuestras][u] = (int16_t)lroundf(objetivoX[u] * 10.0f);
    muestraY[numMuestras][u] = (int16_t)lroundf(objetivoY[u] * 10.0f);
  }
  tipoMuestra[numMuestras] = tipo;
  numMuestras++;
  Serial.printf("[MUESTREO] Muestra %d guardada (foto numero %d)\n", numMuestras - 1, numMuestras);
}

void imprimirCSV() {
  if (numMuestras == 0) {
    Serial.println("[MUESTREO] No hay muestras todavia");
    return;
  }
  Serial.println();
  Serial.printf("----- CSV: %d muestras (copia desde 'muestra,' hasta antes de 'FIN') -----\n", numMuestras);
  Serial.println("muestra,foto,tipo,numero,theta1_deg,theta2_deg");
  for (int m = 0; m < numMuestras; m++) {
    for (int u = 0; u < NUM_UNIDADES; u++) {
      Serial.printf("%d,%d,%c,%d,%.1f,%.1f\n", m, m + 1, tipoMuestra[m], u,
                    muestraX[m][u] / 10.0f, muestraY[m][u] / 10.0f);
    }
  }
  Serial.println("----- FIN -----");
  Serial.println("[MUESTREO] Guarda eso como muestreo.csv junto con las fotos (foto 1 = muestra 0, ...)");
}

void desalinear(bool todas) {
  int n = placasEncontradas * UNIDADES_POR_PLACA;
  if (n == 0) {
    Serial.println("[DESALINEO] No hay placas PCA9685");
    return;
  }
  int cuantas = todas ? n : (DESALINEO_N < n ? DESALINEO_N : n);

  bool elegida[NUM_UNIDADES] = {false};
  for (int k = 0; k < cuantas; ) {
    int u = esp_random() % n;
    if (!elegida[u]) { elegida[u] = true; k++; }
  }

  for (int u = 0; u < NUM_UNIDADES; u++) {
    objetivoX[u] = 0.0f;
    objetivoY[u] = 0.0f;
    if (elegida[u]) {
      float x, y;
      do {   // redondeado a 0.5°
        x = roundf(azarEntre(-DESALINEO_MAX, DESALINEO_MAX) * 2.0f) / 2.0f;
        y = roundf(azarEntre(-DESALINEO_MAX, DESALINEO_MAX) * 2.0f) / 2.0f;
      } while (hypotf(x, y) < DESALINEO_MIN);
      objetivoX[u] = x;
      objetivoY[u] = y;
    }
  }

  avisado = false;
  guardarMuestra(todas ? 'D' : 'd');
  Serial.printf("[DESALINEO] %d unidades al azar (max %.0f grados por eje). Moviendo...\n",
                cuantas, DESALINEO_MAX);
  imprimirAngulos();
}

void alCentro() {
  for (int u = 0; u < NUM_UNIDADES; u++) objetivoX[u] = objetivoY[u] = 0.0f;
  avisado = false;
  guardarMuestra('0');
  Serial.println("[DESALINEO] Al centro...");
}

// =============================================
// MOVIMIENTO (EMA, o por turnos si USAR_EMA = false)
// =============================================
// Por turnos: cada paso solo POR_TURNO unidades que no han llegado dan
// un salto; el salto se agranda para que el promedio siga siendo VELOCIDAD

// Objetivo del servo (los objetivos se guardan en ángulos de la app)
float servoX(int u) { return objetivoX[u] * SERVO_X_POR_THETA1; }
float servoY(int u) { return objetivoY[u] * SERVO_Y_POR_THETA2; }

bool falta(int u) {
  return fabsf(servoX(u) - actualX[u]) > LLEGADA_EMA || fabsf(servoY(u) - actualY[u]) > LLEGADA_EMA;
}

// EMA: todas las que faltan se acercan K_SUAVIZADO de lo que les queda
void pasoEMA(int n) {
  for (int u = 0; u < n; u++) {
    if (!falta(u)) continue;
    actualX[u] += (servoX(u) - actualX[u]) * K_SUAVIZADO;
    actualY[u] += (servoY(u) - actualY[u]) * K_SUAVIZADO;
    if (!falta(u)) {
      actualX[u] = servoX(u);
      actualY[u] = servoY(u);
    }
    escribirUnidad(u);
  }
}

void pasoMovimiento() {
  int n = placasEncontradas * UNIDADES_POR_PLACA;
  int pendientes = 0;
  for (int u = 0; u < n; u++) if (falta(u)) pendientes++;

  if (pendientes == 0) {
    if (!avisado) {
      avisado = true;
      Serial.printf("[DESALINEO] Listo: todas quietas, ya puedes tomar la FOTO %d\n", numMuestras);
    }
    return;
  }

  if (USAR_EMA) {
    pasoEMA(n);
    return;
  }

  int rondas = (pendientes + POR_TURNO - 1) / POR_TURNO;
  float salto = VELOCIDAD * (TS_MS / 1000.0f) * rondas;
  if (salto > 5.0f) salto = 5.0f;

  int movidas = 0;
  for (int i = 0; i < n && movidas < POR_TURNO; i++) {
    int u = (siguienteTurno + i) % n;
    if (!falta(u)) continue;
    float dx = servoX(u) - actualX[u];
    float dy = servoY(u) - actualY[u];
    float d = sqrtf(dx * dx + dy * dy);
    if (d <= salto) {
      actualX[u] = servoX(u);
      actualY[u] = servoY(u);
    } else {
      actualX[u] += dx / d * salto;
      actualY[u] += dy / d * salto;
    }
    escribirUnidad(u);
    movidas++;
    siguienteTurno = (u + 1) % n;
  }
}

// =============================================
// SETUP / LOOP
// =============================================

void setup() {
  Serial.begin(115200);
  delay(500);
  Serial.println("\n=== SOFIA - DESALINEADO AL AZAR ===");
  iniciarServos();
  if (placasEncontradas == 0) {
    Serial.println("ERROR: ningun PCA9685 detectado");
  }
  Serial.println("Teclas: d = 4 al azar, D = las 16, r = imprimir, 0 = al centro");
  Serial.println("Muestreo: f = sacar el CSV de todas, x = borrar la ultima, n = empezar otro");
}

void loop() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == 'd')                  desalinear(false);
    else if (c == 'D')             desalinear(true);
    else if (c == 'r' || c == 'R') imprimirAngulos();
    else if (c == '0')             alCentro();
    else if (c == 'f' || c == 'F') imprimirCSV();
    else if (c == 'x' || c == 'X') {
      if (numMuestras > 0) {
        numMuestras--;
        Serial.printf("[MUESTREO] Borrada la muestra %d (quedan %d)\n", numMuestras, numMuestras);
      }
    }
    else if (c == 'n' || c == 'N') {
      numMuestras = 0;
      Serial.println("[MUESTREO] Muestreo nuevo: 0 muestras");
    }
  }

  if (millis() - ultimoPaso >= TS_MS) {
    ultimoPaso = millis();
    pasoMovimiento();
  }
}
