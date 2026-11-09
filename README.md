# ADB Permission Manager

Interactive terminal tool for managing Android app permissions across any device via ADB.

## Features

- **Universal Device Support** — Works with Realme, Xiaomi, Samsung, OnePlus, Pixel, custom ROMs, etc.
- **Full App Scanner** — Scans ALL packages (user + system) with runtime permissions and AppOps
- **Interactive Editor** — Browse apps, toggle permissions, batch revoke across all apps
- **Profile Save/Load** — JSON profiles saved per device identity (`~/.adb-perms/profiles/`)
- **Diff Detection** — Detects permission changes since last save, shows color-coded diff
- **Dual Permission Engine** — Uses `pm grant/revoke` with automatic `appops` fallback for system apps
- **Preview & Confirm** — Shows exactly what will change before applying

## Requirements

- Python 3.10+
- ADB (`android-platform-tools`) installed and in PATH
- USB debugging enabled on target device

## Install

```bash
cd adb-permission-manager
pip install -r requirements.txt
```

## Usage

```bash
python perm_manager.py
```

### Workflow

1. **Connect** your Android device via USB with debugging enabled
2. **Run** the script — it auto-detects your device
3. **If saved profile exists**: shows a diff of what changed since last time
   - `[R]` Restore saved config
   - `[K]` Keep current (update profile)
   - `[E]` Edit interactively
4. **Interactive Editor**: browse apps, toggle permissions
   - Enter a number to view/edit an app's permissions
   - `g 1 3 5` — grant permissions 1, 3, 5
   - `r 2 4` — revoke permissions 2, 4
   - `ga` / `ra` — grant/revoke ALL permissions for the app
   - `o 1 deny` — set AppOps operation 1 to deny
   - `b` — batch revoke a permission across ALL apps
   - `/camera` — filter apps by name
   - `t` — toggle system app visibility
5. **Apply** changes with preview, then save profile

### Profiles

Profiles are saved as JSON in `~/.adb-perms/profiles/<device_id>.json`.
Each device gets a unique profile based on brand + model + serial.

You can:
- Back up profiles by copying the JSON files
- Share profiles between machines
- Hand-edit the JSON if needed
- Version control your profiles with git

## Architecture

```
perm_manager.py    — Main entry point + interactive TUI
adb_client.py      — ADB command wrapper (subprocess)
scanner.py         — Device scanner (dumpsys + appops parser)
profile.py         — Profile save/load/diff/import/export
applier.py         — Permission applier (pm + appops fallback)
models.py          — Data classes and enums
```

## Limitations

- **Install-time permissions** (INTERNET, BLUETOOTH, etc.) cannot be revoked without root
- **Signature-level permissions** on some OEM system apps may resist changes
- **Samsung Knox** protected apps may block some operations
- The tool reports failures clearly and suggests alternatives

## License

MIT
