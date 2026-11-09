#!/usr/bin/env python3
"""ADB Permission Manager — Interactive TUI for managing Android app permissions.

Run: adb-perms
"""

import sys
import os
import time
from typing import Optional

# Rich for styled terminal output (fallback to plain text if unavailable)
try:
    from rich.console import Console
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
    HAS_RICH = True
except ImportError:
    HAS_RICH = False

from .adb_client import ADBClient, ADBError
from .scanner import PermissionScanner
from .models import (
    DeviceInfo, AppInfo, PermissionInfo, PermissionState,
    AppOpsInfo, AppOpsMode, PermissionChange, DeviceProfile,
)
from .profile import ProfileManager
from .applier import PermissionApplier, ApplyResult
from .tui import read_key, visible_rows


# ---------------------------------------------------------------------------
# Console helpers
# ---------------------------------------------------------------------------

if HAS_RICH:
    console = Console()
else:
    class _FallbackConsole:
        def print(self, *args, **kwargs):
            kwargs.pop("style", None)
            kwargs.pop("highlight", None)
            print(*args, **kwargs)
        def rule(self, title="", **kwargs):
            print(f"\n{'='*60}")
            if title:
                print(f"  {title}")
            print(f"{'='*60}")
    console = _FallbackConsole()


def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")


def print_header():
    """Print the app banner."""
    if HAS_RICH:
        console.print("\n[bold cyan]╔══════════════════════════════════════╗[/bold cyan]")
        console.print("[bold cyan]║   ADB Permission Manager  v1.0      ║[/bold cyan]")
        console.print("[bold cyan]╚══════════════════════════════════════╝[/bold cyan]\n")
    else:
        console.print("\n  ADB Permission Manager v1.0\n")


# ---------------------------------------------------------------------------
# State display helpers
# ---------------------------------------------------------------------------

_STATE_DISPLAY = {
    "granted":    ("✓", "GRANTED ",  "green"),
    "revoked":    ("✗", "REVOKED ",  "red"),
    "allow":      ("✓", "ALLOW   ",  "green"),
    "deny":       ("✗", "DENY    ",  "red"),
    "ignore":     ("○", "IGNORE  ",  "yellow"),
    "foreground": ("◐", "FG ONLY ",  "cyan"),
    "default":    ("·", "DEFAULT ",  "dim"),
    "unknown":    ("?", "UNKNOWN ",  "yellow"),
}

# Possible actions per item kind (key char -> new state value)
_PERM_ACTIONS = {"g": "granted", "r": "revoked"}
_APPOPS_ACTIONS = {"g": "allow", "r": "deny", "f": "foreground", "i": "ignore", "d": "default"}


def _state_info(state: str):
    """Return (symbol, label, style) for a state value."""
    return _STATE_DISPLAY.get(state, ("?", state.upper().ljust(8), "yellow"))


def _render_state(state: str) -> str:
    """Return a Rich-formatted or plain string for a state."""
    sym, label, style = _state_info(state)
    if HAS_RICH:
        return f"[{style}]{sym} {label}[/{style}]"
    return f"{sym} {label}"


# ---------------------------------------------------------------------------
# Device selection
# ---------------------------------------------------------------------------

def select_device(adb: ADBClient) -> Optional[DeviceInfo]:
    """Detect and let user select a connected device."""
    console.print("🔍 Detecting devices...", style="bold" if HAS_RICH else None)

    try:
        devices = adb.list_devices()
    except ADBError as e:
        console.print(f"❌ ADB error: {e}", style="red" if HAS_RICH else None)
        return None

    if not devices:
        console.print("❌ No devices found. Make sure USB debugging is enabled.", style="red" if HAS_RICH else None)
        return None

    if len(devices) == 1:
        dev = devices[0]
        adb.serial = dev["serial"]
        info = adb.get_device_info()
        console.print(f"  ✓ Found: {info.brand} {info.model} (serial: {info.serial})",
                       style="green" if HAS_RICH else None)
        return info

    # Multiple devices — let user pick
    console.print(f"\n  Found {len(devices)} devices:\n")
    for i, dev in enumerate(devices):
        console.print(f"    [{i+1}] {dev['serial']}  (model: {dev.get('model', '?')})")

    while True:
        try:
            choice = input(f"\n  Select device [1-{len(devices)}]: ").strip()
            idx = int(choice) - 1
            if 0 <= idx < len(devices):
                adb.serial = devices[idx]["serial"]
                info = adb.get_device_info()
                console.print(f"\n  ✓ Selected: {info.brand} {info.model}",
                               style="green" if HAS_RICH else None)
                return info
        except (ValueError, IndexError):
            pass
        console.print("  Invalid choice, try again.", style="yellow" if HAS_RICH else None)


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------

def scan_device(scanner: PermissionScanner, include_system: bool = True) -> list[AppInfo]:
    """Scan all packages on the device with progress display."""
    console.print("\n📱 Scanning device packages...\n", style="bold" if HAS_RICH else None)

    apps = []
    start_time = time.time()

    if HAS_RICH:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
        ) as progress:
            task = None

            def progress_cb(current, total, pkg_name):
                nonlocal task
                if task is None:
                    task = progress.add_task("Scanning", total=total)
                progress.update(task, completed=current, description=f"Scanning {pkg_name[:40]}")

            apps = scanner.scan_all_packages(include_system=include_system, progress_callback=progress_cb)
    else:
        def progress_cb(current, total, pkg_name):
            if current % 20 == 0:
                print(f"  Scanning... {current}/{total} ({pkg_name})")
        apps = scanner.scan_all_packages(include_system=include_system, progress_callback=progress_cb)

    elapsed = time.time() - start_time
    console.print(f"\n  ✓ Scanned {len(apps)} packages in {elapsed:.1f}s\n",
                   style="green" if HAS_RICH else None)
    return apps


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def display_apps_summary(apps: list[AppInfo]):
    """Show a summary table of all apps."""
    user_apps = [a for a in apps if not a.is_system]
    sys_apps = [a for a in apps if a.is_system]
    console.print(f"\n  📊 Total: {len(apps)} apps ({len(user_apps)} user, {len(sys_apps)} system)\n")


def display_app_permissions(app: AppInfo) -> None:
    """Display permissions for a single app (used in diff view)."""
    label = "[SYSTEM] " if app.is_system else ""
    console.print(f"\n  {label}{app.display_name} ({app.package_name})")

    if app.runtime_permissions:
        console.print(f"    Runtime Permissions ({len(app.runtime_permissions)}):")
        for i, perm in enumerate(app.runtime_permissions):
            short = perm.name.replace("android.permission.", "")
            console.print(f"      [{i+1:2d}] {_render_state(perm.state.value)}  {short}")

    if app.appops:
        console.print(f"    App Ops ({len(app.appops)}):")
        for i, op in enumerate(app.appops):
            console.print(f"      [{i+1:2d}] {_render_state(op.mode.value)}  {op.name}")


# ---------------------------------------------------------------------------
# Scroll/cursor helpers
# ---------------------------------------------------------------------------

def _clamp(val: int, lo: int, hi: int) -> int:
    return max(lo, min(val, hi))


def _ensure_visible(cursor: int, scroll: int, page: int) -> int:
    """Return adjusted scroll so that cursor is visible."""
    if cursor < scroll:
        return cursor
    if cursor >= scroll + page:
        return cursor - page + 1
    return scroll


# ---------------------------------------------------------------------------
# Interactive editor — main app list (arrow-key navigated)
# ---------------------------------------------------------------------------

def interactive_editor(apps: list[AppInfo], device: DeviceInfo,
                       applier: PermissionApplier, profile_mgr: ProfileManager,
                       scanner: Optional[PermissionScanner] = None) -> list[AppInfo]:
    """Main interactive loop — arrow keys to navigate, Enter to drill in."""
    apps_sorted = sorted(apps, key=lambda a: (a.is_system, a.package_name))
    pending_changes: list[PermissionChange] = []
    filter_text = ""
    filter_mode = False
    filter_buf: list[str] = []
    show_system = True
    cursor = 0
    scroll = 0

    while True:
        # Build filtered list
        filtered = apps_sorted
        if filter_text:
            ft = filter_text.lower()
            filtered = [a for a in filtered if ft in a.package_name.lower() or ft in a.app_name.lower()]
        if not show_system:
            filtered = [a for a in filtered if not a.is_system]

        n = len(filtered)
        cursor = _clamp(cursor, 0, max(0, n - 1))
        page = visible_rows()
        scroll = _ensure_visible(cursor, scroll, page)

        # --- Render ---
        clear_screen()
        print_header()
        console.print(f"  Device: {device.brand} {device.model} ({device.serial})")

        parts = []
        if filter_text:
            parts.append(f"Filter: '{filter_text}'")
        parts.append(f"System: {'shown' if show_system else 'hidden'}")
        if pending_changes:
            parts.append(f"Pending: {len(pending_changes)}")
        console.print(f"  {' │ '.join(parts)}\n")

        if not filtered:
            console.print("  No apps match the current filter.\n")
        else:
            console.print(f"  Apps ({n}):\n")
            for vi in range(min(page, n - scroll)):
                ai = scroll + vi
                app = filtered[ai]
                mark = " ▸" if ai == cursor else "  "
                sys_tag = " [SYS]" if app.is_system else ""
                rt = app.runtime_permissions
                granted = sum(1 for p in rt if p.state == PermissionState.GRANTED)
                revoked = len(rt) - granted
                ops = len(app.appops)
                if rt:
                    pi = f"{granted}G/{revoked}R" if not HAS_RICH else f"[green]{granted}G[/green]/[red]{revoked}R[/red]"
                else:
                    pi = "0"
                line = f"{mark} {ai+1:4d}. {app.display_name}{sys_tag}  ({pi} perms, {ops} ops)"
                if ai == cursor and HAS_RICH:
                    console.print(f"[bold]{line}[/bold]")
                else:
                    console.print(line)

        # --- Footer ---
        console.print(f"\n{'─'*62}")
        if filter_mode:
            console.print(f"  Filter: {''.join(filter_buf)}▌  (Enter confirm · Esc cancel)")
        else:
            console.print("  ↑↓/jk Navigate  Enter View app  /Filter  t Sys  m Permissions")
            console.print("  v Pending  a Apply  s Save  q Quit")
        console.print(f"{'─'*62}")

        # --- Input ---
        key = read_key()

        # Filter-mode input
        if filter_mode:
            if key == "ENTER":
                filter_text = "".join(filter_buf)
                filter_mode = False
                cursor = 0
                scroll = 0
            elif key == "ESC":
                filter_mode = False
                filter_buf.clear()
            elif key == "BACKSPACE":
                if filter_buf:
                    filter_buf.pop()
            elif len(key) == 1 and key.isprintable():
                filter_buf.append(key)
            continue

        # Normal-mode keys
        if key in ("UP", "k"):
            cursor = max(0, cursor - 1)
        elif key in ("DOWN", "j"):
            cursor = min(max(0, n - 1), cursor + 1)
        elif key == "PGUP":
            cursor = max(0, cursor - page)
        elif key == "PGDN":
            cursor = min(max(0, n - 1), cursor + page)
        elif key == "ENTER" and filtered:
            app = filtered[cursor]
            new_changes = _edit_app_permissions(app)
            if new_changes:
                pending_changes.extend(new_changes)
        elif key == "/":
            filter_mode = True
            filter_buf = list(filter_text)
        elif key == "t":
            show_system = not show_system
            cursor = 0
            scroll = 0
        elif key == "m":
            new_changes = _permission_browser(filtered)
            if new_changes:
                pending_changes.extend(new_changes)
        elif key == "v":
            clear_screen()
            _view_pending_changes(pending_changes)
            console.print("\n  Press any key to continue...")
            read_key()
        elif key == "a":
            if pending_changes:
                clear_screen()
                apps = _apply_and_save(pending_changes, applier, profile_mgr, device, apps, scanner)
                apps_sorted = sorted(apps, key=lambda a: (a.is_system, a.package_name))
                pending_changes.clear()
                console.print("\n  Press any key to continue...")
                read_key()
        elif key == "s":
            profile_mgr.save_profile(device, apps)
            # Confirmation shows briefly; re-renders next loop
        elif key in ("q", "ESC"):
            if pending_changes:
                clear_screen()
                console.print(f"\n  ⚠ {len(pending_changes)} pending changes will be discarded.")
                console.print("  Press q again to quit, any other key to stay.")
                if read_key() != "q":
                    continue
            break

    return apps


# ---------------------------------------------------------------------------
# App permission editor (arrow-key, unified perms + appops)
# ---------------------------------------------------------------------------

def _edit_app_permissions(app: AppInfo) -> list[PermissionChange]:
    """Edit permissions for a single app. Arrow keys + single-key actions."""
    from .descriptions import get_description

    # Build unified item list: (kind, name, original_state, is_uid, access_str)
    items: list[tuple[str, str, str, bool, str]] = []
    for perm in app.runtime_permissions:
        items.append(("permission", perm.name, perm.state.value, False, ""))
    perm_count = len(app.runtime_permissions)

    # Separate package-level and UID-level appops
    pkg_ops = [op for op in app.appops if not op.is_uid_mode]
    uid_ops = [op for op in app.appops if op.is_uid_mode]
    for op in pkg_ops:
        access = op.last_access or ""
        items.append(("appops", op.name, op.mode.value, False, access))
    uid_start = len(items)
    for op in uid_ops:
        access = op.last_access or ""
        items.append(("appops", op.name, op.mode.value, True, access))

    if not items:
        return []

    staged: dict[str, str] = {}  # name -> new state (only if changed)
    cursor = 0
    scroll = 0

    while True:
        n = len(items)
        cursor = _clamp(cursor, 0, n - 1)
        page = visible_rows()
        scroll = _ensure_visible(cursor, scroll, page)

        clear_screen()
        label = "[SYSTEM] " if app.is_system else ""
        console.print(f"\n  {label}{app.display_name} ({app.package_name})")
        staged_count = sum(1 for name, nv in staged.items()
                          if any(nm == name and orig != nv for _, nm, orig, _, _ in items))
        if staged_count:
            console.print(f"  Staged: {staged_count} change(s)", style="yellow" if HAS_RICH else None)
        console.print("")

        # Section labels explaining categories
        if perm_count > 0:
            if HAS_RICH:
                console.print("      [dim]── Runtime Permissions (dangerous — user-grantable) ──[/dim]")
            else:
                console.print("      ── Runtime Permissions (dangerous — user-grantable) ──")

        # Render items
        showed_ops = False
        showed_uid = False
        for vi in range(min(page, n - scroll)):
            ai = scroll + vi
            kind, name, original, is_uid, access = items[ai]

            # Section separators with category explanations
            if not showed_ops and kind == "appops" and not is_uid and perm_count > 0:
                if HAS_RICH:
                    console.print("      [dim]── App Ops (system-level operation controls) ──[/dim]")
                else:
                    console.print("      ── App Ops (system-level operation controls) ──")
                showed_ops = True
            if not showed_uid and is_uid and uid_start > 0:
                if HAS_RICH:
                    console.print("      [dim]── App Ops UID (shared across all apps with same UID) ──[/dim]")
                else:
                    console.print("      ── App Ops UID (shared across all apps with same UID) ──")
                showed_uid = True

            effective = staged.get(name, original)
            mark = " ▸" if ai == cursor else "  "
            changed = " *" if name in staged and staged[name] != original else ""
            short = name.replace("android.permission.", "") if kind == "permission" else name

            # Build access time suffix
            time_str = ""
            if access:
                time_str = f"  {access}" if not HAS_RICH else f"  [dim]{access}[/dim]"

            if ai == cursor and HAS_RICH:
                console.print(f"[bold]{mark} [{ai+1:2d}] {_render_state(effective)}  {short}{changed}{time_str}[/bold]")
            else:
                console.print(f"{mark} [{ai+1:2d}] {_render_state(effective)}  {short}{changed}{time_str}")

        # Description for cursor item
        _, cur_name, _, cur_uid, _ = items[cursor]
        cur_short = cur_name.replace("android.permission.", "")
        desc = get_description(cur_short)
        if desc:
            console.print("")
            if HAS_RICH:
                console.print(f"  [dim italic]ℹ {desc}[/dim italic]")
            else:
                console.print(f"  ℹ {desc}")

        # Footer — adapt to cursor kind
        cur_kind = items[cursor][0]
        console.print(f"\n{'─'*62}")
        if cur_kind == "permission":
            console.print("  ↑↓ Navigate   g Grant   r Revoke   u Undo   Esc Back")
        else:
            console.print("  ↑↓ Navigate   g Allow   r Deny   f FG only   i Ignore   d Default")
            console.print("  u Undo   Esc Back")
        if staged_count:
            if HAS_RICH:
                console.print(f"  [yellow]★ {staged_count} staged — Esc to go back, then 'a' to apply[/yellow]")
            else:
                console.print(f"  ★ {staged_count} staged — Esc to go back, then 'a' to apply")
        console.print(f"{'─'*62}")

        key = read_key()

        if key in ("UP", "k"):
            cursor = max(0, cursor - 1)
        elif key in ("DOWN", "j"):
            cursor = min(n - 1, cursor + 1)
        elif key == "PGUP":
            cursor = max(0, cursor - page)
        elif key == "PGDN":
            cursor = min(n - 1, cursor + page)
        elif key == "u":
            # Undo: revert staged change on current item
            _, name, _, _, _ = items[cursor]
            staged.pop(name, None)
        elif key in ("q", "ESC"):
            break
        else:
            kind, name, original, _, _ = items[cursor]
            actions = _APPOPS_ACTIONS if kind == "appops" else _PERM_ACTIONS
            new_val = actions.get(key)
            if new_val is not None:
                if new_val == original:
                    staged.pop(name, None)  # revert to original
                else:
                    staged[name] = new_val

    # Convert staged dict to PermissionChange list
    changes: list[PermissionChange] = []
    for kind, name, original, _, _ in items:
        new_val = staged.get(name)
        if new_val is not None and new_val != original:
            changes.append(PermissionChange(
                package_name=app.package_name,
                permission_name=name,
                change_type=kind,
                old_value=original,
                new_value=new_val,
            ))
    return changes


# ---------------------------------------------------------------------------
# Permission browser (arrow-key, browse perms + appops across apps)
# ---------------------------------------------------------------------------

def _permission_browser(apps: list[AppInfo]) -> list[PermissionChange]:
    """Browse all permissions/appops across apps. Arrow keys to navigate."""
    from .descriptions import get_description

    all_changes: list[PermissionChange] = []
    cursor = 0
    scroll = 0

    while True:
        # Build unified index with deduplication.
        # For each permission name, keep one entry per app. If an app has both
        # a runtime permission AND an appops entry for the same capability,
        # we merge them — showing the appops entry (more granular control)
        # and noting it covers both.
        #
        # Canonical name mapping: runtime permission -> appops short name
        _perm_to_ops = {
            "android.permission.ACCESS_FINE_LOCATION": "FINE_LOCATION",
            "android.permission.ACCESS_COARSE_LOCATION": "COARSE_LOCATION",
            "android.permission.CAMERA": "CAMERA",
            "android.permission.RECORD_AUDIO": "RECORD_AUDIO",
            "android.permission.READ_CONTACTS": "READ_CONTACTS",
            "android.permission.WRITE_CONTACTS": "WRITE_CONTACTS",
            "android.permission.READ_CALENDAR": "READ_CALENDAR",
            "android.permission.WRITE_CALENDAR": "WRITE_CALENDAR",
            "android.permission.READ_SMS": "READ_SMS",
            "android.permission.SEND_SMS": "SEND_SMS",
            "android.permission.READ_CALL_LOG": "READ_CALL_LOG",
            "android.permission.READ_PHONE_STATE": "READ_PHONE_STATE",
            "android.permission.READ_EXTERNAL_STORAGE": "READ_EXTERNAL_STORAGE",
            "android.permission.WRITE_EXTERNAL_STORAGE": "WRITE_EXTERNAL_STORAGE",
            "android.permission.READ_MEDIA_IMAGES": "READ_MEDIA_IMAGES",
            "android.permission.READ_MEDIA_VIDEO": "READ_MEDIA_VIDEO",
            "android.permission.READ_MEDIA_AUDIO": "READ_MEDIA_AUDIO",
            "android.permission.BODY_SENSORS": "BODY_SENSORS",
            "android.permission.POST_NOTIFICATIONS": "POST_NOTIFICATION",
            "android.permission.BLUETOOTH_SCAN": "BLUETOOTH_SCAN",
            "android.permission.BLUETOOTH_CONNECT": "BLUETOOTH_CONNECT",
        }

        # Collect appops names that exist for each app (for dedup)
        app_ops_names: dict[str, set[str]] = {}  # pkg -> set of op names
        for app in apps:
            ops_set = set()
            for op in app.appops:
                ops_set.add(op.name)
            app_ops_names[app.package_name] = ops_set

        # _BrowserEntry: (app, state_value, kind, access_time, is_uid)
        perm_index: dict[str, list[tuple[AppInfo, str, str, str, bool]]] = {}

        for app in apps:
            pkg_ops = app_ops_names.get(app.package_name, set())
            for perm in app.runtime_permissions:
                # Skip if there's a matching appops entry (it'll be added below)
                appops_name = _perm_to_ops.get(perm.name)
                if appops_name and appops_name in pkg_ops:
                    continue  # Appops entry covers this
                short = perm.name.replace("android.permission.", "")
                perm_index.setdefault(short, []).append(
                    (app, perm.state.value, "permission", "", False)
                )
            for op in app.appops:
                access = op.last_access or ""
                perm_index.setdefault(op.name, []).append(
                    (app, op.mode.value, "appops", access, op.is_uid_mode)
                )

        if not perm_index:
            clear_screen()
            console.print("\n  No permissions or app ops found.", style="yellow" if HAS_RICH else None)
            console.print("\n  Press any key...")
            read_key()
            return all_changes

        # Categorize: runtime permissions, package appops, UID appops
        perm_entries = []
        ops_entries = []
        uid_entries = []
        for entry_name, entries in perm_index.items():
            kind = entries[0][2]
            is_uid = entries[0][4]
            if kind == "permission":
                perm_entries.append((entry_name, entries, "dangerous"))
            elif is_uid:
                uid_entries.append((entry_name, entries, "appops_uid"))
            else:
                ops_entries.append((entry_name, entries, "appops"))

        perm_entries.sort(key=lambda x: -len(x[1]))
        ops_entries.sort(key=lambda x: -len(x[1]))
        uid_entries.sort(key=lambda x: -len(x[1]))
        sorted_all = perm_entries + ops_entries + uid_entries

        n = len(sorted_all)
        cursor = _clamp(cursor, 0, max(0, n - 1))
        page = visible_rows()
        scroll = _ensure_visible(cursor, scroll, page)

        # Render
        clear_screen()
        console.print("\n  📋 Permission Browser")
        if all_changes:
            console.print(f"  Staged: {len(all_changes)} change(s)", style="yellow" if HAS_RICH else None)
        console.print("")

        showed_perm_header = False
        showed_ops = False
        showed_uid = False
        for vi in range(min(page, n - scroll)):
            ai = scroll + vi
            entry_name, entries, category = sorted_all[ai]

            # Section headers with explanations
            if not showed_perm_header and category == "dangerous":
                if HAS_RICH:
                    console.print("      [dim]── Dangerous (runtime permissions — grant/revoke via Settings) ──[/dim]")
                else:
                    console.print("      ── Dangerous (runtime permissions — grant/revoke via Settings) ──")
                showed_perm_header = True
            if not showed_ops and category == "appops":
                if HAS_RICH:
                    console.print("      [dim]── App Ops (system-level operation controls per app) ──[/dim]")
                else:
                    console.print("      ── App Ops (system-level operation controls per app) ──")
                showed_ops = True
            if not showed_uid and category == "appops_uid":
                if HAS_RICH:
                    console.print("      [dim]── App Ops UID (controls shared by all apps with same user ID) ──[/dim]")
                else:
                    console.print("      ── App Ops UID (controls shared by all apps with same user ID) ──")
                showed_uid = True

            kind = entries[0][2]
            short = entry_name
            total = len(entries)
            active_states = {"granted", "allow", "foreground"}
            active = sum(1 for _, s, _, _, _ in entries if s in active_states)
            restricted = total - active

            mark = " ▸" if ai == cursor else "  "
            if HAS_RICH:
                summary = f"[green]{active} active[/green] / [red]{restricted} restricted[/red]"
            else:
                summary = f"{active} active / {restricted} restricted"
            line = f"{mark} [{ai+1:3d}] {short:38s}  {total} apps  ({summary})"
            if ai == cursor and HAS_RICH:
                console.print(f"[bold]{line}[/bold]")
            else:
                console.print(line)

        # Description for cursor item
        if sorted_all:
            cur_name = sorted_all[cursor][0]
            desc = get_description(cur_name)
            if desc:
                console.print("")
                if HAS_RICH:
                    console.print(f"  [dim italic]ℹ {desc}[/dim italic]")
                else:
                    console.print(f"  ℹ {desc}")

        console.print(f"\n{'─'*62}")
        console.print("  ↑↓ Navigate   Enter Manage per-app   Esc Back")
        if all_changes:
            if HAS_RICH:
                console.print(f"  [yellow]★ {len(all_changes)} staged — Esc to main, then 'a' to apply[/yellow]")
            else:
                console.print(f"  ★ {len(all_changes)} staged — Esc to main, then 'a' to apply")
        console.print(f"{'─'*62}")

        key = read_key()
        if key in ("UP", "k"):
            cursor = max(0, cursor - 1)
        elif key in ("DOWN", "j"):
            cursor = min(max(0, n - 1), cursor + 1)
        elif key == "PGUP":
            cursor = max(0, cursor - page)
        elif key == "PGDN":
            cursor = min(max(0, n - 1), cursor + page)
        elif key == "ENTER" and sorted_all:
            entry_name, entries, category = sorted_all[cursor]
            kind = entries[0][2]
            new_changes = _manage_single_permission(entry_name, kind, entries)
            if new_changes:
                all_changes.extend(new_changes)
        elif key in ("q", "ESC"):
            break

    return all_changes


# ---------------------------------------------------------------------------
# Per-permission app manager (arrow-key, selective grant/revoke per app)
# ---------------------------------------------------------------------------

def _manage_single_permission(
    entry_name: str,
    kind: str,
    app_entries: list[tuple[AppInfo, str, str, str, bool]],
) -> list[PermissionChange]:
    """Manage a single permission/appop across all apps that have it.

    Each entry in app_entries is (app, state_value, kind, access_time, is_uid).
    """
    from .descriptions import get_description

    short = entry_name.replace("android.permission.", "") if kind == "permission" else entry_name

    # Deduplicate by package name — keep the first entry per app
    seen_pkgs: set[str] = set()
    deduped: list[tuple[AppInfo, str, str, str, bool]] = []
    for entry in app_entries:
        pkg = entry[0].package_name
        if pkg not in seen_pkgs:
            seen_pkgs.add(pkg)
            deduped.append(entry)
    app_entries = deduped

    # Sort: active first, then by name
    active_states = {"granted", "allow", "foreground"}
    app_entries = sorted(
        app_entries,
        key=lambda x: (0 if x[1] in active_states else 1, x[0].package_name),
    )

    staged: dict[str, str] = {}  # package_name -> new state
    originals: dict[str, str] = {app.package_name: state for app, state, _, _, _ in app_entries}
    cursor = 0
    scroll = 0

    while True:
        n = len(app_entries)
        cursor = _clamp(cursor, 0, max(0, n - 1))
        page = visible_rows()
        scroll = _ensure_visible(cursor, scroll, page)

        clear_screen()
        total = n
        active = sum(1 for _, s, _, _, _ in app_entries if s in active_states)

        # Category label
        if kind == "permission":
            cat_label = "dangerous"
        elif app_entries and app_entries[0][4]:
            cat_label = "appops uid"
        else:
            cat_label = "appops"

        if HAS_RICH:
            console.print(f"\n  🔐 [bold]{short}[/bold]  ({cat_label})")
            console.print(f"     {total} apps  ([green]{active} active[/green] / [red]{total - active} restricted[/red])")
        else:
            console.print(f"\n  🔐 {short}  ({cat_label})")
            console.print(f"     {total} apps  ({active} active / {total - active} restricted)")

        # Show description
        desc = get_description(short)
        if desc:
            if HAS_RICH:
                console.print(f"  [dim italic]ℹ {desc}[/dim italic]")
            else:
                console.print(f"  ℹ {desc}")

        staged_count = sum(1 for pkg, nv in staged.items() if originals.get(pkg) != nv)
        if staged_count:
            console.print(f"  Staged: {staged_count} change(s)", style="yellow" if HAS_RICH else None)
        console.print("")

        for vi in range(min(page, n - scroll)):
            ai = scroll + vi
            app, original, _, access, is_uid = app_entries[ai]
            effective = staged.get(app.package_name, original)
            mark = " ▸" if ai == cursor else "  "
            sys_tag = " [SYS]" if app.is_system else ""
            changed = " *" if app.package_name in staged and staged[app.package_name] != original else ""

            # Access time suffix
            time_str = ""
            if access:
                time_str = f"  {access}" if not HAS_RICH else f"  [dim]{access}[/dim]"

            if ai == cursor and HAS_RICH:
                console.print(f"[bold]{mark} [{ai+1:3d}] {_render_state(effective)}  {app.display_name}{sys_tag}{changed}{time_str}[/bold]")
            else:
                console.print(f"{mark} [{ai+1:3d}] {_render_state(effective)}  {app.display_name}{sys_tag}{changed}{time_str}")

        # Footer
        actions = _APPOPS_ACTIONS if kind == "appops" else _PERM_ACTIONS
        console.print(f"\n{'─'*62}")
        if kind == "permission":
            console.print("  ↑↓ Navigate   g Grant   r Revoke   u Undo")
            console.print("  G Grant ALL   R Revoke ALL")
        else:
            console.print("  ↑↓ Navigate   g Allow   r Deny   f FG only   i Ignore   d Default")
            console.print("  u Undo   G Allow ALL   R Deny ALL")
        if staged_count:
            if HAS_RICH:
                console.print(f"  [yellow]★ {staged_count} staged — Esc to go back, then 'a' to apply[/yellow]")
            else:
                console.print(f"  ★ {staged_count} staged — Esc to go back, then 'a' to apply")
        console.print("  Esc Back")
        console.print(f"{'─'*62}")

        key = read_key()

        if key in ("UP", "k"):
            cursor = max(0, cursor - 1)
        elif key in ("DOWN", "j"):
            cursor = min(max(0, n - 1), cursor + 1)
        elif key == "PGUP":
            cursor = max(0, cursor - page)
        elif key == "PGDN":
            cursor = min(max(0, n - 1), cursor + page)
        elif key == "u":
            # Undo: revert staged change on current item
            if app_entries:
                app, _, _, _, _ = app_entries[cursor]
                staged.pop(app.package_name, None)
        elif key in ("q", "ESC"):
            break
        elif key == "G":
            # Grant/allow ALL
            new_val = "granted" if kind == "permission" else "allow"
            for app, original, _, _, _ in app_entries:
                if original != new_val:
                    staged[app.package_name] = new_val
                else:
                    staged.pop(app.package_name, None)
        elif key == "R":
            # Revoke/deny ALL
            new_val = "revoked" if kind == "permission" else "deny"
            for app, original, _, _, _ in app_entries:
                if original != new_val:
                    staged[app.package_name] = new_val
                else:
                    staged.pop(app.package_name, None)
        else:
            # Single-item action
            new_val = actions.get(key)
            if new_val is not None and app_entries:
                app, original, _, _, _ = app_entries[cursor]
                if new_val == original:
                    staged.pop(app.package_name, None)
                else:
                    staged[app.package_name] = new_val

    # Build changes
    changes: list[PermissionChange] = []
    for app, original, _, _, _ in app_entries:
        new_val = staged.get(app.package_name)
        if new_val is not None and new_val != original:
            changes.append(PermissionChange(
                package_name=app.package_name,
                permission_name=entry_name,
                change_type=kind,
                old_value=original,
                new_value=new_val,
            ))
    return changes


# ---------------------------------------------------------------------------
# Pending changes view
# ---------------------------------------------------------------------------

def _view_pending_changes(changes: list[PermissionChange]):
    """Display pending changes in a structured, grouped view."""
    if not changes:
        console.print("\n  No pending changes.")
        return

    by_package: dict[str, list[PermissionChange]] = {}
    for change in changes:
        by_package.setdefault(change.package_name, []).append(change)

    grant_total = sum(1 for c in changes if c.is_grant)
    revoke_total = len(changes) - grant_total

    if HAS_RICH:
        console.print(
            f"\n  Pending Changes: {len(changes)} total "
            f"([green]{grant_total} grant[/green], [red]{revoke_total} revoke/restrict[/red]) "
            f"across {len(by_package)} app(s)\n"
        )
    else:
        console.print(
            f"\n  Pending Changes: {len(changes)} total "
            f"({grant_total} grant, {revoke_total} revoke/restrict) "
            f"across {len(by_package)} app(s)\n"
        )

    for pkg, pkg_changes in sorted(by_package.items()):
        console.print(f"  {pkg}:")
        for change in pkg_changes:
            short = change.permission_name.replace("android.permission.", "")
            tag = " [appops]" if change.change_type == "appops" else ""
            console.print(f"    {_render_state(change.new_value)}  {short}{tag}")
        console.print("")


# ---------------------------------------------------------------------------
# Apply and save
# ---------------------------------------------------------------------------

def _apply_and_save(changes: list[PermissionChange], applier: PermissionApplier,
                     profile_mgr: ProfileManager, device: DeviceInfo,
                     apps: list[AppInfo], scanner=None) -> list[AppInfo]:
    """Preview, apply changes, and optionally save profile."""
    console.print("\n  Preview of changes:\n")
    preview = applier.generate_preview(changes)
    console.print(preview)

    ans = input(f"\n  Apply {len(changes)} changes? (y/n): ").strip().lower()
    if ans != "y":
        console.print("  Cancelled.", style="yellow" if HAS_RICH else None)
        return apps

    console.print("")
    results = applier.apply_changes(changes)
    console.print("\n" + applier.generate_summary(results))

    ans = input("\n  Save updated profile? (y/n): ").strip().lower()
    if ans == "y":
        if scanner:
            console.print("\n  Re-scanning to verify...", style="bold" if HAS_RICH else None)
            apps = scan_device(scanner)
        profile_mgr.save_profile(device, apps)
        console.print("  ✓ Profile saved!", style="green" if HAS_RICH else None)

    return apps


# ---------------------------------------------------------------------------
# Diff mode
# ---------------------------------------------------------------------------

def handle_diff(saved_profile: DeviceProfile, current_apps: list[AppInfo],
                 profile_mgr: ProfileManager, applier: PermissionApplier,
                 device: DeviceInfo, scanner: PermissionScanner) -> list[AppInfo]:
    """Handle the case when a saved profile exists — show diff and options."""
    changes = profile_mgr.diff_profiles(saved_profile, current_apps)

    console.print(f"\n📂 Loaded saved profile (last saved: {saved_profile.last_saved})")

    if not changes:
        console.print("\n  ✓ No differences detected. Device matches saved profile.\n",
                       style="green" if HAS_RICH else None)
        input("  Press Enter to continue to editor...")
        return current_apps

    console.print(f"\n⚠️  {len(changes)} permission(s) CHANGED since last save:\n",
                   style="yellow bold" if HAS_RICH else None)

    for change in changes:
        short_perm = change.permission_name.rsplit(".", 1)[-1]
        ptype = f"[{change.change_type}]"
        if HAS_RICH:
            console.print(
                f"  {change.package_name}:\n"
                f"    {short_perm:30s} saved=[bold]{change.old_value}[/bold] → current=[bold red]{change.new_value}[/bold red]  {ptype}"
            )
        else:
            console.print(
                f"  {change.package_name}:\n"
                f"    {short_perm:30s} saved={change.old_value} → current={change.new_value}  {ptype}"
            )

    console.print(f"\n  Options:")
    console.print(f"    [R] Restore saved config (apply {len(changes)} changes)")
    console.print(f"    [K] Keep current state (update profile)")
    console.print(f"    [E] Edit interactively")
    console.print(f"    [Q] Quit")

    while True:
        choice = input("\n  > ").strip().upper()

        if choice == "R":
            restore_changes = []
            for change in changes:
                restore_changes.append(PermissionChange(
                    package_name=change.package_name,
                    permission_name=change.permission_name,
                    change_type=change.change_type,
                    old_value=change.new_value,
                    new_value=change.old_value,
                ))
            current_apps = _apply_and_save(restore_changes, applier, profile_mgr, device, current_apps, scanner)
            return current_apps

        elif choice == "K":
            profile_mgr.save_profile(device, current_apps)
            console.print("\n  ✓ Profile updated with current state.", style="green" if HAS_RICH else None)
            input("  Press Enter to continue...")
            return current_apps

        elif choice == "E":
            return current_apps

        elif choice == "Q":
            sys.exit(0)

        else:
            console.print("  Invalid choice. Use R, K, E, or Q.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    """Main entry point."""
    clear_screen()
    print_header()

    try:
        adb = ADBClient()
    except ADBError as e:
        console.print(f"❌ {e}", style="red" if HAS_RICH else None)
        sys.exit(1)

    device = select_device(adb)
    if not device:
        sys.exit(1)

    scanner = PermissionScanner(adb)
    profile_mgr = ProfileManager()
    applier = PermissionApplier(adb)

    saved_profile = profile_mgr.load_profile(device)

    if saved_profile:
        console.print(f"\n📂 Found saved profile for this device.", style="cyan" if HAS_RICH else None)
        console.print(f"   Last saved: {saved_profile.last_saved}")
        current_apps = scan_device(scanner)
        current_apps = handle_diff(saved_profile, current_apps, profile_mgr, applier, device, scanner)
    else:
        console.print(f"\n📱 No saved profile for this device. Running full scan...",
                       style="cyan" if HAS_RICH else None)
        current_apps = scan_device(scanner)

    display_apps_summary(current_apps)

    current_apps = interactive_editor(current_apps, device, applier, profile_mgr, scanner)

    ans = input("\n  Save profile before exit? (y/n): ").strip().lower()
    if ans == "y":
        profile_mgr.save_profile(device, current_apps)
        console.print("  ✓ Profile saved!", style="green" if HAS_RICH else None)

    console.print("\n  Goodbye! 👋\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n  Interrupted. Goodbye!\n")
        sys.exit(0)
