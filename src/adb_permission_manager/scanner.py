"""Scanner module for discovering packages and their permissions/appops on Android devices.

Parses dumpsys and appops output from ADB to build structured permission data.
Designed to be robust across different Android versions and OEM skins.
"""

import logging
import re
from typing import Callable, Optional

from .adb_client import ADBClient
from .models import AppInfo, AppOpsInfo, AppOpsMode, PermissionInfo, PermissionState

logger = logging.getLogger(__name__)


class PermissionScanner:
    """Scans an Android device via ADB for all packages and their permissions/appops."""

    def __init__(self, adb: ADBClient) -> None:
        self._adb = adb

        # Well-known Android runtime (dangerous) permissions, grouped by category.
        self._known_runtime_permissions: set[str] = {
            # Calendar
            "android.permission.READ_CALENDAR",
            "android.permission.WRITE_CALENDAR",
            # Camera
            "android.permission.CAMERA",
            # Contacts
            "android.permission.READ_CONTACTS",
            "android.permission.WRITE_CONTACTS",
            "android.permission.GET_ACCOUNTS",
            # Location
            "android.permission.ACCESS_FINE_LOCATION",
            "android.permission.ACCESS_COARSE_LOCATION",
            "android.permission.ACCESS_BACKGROUND_LOCATION",
            # Microphone
            "android.permission.RECORD_AUDIO",
            # Phone
            "android.permission.READ_PHONE_STATE",
            "android.permission.READ_PHONE_NUMBERS",
            "android.permission.CALL_PHONE",
            "android.permission.ANSWER_PHONE_CALLS",
            "android.permission.ADD_VOICEMAIL",
            "android.permission.USE_SIP",
            "android.permission.READ_CALL_LOG",
            "android.permission.WRITE_CALL_LOG",
            "android.permission.PROCESS_OUTGOING_CALLS",
            # Sensors
            "android.permission.BODY_SENSORS",
            "android.permission.BODY_SENSORS_BACKGROUND",
            # SMS
            "android.permission.SEND_SMS",
            "android.permission.RECEIVE_SMS",
            "android.permission.READ_SMS",
            "android.permission.RECEIVE_WAP_PUSH",
            "android.permission.RECEIVE_MMS",
            # Storage
            "android.permission.READ_EXTERNAL_STORAGE",
            "android.permission.WRITE_EXTERNAL_STORAGE",
            "android.permission.READ_MEDIA_IMAGES",
            "android.permission.READ_MEDIA_VIDEO",
            "android.permission.READ_MEDIA_AUDIO",
            "android.permission.MANAGE_EXTERNAL_STORAGE",
            # Nearby / Bluetooth / WiFi
            "android.permission.BLUETOOTH_SCAN",
            "android.permission.BLUETOOTH_ADVERTISE",
            "android.permission.BLUETOOTH_CONNECT",
            "android.permission.NEARBY_WIFI_DEVICES",
            "android.permission.UWB_RANGING",
            # Notifications
            "android.permission.POST_NOTIFICATIONS",
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def scan_all_packages(
        self,
        include_system: bool = True,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
    ) -> list[AppInfo]:
        """Scan every installed package and return structured permission data.

        Args:
            include_system: If ``True``, system packages are included in the
                results.  They are always *scanned* so that the caller can
                filter later, but when ``False`` they are omitted from the
                returned list.
            progress_callback: Optional ``(current_index, total_count,
                package_name)`` callable invoked once per package.

        Returns:
            A list of :class:`AppInfo` instances, one per successfully scanned
            package.
        """
        packages: list[tuple[str, bool]] = self._adb.list_packages()
        total = len(packages)
        results: list[AppInfo] = []

        for idx, (pkg_name, is_system) in enumerate(packages):
            if progress_callback is not None:
                progress_callback(idx, total, pkg_name)

            if not include_system and is_system:
                continue

            try:
                app_info = self.scan_package(pkg_name, is_system=is_system)
                results.append(app_info)
            except Exception:
                logger.warning(
                    "Failed to scan package '%s', skipping.", pkg_name, exc_info=True
                )

        return results

    def scan_package(self, package_name: str, is_system: bool = False) -> AppInfo:
        """Scan a single package for runtime permissions and appops.

        Args:
            package_name: Fully-qualified package name (e.g.
                ``com.example.app``).
            is_system: Whether this package is a system app.

        Returns:
            An :class:`AppInfo` populated with permission and appops data.
        """
        dumpsys_output: str = self._adb.dumpsys_package(package_name)
        permissions = self._parse_runtime_permissions(dumpsys_output)
        appops = self._parse_appops(package_name)

        return AppInfo(
            package_name=package_name,
            is_system=is_system,
            permissions=permissions,
            appops=appops,
        )

    # ------------------------------------------------------------------
    # Internal parsing helpers
    # ------------------------------------------------------------------

    def _parse_runtime_permissions(self, dumpsys_output: str) -> list[PermissionInfo]:
        """Extract runtime permission entries from ``dumpsys package`` output.

        The parser is intentionally lenient to cope with format differences
        across Android versions (9‑14+) and OEM skins.

        Strategy:
        1. Collect *requested* permissions so we know the full set the app
           declared in its manifest.
        2. Walk through the ``runtime permissions:`` section (scoped to
           ``User 0:`` when present) and parse granted / flags.
        3. Any requested permission that is also in the known-runtime set but
           was *not* listed under runtime permissions is reported with state
           ``UNKNOWN``.
        """
        permissions: list[PermissionInfo] = []
        seen_names: set[str] = set()

        # --- 1. Collect requested permissions ----------------------------
        requested_perms: set[str] = set()
        requested_section = False
        for line in dumpsys_output.splitlines():
            stripped = line.strip()
            if stripped.startswith("requested permissions:"):
                requested_section = True
                continue
            if requested_section:
                # Section ends at the next non-indented / non-permission line
                if stripped.startswith("android.permission.") or stripped.startswith(
                    "com."
                ):
                    requested_perms.add(stripped)
                elif stripped == "":
                    continue  # blank lines inside section
                else:
                    # Heuristic: if the line doesn't look like a permission,
                    # we've left the section.
                    if not stripped.startswith("android.") and not stripped.startswith(
                        "com."
                    ):
                        requested_section = False

        # --- 2. Parse runtime permissions section -------------------------
        # We want the block under "User 0:" → "runtime permissions:".
        # On single-user devices it may just be "runtime permissions:" at root.
        runtime_section_lines = self._extract_runtime_section(dumpsys_output)

        # Pattern covers both old and new formats:
        #   android.permission.CAMERA: granted=true
        #   android.permission.CAMERA: granted=true, flags=[ USER_SET ]
        perm_re = re.compile(
            r"^\s*"
            r"(?P<name>[\w.]+)"  # permission name
            r"\s*:\s*"
            r"granted\s*=\s*(?P<granted>true|false)"  # granted value
            r"(?:\s*,\s*flags\s*=\s*\[\s*(?P<flags>[^\]]*)\])?"  # optional flags
        )

        for line in runtime_section_lines:
            m = perm_re.match(line)
            if m is None:
                continue
            perm_name = m.group("name")
            granted = m.group("granted") == "true"
            is_runtime = self._is_runtime_permission(perm_name)

            state = PermissionState.GRANTED if granted else PermissionState.REVOKED

            permissions.append(
                PermissionInfo(
                    name=perm_name,
                    is_runtime=is_runtime,
                    state=state,
                )
            )
            seen_names.add(perm_name)

        # --- 3. Cross-reference requested permissions ---------------------
        for perm_name in sorted(requested_perms):
            if perm_name in seen_names:
                continue
            if self._is_runtime_permission(perm_name):
                permissions.append(
                    PermissionInfo(
                        name=perm_name,
                        is_runtime=True,
                        state=PermissionState.UNKNOWN,
                    )
                )

        return permissions

    def _extract_runtime_section(self, dumpsys_output: str) -> list[str]:
        """Return the lines belonging to the *runtime permissions* block.

        Attempts to scope to ``User 0:`` first.  Falls back to the first
        ``runtime permissions:`` header found anywhere in the output.
        """
        lines = dumpsys_output.splitlines()

        # Try to find "User 0:" scoped section first.
        user0_start: Optional[int] = None
        for i, line in enumerate(lines):
            if re.match(r"^\s*User\s+0\s*:", line):
                user0_start = i
                break

        search_start = user0_start if user0_start is not None else 0

        runtime_start: Optional[int] = None
        for i in range(search_start, len(lines)):
            if re.match(r"^\s*runtime permissions:\s*$", lines[i]):
                runtime_start = i + 1
                break

        if runtime_start is None:
            return []

        # Determine the indentation level of the header to know when we leave
        # the block.
        header_indent = len(lines[runtime_start - 1]) - len(
            lines[runtime_start - 1].lstrip()
        )

        result: list[str] = []
        for i in range(runtime_start, len(lines)):
            stripped = lines[i].strip()
            if stripped == "":
                continue
            current_indent = len(lines[i]) - len(lines[i].lstrip())
            # If we encounter a line at the same or lesser indentation that
            # doesn't look like a permission entry, we've left the section.
            if current_indent <= header_indent and stripped != "":
                break
            result.append(lines[i])

        return result

    def _parse_appops(self, package_name: str) -> list[AppOpsInfo]:
        """Parse ``appops get <package>`` output into structured data.

        Handles all common output formats across Android versions:

        Old format::

            COARSE_LOCATION: allow; time=+15h ago; duration=+106ms

        New format (Android 12+)::

            COARSE_LOCATION (uid=10234): mode=ignore; time=+15h ago
            Uid mode:
              START_FOREGROUND (uid=10234): mode=allow; time=+2m ago

        Also handles: ``No operations.``

        Returns:
            A list of :class:`AppOpsInfo`, with uid-mode entries marked.
        """
        raw_output: str = self._adb.appops_get(package_name)

        if not raw_output or "No operations" in raw_output:
            return []

        results: list[AppOpsInfo] = []

        # Regex handles both old and new formats:
        #   OP_NAME: mode                       (old)
        #   OP_NAME (uid=N): mode=value; ...    (new)
        op_re = re.compile(
            r"(?P<name>[A-Z][A-Z0-9_]*)"       # operation name
            r"(?:\s*\([^)]*\))?"                # optional (uid=N) annotation
            r"\s*:\s*"
            r"(?:mode\s*=\s*)?"                 # optional "mode=" prefix (new format)
            r"(?P<mode>\w+)"                    # mode value
            r"(?:\s*;\s*(?P<extras>.*))?",       # optional semicolon-separated extras
        )

        time_re = re.compile(r"(?<!\w)time\s*=\s*\+?(?P<val>[^;]+?)(?:\s+ago)?(?:\s*;|$)")
        reject_re = re.compile(r"rejectTime\s*=\s*\+?(?P<val>[^;]+?)(?:\s+ago)?(?:\s*;|$)")
        duration_re = re.compile(r"duration\s*=\s*\+?(?P<val>[^\s;]+)")

        in_uid_mode = False

        for line in raw_output.splitlines():
            stripped = line.strip()
            if not stripped:
                continue

            # Section headers
            lower = stripped.lower()
            if lower.startswith("uid mode"):
                in_uid_mode = True
                continue
            if lower.startswith("package mode"):
                in_uid_mode = False
                continue

            # Skip package name header lines (e.g., "com.dot.gallery:")
            if stripped.endswith(":") and "." in stripped and " " not in stripped.rstrip(":"):
                continue

            m = op_re.match(stripped)
            if m is None:
                logger.debug(
                    "Skipping unparseable appops line for %s: %r",
                    package_name,
                    stripped,
                )
                continue

            op_name = m.group("name")
            mode_str = m.group("mode")
            extras = m.group("extras") or ""

            try:
                mode = AppOpsMode.from_adb(mode_str)
            except (ValueError, KeyError):
                logger.warning(
                    "Unknown appops mode '%s' for op '%s' in package '%s', skipping.",
                    mode_str,
                    op_name,
                    package_name,
                )
                continue

            duration: Optional[str] = None
            dur_m = duration_re.search(extras)
            if dur_m:
                duration = dur_m.group("val")

            last_access: Optional[str] = None
            time_m = time_re.search(extras)
            if time_m:
                last_access = time_m.group("val").strip()

            last_reject: Optional[str] = None
            rej_m = reject_re.search(extras)
            if rej_m:
                last_reject = rej_m.group("val").strip()

            results.append(
                AppOpsInfo(
                    name=op_name,
                    mode=mode,
                    is_uid_mode=in_uid_mode,
                    duration=duration,
                    last_access=last_access,
                    last_reject=last_reject,
                )
            )

        return results

    def _is_runtime_permission(self, perm_name: str) -> bool:
        """Return ``True`` if *perm_name* is a known Android runtime permission."""
        return perm_name in self._known_runtime_permissions
