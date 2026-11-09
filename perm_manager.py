#!/usr/bin/env python3
"""ADB Permission Manager — Interactive TUI for managing Android app permissions.

Run: python perm_manager.py
"""

import sys
import os
import signal
import time
from typing import Optional

# Rich for styled terminal output (fallback to plain text if unavailable)
try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.prompt import Prompt, Confirm
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
    from rich.text import Text
    from rich import print as rprint
    HAS_RICH = True
except ImportError:
    HAS_RICH = False

from adb_client import ADBClient, ADBError
from scanner import PermissionScanner
from models import (
    DeviceInfo, AppInfo, PermissionInfo, PermissionState,
    AppOpsInfo, AppOpsMode, PermissionChange, DeviceProfile,
)
from profile import ProfileManager
from applier import PermissionApplier, ApplyResult


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
    console.print("\n[bold cyan]╔══════════════════════════════════════╗[/bold cyan]" if HAS_RICH else "")
    console.print("[bold cyan]║   ADB Permission Manager  v1.0      ║[/bold cyan]" if HAS_RICH else "  ADB Permission Manager v1.0")
    console.print("[bold cyan]╚══════════════════════════════════════╝[/bold cyan]\n" if HAS_RICH else "")


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
# Display apps and permissions
# ---------------------------------------------------------------------------

def display_apps_summary(apps: list[AppInfo]):
    """Show a summary table of all apps."""
    user_apps = [a for a in apps if not a.is_system]
    sys_apps = [a for a in apps if a.is_system]

    console.print(f"\n  📊 Total: {len(apps)} apps ({len(user_apps)} user, {len(sys_apps)} system)\n")


def display_app_permissions(app: AppInfo, index: int = 0) -> None:
    """Display permissions for a single app."""
    label = "[SYSTEM] " if app.is_system else ""
    console.print(f"\n  {label}{app.display_name} ({app.package_name})")

    if app.runtime_permissions:
        console.print(f"    Runtime Permissions ({len(app.runtime_permissions)}):")
        for i, perm in enumerate(app.runtime_permissions):
            short = perm.name.replace("android.permission.", "")
            if perm.state == PermissionState.GRANTED:
                status = "✓ GRANTED"
                style = "green"
            elif perm.state == PermissionState.REVOKED:
                status = "✗ REVOKED"
                style = "red"
            else:
                status = "? UNKNOWN"
                style = "yellow"
            if HAS_RICH:
                console.print(f"      [{i+1:2d}] {short:40s} [{style}]{status}[/{style}]")
            else:
                console.print(f"      [{i+1:2d}] {short:40s} {status}")

    if app.appops:
        console.print(f"    App Ops ({len(app.appops)}):")
        for i, op in enumerate(app.appops):
            mode_str = op.mode.value.upper()
            style = "green" if op.mode == AppOpsMode.ALLOW else "red" if op.mode == AppOpsMode.DENY else "yellow"
            if HAS_RICH:
                console.print(f"      [{i+1:2d}] {op.name:40s} [{style}]{mode_str}[/{style}]")
            else:
                console.print(f"      [{i+1:2d}] {op.name:40s} {mode_str}")


# ---------------------------------------------------------------------------
# Interactive permission editor
# ---------------------------------------------------------------------------

def interactive_editor(apps: list[AppInfo], device: DeviceInfo,
                       applier: PermissionApplier, profile_mgr: ProfileManager) -> list[AppInfo]:
    """Main interactive loop for browsing and editing permissions."""

    # Sort: user apps first, then system
    apps_sorted = sorted(apps, key=lambda a: (a.is_system, a.package_name))
    pending_changes: list[PermissionChange] = []
    filter_text = ""
    show_system = True
    page = 0
    page_size = 20

    while True:
        clear_screen()
        print_header()
        console.print(f"  Device: {device.brand} {device.model} ({device.serial})\n")

        # Filter apps
        filtered = apps_sorted
        if filter_text:
            ft = filter_text.lower()
            filtered = [a for a in filtered if ft in a.package_name.lower() or ft in a.app_name.lower()]
        if not show_system:
            filtered = [a for a in filtered if not a.is_system]

        total_pages = max(1, (len(filtered) + page_size - 1) // page_size)
        page = min(page, total_pages - 1)
        page_apps = filtered[page * page_size : (page + 1) * page_size]

        # Display app list
        console.print(f"  Apps ({len(filtered)} shown, page {page+1}/{total_pages})")
        if filter_text:
            console.print(f"  Filter: '{filter_text}'")
        console.print(f"  System apps: {'shown' if show_system else 'hidden'}")
        if pending_changes:
            console.print(f"  Pending changes: {len(pending_changes)}", style="yellow" if HAS_RICH else None)
        console.print("")

        for i, app in enumerate(page_apps):
            idx = page * page_size + i + 1
            sys_tag = " [SYS]" if app.is_system else ""
            perm_count = len(app.runtime_permissions)
            ops_count = len(app.appops)
            console.print(f"  {idx:4d}. {app.display_name}{sys_tag}  ({perm_count} perms, {ops_count} ops)")

        # Menu
        console.print(f"\n{'─'*60}")
        console.print("  Commands:")
        console.print("    [number]   View/edit app permissions")
        console.print("    /text      Filter apps by name")
        console.print("    /          Clear filter")
        console.print("    n/p        Next/Previous page")
        console.print("    t          Toggle system apps")
        console.print("    b          Batch: revoke a permission from ALL apps")
        console.print("    v          View pending changes")
        console.print("    a          Apply pending changes")
        console.print("    s          Save profile (no changes applied)")
        console.print("    q          Quit")
        console.print(f"{'─'*60}")

        cmd = input("\n  > ").strip()

        if cmd.lower() == "q":
            if pending_changes:
                ans = input(f"\n  You have {len(pending_changes)} pending changes. Discard? (y/n): ").strip().lower()
                if ans != "y":
                    continue
            break

        elif cmd.lower() == "n":
            page = min(page + 1, total_pages - 1)

        elif cmd.lower() == "p":
            page = max(page - 1, 0)

        elif cmd.lower() == "t":
            show_system = not show_system
            page = 0

        elif cmd.startswith("/"):
            filter_text = cmd[1:].strip()
            page = 0

        elif cmd.lower() == "v":
            _view_pending_changes(pending_changes, applier)
            input("\n  Press Enter to continue...")

        elif cmd.lower() == "a":
            if not pending_changes:
                console.print("\n  No pending changes.", style="yellow" if HAS_RICH else None)
                input("  Press Enter to continue...")
                continue
            apps = _apply_and_save(pending_changes, applier, profile_mgr, device, apps, scanner=None)
            pending_changes.clear()
            input("\n  Press Enter to continue...")

        elif cmd.lower() == "s":
            profile_mgr.save_profile(device, apps)
            console.print("\n  ✓ Profile saved!", style="green" if HAS_RICH else None)
            input("  Press Enter to continue...")

        elif cmd.lower() == "b":
            new_changes = _batch_revoke_menu(filtered)
            if new_changes:
                pending_changes.extend(new_changes)
                console.print(f"\n  Added {len(new_changes)} changes to pending list.",
                               style="green" if HAS_RICH else None)
            input("\n  Press Enter to continue...")

        else:
            # Try to parse as app number
            try:
                app_num = int(cmd)
                if 1 <= app_num <= len(filtered):
                    app = filtered[app_num - 1]
                    new_changes = _edit_app_permissions(app)
                    if new_changes:
                        pending_changes.extend(new_changes)
                else:
                    console.print(f"  Invalid number. Range: 1-{len(filtered)}")
                    input("  Press Enter...")
            except ValueError:
                console.print("  Unknown command. Try again.", style="yellow" if HAS_RICH else None)
                input("  Press Enter...")

    return apps


def _edit_app_permissions(app: AppInfo) -> list[PermissionChange]:
    """Edit permissions for a single app. Returns list of changes."""
    changes: list[PermissionChange] = []

    while True:
        clear_screen()
        display_app_permissions(app)

        console.print(f"\n{'─'*60}")
        console.print("  Commands:")
        console.print("    g <num>    Grant permission #num")
        console.print("    r <num>    Revoke permission #num")
        console.print("    ga         Grant ALL runtime permissions")
        console.print("    ra         Revoke ALL runtime permissions")
        console.print("    o <num> <mode>   Set appop #num (allow/deny/ignore)")
        console.print("    b          Back (keep staged changes)")
        console.print(f"{'─'*60}")

        if changes:
            console.print(f"\n  Staged changes for this app: {len(changes)}",
                           style="yellow" if HAS_RICH else None)

        cmd = input("\n  > ").strip().lower()

        if cmd == "b":
            break

        parts = cmd.split()
        if not parts:
            continue

        action = parts[0]

        if action == "ga":
            # Grant all runtime permissions
            for perm in app.runtime_permissions:
                if perm.state != PermissionState.GRANTED:
                    changes.append(PermissionChange(
                        package_name=app.package_name,
                        permission_name=perm.name,
                        change_type="permission",
                        old_value=perm.state.value,
                        new_value="granted",
                    ))
            console.print(f"  ✓ Staged: grant all permissions", style="green" if HAS_RICH else None)
            input("  Press Enter...")

        elif action == "ra":
            # Revoke all runtime permissions
            for perm in app.runtime_permissions:
                if perm.state != PermissionState.REVOKED:
                    changes.append(PermissionChange(
                        package_name=app.package_name,
                        permission_name=perm.name,
                        change_type="permission",
                        old_value=perm.state.value,
                        new_value="revoked",
                    ))
            console.print(f"  ✓ Staged: revoke all permissions", style="green" if HAS_RICH else None)
            input("  Press Enter...")

        elif action in ("g", "r") and len(parts) >= 2:
            try:
                nums = [int(x) for x in parts[1:]]
                for num in nums:
                    if 1 <= num <= len(app.runtime_permissions):
                        perm = app.runtime_permissions[num - 1]
                        new_val = "granted" if action == "g" else "revoked"
                        if perm.state.value != new_val:
                            changes.append(PermissionChange(
                                package_name=app.package_name,
                                permission_name=perm.name,
                                change_type="permission",
                                old_value=perm.state.value,
                                new_value=new_val,
                            ))
                            console.print(f"  ✓ Staged: {new_val} {perm.name.split('.')[-1]}",
                                           style="green" if HAS_RICH else None)
                    else:
                        console.print(f"  Invalid permission number: {num}")
            except ValueError:
                console.print("  Usage: g <num> or r <num>")
            input("  Press Enter...")

        elif action == "o" and len(parts) >= 3:
            try:
                num = int(parts[1])
                mode = parts[2]
                if mode not in ("allow", "deny", "ignore", "default", "foreground"):
                    console.print(f"  Invalid mode: {mode}")
                elif 1 <= num <= len(app.appops):
                    op = app.appops[num - 1]
                    if op.mode.value != mode:
                        changes.append(PermissionChange(
                            package_name=app.package_name,
                            permission_name=op.name,
                            change_type="appops",
                            old_value=op.mode.value,
                            new_value=mode,
                        ))
                        console.print(f"  ✓ Staged: {op.name} → {mode}",
                                       style="green" if HAS_RICH else None)
            except (ValueError, IndexError):
                console.print("  Usage: o <num> <allow|deny|ignore>")
            input("  Press Enter...")

        else:
            console.print("  Unknown command.", style="yellow" if HAS_RICH else None)
            input("  Press Enter...")

    return changes


def _batch_revoke_menu(apps: list[AppInfo]) -> list[PermissionChange]:
    """Batch revoke a specific permission from all apps."""
    # Collect all unique runtime permissions across apps
    all_perms: dict[str, int] = {}
    for app in apps:
        for perm in app.runtime_permissions:
            short = perm.name.replace("android.permission.", "")
            all_perms[perm.name] = all_perms.get(perm.name, 0) + 1

    if not all_perms:
        console.print("\n  No runtime permissions found.", style="yellow" if HAS_RICH else None)
        return []

    console.print("\n  Available permissions (and how many apps have them):\n")
    sorted_perms = sorted(all_perms.items(), key=lambda x: -x[1])
    for i, (perm, count) in enumerate(sorted_perms):
        short = perm.replace("android.permission.", "")
        console.print(f"    [{i+1:2d}] {short:40s} ({count} apps)")

    console.print(f"\n  Enter permission numbers to REVOKE from all apps (e.g., '1 3 5')")
    console.print(f"  Or 'c' to cancel")

    cmd = input("\n  > ").strip()
    if cmd.lower() == "c":
        return []

    changes = []
    try:
        nums = [int(x) for x in cmd.split()]
        target_perms = set()
        for num in nums:
            if 1 <= num <= len(sorted_perms):
                target_perms.add(sorted_perms[num - 1][0])

        for app in apps:
            for perm in app.runtime_permissions:
                if perm.name in target_perms and perm.state == PermissionState.GRANTED:
                    changes.append(PermissionChange(
                        package_name=app.package_name,
                        permission_name=perm.name,
                        change_type="permission",
                        old_value="granted",
                        new_value="revoked",
                    ))
    except ValueError:
        console.print("  Invalid input.", style="red" if HAS_RICH else None)

    return changes


def _view_pending_changes(changes: list[PermissionChange], applier: PermissionApplier):
    """Display pending changes."""
    if not changes:
        console.print("\n  No pending changes.")
        return

    console.print(f"\n  Pending Changes ({len(changes)}):\n")
    preview = applier.generate_preview(changes)
    console.print(preview)


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

    # Save profile
    ans = input("\n  Save updated profile? (y/n): ").strip().lower()
    if ans == "y":
        # Re-scan if possible to get accurate state
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
            # Create reverse changes (restore saved values)
            restore_changes = []
            for change in changes:
                restore_changes.append(PermissionChange(
                    package_name=change.package_name,
                    permission_name=change.permission_name,
                    change_type=change.change_type,
                    old_value=change.new_value,  # current becomes old
                    new_value=change.old_value,   # saved becomes target
                ))
            current_apps = _apply_and_save(restore_changes, applier, profile_mgr, device, current_apps, scanner)
            return current_apps

        elif choice == "K":
            profile_mgr.save_profile(device, current_apps)
            console.print("\n  ✓ Profile updated with current state.", style="green" if HAS_RICH else None)
            input("  Press Enter to continue...")
            return current_apps

        elif choice == "E":
            return current_apps  # Will proceed to interactive editor

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

    # Check for adb
    try:
        adb = ADBClient()
    except ADBError as e:
        console.print(f"❌ {e}", style="red" if HAS_RICH else None)
        sys.exit(1)

    # Select device
    device = select_device(adb)
    if not device:
        sys.exit(1)

    # Initialize components
    scanner = PermissionScanner(adb)
    profile_mgr = ProfileManager()
    applier = PermissionApplier(adb)

    # Check for saved profile
    saved_profile = profile_mgr.load_profile(device)

    if saved_profile:
        console.print(f"\n📂 Found saved profile for this device.", style="cyan" if HAS_RICH else None)
        console.print(f"   Last saved: {saved_profile.last_saved}")

        # Scan current state
        current_apps = scan_device(scanner)

        # Show diff
        current_apps = handle_diff(saved_profile, current_apps, profile_mgr, applier, device, scanner)
    else:
        console.print(f"\n📱 No saved profile for this device. Running full scan...",
                       style="cyan" if HAS_RICH else None)
        current_apps = scan_device(scanner)

    # Display summary
    display_apps_summary(current_apps)

    # Enter interactive editor
    current_apps = interactive_editor(current_apps, device, applier, profile_mgr)

    # Final save prompt
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
