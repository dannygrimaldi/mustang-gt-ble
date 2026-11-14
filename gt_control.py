"""Prueba de control del Mustang GT: cambio de preset (407) y parámetro en vivo (102).

Deja el ampli como estaba: restaura el gain original y vuelve al preset inicial.
Nunca guarda presets.
Uso: python gt_control.py <device_id>
"""
import asyncio
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pklg_gt import msg_type, varint  # noqa: E402

from bleak import BleakClient, BleakScanner  # noqa: E402

NOTIFY = "1017adcc-dcbc-4387-a59f-2546b2ea5bb0"
WRITE = "820a7e34-4e0a-4f90-8520-04ebce35a3a1"
AMP_SLOT = "DUBS_LinearGain_1"
PAUSE = 4


# ---------- codificación protobuf mínima ----------
def enc_varint(v: int) -> bytes:
    out = bytearray()
    while True:
        b = v & 0x7F
        v >>= 7
        out.append(b | (0x80 if v else 0))
        if not v:
            return bytes(out)


def ld(field: int, payload: bytes) -> bytes:
    return enc_varint((field << 3) | 2) + enc_varint(len(payload)) + payload


def msg_empty(field):
    return ld(field, b"")


def msg_select_preset(n: int) -> bytes:
    return ld(407, enc_varint((1 << 3) | 0) + enc_varint(n))


def msg_set_param(slot: str, param: str, value: float) -> bytes:
    body = ld(1, slot.encode()) + ld(2, param.encode()) + bytes([(3 << 3) | 5]) + struct.pack("<f", value)
    return ld(102, body)


assert msg_select_preset(198).hex() == "ba190308c601"
assert msg_set_param(AMP_SLOT, "gain", 0.4).hex().startswith("b2061e0a11445542535f4c696e6561724761696e5f3112046761696e1d")


# ---------- decodificación estructurada ----------
def fields(b: bytes):
    out, i = [], 0
    while i < len(b):
        key, i = varint(b, i)
        f, wt = key >> 3, key & 7
        if wt == 0:
            v, i = varint(b, i)
        elif wt == 2:
            n, i = varint(b, i)
            v = b[i:i + n]
            i += n
        elif wt == 5:
            (v,) = struct.unpack("<f", b[i:i + 4])
            i += 4
        elif wt == 1:
            (v,) = struct.unpack("<d", b[i:i + 8])
            i += 8
        else:
            raise ValueError(wt)
        out.append((f, v))
    return out


def body(msg: bytes) -> bytes:
    return fields(msg)[0][1]


class GT:
    def __init__(self, client):
        self.client = client
        self.inbox = []

    def on_notify(self, _, data):
        self.inbox.append(bytes(data))

    async def send(self, payload: bytes, wait: float = 2.5):
        self.inbox.clear()
        await self.client.write_gatt_char(WRITE, payload, response=True)
        await asyncio.sleep(wait)
        return [m for m in self.inbox if msg_type(m) != 306]

    async def drain(self, quiet: float = 1.5, limit: float = 15):
        """Espera hasta que el ampli deje de mandar mensajes (p. ej. la lista de presets)."""
        waited, last = 0.0, -1
        while waited < limit:
            await asyncio.sleep(quiet)
            waited += quiet
            n = len([m for m in self.inbox if msg_type(m) != 306])
            if n == last:
                return
            last = n

    async def current(self):
        msgs = await self.send(msg_empty(920), 3)
        info = {"params": {}, "chain": [], "dirty": None}
        seen_214 = False
        for m in msgs:
            t = msg_type(m)
            if t == 214:
                seen_214 = True
            if t == 903 and seen_214 and "number" not in info:
                d = dict(fields(body(m)))
                info["number"], info["name"] = d[1], d[2].decode()
            elif t == 201:
                for f, slot in fields(body(m)):
                    s = dict(fields(slot))
                    info["chain"].append(f"{s[1].decode()}={s[2].decode()}")
            elif t == 203:
                d = fields(body(m))
                slot, param = d[0][1].decode(), d[1][1]
                if isinstance(param, bytes) and slot == AMP_SLOT:
                    info["params"][param.decode()] = d[2][1]
            elif t == 214:
                info["dirty"] = dict(fields(body(m))).get(1, 0)
        return info


def show(label, info):
    print(f"\n[{label}] preset {info.get('number')} '{info.get('name')}'  "
          f"modificado={info['dirty']}  gain={info['params'].get('gain')}")
    print("   cadena: " + " → ".join(info["chain"]))


async def main(address):
    dev = await BleakScanner.find_device_by_address(address, timeout=20)
    if dev is None:
        sys.exit("No encontré el ampli. ¿Encendido y sin el iPhone conectado?")
    async with BleakClient(dev, timeout=20) as client:
        gt = GT(client)
        await client.start_notify(NOTIFY, gt.on_notify)
        gt.inbox.clear()
        await client.write_gatt_char(WRITE, msg_empty(901), response=True)
        await gt.drain()

        if len(sys.argv) > 2 and sys.argv[2] == "--restore":
            n = int(sys.argv[3])
            print(f">>> 407: seleccionando preset {n}")
            await gt.send(msg_select_preset(n), 1)
            show("restaurado", await gt.current())
            await client.stop_notify(NOTIFY)
            return

        start = await gt.current()
        show("1. inicio", start)
        original = start["number"]
        target = original + 1 if original < 200 else original - 1

        print(f"\n>>> 407: cambiando al preset {target}")
        await gt.send(msg_select_preset(target), 1)
        other = await gt.current()
        show("2. después de cambiar", other)
        await asyncio.sleep(PAUSE)

        orig_gain = other["params"].get("gain")
        if isinstance(orig_gain, float):
            new_gain = round(min(1.0, orig_gain + 0.3) if orig_gain < 0.7 else orig_gain - 0.3, 3)
            print(f"\n>>> 102: gain {orig_gain:.3f} → {new_gain}")
            replies = await gt.send(msg_set_param(AMP_SLOT, "gain", new_gain), 1.5)
            print("   respuestas: " + ", ".join(f"{msg_type(m)}:{dict(fields(body(m)))}" for m in replies))
            await asyncio.sleep(PAUSE)
            print(f">>> 102: restaurando gain a {orig_gain:.3f}")
            await gt.send(msg_set_param(AMP_SLOT, "gain", orig_gain), 1.5)
            check = await gt.current()
            show("3. gain restaurado", check)
        else:
            print("   (este preset no expone 'gain' en el ampli; me salto el paso 102)")

        print(f"\n>>> 407: volviendo al preset {original}")
        await gt.send(msg_select_preset(original), 1)
        end = await gt.current()
        show("4. final", end)
        ok = end.get("number") == original and end["dirty"] == 0
        print("\n" + ("✅ El ampli quedó como estaba." if ok else "⚠️ Revisa el ampli: el estado final no coincide."))
        await client.stop_notify(NOTIFY)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
