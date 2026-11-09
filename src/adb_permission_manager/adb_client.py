"""ADB client module — wraps ADB shell commands via subprocess.

Provides a high-level Python interface for communicating with Android
devices over ADB, used by the ADB Permission Manager tool.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .models import DeviceInfo


class ADBError(Exception):
    """Raised when an ADB command fails."""

    def __init__(
        self,
        message: str,
        command: Optional[str] = None,
        returncode: Optional[int] = None,
    ) -> None:
        self.message = message
        self.command = command
        self.returncode = returncode
        super().__init__(message)

    def __str__(self) -> str:
        parts = [self.message]
        if self.command:
            parts.append(f"command={self.command!r}")
        if self.returncode is not None:
            parts.append(f"returncode={self.returncode}")
        return " | ".join(parts)


class ADBClient:
    """High-level wrapper around the ``adb`` command-line tool.

    Parameters
    ----------
    serial:
        Serial number of a specific device to target.  When *None*, ADB
        uses its default device selection (fails if multiple devices are
        connected).
    adb_path:
        Explicit path to the ``adb`` binary.  Auto-detected via
        :func:`shutil.which` when *None*.
    """

    def __init__(
        self,
        serial: Optional[str] = None,
        adb_path: Optional[str] = None,
    ) -> None:
        if adb_path:
            self.adb_path = adb_path
        else:
            detected = shutil.which("adb")
            if detected is None:
                raise ADBError(
                    "adb not found on PATH. Install Android SDK Platform-Tools "
                    "and ensure 'adb' is in your PATH.  "
                    "Download: https://developer.android.com/tools/releases/platform-tools"
                )
            self.adb_path = detected

        self.serial: Optional[str] = serial

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _run(self, args: list[str], timeout: int = 30) -> str:
        """Execute an ADB command and return its stripped stdout.

        Parameters
        ----------
        args:
            Arguments appended after ``adb [-s <serial>]``.
        timeout:
            Maximum seconds to wait before killing the process.

        Raises
        ------
        ADBError
            On non-zero exit code or any subprocess error.
        """
        cmd: list[str] = [self.adb_path]
        if self.serial:
            cmd.extend(["-s", self.serial])
        cmd.extend(args)

        cmd_str = " ".join(cmd)

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise ADBError(
                f"ADB command timed out after {timeout}s",
                command=cmd_str,
            ) from exc
        except FileNotFoundError as exc:
            raise ADBError(
                f"ADB binary not found at {self.adb_path!r}",
                command=cmd_str,
            ) from exc
        except OSError as exc:
            raise ADBError(
                f"Failed to execute ADB: {exc}",
                command=cmd_str,
            ) from exc

        if result.returncode != 0:
            stderr = result.stderr.strip() or result.stdout.strip()
            raise ADBError(
                message=stderr or f"ADB command failed with code {result.returncode}",
                command=cmd_str,
                returncode=result.returncode,
            )

        return result.stdout.strip()

    # ------------------------------------------------------------------
    # Shell access
    # ------------------------------------------------------------------

    def shell(self, command: str, timeout: int = 30) -> str:
        """Run ``adb shell <command>`` and return its output.

        Parameters
        ----------
        command:
            The shell command string to execute on-device.
        timeout:
            Maximum seconds to wait.
        """
        return self._run(["shell", command], timeout=timeout)

    def get_prop(self, prop: str) -> str:
        """Return the value of a system property via ``getprop``.

        Parameters
        ----------
        prop:
            Property name, e.g. ``ro.product.model``.
        """
        return self._run(["shell", "getprop", prop])

    # ------------------------------------------------------------------
    # Device enumeration
    # ------------------------------------------------------------------

    def list_devices(self) -> list[dict[str, str]]:
        """List authorized ADB devices.

        Runs ``adb devices -l`` (ignoring *self.serial* so every visible
        device is returned) and parses each output line into a dict with
        keys: ``serial``, ``state``, ``model``, ``device``, ``transport_id``.

        Only devices in the ``device`` (authorized) state are included.
        """
        try:
            result = subprocess.run(
                [self.adb_path, "devices", "-l"],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            raise ADBError(f"Failed to list devices: {exc}") from exc

        devices: list[dict[str, str]] = []
        for line in result.stdout.splitlines():
            line = line.strip()
            # Skip header and blank lines
            if not line or line.startswith("List of devices"):
                continue

            parts = line.split()
            if len(parts) < 2:
                continue

            serial = parts[0]
            state = parts[1]

            # Only include authorized ("device") entries
            if state != "device":
                continue

            # Parse key:value tokens from the remainder
            info: dict[str, str] = {
                "serial": serial,
                "state": state,
                "model": "",
                "device": "",
                "transport_id": "",
            }
            for token in parts[2:]:
                if ":" in token:
                    key, _, value = token.partition(":")
                    if key in ("model", "device", "transport_id"):
                        info[key] = value

            devices.append(info)

        return devices

    # ------------------------------------------------------------------
    # Device information
    # ------------------------------------------------------------------

    def get_device_info(self) -> DeviceInfo:
        """Collect basic device metadata and return a :class:`DeviceInfo`.

        Queries several ``ro.*`` system properties and the device serial.
        """
        from .models import DeviceInfo  # runtime import to avoid circular deps

        model = self.get_prop("ro.product.model")
        brand = self.get_prop("ro.product.brand")
        android_version = self.get_prop("ro.build.version.release")
        sdk_version = self.get_prop("ro.build.version.sdk")
        fingerprint = self.get_prop("ro.build.fingerprint")

        serial = self.serial or self._run(["get-serialno"])

        return DeviceInfo(
            serial=serial,
            model=model,
            brand=brand,
            android_version=android_version,
            sdk_version=int(sdk_version) if sdk_version.isdigit() else 0,
            fingerprint=fingerprint,
        )

    # ------------------------------------------------------------------
    # Permission management
    # ------------------------------------------------------------------

    def pm_grant(self, package: str, permission: str) -> tuple[bool, str]:
        """Grant a runtime permission to *package*.

        Returns
        -------
        tuple[bool, str]
            ``(True, "")`` on success, ``(False, error_message)`` on
            failure.
        """
        try:
            self.shell(f"pm grant {package} {permission}")
            return True, ""
        except ADBError as exc:
            return False, exc.message

    def pm_revoke(self, package: str, permission: str) -> tuple[bool, str]:
        """Revoke a runtime permission from *package*.

        Returns
        -------
        tuple[bool, str]
            ``(True, "")`` on success, ``(False, error_message)`` on
            failure.
        """
        try:
            self.shell(f"pm revoke {package} {permission}")
            return True, ""
        except ADBError as exc:
            return False, exc.message

    # ------------------------------------------------------------------
    # AppOps
    # ------------------------------------------------------------------

    def appops_set(
        self, package: str, op: str, mode: str
    ) -> tuple[bool, str]:
        """Set an AppOps mode for *package*.

        Parameters
        ----------
        package:
            Application package name.
        op:
            AppOps operation name (e.g. ``RUN_IN_BACKGROUND``).
        mode:
            One of ``allow``, ``deny``, ``ignore``, ``default``,
            ``foreground``.

        Returns
        -------
        tuple[bool, str]
            ``(True, "")`` on success, ``(False, error_message)`` on
            failure.
        """
        valid_modes = {"allow", "deny", "ignore", "default", "foreground"}
        if mode not in valid_modes:
            return False, f"Invalid mode {mode!r}. Must be one of: {', '.join(sorted(valid_modes))}"

        try:
            self.shell(f"appops set {package} {op} {mode}")
            return True, ""
        except ADBError as exc:
            return False, exc.message

    def appops_get(self, package: str) -> str:
        """Return raw ``appops get`` output for *package*."""
        return self.shell(f"appops get {package}")

    # ------------------------------------------------------------------
    # Package queries
    # ------------------------------------------------------------------

    def list_packages(
        self, include_system: bool = True
    ) -> list[tuple[str, bool]]:
        """List installed packages on the device.

        Parameters
        ----------
        include_system:
            When *True* (default), system packages are included in the
            result.  When *False*, only non-system packages are returned.

        Returns
        -------
        list[tuple[str, bool]]
            Each entry is ``(package_name, is_system)``.
        """
        # Determine which packages are system packages
        system_output = self.shell("pm list packages -s")
        system_packages: set[str] = set()
        for line in system_output.splitlines():
            line = line.strip()
            if line.startswith("package:"):
                system_packages.add(line[len("package:"):])

        # Get all packages
        all_output = self.shell("pm list packages")
        result: list[tuple[str, bool]] = []
        for line in all_output.splitlines():
            line = line.strip()
            if line.startswith("package:"):
                pkg = line[len("package:"):]
                is_system = pkg in system_packages
                if include_system or not is_system:
                    result.append((pkg, is_system))

        return result

    def dumpsys_package(self, package: str) -> str:
        """Return full ``dumpsys package`` output for *package*.

        Uses an extended 60-second timeout because dumpsys can be slow on
        some devices.
        """
        return self.shell(f"dumpsys package {package}", timeout=60)

    # ------------------------------------------------------------------
    # Device readiness
    # ------------------------------------------------------------------

    def wait_for_device(self, timeout: int = 30) -> bool:
        """Block until a device is available or *timeout* seconds elapse.

        Returns
        -------
        bool
            *True* if a device became available, *False* on timeout.
        """
        try:
            self._run(["wait-for-device"], timeout=timeout)
            return True
        except ADBError:
            return False
