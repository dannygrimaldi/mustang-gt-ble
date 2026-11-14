"""Prueba de lectura del protocolo Mustang GT desde la Mac.

Solo envía peticiones de lectura:
  901 (saludo: info + lista de presets) y 920 (preset actual completo).
Uso: python gt_probe.py <device_id>
"""
import asyncio
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pklg_gt import frame, msg_type  # noqa: E402

from bleak import BleakClient, BleakScanner  # noqa: E402

NOTIFY = "1017adcc-dcbc-4387-a59f-2546b2ea5bb0"
WRITE = "820a7e34-4e0a-4f90-8520-04ebce35a3a1"


def empty_msg(field: int) -> bytes:
    """Mensaje protobuf con un único campo length-delimited vacío."""
    key, out = (field << 3) | 2, bytearray()
    while True:
        b = key & 0x7F
        key >>= 7
        out.append(b | (0x80 if key else 0))
        if not key:
            break
    return bytes(out) + b"\x00"


READ_ONLY = {901: empty_msg(901), 920: empty_msg(920)}
assert READ_ONLY[901].hex() == "aa3800" and READ_ONLY[920].hex() == "c23900"


async def main(address):
    dev = await BleakScanner.find_device_by_address(address, timeout=20)
    if dev is None:
        sys.exit("No encontré el ampli. ¿Encendido y con Fender Tone cerrada?")
    received = []

    def on_notify(_, data: bytearray):
        received.append((time.time(), bytes(data)))

    async with BleakClient(dev, timeout=20) as client:
        await client.start_notify(NOTIFY, on_notify)
        for name, payload in READ_ONLY.items():
            start = len(received)
            print(f"\n>>> Enviando {name} ({payload.hex()})")
            await client.write_gatt_char(WRITE, payload, response=True)
            await asyncio.sleep(6)
            batch = received[start:]
            counts = Counter(msg_type(v) for _, v in batch)
            print(f"<<< {len(batch)} mensajes: {dict(counts)}")
            shown = Counter()
            for _, v in batch:
                mt = msg_type(v)
                if mt == 306:
                    continue
                shown[mt] += 1
                if shown[mt] <= (3 if mt in (903, 203) else 2):
                    print(f"    {frame(v)[:180]}")
                elif shown[mt] == (4 if mt in (903, 203) else 3):
                    print(f"    ... (más mensajes tipo {mt})")
        await client.stop_notify(NOTIFY)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
