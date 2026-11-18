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
 *  Las figuras son LAS MISMAS de la simulación (Webots,
 *  tracker_esfera_cpp/patrones.hpp): misma forma, mismo tamaño
 *  (±20°), misma velocidad y el mismo suavizado. El servo X hace
 *  la "u" de la sim (derecha en la cámara) y el Y la "v" (arriba):
 *
 *      1 INICIO    -> arriba-abajo
 *      2 RECARGAR  -> "círculo de carga": solo las 12 unidades del
 *                     borde, una tras otra en sentido horario,
 *                     inclinándose hacia afuera (2 vueltas)
 *      3 ESCUDO    -> rombo
 *      4 ATAQUE    -> una L
 *      5 FIN       -> izquierda-derecha (despedida)
 *
 *  En la sim las 16 unidades dibujan al unísono. Aquí, para no
 *  pedir la corriente de 32 servos juntos, entran POR TURNOS
 *  (SIMULTANEAS a la vez, desfasadas). Con SIMULTANEAS = 16
 *  arrancan todas juntas, exactamente como en la sim.
 *  RECARGAR siempre es como en la sim (ya mueve ~4 a la vez).
 *
 *  Todas las figuras son UNA lista de puntos compartida; cada
 *  unidad solo guarda en qué punto va (pocos bytes por unidad).
 *
 *  En modo TRACKING las 16 apuntan hacia la mano POR TURNOS, como el
 *  reloj de un CPU: cada 20 ms solo 4 unidades dan un salto corto y
 *  ceden el turno a las siguientes 4. Avanzan casi juntas pero nunca
 *  arrancan más de 8 servos a la vez. El regreso al centro (STOP,
 *  estado seguro, fin del TRACKING) usa los mismos turnos.
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

// Velocidad de cada figura, igual que en la sim: en "AMPLITUDES por
// segundo" (2.5 = recorre 2.5 x 20° = 50 °/s). Todas quedan por
// debajo de los 120 °/s del ajuste fino
//                         -  INICIO  RECARGAR  ESCUDO  ATAQUE  FIN
const float VEL_FIGURA[6] = {0, 2.5f,   0,        2.5f,   3.0f,   3.5f};

// Suavizado de la sim (K = 0.15 cada 8 ms) pasado a pasos de 20 ms:
// cada paso la unidad avanza este tanto de lo que le falta
const float K_SUAVIZADO = 0.33f;

// RECARGAR ("círculo de carga"), igual que en la sim
const float RECARGA_VUELTA_S = 1.2f;   // segundos por vuelta
const int   RECARGA_VUELTAS  = 2;
const float RECARGA_COLA     = 2.2f;   // rad de "cola" encendida detrás de la cabeza

const float VEL_REGRESO = 120.0f;   // °/s al volver al centro si se interrumpe
const float VEL_TRACK   = 120.0f;   // °/s promedio de cada unidad en TRACKING

// TRACKING POR TURNOS (como el reloj de un CPU): en cada paso de 20 ms
// solo se mueven TRACK_POR_TURNO unidades, dan un salto corto hacia la
// mano y le ceden el turno a las siguientes 4. Así las 16 avanzan casi
// juntas pero nunca hay más de 4 unidades (8 servos) arrancando a la vez.
// El salto se calcula para que el promedio sea VEL_TRACK; con 16
// unidades: 120 °/s x 0.02 s x 4 turnos = 9.6° por salto, cada 80 ms
const int   TRACK_POR_TURNO = 4;
// Tope del salto: un SG90 recorre ~10° en los 20 ms de su turno, así
// termina su salto antes de que le toque a las siguientes
const float TRACK_SALTO_MAX = 10.0f;

// Cuántas unidades dibujan la figura al mismo tiempo (las que
// regresan al centro no cuentan). Más = la tanda acaba antes
// pero se mueven más servos juntos (más corriente).
// 16 = todas al unísono, como en la sim
const int SIMULTANEAS = 3;

// Orden en que entran las unidades a la cola (1 = primera unidad).
// Se puede cambiar para seguir el acomodo físico del módulo
const uint8_t ORDEN_UNIDADES[NUM_UNIDADES] = {
  1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16
};

// Dónde está cada unidad en el módulo, como los paneles de la sim
// ("Panel_<fila>_<columna>"). Sirve para RECARGAR (cuáles son del
// borde y hacia dónde es "afuera"). Por defecto: placa 1 = filas 0 y
// 1, placa 2 = filas 2 y 3. Si el cableado es otro, cámbialo aquí
//                                    unidad: 1  2  3  4  5  6  7  8  9 10 11 12 13 14 15 16
const uint8_t FILA_UNIDAD[NUM_UNIDADES]    = {0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3};
const uint8_t COLUMNA_UNIDAD[NUM_UNIDADES] = {0, 1, 2, 3, 0, 1, 2, 3, 0, 1, 2, 3, 0, 1, 2, 3};

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
  U_RECARGA,    // haciendo el círculo de carga (RECARGAR)
};

struct Unidad {
  float x, y;                 // posición actual (grados)
  float enviadoX, enviadoY;   // última enviada al PCA9685
  float ox, oy;               // punto de la figura (antes del suavizado)
  int16_t indice;             // punto de la ruta al que va
  FaseUnidad fase;
};

const char* NOMBRES_PATRON[] = {
  "CENTRO", "ARRIBA-ABAJO", "CIRCULO DE CARGA", "ROMBO", "L", "IZQUIERDA-DERECHA"
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
float velocidadFigura = 50.0f;   // °/s de la figura actual
unsigned long inicioRecargaMs = 0;

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
    unidades[u] = {0.0f, 0.0f, -1000.0f, -1000.0f, 0.0f, 0.0f, 0, U_QUIETA};
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

// Agrega una figura (coordenadas de -1 a 1) escalada a AMPLITUD
void agregarFigura(const Punto* figura, int n) {
  for (int i = 0; i < n; i++) {
    agregarPunto(figura[i].x * AMPLITUD, figura[i].y * AMPLITUD);
  }
}

// -----------------------------
// FIGURAS: copiadas de la sim (patrones.hpp), x = u, y = v.
// Todas salen del centro y terminan en el centro
// -----------------------------

// 1 INICIO: arriba-abajo
const Punto FIG_INICIO[] = {{0, 1}, {0, -1}, {0, 0}};

// 3 ESCUDO: rombo
const Punto FIG_ESCUDO[] = {{0, 1}, {1, 0}, {0, -1}, {-1, 0}, {0, 1}, {0, 0}};

// 4 ATAQUE: una L
const Punto FIG_ATAQUE[] = {{-0.5f, 1}, {-0.5f, -1}, {0.8f, -1}, {0, 0}};

// 5 FIN: izquierda-derecha (despedida)
const Punto FIG_FIN[] = {{-1, 0}, {1, 0}, {-1, 0}, {1, 0}, {0, 0}};

#define N_FIG(f) ((int)(sizeof(f) / sizeof(f[0])))

// -----------------------------
// 2 RECARGAR: círculo de carga (igual que recarga() de la sim)
// -----------------------------

// Dirección de la unidad vista desde el centro del módulo, en la
// imagen de la cámara (u = derecha, v = arriba). Mismas posiciones
// que los paneles de sofia.wbt
void direccionUnidad(int u, float& du, float& dv) {
  const float FILAS_X[4] = {-0.1741f, -0.0580f, 0.0580f, 0.1741f};
  int f = FILA_UNIDAD[u], c = COLUMNA_UNIDAD[u];
  float y = -0.201f + 0.067f * (f % 2) + 0.134f * c;
  du = -(y - 0.0335f);
  dv = FILAS_X[f];
}

bool enBorde(int u) {
  int f = FILA_UNIDAD[u], c = COLUMNA_UNIDAD[u];
  return f == 0 || f == 3 || c == 0 || c == 3;
}

// Punto de la unidad u a los t segundos del círculo de carga
void puntoRecarga(int u, float t, float& x, float& y) {
  x = 0.0f;
  y = 0.0f;

  float du, dv;
  direccionUnidad(u, du, dv);
  float norma = sqrtf(du * du + dv * dv);
  if (norma <= 0.0f) return;

  float anguloUnidad = atan2f(dv, du);
  float cabeza = -2.0f * PI * t / RECARGA_VUELTA_S;   // sentido horario

  float atras = fmodf(anguloUnidad - cabeza, 2.0f * PI);
  if (atras < 0.0f) atras += 2.0f * PI;

  float intensidad = atras < RECARGA_COLA ? 1.0f - atras / RECARGA_COLA : 0.0f;

  // Inclinarse hacia afuera del módulo
  x = AMPLITUD * intensidad * du / norma;
  y = AMPLITUD * intensidad * dv / norma;
}

// Tiempo que tarda una unidad en recorrer la ruta desde el centro
unsigned long duracionRutaMs() {
  float largo = 0.0f, x = 0.0f, y = 0.0f;
  for (int i = 0; i < numPuntos; i++) {
    largo += sqrtf((ruta[i].x - x) * (ruta[i].x - x) + (ruta[i].y - y) * (ruta[i].y - y));
    x = ruta[i].x;
    y = ruta[i].y;
  }
  return (unsigned long)(1000.0f * largo / velocidadFigura);
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

  switch (pose) {
    case 1: agregarFigura(FIG_INICIO, N_FIG(FIG_INICIO)); break;
    case 3: agregarFigura(FIG_ESCUDO, N_FIG(FIG_ESCUDO)); break;
    case 4: agregarFigura(FIG_ATAQUE, N_FIG(FIG_ATAQUE)); break;
    case 5: agregarFigura(FIG_FIN, N_FIG(FIG_FIN));       break;
  }
  velocidadFigura = VEL_FIGURA[pose] * AMPLITUD;

  // Las que venían de la postura anterior regresan al centro;
  // si les toca turno antes de llegar, arrancan desde donde estén
  for (int u = 0; u < NUM_UNIDADES; u++) {
    if (unidades[u].fase == U_FIGURA || unidades[u].fase == U_MANO ||
        unidades[u].fase == U_RECARGA) {
      unidades[u].fase = U_REGRESO;
    }
  }

  patronActual = pose;
  estado = PATRON;

  // RECARGAR: como en la sim, las 12 del borde a la vez, cada una
  // con su retraso según dónde está (no usa la cola)
  if (pose == 2) {
    largoCola = 0;
    siguienteEnCola = 0;
    inicioRecargaMs = millis();
    int n = 0;
    for (int u = 0; u < placasEncontradas * UNIDADES_POR_PLACA; u++) {
      bool participa = unidadPrueba >= 0 ? u == unidadPrueba : enBorde(u);
      if (participa) {
        unidades[u].fase = U_RECARGA;
        n++;
      }
    }
    Serial.printf("[MOV] Patron: %s (%d unidades, %.1f s)\n",
                  NOMBRES_PATRON[pose], n, RECARGA_VUELTA_S * RECARGA_VUELTAS);
    return;
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
  // (una acabando, otra a la mitad, otra empezando).
  // SIMULTANEAS >= 16: todas a la vez, como en la sim
  unsigned long duracion = duracionRutaMs();
  intervaloArranqueMs = SIMULTANEAS >= NUM_UNIDADES ? 0 : duracion / SIMULTANEAS;
  ultimoArranqueMs = millis() - intervaloArranqueMs;   // la primera arranca ya

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
// arriba-abajo sola (INICIO); con 1-5 dibuja cualquier figura
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
    iniciarPatron(1);   // arriba-abajo, para que se vea cuál es
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

// -----------------------------
// TURNOS (TRACKING y regreso al centro)
// -----------------------------
// Como el reloj de un CPU: cada paso de 20 ms solo TRACK_POR_TURNO
// unidades que aún no llegan dan un salto corto; el siguiente paso les
// toca a las siguientes, en ronda. Ninguna completa su movimiento de
// golpe: todas avanzan "a saltitos" casi al mismo tiempo, pero nunca
// arrancan más de 4 unidades (8 servos) juntas

int siguienteTurno = 0;   // por qué unidad empieza la siguiente ronda

void objetivoDe(const Unidad& un, float& x, float& y) {
  if (un.fase == U_MANO) { x = objetivoMano.x; y = objetivoMano.y; }
  else                   { x = 0.0f;           y = 0.0f; }
}

bool necesitaTurno(const Unidad& un) {
  if (un.fase != U_MANO && un.fase != U_REGRESO) return false;
  float x, y;
  objetivoDe(un, x, y);
  return fabsf(x - un.x) >= E_QUANT || fabsf(y - un.y) >= E_QUANT;
}

// Marca en 'turno' las unidades que se mueven en este paso y regresa
// el tamaño del salto (grados)
float elegirTurno(bool turno[]) {
  int pendientes = 0;
  for (int u = 0; u < NUM_UNIDADES; u++) {
    turno[u] = false;
    if (necesitaTurno(unidades[u])) pendientes++;
  }
  if (pendientes == 0) return 0.0f;

  // Cada unidad se mueve 1 de cada 'rondas' pasos: el salto se agranda
  // en esa proporción para que el promedio siga siendo VEL_TRACK
  int rondas = (pendientes + TRACK_POR_TURNO - 1) / TRACK_POR_TURNO;
  float salto = VEL_TRACK * TS_S * rondas;
  if (salto > TRACK_SALTO_MAX) salto = TRACK_SALTO_MAX;

  int elegidas = 0;
  for (int i = 0; i < NUM_UNIDADES && elegidas < TRACK_POR_TURNO; i++) {
    int u = (siguienteTurno + i) % NUM_UNIDADES;
    if (necesitaTurno(unidades[u])) {
      turno[u] = true;
      elegidas++;
      siguienteTurno = (u + 1) % NUM_UNIDADES;
    }
  }
  return salto;
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
    while (siguienteEnCola < largoCola &&
           unidadesEnFigura() < SIMULTANEAS &&
           ms - ultimoArranqueMs >= intervaloArranqueMs) {
      Unidad& un = unidades[cola[siguienteEnCola++]];
      un.fase = U_FIGURA;
      un.indice = 0;
      un.ox = un.x;   // la figura arranca desde donde esté
      un.oy = un.y;
      ultimoArranqueMs = ms;
      if (intervaloArranqueMs > 0) break;   // por turnos: una por paso
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

  bool turno[NUM_UNIDADES];
  float salto = elegirTurno(turno);

  for (int u = 0; u < NUM_UNIDADES; u++) {
    Unidad& un = unidades[u];

    switch (un.fase) {

      case U_FIGURA: {
        // El punto de la figura (ox, oy) recorre la ruta a velocidad
        // constante sin frenar en las esquinas, como en la sim
        float paso = velocidadFigura * TS_S;
        while (paso > 0.0f && un.indice < numPuntos) {
          float dx = ruta[un.indice].x - un.ox;
          float dy = ruta[un.indice].y - un.oy;
          float d = sqrtf(dx * dx + dy * dy);
          if (d <= paso) {
            un.ox = ruta[un.indice].x;
            un.oy = ruta[un.indice].y;
            un.indice++;
            paso -= d;
          } else {
            un.ox += dx / d * paso;
            un.oy += dy / d * paso;
            paso = 0.0f;
          }
        }
        // ...y la unidad lo sigue con el mismo suavizado de la sim
        un.x += (un.ox - un.x) * K_SUAVIZADO;
        un.y += (un.oy - un.y) * K_SUAVIZADO;
        if (un.indice >= numPuntos) {
          un.fase = U_REGRESO;
        }
        break;
      }

      case U_RECARGA: {
        float t = (millis() - inicioRecargaMs) / 1000.0f;
        if (t > RECARGA_VUELTA_S * RECARGA_VUELTAS) {
          un.fase = U_REGRESO;
        } else {
          puntoRecarga(u, t, un.ox, un.oy);
          un.x += (un.ox - un.x) * K_SUAVIZADO;
          un.y += (un.oy - un.y) * K_SUAVIZADO;
        }
        break;
      }

      case U_REGRESO:
        // Por turnos, para que un STOP o el fin del TRACKING no
        // regrese las 16 de golpe. El salto se escala a VEL_REGRESO
        if (!necesitaTurno(un)) {
          un.x = 0.0f;
          un.y = 0.0f;
          un.fase = U_QUIETA;
        } else if (turno[u] &&
                   avanzarHacia(un, 0.0f, 0.0f, salto * (VEL_REGRESO / VEL_TRACK) / TS_S)) {
          un.fase = U_QUIETA;
        }
        break;

      case U_MANO:
        // Solo se mueve cuando le toca turno (salto corto hacia la mano)
        if (turno[u]) {
          avanzarHacia(un, objetivoMano.x, objetivoMano.y, salto / TS_S);
        }
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