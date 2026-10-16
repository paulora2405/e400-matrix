# Reverse-engineering notes (E400 / E400 Plus)

Goal: drive the cooler's USB matrix display from Linux without the Windows-only
vendor app.

## Source material

Official package from darkFlash:

`darkFlash_E400 Series_Driver.7z`
→ `darkFlash EXPLORE E400 Air CPU Cooler Driver.rar`
→ `darkFlash E400.msi`
→ installed payload:

- `darkFlash E400.exe` — .NET WinForms UI (`ComputereMonitor`)
- `CyUSB.dll` — Cypress HID helper
- `cpuidsdk*.dll` — host sensor readings
- `SunnyUI*.dll` — UI chrome
- `config.ini` — last-selected sensors / °C flag / auto-start

This is a different stack from the DH360D AIO (`CH340` serial). The E400 panel
is a **USB HID** device.

## Method

1. Extract the MSI with `msiextract` / `7z`.
2. Confirm PE is a .NET assembly (`Mono/.Net assembly`).
3. Disassemble with `monodis` → `e400.il`.
4. Trace:
   - `USB_Init` / `Get_Devices` / `UsbDevices_DeviceAttached`
   - `Thread_Send` → `SendData2` → `send_usb_data`
   - `GetPCParam` (builds `SendValueArray`)
   - `GetNowShow` (ShowData bitmask)
   - `frmMain_FormClosing` (shutdown `0x0F`)

## Key constants recovered

```
VID = 20785 = 0x5131
PID =  8199 = 0x2007
USBDeviceList mask = 4 (HID)
payload length = 0x40 (64)
send loop sleep = 200 ms
```

## Hardware verification still needed

This cloud environment cannot see your local Windows disk or the physical
cooler. Before relying on the daemon:

1. On Linux with the cooler plugged into an internal USB 2.0 header:
   `lsusb | grep -i 5131` — confirm `5131:2007`.
2. `python -m e400plus detect`
3. `python -m e400plus push --cpu-temp 42 --cpu-usage 15 -v` (via daemon verbose)
4. Confirm the matrix updates.

If the VID/PID differs on your unit, open an issue / patch `e400plus/__init__.py`
and the udev rule.

## What we did **not** copy

- CPUID SDK binaries
- SunnyUI / WinForms UI
- Any installer logic or auto-start registry hooks

Sensors come from Linux `hwmon` + `psutil` instead.

## Second pass: what the vendor software can and cannot do

Goal of this pass: find out whether the display's two quirks (it falls back to
the all-pixels pattern when frames stop, including when the PC is off) can be
fixed from the host. Evidence is labelled **observed** (read from the shipped
files or the attached device), **inferred**, or **unknown**.

### Package map

| Archive | Contents |
|---|---|
| `darkFlash EXPLORE E400 Air CPU Cooler Driver.rar` | the MSI the first pass used (.NET Framework 4.7.2 `darkFlash E400.exe`, `CyUSB.dll`, CPUID SDK) |
| `... 1.0.7 (Radeon Optimized)_20260910.rar` and `darkFlash Setup 1.0.7_20260910.exe` | the same file twice: an NSIS installer wrapping an **Electron app** (`app.asar`, internal name "HT_LED", shared by many vendors' display products) |

The Electron app has no E400-specific name, but its `hidWhiteList` contains
VID 20785 (0x5131) / PID 8199 (0x2007), commented "generic Tongtianxiao digital
display". Same device as the E400 (**observed**).

### Findings

1. **The vendor has one HID write path.** Old app: `send_usb_data` →
   `CyHidDevice.WriteOutput`. New app: `client.write(sendList)` in
   `_baseClass/device_hid.js`. There is no feature report, control transfer,
   OTA, brightness, hold, blank or timeout command in either (**observed**;
   the old app's only `CyUSB` calls are `WriteOutput`, `ReadInput`, device
   enumeration and attach/remove events).
2. **Neither app reads from the device.** The old app's `receive_usb_data`
   (the only `ReadInput` user) has no callers (**observed**).
3. **Neither app reacts to power events with a command.**
   - Old app: no `SystemEvents` / `PowerModeChanged` hooks. It sends
     `payload[1]=0x0F` (rest zero) once, in `frmMain_FormClosing` (**observed**,
     IL `IL_9fd4..IL_9fe5`).
   - New app: on lock-screen/suspend it only sets `stops = true`, which halts
     the send loop. It never sends a frame to blank or hold. It sends no `0x0F`
     at all (**observed**). The vendor's own newest software therefore lets the
     panel fall back to its default pattern, which suggests the behaviour is
     firmware, not a driver limitation (**inferred**).
4. **Send period is 200 ms** in both apps (`Thread.Sleep(200)` /
   `getSendIntervalTime() = 200`). The Linux port's default is 500 ms. The
   firmware's silence threshold is **unknown** (`probe silence` measures it).
5. **The frame is the same in both apps** apart from extra fields in the new
   one (see PROTOCOL.md). The new app's first byte `1` sits where the old app
   writes the report ID, which the old app takes from the descriptor
   (`CyHidReport.ID`). The wire payload after that byte is identical.
6. **The port did not send `0x0F` when systemd stopped it.** The daemon only
   sent it on SIGINT; systemd and poweroff use SIGTERM. Fixed in this pass.

### The attached device (passive sysfs read, no I/O)

```
USB 1.1 full speed, bMaxPower 70 mA, 1 configuration, 1 interface
  VID 5131  PID 2007  bcdDevice 0000  iManufacturer/iProduct/iSerial = 0 (no strings)
  Interface 0: class 3 (HID), subclass 0, protocol 0, iInterface 5
  HID 1.00, one report descriptor, wDescriptorLength = 34
  EP 0x81 IN  interrupt 64 B, interval 1
  EP 0x01 OUT interrupt 64 B, interval 1
```

34 bytes matches a minimal vendor-page template with one 64-byte input and one
64-byte output report and no report IDs (**inferred**, not read). That fits the
port writing report ID 0. The actual descriptor has not been read yet.

### Still unknown, and how to find out

The vendor software cannot answer these. The firmware is on the device, not in
the packages. They need the hardware, with the daemon stopped:

| Question | Experiment |
|---|---|
| Does `0x0F` blank the panel, hold the last frame, or do nothing? | `python -m e400plus probe shutdown` |
| How long can the host stay silent before the default pattern appears? | `python -m e400plus probe silence 0.25,0.5,1,2,5` |
| Are there other command bytes at `payload[1]`? | `python -m e400plus probe cmd 0x02` (one value at a time) |
| Exact report descriptor | read it with `usbhid-dump` or `lsusb -v` |

Caution for `probe cmd`: an unknown command byte could be anything, including
a firmware-update entry on some chips. Nothing in the vendor software suggests
one exists on this device, but sweep one value at a time and start with small
values.

### How this answers the two problems

- **Static pattern / hold:** no vendor command exists, so a host-side "hold" is
  only possible if `0x0F` or an undiscovered command does it. Until then the
  only fix is to keep streaming; the silence experiment gives the longest safe
  interval.
- **PC off with USB powered:** nothing on the host can run once the PC is off.
  The only possible fix is a last frame sent during shutdown that makes the
  firmware latch blank or hold. `0x0F` is the one candidate. The daemon now
  sends it on SIGTERM, so a poweroff test is meaningful. If `probe shutdown`
  shows `0x0F` blanks the panel but a poweroff still ends in all-pixels, the
  firmware drops back after a timeout and the second problem is inherent.

## Hardware results (probe runs on a real E400)

Observed by the user, with the daemon stopped:

| Experiment | Result |
|---|---|
| `probe shutdown` (stream, `0x0F`, silence) | all-pixels pattern appeared almost immediately, about 200 ms (eyeballed) |
| `probe silence 0.25,0.5,1,2,5` | all-pixels pattern at **every** gap, including 0.25 s |
| `probe cmd 0x01` .. `0x08` (one frame, rest zero, then silence) | live data while streaming, then all-pixels during the silence. No value latched, held or blanked anything |

What this establishes:

- The firmware has a host-silence watchdog shorter than 0.25 s plus the 200 ms
  stream period (so somewhere around 200 to 450 ms between frames), and nothing
  tested extends it. The vendor's 200 ms send period sits just inside it.
- `0x0F` does **not** blank or latch the display. The exit frame is not a "stay
  off" command, so it cannot fix the PC-off case. (It may still be harmless
  cleanup; the display reset is the same with or without it.)
- Command bytes `0x01` to `0x08` at `payload[1]` do nothing visible.
- The old default of 500 ms per frame was above the watchdog, so the panel
  flashed the default pattern between frames. The default is now 200 ms.

Not yet tested: `0x09` to `0x0E` and `0x10` upward at `payload[1]`; variants in
`payload[0]` and `payload[2]`; the longest steady period that doesn't flicker
(`probe interval 100,200,300,400`).

## Conclusion on the two problems

1. **Static pattern.** Not solvable by a hold command, because none has been
   found in the software or by probing `0x01`..`0x08`. The workaround is to keep
   streaming at a period under the watchdog. Use 200 ms (vendor value, known to
   work), or faster if the interval probe shows flicker at 200 ms.
2. **PC off, USB powered.** Not solvable from the host. With the host off nothing
   sends frames, the watchdog expires in well under a second, and no latching
   command exists. Realistic options are outside software: cut power to the
   cooler's USB header in S5 (BIOS "USB power in S5" / ErP setting, or a header
   that isn't on standby power), or a powered-off-aware USB port switch such as
   `uhubctl` on a hub with per-port power switching (unverified on this
   hardware), or accept the default pattern.
