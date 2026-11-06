"""
CLIENTE DE WEBOTS EN VIVO - SOFIA (diagnóstico de alineación)

Habla con el controlador Webots/Sofia/controllers/diagnostico_vivo
(mundo sofia_diagnostico_vivo.wbt) por TCP :5557. Lo usa el hilo de
diagnóstico (no es un hilo propio): leer() espera muy poco y regresa.

    cliente = ClienteWebots()
    cliente.conectar()
    cliente.ordenar("azar", paneles=3, grados=10)
    for tipo, dato in cliente.leer():      # ("imagen", (bgr, version)) / ("estado", dict)
        ...

Ver el protocolo en el docstring del controlador.
"""

import json
import select
import socket
import struct

import numpy as np

HOST = "127.0.0.1"
PORT = 5557

ENCABEZADO = struct.Struct("<4sI")
ENCABEZADO_IMAGEN = struct.Struct("<HHI")
MAXIMO_PAQUETE = 64 * 1024 * 1024


class ClienteWebots:

    def __init__(self, host=HOST, port=PORT):
        self.host = host
        self.port = port
        self.socket = None
        self.buffer = bytearray()

    @property
    def conectado(self):
        return self.socket is not None

    def conectar(self, timeout=3.0):
        self.cerrar()
        self.socket = socket.create_connection((self.host, self.port), timeout=timeout)
        self.socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8 * 1024 * 1024)
        self.socket.settimeout(None)
        self.buffer = bytearray()

    def cerrar(self):
        if self.socket is not None:
            try:
                self.socket.close()
            except OSError:
                pass
        self.socket = None
        self.buffer = bytearray()

    def ordenar(self, orden, **datos):
        if self.socket is None:
            raise ConnectionError("no hay conexión con Webots")
        linea = json.dumps({"orden": orden, **datos}) + "\n"
        self.socket.sendall(linea.encode())

    def leer(self, espera=0.02):
        """
        Lee lo que haya llegado (espera como máximo `espera` segundos).
        Regresa una lista de ("imagen", (bgr, version)) y ("estado", dict).
        Lanza ConnectionError si Webots cerró la conexión.
        """
        if self.socket is None:
            return []

        listo, _, _ = select.select([self.socket], [], [], espera)
        while listo:
            try:
                datos = self.socket.recv(4 * 1024 * 1024)
            except OSError as error:
                self.cerrar()
                raise ConnectionError(str(error)) from error
            if not datos:
                self.cerrar()
                raise ConnectionError("Webots cerró la conexión (¿se detuvo o reinició la simulación?)")
            self.buffer += datos
            listo, _, _ = select.select([self.socket], [], [], 0)

        return self._paquetes()

    def _paquetes(self):
        eventos = []
        while len(self.buffer) >= ENCABEZADO.size:
            tipo, largo = ENCABEZADO.unpack_from(self.buffer)
            if largo > MAXIMO_PAQUETE:
                self.cerrar()
                raise ConnectionError(f"paquete inválido ({largo} bytes)")
            if len(self.buffer) < ENCABEZADO.size + largo:
                break
            datos = bytes(self.buffer[ENCABEZADO.size:ENCABEZADO.size + largo])
            del self.buffer[:ENCABEZADO.size + largo]

            if tipo == b"ESTA":
                eventos.append(("estado", json.loads(datos)))
            elif tipo == b"IMGN":
                ancho, alto, version = ENCABEZADO_IMAGEN.unpack_from(datos)
                pixeles = np.frombuffer(datos, np.uint8, ancho * alto * 4, ENCABEZADO_IMAGEN.size)
                bgr = pixeles.reshape(alto, ancho, 4)[:, :, :3].copy()
                eventos.append(("imagen", (bgr, version)))
        return eventos
