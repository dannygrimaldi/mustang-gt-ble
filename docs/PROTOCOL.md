**Title:** Mustang GT100 (fw 3.0.43): BLE protocol notes + offer to test

Hi Tim,

I own a Mustang GT100 and read in CONTRIBUTING.md that GT/GTX support would need someone with the hardware. I did some groundwork and wanted to share it before writing any code, as you asked. Everything below was observed on my own amp; no Fender software was decompiled.

## Method
- Captured Fender Tone (iOS) ↔ amp traffic with Apple's Bluetooth logging profile (sysdiagnose `.pklg`), then decoded the ATT layer.
- Reproduced the read requests, preset select and a live parameter change from macOS with Python + Bleak (CoreBluetooth), without Fender Tone.

## Device / GATT
- USB: `1ed8:0032` ("Fender Mustang-GT USB Audio"). It only exposes USB **audio** interfaces (class 1), no HID, so control is BLE-only.
- BLE advertising name: `Mustang GT`. Manufacturer data, company ID `0x0410`: ASCII `mgt100`.
- One vendor service: `82107b48-5a47-4067-bcc1-319844c8f1e8`
  - It is **advertised byte-reversed** as `e8f1c844-9831-c1bc-6740-475a487b1082`, so scan filters need the reversed UUID.
  - Notify (amp → host): `1017adcc-dcbc-4387-a59f-2546b2ea5bb0`
  - Write with response (host → amp): `820a7e34-4e0a-4f90-8520-04ebce35a3a1`
- No encryption, pairing or authentication: enable notifications, then write.

## Framing
Unlike the Micro Plus captures in the repo, there is no separate header. **Each ATT value is one protobuf message whose single top-level field number is the message type**, e.g. `aa 38 00` = field 901, empty. The messages fit in one ATT value; I saw no reassembly across notifications except the explicit 500/501/502 chunking below.

## Message types seen (field numbers)

Host → amp:
| Type | Body | Meaning |
|---|---|---|
| 901 | empty | Session start. Amp replies 303, 902, 903 ×200, 209, 118, 304 |
| 920 | empty | Request the current preset: 303, 214, 903, 201, 203 ×N, 212, 304 |
| 407 | `{1: n}` | Select preset n (1–200, same numbering as 903 field 1) |
| 102 | `{1: slot, 2: param, 3: float32}` | Set a parameter live, e.g. `{"DUBS_LinearGain_1", "gain", 0.4}` |
| 805 | empty | Request setlists; reply 803 `{1:1, 2:"FAVORITES"}`, 825 |
| 123 | `{1: empty}` | Reply 123 `{1:"off"}`. Unknown, possibly tuner state |

Amp → host:
| Type | Content |
|---|---|
| 902 | `{1: BT MAC, 2: "3.0.43", 3: "On", 4: "Mustang GT", 5: "mustang-gt-100"}` |
| 903 | Preset entry `{1: number, 2: name, 3: UUID, 5: unix time, 7: origin model e.g. "gtx-100", 8, 9, 10}` |
| 201 | Signal chain: repeated `{1: slot id, 2: model id, 3: ?}`, e.g. `DUBS_LinearGain_1 → DUBS_Twin65` |
| 203 | One parameter: `{1: slot id, 2: name, 3: float | 4: string | 6: bool/int}` |
| 214 | `{1: 0|1}`: preset modified flag; becomes 1 after any 102 and clears on preset select |
| 500/501/502 | Chunked transfer of a full preset (start with total size / chunks / end) |
| 212 | `{1: float}` (17.4, 36.5, 7.5…). Unknown |
| 303 / 304 | `{1: 19|23}` / `{1: 19|23, 2: 0}`. Look like begin/end markers of a reply group |
| 306 | `{1:"NO\n", 2:"", 3:""}` sent about once per second, even with no session. Possibly tuner output ("no note") |

Example bytes:
- Select preset 198: `ba 19 03 08 c6 01`
- Set amp gain to 0.4: `b2 06 1e 0a 11 "DUBS_LinearGain_1" 12 04 "gain" 1d cd cc cc 3e`

The slot/model/parameter naming (`DUBS_*`, `gain`, `treb`, `cabsimType`, `gatePreset`…) looks very close to what the LT series uses, so the LT preset model might be reusable.

## Verified from macOS (without Fender Tone)
901 and 920 reads, preset select (407) and live gain change (102) followed by restoring the value. I avoided anything that saves or overwrites presets.

## Offer
I'm happy to run test builds or scripts against the GT100, capture more traffic (saving presets, effects on/off, tuner, firmware info) and contribute code if and when you want it. How would you prefer to proceed: a fork, a scripts/ prototype like `mmp_ble.py`, or just more captures attached here?

Thanks for maneline!
