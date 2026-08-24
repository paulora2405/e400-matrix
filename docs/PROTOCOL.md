# E400 / E400 Plus HID protocol

Recovered from the official Windows app `darkFlash E400.exe` (CyUSB HID + CPUID SDK).

## Transport

| Property | Value |
|---|---|
| USB VID:PID | `0513:2007` |
| Class | HID |
| Windows stack | Cypress `CyUSB.dll` → `CyHidDevice` |
| Linux stack | `hidapi` / `hidraw` |
| Payload size | **64 bytes** (plus 1-byte report ID, usually `0x00`) |
| Update rate | Windows app sleeps **200 ms** between frames |

Device discovery uses `USBDeviceList(0x04)` (HID mask) and opens
`usbDevices[0x5131, 0x2007]`.

## Frame layout

Every live stats write is:

```
report_id | payload[64]
```

`payload`:

| Offset | Value | Meaning |
|------:|-------|---------|
| 0 | `0x00` | header |
| 1 | `0x01` | header |
| 2 | `0x02` | header |
| 3…62 | `SendValueArray[0…59]` | packed metrics (see below) |
| 63 | `0x00` | unused / padding |

On app exit (`FormClosing`), Windows sends a 64-byte payload with
`payload[1] = 0x0F` (shutdown) and the rest zero.

`send_usb_data` copies: `DataBuf[0] = report ID`, then
`DataBuf[i] = payload[i-1]` for `i = 1…length`, then `WriteOutput()`.

## SendValueArray map

Indices below are into the 60-int array; on the wire they sit at
`payload[3 + index]`.

| Index | Field |
|------:|-------|
| 0 | CPU temp integer |
| 1 | CPU temp fractional × 100 |
| 2 | `0` = °C, `1` = °F |
| 3 | CPU usage % |
| 4 | CPU power: `floor(W) % 100` |
| 5 | CPU power fractional × 100 |
| 6 | CPU freq MHz ÷ 100 |
| 7 | CPU freq MHz % 100 |
| 8 | CPU voltage integer |
| 9 | CPU voltage fractional × 100 |
| 10 | GPU temp integer |
| 11 | GPU temp fractional × 100 |
| 12 | GPU °C/°F flag |
| 13 | GPU usage % |
| 14 | GPU power: `floor(W) % 100` |
| 15 | GPU power fractional × 100 |
| 16–17 | GPU freq (÷100, %100) |
| 18–19 | Fan RPM (÷100, %100) |
| 20–21 | Water/pump RPM (÷100, %100) |
| 22–23 | Year (`20`, `26` for 2026) |
| 24 | Month |
| 25 | Day |
| 26 | Hour |
| 27 | Minute |
| 28 | Second |
| 29 | Day of week (`.NET`: Sun=0 … Sat=6) |
| 30 | RAM / “mainboard usage” % |
| 31 | CPU power hundreds (`floor(W) // 100`) |
| 32–34 | GPU power hundreds (vendor duplicates) |
| 36 | **ShowData bitmask** |

### ShowData bitmask (`index 36`)

| Bit value | Metric |
|----------:|--------|
| 1 | CPU temperature |
| 2 | CPU usage |
| 4 | GPU temperature |
| 8 | GPU usage |

The panel rotates among the enabled bits.

## Notes

- Values are truncated to bytes (`conv.u1` / `ToInt16` then low 8 bits).
- Large integers (power, frequency, RPM) are split into hundred-groups so
  each digit pair fits in a single byte for the matrix glyph renderer.
- ARGB lighting is **not** controlled over this USB path — it uses the
  motherboard 5V ARGB header.
