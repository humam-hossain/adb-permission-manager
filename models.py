"""Data models for ADB Permission Manager.

Defines all core data structures used throughout the tool:
device info, permissions, app-ops, app metadata, change tracking,
and device profile serialization.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class PermissionState(Enum):
    """State of an Android runtime permission."""

    GRANTED = "granted"
    REVOKED = "revoked"
    UNKNOWN = "unknown"


class AppOpsMode(Enum):
    """Modes for ``adb shell appops set``.

    Each variant maps to an ADB-recognised string.
    """

    ALLOW = "allow"
    DENY = "deny"
    IGNORE = "ignore"
    DEFAULT = "default"
    FOREGROUND = "foreground"

    # -- ADB helpers ----------------------------------------------------------

    def to_adb(self) -> str:
        """Return the lowercase string accepted by ``adb shell appops set``."""
        return self.value

    @classmethod
    def from_adb(cls, s: str) -> AppOpsMode:
        """Parse an *appops* mode from ADB output.

        Handles the common abbreviation ``"fg"`` → :pyattr:`FOREGROUND`.

        Raises:
            ValueError: If *s* is not a recognised mode string.
        """
        normalised = s.strip().lower()
        if normalised == "fg":
            return cls.FOREGROUND
        try:
            return cls(normalised)
        except ValueError:
            raise ValueError(
                f"Unknown AppOps mode: {s!r}. "
                f"Expected one of: {', '.join(m.value for m in cls)}, fg"
            ) from None


# ---------------------------------------------------------------------------
# Device
# ---------------------------------------------------------------------------

@dataclass
class DeviceInfo:
    """Information about a connected Android device."""

    serial: str
    model: str
    brand: str
    android_version: str
    sdk_version: int
    fingerprint: str

    @property
    def device_id(self) -> str:
        """Sanitised identifier: ``{brand}_{model}_{serial}``.

        Spaces and non-alphanumeric characters (except ``_`` and ``-``)
        are replaced with underscores.
        """
        raw = f"{self.brand}_{self.model}_{self.serial}"
        return re.sub(r"[^A-Za-z0-9_\-]", "_", raw)


# ---------------------------------------------------------------------------
# Permissions & App-Ops
# ---------------------------------------------------------------------------

@dataclass
class PermissionInfo:
    """A single Android permission attached to a package."""

    name: str
    state: PermissionState
    is_runtime: bool

    @property
    def is_granted(self) -> bool:
        """Whether the permission is currently granted."""
        return self.state is PermissionState.GRANTED


@dataclass
class AppOpsInfo:
    """A single app-ops entry for a package."""

    name: str
    mode: AppOpsMode
    duration: Optional[str] = None


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

@dataclass
class AppInfo:
    """Metadata and permission/appops snapshot for an installed package."""

    package_name: str
    app_name: str = ""
    is_system: bool = False
    permissions: list[PermissionInfo] = field(default_factory=list)
    appops: list[AppOpsInfo] = field(default_factory=list)

    @property
    def runtime_permissions(self) -> list[PermissionInfo]:
        """All runtime (dangerous) permissions for this package."""
        return [p for p in self.permissions if p.is_runtime]

    @property
    def granted_permissions(self) -> list[PermissionInfo]:
        """All currently granted permissions for this package."""
        return [p for p in self.permissions if p.is_granted]

    @property
    def display_name(self) -> str:
        """Human-friendly label, falling back to the package name."""
        return self.app_name if self.app_name else self.package_name


# ---------------------------------------------------------------------------
# Change tracking
# ---------------------------------------------------------------------------

@dataclass
class PermissionChange:
    """Record of a single permission or appops mutation."""

    package_name: str
    permission_name: str
    change_type: str  # "permission" or "appops"
    old_value: str
    new_value: str

    @property
    def is_grant(self) -> bool:
        """``True`` when the new value represents a grant/allow."""
        return self.new_value.lower() in {"granted", "allow"}

    @property
    def description(self) -> str:
        """Human-readable one-liner, e.g.

        ``com.whatsapp: CAMERA granted → revoked``
        """
        short_perm = self.permission_name.rsplit(".", 1)[-1]
        return (
            f"{self.package_name}: {short_perm} "
            f"{self.old_value} → {self.new_value}"
        )


# ---------------------------------------------------------------------------
# Device profile (serialisation layer)
# ---------------------------------------------------------------------------

@dataclass
class DeviceProfile:
    """Full snapshot of a device's permission state, serialisable to JSON."""

    device: DeviceInfo
    last_saved: str  # ISO-8601 timestamp
    packages: dict[str, AppInfo] = field(default_factory=dict)

    # -- Serialisation --------------------------------------------------------

    def to_dict(self) -> dict:
        """Return a plain-dict representation suitable for ``json.dump``."""
        return {
            "device": {
                "serial": self.device.serial,
                "model": self.device.model,
                "brand": self.device.brand,
                "android_version": self.device.android_version,
                "sdk_version": self.device.sdk_version,
                "fingerprint": self.device.fingerprint,
            },
            "last_saved": self.last_saved,
            "packages": {
                pkg: _app_to_dict(app) for pkg, app in self.packages.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict) -> DeviceProfile:
        """Reconstruct a :class:`DeviceProfile` from a plain dict."""
        dev_d = data["device"]
        device = DeviceInfo(
            serial=dev_d["serial"],
            model=dev_d["model"],
            brand=dev_d["brand"],
            android_version=dev_d["android_version"],
            sdk_version=int(dev_d["sdk_version"]),
            fingerprint=dev_d["fingerprint"],
        )
        packages: dict[str, AppInfo] = {}
        for pkg, app_d in data.get("packages", {}).items():
            packages[pkg] = _app_from_dict(app_d)
        return cls(device=device, last_saved=data["last_saved"], packages=packages)


# ---------------------------------------------------------------------------
# Private serialisation helpers
# ---------------------------------------------------------------------------

def _permission_to_dict(p: PermissionInfo) -> dict:
    return {
        "name": p.name,
        "state": p.state.value,
        "is_runtime": p.is_runtime,
    }


def _permission_from_dict(d: dict) -> PermissionInfo:
    return PermissionInfo(
        name=d["name"],
        state=PermissionState(d["state"]),
        is_runtime=d["is_runtime"],
    )


def _appops_to_dict(o: AppOpsInfo) -> dict:
    result: dict = {"name": o.name, "mode": o.mode.value}
    if o.duration is not None:
        result["duration"] = o.duration
    return result


def _appops_from_dict(d: dict) -> AppOpsInfo:
    return AppOpsInfo(
        name=d["name"],
        mode=AppOpsMode(d["mode"]),
        duration=d.get("duration"),
    )


def _app_to_dict(app: AppInfo) -> dict:
    return {
        "package_name": app.package_name,
        "app_name": app.app_name,
        "is_system": app.is_system,
        "permissions": [_permission_to_dict(p) for p in app.permissions],
        "appops": [_appops_to_dict(o) for o in app.appops],
    }


def _app_from_dict(d: dict) -> AppInfo:
    return AppInfo(
        package_name=d["package_name"],
        app_name=d.get("app_name", ""),
        is_system=d.get("is_system", False),
        permissions=[_permission_from_dict(p) for p in d.get("permissions", [])],
        appops=[_appops_from_dict(o) for o in d.get("appops", [])],
    )
