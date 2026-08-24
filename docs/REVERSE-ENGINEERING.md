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
   `lsusb | grep -i 5131` — confirm `0513:2007`.
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
