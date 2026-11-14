# mustang-gt-ble

Herramientas para explorar y controlar un **Fender Mustang GT100** por Bluetooth LE desde macOS, sin la app Fender Tone.
Las notas del protocolo están en [docs/PROTOCOL.md](docs/PROTOCOL.md) (borrador del issue para [maneline](https://github.com/tim-littlefair/maneline)).

Probado con un GT100, firmware 3.0.43, en macOS 14 (Intel) con Python 3.9.

## Instalación

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

La primera vez, macOS pide permiso de Bluetooth para la app desde la que corres los scripts (Terminal o VS Code).
Cierra Fender Tone en el celular antes de usarlos: el ampli acepta una sola conexión.

## Scripts

| Script | Qué hace | ¿Modifica el ampli? |
|---|---|---|
| `gt_recon.py scan [seg]` | Busca el ampli y muestra su ID | No |
| `gt_recon.py gatt <id>` | Lista servicios y características | No |
| `gt_recon.py listen <id> [seg]` | Escucha notificaciones | No |
| `gt_probe.py <id>` | Saludo (901) y preset actual (920) | No |
| `gt_control.py <id>` | Cambia de preset, sube y restaura el gain, vuelve al preset inicial | Temporalmente; nunca guarda |
| `gt_control.py <id> --restore N` | Selecciona el preset N | Cambia el preset activo |
| `pklg_gt.py <archivo.pklg> [--hide=903,306]` | Decodifica una captura de iPhone (PacketLogger/sysdiagnose) | — |

`<id>` es el identificador CoreBluetooth que muestra `scan`; es propio de cada Mac.

## Privacidad

No subas capturas `.pklg`, sysdiagnose ni las salidas de los scripts: incluyen la dirección MAC del ampli
y, en el caso de las capturas, todo el tráfico Bluetooth del teléfono. El `.gitignore` ya las excluye.
