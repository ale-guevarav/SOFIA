/*
 * =============================================================
 *  SOFIA - MOVIMIENTO DEL MÓDULO (16 UNIDADES, 2 PCA9685)
 * =============================================================
 *
 *  El módulo tiene 16 unidades de 2 servos (32 servos) en dos
 *  PCA9685 del mismo bus I2C, 8 unidades por placa:
 *
 *      placa 1 (dirección menor)  -> unidades 1-8
 *      placa 2                    -> unidades 9-16
 *      en cada placa: canal 0 = X y 1 = Y de su primera unidad,
 *                     canal 2 = X y 3 = Y de la segunda, etc.
 *
 *  Cada postura hace que las 16 unidades dibujen la misma figura
 *  POR TURNOS: unas 3 a la vez y desfasadas (una casi acabando,
 *  otra a la mitad, otra empezando) mientras la que ya terminó
 *  regresa al centro. Así nunca se mueven los 32 servos juntos
 *  (menos corriente) y por I2C solo viajan los canales de las
 *  unidades que se están moviendo. El servo X mueve en
 *  horizontal y el servo Y en vertical:
 *
 *      1 INICIO    -> círculo
 *      2 RECARGAR  -> cuadrado
 *      3 ESCUDO    -> una X
 *      4 ATAQUE    -> línea arriba-abajo (2 veces)
 *      5 FIN       -> zigzag de izquierda a derecha
 *
 *  Todas las figuras son UNA lista de puntos compartida; cada
 *  unidad solo guarda en qué punto va (pocos bytes por unidad).
 *
 *  En modo TRACKING las 16 apuntan juntas hacia la mano.
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

// ESP32-C3 SuperMini + 2 PCA9685 en el mismo bus I2C.
// Pines según la PCB de SOFIA (PCB/SOFIA_PCB en main):
//   GPIO 0 = SDA, GPIO 1 = SCL, GPIO 3 = OE (conectores J1 y J2)
//   GPIO 5 y 6 = RX/TX del MAX485 (no se usan aquí: no tocarlos)
const int SDA_PIN = 0;
const int SCL_PIN = 1;
const int OE_PIN  = 5;     // LOW = salidas de los PCA9685 habilitadas

// 100 kHz, igual que las pruebas de mecatrónica (lo más seguro con
// cables largos entre placas). Como solo se escriben las unidades que
// se mueven (~3), alcanza de sobra dentro de los 20 ms del periodo
const uint32_t I2C_HZ = 100000;

// Direcciones si no se pueden detectar solas. Al arrancar se
// buscan los PCA9685 en el bus y se usan en orden de dirección
// (la segunda placa debe tener puenteado A0 u otro jumper)
const int NUM_PLACAS = 2;
const uint8_t PCA_DIRECCIONES_DEFAULT[NUM_PLACAS] = {0x40, 0x41};

const int UNIDADES_POR_PLACA = 8;
const int NUM_UNIDADES = NUM_PLACAS * UNIDADES_POR_PLACA;   // 16

// Canales de la unidad k (0-7) dentro de su placa
inline int canalX(int k) { return 2 * k; }       // Horizontal
inline int canalY(int k) { return 2 * k + 1; }   // Vertical

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

// Ajuste fino por unidad (grados que se suman a su centro), por si
// alguna placa no queda plana en 0°. Unidad 1 = posición 0
const float AJUSTE_X[NUM_UNIDADES] = {0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0};
const float AJUSTE_Y[NUM_UNIDADES] = {0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0};

// Al arrancar se centran las unidades de una en una con esta pausa,
// para no pedir la corriente de los 32 servos al mismo tiempo
const int PAUSA_ARRANQUE_MS = 1000;

// =============================================
// PARÁMETROS DE MOVIMIENTO
// =============================================

// Periodo de control: 20 ms (igual que las pruebas)
const unsigned long TS_US = 20000UL;
const float TS_S = 0.020f;

// Tamaño de los patrones: grados desde el centro.
// 20° porque las unidades se mueven desfasadas: dos vecinas pueden
// inclinarse una hacia la otra. Con 134 mm entre centros (30 mm entre
// aristas) a ±20° por eje quedan ~6 mm entre placas; a ±25° solo
// ~1.5 mm y a ±30° se tocan
const float AMPLITUD = 20.0f;

// Velocidades (grados/segundo). Las pruebas de mecatrónica
// llegaron hasta 600 °/s. Con 240 °/s cada figura dura ~1-1.5 s
// por unidad y la tanda de 16 unidades ~6-9 s
const float VEL_PATRON  = 120.0f;
const float VEL_REGRESO = 120.0f;
const float VEL_TRACK   = 120.0f;

// Cuántas unidades dibujan la figura al mismo tiempo (las que
// regresan al centro no cuentan). Más = la tanda acaba antes
// pero se mueven más servos juntos (más corriente)
const int SIMULTANEAS = 3;

// Orden en que entran las unidades a la cola (1 = primera unidad).
// Se puede cambiar para seguir el acomodo físico del módulo
const uint8_t ORDEN_UNIDADES[NUM_UNIDADES] = {
  1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16
};

// Veces que se repite cada figura (índice = postura)
//                        -  INICIO  RECARGAR  ESCUDO  ATAQUE  FIN
const uint8_t REPETICIONES[6] = {0,  1,      1,        1,      2,      1};

// TRACKING: grados de giro cuando la mano está
// en el borde de la imagen (x_norm o y_norm = ±1)
const float RANGO_TRACK = 45.0f;

// Si en TRACKING no llega posición en este tiempo,
// las unidades regresan al centro
const unsigned long TRACK_TIMEOUT_MS = 3000UL;

// No se reenvía al PCA9685 si el cambio es menor a esto
const float E_QUANT = 0.10f;

// =============================================
// TIPOS Y ESTADO
// =============================================

struct Punto {
  float x;
  float y;
};

// Estado general del módulo
enum EstadoMovimiento {
  QUIETO,
  PATRON,
  SIGUIENDO_MANO,
  REGRESANDO,
};

// Estado de cada unidad
enum FaseUnidad : uint8_t {
  U_QUIETA,     // en el centro, sin moverse
  U_FIGURA,     // dibujando la figura
  U_REGRESO,    // volviendo al centro
  U_MANO,       // siguiendo la mano (TRACKING)
};

struct Unidad {
  float x, y;                 // posición actual (grados)
  float enviadoX, enviadoY;   // última enviada al PCA9685
  int16_t indice;             // punto de la ruta al que va
  FaseUnidad fase;
};

const char* NOMBRES_PATRON[] = {
  "CENTRO", "CIRCULO", "CUADRADO", "X", "LINEA ARRIBA-ABAJO", "ZIGZAG"
};

Adafruit_PWMServoDriver* placas[NUM_PLACAS] = {nullptr, nullptr};
uint8_t direccionPlaca[NUM_PLACAS] = {0, 0};
int placasEncontradas = 0;

// Prueba de cableado: -1 = todas las unidades;
// 0-15 = solo esa unidad entra a la cola y se mueve
int unidadPrueba = -1;

EstadoMovimiento estado = QUIETO;
Unidad unidades[NUM_UNIDADES];

// Ruta de la figura actual, COMPARTIDA por todas las unidades
// (sin el regreso al centro: eso lo hace cada unidad al acabar)
const int MAX_PUNTOS = 80;
Punto ruta[MAX_PUNTOS];
int numPuntos = 0;
int patronActual = 0;

// Cola de unidades que faltan por dibujar la figura
uint8_t cola[NUM_UNIDADES];
int largoCola = 0;
int siguienteEnCola = 0;
unsigned long ultimoArranqueMs = 0;
unsigned long intervaloArranqueMs = 0;   // duración de la figura / SIMULTANEAS

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

// Escribe los 2 canales de una unidad con setPWM de la librería
// (lo mismo que usaban las pruebas de mecatrónica)
void escribirUnidad(int u) {
  int b = u / UNIDADES_POR_PLACA;
  int k = u % UNIDADES_POR_PLACA;

  if (b >= placasEncontradas) return;

  Unidad& un = unidades[u];
  float thetaX = (INVERTIR_X ? -un.x : un.x) + AJUSTE_X[u];
  float thetaY = (INVERTIR_Y ? -un.y : un.y) + AJUSTE_Y[u];
  int cuentas[2] = {theta_a_pwm(thetaX), theta_a_pwm(thetaY)};

  placas[b]->setPWM(canalX(k), 0, cuentas[0]);
  placas[b]->setPWM(canalY(k), 0, cuentas[1]);

  un.enviadoX = un.x;
  un.enviadoY = un.y;
}

// Solo viajan por I2C las unidades cuya posición cambió
void aplicarServos(bool forzar = false) {
  for (int u = 0; u < NUM_UNIDADES; u++) {
    Unidad& un = unidades[u];
    if (forzar ||
        fabsf(un.x - un.enviadoX) >= E_QUANT ||
        fabsf(un.y - un.enviadoY) >= E_QUANT) {
      escribirUnidad(u);
    }
  }
}

// Busca PCA9685 en el bus (0x40-0x7F; 0x70 es la dirección
// "todas las placas" y se salta). Regresa cuántas encontró
int buscarPlacas(uint8_t encontradas[], int maximo) {
  int n = 0;
  for (uint8_t dir = 0x40; dir <= 0x7F && n < maximo; dir++) {
    if (dir == 0x70) continue;
    Wire.beginTransmission(dir);
    if (Wire.endTransmission() == 0) {
      encontradas[n++] = dir;
    }
  }
  return n;
}

bool iniciarServos() {
  // Mismo orden que las pruebas de mecatrónica
  pinMode(OE_PIN, OUTPUT);
  digitalWrite(OE_PIN, LOW);

  Wire.begin(SDA_PIN, SCL_PIN);
  Wire.setClock(I2C_HZ);

  for (int u = 0; u < NUM_UNIDADES; u++) {
    unidades[u] = {0.0f, 0.0f, -1000.0f, -1000.0f, 0, U_QUIETA};
  }

  uint8_t encontradas[NUM_PLACAS];
  int n = buscarPlacas(encontradas, NUM_PLACAS);

  if (n == 0) {
    // Nada respondió: intentar con las direcciones por defecto
    for (int b = 0; b < NUM_PLACAS; b++) encontradas[b] = PCA_DIRECCIONES_DEFAULT[b];
    n = NUM_PLACAS;
  }

  placasEncontradas = 0;

  for (int b = 0; b < n; b++) {
    Adafruit_PWMServoDriver* placa = new Adafruit_PWMServoDriver(encontradas[b]);

    if (!placa->begin()) {
      Serial.printf("PCA9685 en 0x%02X: no responde\n", encontradas[b]);
      delete placa;
      continue;
    }

    placa->setOscillatorFrequency(27000000);
    placa->setPWMFreq(50);

    placas[placasEncontradas] = placa;
    direccionPlaca[placasEncontradas] = encontradas[b];
    placasEncontradas++;

    int primera = (placasEncontradas - 1) * UNIDADES_POR_PLACA + 1;
    Serial.printf("PCA9685 en 0x%02X -> unidades %d-%d\n",
                  encontradas[b], primera, primera + UNIDADES_POR_PLACA - 1);
  }

  if (placasEncontradas == 0) {
    return false;
  }

  if (placasEncontradas < NUM_PLACAS) {
    Serial.printf("AVISO: solo %d de %d PCA9685; se mueven %d unidades\n",
                  placasEncontradas, NUM_PLACAS, placasEncontradas * UNIDADES_POR_PLACA);
  }

  delay(300);

  // Centrar de una en una (evita el pico de corriente de 32 servos)
  for (int u = 0; u < placasEncontradas * UNIDADES_POR_PLACA; u++) {
    escribirUnidad(u);
    delay(PAUSA_ARRANQUE_MS);
  }

  tControlUs = micros();
  return true;
}

// =============================================
// CONSTRUCCIÓN DE LA RUTA (compartida)
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

// Tiempo que tarda una unidad en recorrer la ruta desde el centro
unsigned long duracionRutaMs() {
  float largo = 0.0f, x = 0.0f, y = 0.0f;
  for (int i = 0; i < numPuntos; i++) {
    largo += sqrtf((ruta[i].x - x) * (ruta[i].x - x) + (ruta[i].y - y) * (ruta[i].y - y));
    x = ruta[i].x;
    y = ruta[i].y;
  }
  return (unsigned long)(1000.0f * largo / VEL_PATRON);
}

// =============================================
// COMANDOS DE MOVIMIENTO
// =============================================

// Toda unidad fuera del centro (o moviéndose) regresa; se vacía la cola
void irAlCentro() {
  largoCola = 0;
  siguienteEnCola = 0;
  patronActual = 0;

  for (int u = 0; u < NUM_UNIDADES; u++) {
    Unidad& un = unidades[u];
    if (un.fase != U_QUIETA || un.x != 0.0f || un.y != 0.0f) {
      un.fase = U_REGRESO;
    }
  }

  estado = REGRESANDO;
}

// pose: 1 INICIO, 2 RECARGAR, 3 ESCUDO, 4 ATAQUE, 5 FIN
void iniciarPatron(uint8_t pose) {
  if (pose < 1 || pose > 5) {
    irAlCentro();
    return;
  }

  numPuntos = 0;
  int vueltas = REPETICIONES[pose];

  switch (pose) {
    case 1: agregarCirculo(vueltas);                                    break;
    case 2: agregarFigura(FIG_CUADRADO, N_FIG(FIG_CUADRADO), vueltas);  break;
    case 3: agregarFigura(FIG_X, N_FIG(FIG_X), vueltas);                break;
    case 4: agregarFigura(FIG_LINEA, N_FIG(FIG_LINEA), vueltas);        break;
    case 5: agregarFigura(FIG_ZIGZAG, N_FIG(FIG_ZIGZAG), vueltas);      break;
  }

  // Las que venían de la postura anterior regresan al centro;
  // si les toca turno antes de llegar, arrancan desde donde estén
  for (int u = 0; u < NUM_UNIDADES; u++) {
    if (unidades[u].fase == U_FIGURA || unidades[u].fase == U_MANO) {
      unidades[u].fase = U_REGRESO;
    }
  }

  // Cola: todas en ORDEN_UNIDADES, o solo la de la prueba de cableado
  largoCola = 0;
  if (unidadPrueba >= 0) {
    cola[largoCola++] = unidadPrueba;
  } else {
    for (int i = 0; i < NUM_UNIDADES; i++) {
      int u = ORDEN_UNIDADES[i] - 1;
      if (u >= 0 && u < placasEncontradas * UNIDADES_POR_PLACA) {
        cola[largoCola++] = u;
      }
    }
  }
  siguienteEnCola = 0;

  // Arrancar una cada (duración / SIMULTANEAS): así quedan desfasadas
  // (una acabando, otra a la mitad, otra empezando)
  unsigned long duracion = duracionRutaMs();
  intervaloArranqueMs = duracion / SIMULTANEAS;
  ultimoArranqueMs = millis() - intervaloArranqueMs;   // la primera arranca ya

  patronActual = pose;
  estado = PATRON;

  Serial.printf("[MOV] Patron: %s (%d puntos, %lu ms por unidad, %d unidades, %d a la vez)\n",
                NOMBRES_PATRON[pose], numPuntos, duracion, largoCola, SIMULTANEAS);
}

// x_norm, y_norm: -1 a 1 (centro de la imagen = 0)
void seguirMano(float xNorm, float yNorm) {
  objetivoMano.x = saturar(xNorm, -1.0f, 1.0f) * RANGO_TRACK;
  objetivoMano.y = saturar(yNorm, -1.0f, 1.0f) * RANGO_TRACK;
  ultimoTrackMs = millis();

  if (estado != SIGUIENDO_MANO) {
    largoCola = 0;
    siguienteEnCola = 0;
    for (int u = 0; u < placasEncontradas * UNIDADES_POR_PLACA; u++) {
      if (unidadPrueba < 0 || u == unidadPrueba) {
        unidades[u].fase = U_MANO;
      }
    }
  }

  estado = SIGUIENDO_MANO;
}

bool enMovimiento() {
  return estado == PATRON || estado == REGRESANDO;
}

// Tecla 'u' del Monitor Serie: recorre las unidades de una en una
// para revisar el cableado. La unidad elegida hace la línea
// arriba-abajo sola; con 1-5 dibuja cualquier figura
void siguienteUnidadPrueba() {
  unidadPrueba++;

  if (unidadPrueba >= placasEncontradas * UNIDADES_POR_PLACA) {
    unidadPrueba = -1;
    Serial.println("[PRUEBA] Todas las unidades se mueven");
  } else {
    int b = unidadPrueba / UNIDADES_POR_PLACA;
    int k = unidadPrueba % UNIDADES_POR_PLACA;
    Serial.printf("[PRUEBA] Solo la unidad %d (PCA 0x%02X, canales %d=X y %d=Y)\n",
                  unidadPrueba + 1, direccionPlaca[b], canalX(k), canalY(k));
    iniciarPatron(4);   // se mueve para que se vea cuál es
  }
}

// =============================================
// AVANCE HACIA UN PUNTO (velocidad constante)
// Regresa true si ya llegó
// =============================================

bool avanzarHacia(Unidad& un, float x, float y, float velocidad) {
  float dx = x - un.x;
  float dy = y - un.y;
  float distancia = sqrtf(dx * dx + dy * dy);
  float paso = velocidad * TS_S;

  if (distancia <= paso) {
    un.x = x;
    un.y = y;
    return true;
  }

  un.x += dx / distancia * paso;
  un.y += dy / distancia * paso;
  return false;
}

int unidadesEnFigura() {
  int n = 0;
  for (int u = 0; u < NUM_UNIDADES; u++) {
    if (unidades[u].fase == U_FIGURA) n++;
  }
  return n;
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

  // -----------------------------
  // COLA: arrancar la siguiente unidad
  // -----------------------------

  if (estado == PATRON && siguienteEnCola < largoCola) {
    unsigned long ms = millis();
    if (unidadesEnFigura() < SIMULTANEAS &&
        ms - ultimoArranqueMs >= intervaloArranqueMs) {
      Unidad& un = unidades[cola[siguienteEnCola++]];
      un.fase = U_FIGURA;
      un.indice = 0;
      ultimoArranqueMs = ms;
    }
  }

  if (estado == SIGUIENDO_MANO && millis() - ultimoTrackMs > TRACK_TIMEOUT_MS) {
    Serial.println("[MOV] Sin posicion de mano: regreso al centro");
    irAlCentro();
  }

  // -----------------------------
  // AVANZAR CADA UNIDAD
  // -----------------------------

  bool algunaActiva = false;

  for (int u = 0; u < NUM_UNIDADES; u++) {
    Unidad& un = unidades[u];

    switch (un.fase) {

      case U_FIGURA: {
        // Recorre la ruta sin frenar en cada punto: lo que sobra del
        // paso al llegar a un punto se usa hacia el siguiente
        float paso = VEL_PATRON * TS_S;
        while (paso > 0.0f && un.indice < numPuntos) {
          float dx = ruta[un.indice].x - un.x;
          float dy = ruta[un.indice].y - un.y;
          float d = sqrtf(dx * dx + dy * dy);
          if (d <= paso) {
            un.x = ruta[un.indice].x;
            un.y = ruta[un.indice].y;
            un.indice++;
            paso -= d;
          } else {
            un.x += dx / d * paso;
            un.y += dy / d * paso;
            paso = 0.0f;
          }
        }
        if (un.indice >= numPuntos) {
          un.fase = U_REGRESO;
        }
        break;
      }

      case U_REGRESO:
        if (avanzarHacia(un, 0.0f, 0.0f, VEL_REGRESO)) {
          un.fase = U_QUIETA;
        }
        break;

      case U_MANO:
        avanzarHacia(un, objetivoMano.x, objetivoMano.y, VEL_TRACK);
        break;

      case U_QUIETA:
        break;
    }

    if (un.fase != U_QUIETA) {
      algunaActiva = true;
    }
  }

  // ¿Terminó la tanda?
  if ((estado == PATRON && siguienteEnCola >= largoCola && !algunaActiva) ||
      (estado == REGRESANDO && !algunaActiva)) {
    if (estado == PATRON) {
      Serial.printf("[MOV] Patron %s terminado\n", NOMBRES_PATRON[patronActual]);
    }
    estado = QUIETO;
  }

  aplicarServos();
}