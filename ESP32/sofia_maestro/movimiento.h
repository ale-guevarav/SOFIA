/*
 * =============================================================
 *  SOFIA - MOVIMIENTO DE UNA UNIDAD (2 SERVOS, 2 GDL)
 * =============================================================
 *
 *  Cada postura detectada por visión dibuja un patrón con la
 *  unidad. El servo X (canal 0) mueve en horizontal y el
 *  servo Y (canal 1) en vertical:
 *
 *      1 INICIO    -> círculo (2 vueltas)
 *      2 RECARGAR  -> cuadrado (2 vueltas)
 *      3 ESCUDO    -> una X
 *      4 ATAQUE    -> línea arriba-abajo (3 veces)
 *      5 FIN       -> zigzag de izquierda a derecha
 *
 *  Al terminar cada patrón la unidad regresa al centro.
 *
 *  En modo TRACKING la unidad apunta hacia la posición
 *  de la mano que manda la PC.
 *
 *  Hardware y calibración tomados de las pruebas de
 *  mecatrónica (Prueba_Servos / SG90_WindowVelocity_PCA).
 * =============================================================
 */

#pragma once

#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_PWMServoDriver.h>
#include <math.h>

// =============================================
// HARDWARE (igual que las pruebas de mecatrónica)
// =============================================

// ESP32-C3 + PCA9685
const int SDA_PIN = 0;
const int SCL_PIN = 1;
const int OE_PIN  = 5;     // LOW = salidas del PCA9685 habilitadas

const uint8_t PCA9685_ADDR = 0x40;

const int CANAL_SERVO_X = 0;   // Horizontal (izquierda / derecha)
const int CANAL_SERVO_Y = 1;   // Vertical (arriba / abajo)

// =============================================
// CALIBRACIÓN (de SG90_WindowVelocity_PCA)
// =============================================

const float THETA_MIN = -60.0f;   // grados
const float THETA_MAX =  60.0f;

const int PWM_EN_THETA_MIN = 385;   // cuentas del PCA9685 en -60°
const int PWM_EN_THETA_MAX = 225;   // cuentas del PCA9685 en +60°

// Si un eje se mueve al revés de lo esperado,
// cambiar a true (no hace falta tocar nada más)
const bool INVERTIR_X = false;
const bool INVERTIR_Y = false;

// =============================================
// PARÁMETROS DE MOVIMIENTO
// =============================================

// Periodo de control: 20 ms (igual que las pruebas)
const unsigned long TS_US = 20000UL;
const float TS_S = 0.020f;

// Tamaño de los patrones: grados desde el centro
const float AMPLITUD = 35.0f;

// Velocidades (grados/segundo). Las pruebas de
// mecatrónica llegaron hasta 600 °/s; se usa un
// valor holgado para que el movimiento se vea limpio
const float VEL_PATRON  = 120.0f;
const float VEL_REGRESO = 90.0f;
const float VEL_TRACK   = 300.0f;

// TRACKING: grados de giro cuando la mano está
// en el borde de la imagen (x_norm o y_norm = ±1)
const float RANGO_TRACK = 45.0f;

// Si en TRACKING no llega posición en este tiempo,
// la unidad regresa al centro
const unsigned long TRACK_TIMEOUT_MS = 1500UL;

// No se reenvía al PCA9685 si el cambio es menor a esto
const float E_QUANT = 0.10f;

// =============================================
// TIPOS Y ESTADO
// =============================================

struct Punto {
  float x;
  float y;
};

enum EstadoMovimiento {
  QUIETO,
  PATRON,
  SIGUIENDO_MANO,
  REGRESANDO,
};

const char* NOMBRES_PATRON[] = {
  "CENTRO", "CIRCULO", "CUADRADO", "X", "LINEA ARRIBA-ABAJO", "ZIGZAG"
};

Adafruit_PWMServoDriver pwm = Adafruit_PWMServoDriver(PCA9685_ADDR);

EstadoMovimiento estado = QUIETO;

// Posición actual y última enviada (grados)
float posX = 0.0f, posY = 0.0f;
float enviadoX = -1000.0f, enviadoY = -1000.0f;

// Trayectoria: lista de puntos a recorrer (grados)
const int MAX_PUNTOS = 160;
Punto ruta[MAX_PUNTOS];
int numPuntos = 0;
int indicePunto = 0;
float velocidadRuta = VEL_PATRON;
int patronActual = 0;

// Objetivo en TRACKING
Punto objetivoMano = {0.0f, 0.0f};
unsigned long ultimoTrackMs = 0;

unsigned long tControlUs = 0;

// =============================================
// SERVOS
// =============================================

float saturar(float x, float xmin, float xmax) {
  if (x < xmin) return xmin;
  if (x > xmax) return xmax;
  return x;
}

int theta_a_pwm(float theta) {
  theta = saturar(theta, THETA_MIN, THETA_MAX);

  float m = (float)(PWM_EN_THETA_MAX - PWM_EN_THETA_MIN) / (THETA_MAX - THETA_MIN);

  return (int)roundf(PWM_EN_THETA_MIN + m * (theta - THETA_MIN));
}

void aplicarServos(bool forzar = false) {
  if (!forzar &&
      fabsf(posX - enviadoX) < E_QUANT &&
      fabsf(posY - enviadoY) < E_QUANT) {
    return;
  }

  float thetaX = INVERTIR_X ? -posX : posX;
  float thetaY = INVERTIR_Y ? -posY : posY;

  pwm.setPWM(CANAL_SERVO_X, 0, theta_a_pwm(thetaX));
  pwm.setPWM(CANAL_SERVO_Y, 0, theta_a_pwm(thetaY));

  enviadoX = posX;
  enviadoY = posY;
}

bool iniciarServos() {
  // Mismo orden que las pruebas de mecatrónica
  pinMode(OE_PIN, OUTPUT);
  digitalWrite(OE_PIN, LOW);

  Wire.begin(SDA_PIN, SCL_PIN);

  if (!pwm.begin()) {
    return false;
  }

  pwm.setOscillatorFrequency(27000000);
  pwm.setPWMFreq(50);
  delay(300);

  posX = 0.0f;
  posY = 0.0f;
  aplicarServos(true);

  tControlUs = micros();
  return true;
}

// =============================================
// CONSTRUCCIÓN DE RUTAS
// =============================================

void agregarPunto(float x, float y) {
  if (numPuntos < MAX_PUNTOS) {
    ruta[numPuntos++] = {x, y};
  }
}

// Agrega una figura (coordenadas de -1 a 1) escalada
// a AMPLITUD, repetida 'vueltas' veces
void agregarFigura(const Punto* figura, int n, int vueltas) {
  for (int v = 0; v < vueltas; v++) {
    for (int i = 0; i < n; i++) {
      agregarPunto(figura[i].x * AMPLITUD, figura[i].y * AMPLITUD);
    }
  }
}

// -----------------------------
// FIGURAS (coordenadas normalizadas)
// -----------------------------

// 2 RECARGAR: cuadrado
const Punto FIG_CUADRADO[] = {
  {-1, -1}, {-1, 1}, {1, 1}, {1, -1}, {-1, -1},
};

// 3 ESCUDO: X (las dos diagonales cruzando por el centro)
const Punto FIG_X[] = {
  {-1, 1}, {1, -1}, {0, 0}, {1, 1}, {-1, -1},
};

// 4 ATAQUE: línea arriba-abajo
const Punto FIG_LINEA[] = {
  {0, 1}, {0, -1},
};

// 5 FIN: zigzag de izquierda a derecha
const Punto FIG_ZIGZAG[] = {
  {-1, 0}, {-0.6f, 0.7f}, {-0.2f, -0.7f}, {0.2f, 0.7f}, {0.6f, -0.7f}, {1, 0},
};

#define N_FIG(f) ((int)(sizeof(f) / sizeof(f[0])))

void agregarCirculo(int vueltas) {
  const int PASOS = 36;   // un punto cada 10°
  for (int v = 0; v < vueltas; v++) {
    for (int i = 0; i <= PASOS; i++) {
      float a = 2.0f * PI * i / PASOS;
      agregarPunto(cosf(a) * AMPLITUD, sinf(a) * AMPLITUD);
    }
  }
}

// =============================================
// COMANDOS DE MOVIMIENTO
// =============================================

void irAlCentro() {
  numPuntos = 0;
  indicePunto = 0;
  agregarPunto(0.0f, 0.0f);

  velocidadRuta = VEL_REGRESO;
  patronActual = 0;
  estado = REGRESANDO;
}

// pose: 1 INICIO, 2 RECARGAR, 3 ESCUDO, 4 ATAQUE, 5 FIN
void iniciarPatron(uint8_t pose) {
  numPuntos = 0;
  indicePunto = 0;

  switch (pose) {
    case 1: agregarCirculo(2);                          break;
    case 2: agregarFigura(FIG_CUADRADO, N_FIG(FIG_CUADRADO), 2); break;
    case 3: agregarFigura(FIG_X, N_FIG(FIG_X), 1);      break;
    case 4: agregarFigura(FIG_LINEA, N_FIG(FIG_LINEA), 3); break;
    case 5: agregarFigura(FIG_ZIGZAG, N_FIG(FIG_ZIGZAG), 1); break;
    default: irAlCentro(); return;
  }

  // Siempre termina en el centro
  agregarPunto(0.0f, 0.0f);

  velocidadRuta = VEL_PATRON;
  patronActual = pose;
  estado = PATRON;

  Serial.printf("[MOV] Patron: %s (%d puntos)\n", NOMBRES_PATRON[pose], numPuntos);
}

// x_norm, y_norm: -1 a 1 (centro de la imagen = 0)
void seguirMano(float xNorm, float yNorm) {
  objetivoMano.x = saturar(xNorm, -1.0f, 1.0f) * RANGO_TRACK;
  objetivoMano.y = saturar(yNorm, -1.0f, 1.0f) * RANGO_TRACK;
  ultimoTrackMs = millis();
  estado = SIGUIENDO_MANO;
}

bool enMovimiento() {
  return estado == PATRON || estado == REGRESANDO;
}

// =============================================
// AVANCE HACIA UN PUNTO (velocidad constante)
// Regresa true si ya llegó
// =============================================

bool avanzarHacia(float x, float y, float velocidad) {
  float dx = x - posX;
  float dy = y - posY;
  float distancia = sqrtf(dx * dx + dy * dy);
  float paso = velocidad * TS_S;

  if (distancia <= paso) {
    posX = x;
    posY = y;
    return true;
  }

  posX += dx / distancia * paso;
  posY += dy / distancia * paso;
  return false;
}

// =============================================
// ACTUALIZAR (llamar en cada loop; corre cada 20 ms)
// =============================================

void actualizarMovimiento() {
  unsigned long ahora = micros();

  if ((unsigned long)(ahora - tControlUs) < TS_US) {
    return;
  }
  tControlUs += TS_US;

  // Si el loop se atrasó mucho, no intentar "alcanzar"
  if ((unsigned long)(ahora - tControlUs) > 5 * TS_US) {
    tControlUs = ahora;
  }

  switch (estado) {

    case PATRON:
    case REGRESANDO:
      if (avanzarHacia(ruta[indicePunto].x, ruta[indicePunto].y, velocidadRuta)) {
        indicePunto++;
        if (indicePunto >= numPuntos) {
          if (estado == PATRON) {
            Serial.printf("[MOV] Patron %s terminado\n", NOMBRES_PATRON[patronActual]);
          }
          estado = QUIETO;
        }
      }
      break;

    case SIGUIENDO_MANO:
      if (millis() - ultimoTrackMs > TRACK_TIMEOUT_MS) {
        Serial.println("[MOV] Sin posicion de mano: regreso al centro");
        irAlCentro();
      } else {
        avanzarHacia(objetivoMano.x, objetivoMano.y, VEL_TRACK);
      }
      break;

    case QUIETO:
      break;
  }

  aplicarServos();
}
