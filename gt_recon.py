"""Reconocimiento BLE de solo lectura para Fender Mustang GT.

Uso:
  python gt_recon.py scan [segundos]
  python gt_recon.py gatt <device_id>
  python gt_recon.py listen <device_id> [segundos]

Nunca escribe en características del amplificador. `listen` solo activa
notificaciones (descriptor CCCD estándar), que es lo que hace cualquier cliente.
"""
import asyncio
import json
import sys
import time
from pathlib import Path

from bleak import BleakClient, BleakScanner

MMP_SERVICE = "90559580-b707-11ee-acb1-7b7e30f1af54"
LOG = Path(__file__).with_name("gt_recon.jsonl")
KEYWORDS = ("fender", "mustang", "gt", "fmic")


def log(event, **data):
    rec = {"t": round(time.time(), 3), "event": event, **data}
    with LOG.open("a") as f:
        f.write(json.dumps(rec) + "\n")


async def scan(seconds):
    found = await BleakScanner.discover(timeout=seconds, return_adv=True)
    rows = []
    for dev, adv in found.values():
        name = adv.local_name or dev.name or ""
        rows.append((adv.rssi, dev.address, name, adv))
    rows.sort(key=lambda r: r[0], reverse=True)
    print(f"{len(rows)} dispositivos BLE encontrados\n")
    for rssi, addr, name, adv in rows:
        hit = any(k in name.lower() for k in KEYWORDS) or MMP_SERVICE in adv.service_uuids
        mark = ">>" if hit else "  "
        print(f"{mark} {rssi:>4} dBm  {addr}  {name or '(sin nombre)'}")
        if hit:
            print(f"      servicios anunciados: {adv.service_uuids}")
            print(f"      fabricante: { {k: v.hex() for k, v in adv.manufacturer_data.items()} }")
            print(f"      ¿servicio del Micro Plus?: {MMP_SERVICE in adv.service_uuids}")
            log("scan_hit", address=addr, name=name, rssi=rssi,
                services=adv.service_uuids,
                manufacturer={str(k): v.hex() for k, v in adv.manufacturer_data.items()})


async def gatt(address):
    async with BleakClient(await find(address), timeout=20) as client:
        print(f"Conectado a {address}\n")
        for svc in client.services:
            print(f"[servicio] {svc.uuid}  {svc.description}")
            log("service", uuid=svc.uuid, description=svc.description)
            for ch in svc.characteristics:
                print(f"   [car] {ch.uuid}  props={ch.properties}  {ch.description}")
                value = None
                if "read" in ch.properties:
                    try:
                        raw = await client.read_gatt_char(ch)
                        value = raw.hex()
                        text = raw.decode("utf-8", "replace") if raw and all(32 <= b < 127 for b in raw) else ""
                        print(f"         valor: {value}  {repr(text) if text else ''}")
                    except Exception as e:  # noqa: BLE001
                        print(f"         (no se pudo leer: {e})")
                log("characteristic", service=svc.uuid, uuid=ch.uuid,
                    properties=ch.properties, value=value)
                for d in ch.descriptors:
                    print(f"         [desc] {d.uuid}  {d.description}")


async def find(address):
    dev = await BleakScanner.find_device_by_address(address, timeout=20)
    if dev is None:
        sys.exit("No encontré el ampli. ¿Está encendido y sin Fender Tone conectada?")
    return dev


async def listen(address, seconds):
    async with BleakClient(await find(address), timeout=20) as client:
        targets = [ch for svc in client.services for ch in svc.characteristics
                   if {"notify", "indicate"} & set(ch.properties)]
        print(f"Escuchando {len(targets)} características durante {seconds}s.")
        print("Cambia de preset y mueve perillas en el ampli ahora...\n")

        def handler_for(uuid):
            def handler(_, data: bytearray):
                print(f"{time.strftime('%H:%M:%S')}  {uuid[:8]}  {len(data):>3}B  {data.hex()}")
                log("notify", char=uuid, data=data.hex())
            return handler

        for ch in targets:
            try:
                await client.start_notify(ch, handler_for(ch.uuid))
            except Exception as e:  # noqa: BLE001
                print(f"(no se pudo suscribir a {ch.uuid}: {e})")
        await asyncio.sleep(seconds)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "scan"
    if cmd == "scan":
        asyncio.run(scan(float(sys.argv[2]) if len(sys.argv) > 2 else 12))
    elif cmd == "gatt":
        asyncio.run(gatt(sys.argv[2]))
    elif cmd == "listen":
        asyncio.run(listen(sys.argv[2], float(sys.argv[3]) if len(sys.argv) > 3 else 60))
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
