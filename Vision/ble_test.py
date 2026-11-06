"""
PRUEBA DE COMUNICACIÓN PC -> ESP32 MAESTRO - SOFIA

Script independiente (sin GUI) para demostrar que el ESP32
recibe, interpreta y confirma comandos enviados desde la PC.

Pasos:
    1. Busca el ESP32 por nombre ("SOFIA-ESP32") y se conecta.
    2. Envía PING           -> espera ACK.
    3. Envía POSE = ESCUDO  -> espera ACK.
    4. Envía un TRACK       -> no espera ACK (flujo continuo).
    5. Envía una trama con CRC dañado -> espera NACK (ERR_CRC).

Uso (dentro de Vision/, con el venv activo):
    python ble_test.py
"""

import asyncio
import sys
import time

from bleak import BleakClient, BleakScanner

from comunicacion import protocol as p


responses = asyncio.Queue()


def on_notify(_sender, data):
    responses.put_nowait(bytes(data))


async def wait_response(timeout=p.ACK_TIMEOUT_S * 3):
    try:
        return p.parse_frame(await asyncio.wait_for(responses.get(), timeout))
    except asyncio.TimeoutError:
        return None


async def send(client, frame_bytes, description):

    print(f"\n→ {description}")
    print(f"  Bytes: {frame_bytes.hex(' ')}")

    start = time.perf_counter()
    await client.write_gatt_char(p.RX_CHAR_UUID, frame_bytes, response=False)
    response = await wait_response()
    elapsed = (time.perf_counter() - start) * 1000

    if response is None:
        print("  ← Sin respuesta")
        return None

    if response.type == p.TYPE_ACK:
        acked_type, acked_seq = p.decode_ack(response)
        print(f"  ← ACK de {p.TYPE_NAMES.get(acked_type)} seq={acked_seq} ({elapsed:.0f} ms)")
        return "ACK"

    if response.type == p.TYPE_NACK:
        nacked_type, nacked_seq, code = p.decode_nack(response)
        print(
            f"  ← NACK de {p.TYPE_NAMES.get(nacked_type, nacked_type)} "
            f"seq={nacked_seq}: {p.ERROR_NAMES.get(code, code)} ({elapsed:.0f} ms)"
        )
        return "NACK"

    print(f"  ← Respuesta inesperada: {response}")
    return None


async def main():

    print(f"Buscando '{p.DEVICE_NAME}'...")
    device = await BleakScanner.find_device_by_name(p.DEVICE_NAME, timeout=10.0)

    if device is None:
        print("No se encontró el ESP32. Revisa que esté encendido y cerca.")
        return 1

    print(f"Encontrado: {device.name} ({device.address})")

    async with BleakClient(device) as client:

        await client.start_notify(p.TX_CHAR_UUID, on_notify)
        print("Conectado")

        results = []

        # 1. Comando de prueba
        results.append(await send(
            client,
            p.build_frame(p.TYPE_PING, 1),
            "PING (comando de prueba)",
        ))

        # 2. Postura
        results.append(await send(
            client,
            p.build_frame(p.TYPE_POSE, 2, p.pose_payload(p.POSE_IDS["ESCUDO"])),
            "POSE = ESCUDO (3)",
        ))

        # 3. Tracking (no lleva ACK)
        track = p.build_frame(
            p.TYPE_TRACK, 3,
            p.track_payload(p.HAND_IDS["DERECHA"], 0.25, -0.40, 0.472, 302.0),
        )
        print("\n→ TRACK mano derecha x=+0.25 y=-0.40 (sin ACK)")
        print(f"  Bytes: {track.hex(' ')}")
        await client.write_gatt_char(p.RX_CHAR_UUID, track, response=False)

        # 4. Trama dañada: se cambia el CRC a propósito
        broken = bytearray(p.build_frame(p.TYPE_PING, 4))
        broken[-1] ^= 0xFF
        nack_ok = await send(client, bytes(broken), "PING con CRC dañado (debe dar NACK)") == "NACK"

        await asyncio.sleep(0.2)
        await client.stop_notify(p.TX_CHAR_UUID)

    print("\n================ RESULTADO ================")
    print(f"PING confirmado:        {'OK' if results[0] == 'ACK' else 'FALLÓ'}")
    print(f"POSE confirmada:        {'OK' if results[1] == 'ACK' else 'FALLÓ'}")
    print(f"Error de CRC detectado: {'OK' if nack_ok else 'FALLÓ'}")

    return 0 if results == ["ACK", "ACK"] and nack_ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
