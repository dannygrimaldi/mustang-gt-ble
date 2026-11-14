"""Extrae el tráfico ATT entre un iPhone y el Mustang GT de un PacketLogger .pklg.

Uso: python pklg_gt.py <archivo.pklg> [--all]
"""
import struct
import sys
from collections import defaultdict

GT_SERVICE = "82107b48-5a47-4067-bcc1-319844c8f1e8"
GT_NOTIFY = "1017adcc-dcbc-4387-a59f-2546b2ea5bb0"
GT_WRITE = "820a7e34-4e0a-4f90-8520-04ebce35a3a1"
MARKER = b"mgt100"


def uuid128(le: bytes) -> str:
    h = le[::-1].hex()
    return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


def records(path):
    data = open(path, "rb").read()
    i = 0
    while i + 13 <= len(data):
        (length,) = struct.unpack(">I", data[i:i + 4])
        secs, usecs = struct.unpack(">II", data[i + 4:i + 12])
        typ = data[i + 12]
        payload = data[i + 13:i + 4 + length]
        yield secs + usecs / 1e6, typ, payload
        i += 4 + length


def varint(b, i):
    shift = val = 0
    while True:
        c = b[i]; i += 1
        val |= (c & 0x7F) << shift
        if not c & 0x80:
            return val, i
        shift += 7


def pb(b, depth=0):
    """Decodificación protobuf genérica (sin esquema). Devuelve texto o None."""
    out, i = [], 0
    try:
        while i < len(b):
            key, i = varint(b, i)
            field, wt = key >> 3, key & 7
            if field == 0:
                return None
            if wt == 0:
                v, i = varint(b, i); out.append(f"{field}:{v}")
            elif wt == 2:
                n, i = varint(b, i)
                sub = b[i:i + n]; i += n
                if len(sub) != n:
                    return None
                printable = sub and all(32 <= c < 127 or c in (9, 10) for c in sub)
                inner = pb(sub, depth + 1) if sub and depth < 6 and not printable else None
                if printable:
                    out.append(f"{field}:{sub.decode()!r}")
                elif inner is not None and inner:
                    out.append(f"{field}:{{{inner}}}")
                else:
                    out.append(f"{field}:0x{sub.hex()}")
            elif wt == 5:
                (v,) = struct.unpack("<f", b[i:i + 4]); i += 4; out.append(f"{field}:f{v:.4g}")
            elif wt == 1:
                (v,) = struct.unpack("<d", b[i:i + 8]); i += 8; out.append(f"{field}:d{v:.4g}")
            else:
                return None
        return " ".join(out)
    except (IndexError, struct.error):
        return None


def frame(val: bytes) -> str:
    """El mensaje completo es protobuf: un campo de primer nivel (tipo de mensaje)."""
    dec = pb(val)
    return dec if dec is not None else "(sin formato reconocido) " + val.hex()


def msg_type(val: bytes):
    try:
        key, _ = varint(val, 0)
        return key >> 3
    except IndexError:
        return None


def main():
    path = sys.argv[1]
    t0 = None
    gt_addrs, conn_peer = set(), {}
    acl_buf = {}
    handle_uuid = defaultdict(dict)  # conn -> {attr handle: uuid}
    events = []  # (t, conn, dir, opcode, attr_handle, value)

    for t, typ, p in records(path):
        if t0 is None:
            t0 = t
        if typ == 0x01 and len(p) >= 3 and p[0] == 0x3E:  # LE meta event
            sub = p[2]
            if sub in (0x02, 0x0D) and MARKER in p:
                # el reporte contiene "mgt100": buscar la dirección (6 bytes) del anunciante
                if sub == 0x02:
                    addr = p[6:12]
                else:
                    addr = p[7:13]
                gt_addrs.add(addr)
            elif sub in (0x01, 0x0A):
                status, conn = p[3], struct.unpack("<H", p[4:6])[0] & 0x0FFF
                addr = p[8:14]
                if status == 0:
                    conn_peer[conn] = addr
        elif typ in (0x02, 0x03) and len(p) >= 4:
            hdr, ln = struct.unpack("<HH", p[:4])
            conn, pbf = hdr & 0x0FFF, (hdr >> 12) & 0x3
            chunk = p[4:4 + ln]
            key = (conn, typ)
            if pbf in (0x00, 0x02):
                acl_buf[key] = bytearray(chunk)
            else:
                acl_buf.setdefault(key, bytearray()).extend(chunk)
            buf = acl_buf[key]
            if len(buf) < 4:
                continue
            l2len, cid = struct.unpack("<HH", buf[:4])
            if len(buf) < 4 + l2len:
                continue
            pdu = bytes(buf[4:4 + l2len]); del acl_buf[key]
            if cid != 0x0004 or not pdu:
                continue
            op = pdu[0]
            d = "iPhone→GT" if typ == 0x02 else "GT→iPhone"
            if op == 0x09 and len(pdu) > 2:  # Read By Type Response (declaraciones)
                n = pdu[1]
                for j in range(2, len(pdu) - n + 1, n):
                    ent = pdu[j:j + n]
                    if n == 21:
                        handle_uuid[conn][struct.unpack("<H", ent[3:5])[0]] = uuid128(ent[5:21])
            elif op == 0x05 and len(pdu) > 2:  # Find Information Response
                fmt = pdu[1]; step = 4 if fmt == 1 else 18
                for j in range(2, len(pdu) - step + 1, step):
                    h = struct.unpack("<H", pdu[j:j + 2])[0]
                    u = pdu[j + 2:j + step]
                    handle_uuid[conn].setdefault(h, f"0x{struct.unpack('<H', u)[0]:04x}" if fmt == 1 else uuid128(u))
            elif op in (0x52, 0x12, 0x1B, 0x1D, 0x0B):
                h = struct.unpack("<H", pdu[1:3])[0] if op != 0x0B else None
                val = pdu[3:] if op != 0x0B else pdu[1:]
                events.append((t - t0, conn, d, op, h, val))

    gt_conns = {c for c, a in conn_peer.items() if a in gt_addrs}
    # respaldo: conexiones que descubrieron las características del GT
    for c, m in handle_uuid.items():
        if GT_NOTIFY in m.values() or GT_WRITE in m.values():
            gt_conns.add(c)
    print(f"Direcciones que anuncian 'mgt100': {[a[::-1].hex(':') for a in gt_addrs]}")
    print(f"Conexiones del GT: {sorted(gt_conns)}")
    for c in sorted(gt_conns):
        print(f"\nMapa de handles conexión 0x{c:03x}:")
        for h, u in sorted(handle_uuid[c].items()):
            tag = " <- NOTIFY GT" if u == GT_NOTIFY else " <- WRITE GT" if u == GT_WRITE else ""
            print(f"  0x{h:04x} {u}{tag}")

    names = {0x52: "WriteCmd", 0x12: "WriteReq", 0x1B: "Notify", 0x1D: "Indicate", 0x0B: "ReadRsp"}
    show_all = "--all" in sys.argv
    hide = {int(x) for a in sys.argv if a.startswith("--hide=") for x in a[7:].split(",")}
    print("\nTráfico:")
    last = None
    repeat = 0
    hidden = defaultdict(int)
    for t, c, d, op, h, val in events:
        if c not in gt_conns or op == 0x0B:
            continue
        mt = msg_type(val) if h in (0x0c, 0x10) else None
        if mt in hide:
            hidden[mt] += 1
            continue
        if hidden:
            print("          ... ocultos: " + ", ".join(f"tipo {k} x{v}" for k, v in hidden.items()))
            hidden.clear()
        line = f"{d} h=0x{(h or 0):04x} tipo={mt}  {frame(val) if mt else val.hex()}"
        if not show_all and line == last:
            repeat += 1
            continue
        if repeat:
            print(f"          ... (x{repeat} repetido)")
            repeat = 0
        last = line
        print(f"{t:9.3f}s  {line}")
    if repeat:
        print(f"          ... (x{repeat} repetido)")


if __name__ == "__main__":
    main()
