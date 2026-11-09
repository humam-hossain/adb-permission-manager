"""Profile management for ADB Permission Manager.

Handles saving, loading, diffing, exporting, and importing device
permission profiles stored as human-readable JSON files.
"""

import json
import os
import shutil
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

from models import (
    DeviceInfo,
    DeviceProfile,
    AppInfo,
    PermissionInfo,
    PermissionState,
    AppOpsInfo,
    AppOpsMode,
    PermissionChange,
)

_DEFAULT_PROFILES_DIR = "~/.adb-perms/profiles/"


class ProfileManager:
    """Manages device permission profiles on disk.

    Profiles are stored as pretty-printed JSON files, one per device,
    keyed by ``device_id``.  The format is deliberately human-readable
    and safe to hand-edit when needed.
    """

    def __init__(self, profiles_dir: Optional[str] = None) -> None:
        """Initialise the profile manager.

        Args:
            profiles_dir: Directory to store profile JSON files.
                Defaults to ``~/.adb-perms/profiles/``.
        """
        self.profiles_dir: Path = Path(
            profiles_dir if profiles_dir is not None else _DEFAULT_PROFILES_DIR
        ).expanduser()
        self.profiles_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------

    def get_profile_path(self, device: DeviceInfo) -> Path:
        """Return the canonical file path for a device's profile.

        Args:
            device: Device whose profile path is requested.

        Returns:
            ``<profiles_dir>/<device_id>.json``
        """
        return self.profiles_dir / f"{device.device_id}.json"

    # ------------------------------------------------------------------
    # CRUD operations
    # ------------------------------------------------------------------

    def save_profile(self, device: DeviceInfo, apps: list[AppInfo]) -> Path:
        """Snapshot the current device state to a JSON profile.

        A :class:`DeviceProfile` is created with the current UTC
        timestamp, serialised via ``to_dict()``, and written as
        pretty-printed JSON (indent=2).

        Args:
            device: Device metadata.
            apps: Current list of installed applications with their
                permissions and appops.

        Returns:
            The :class:`Path` the profile was saved to.
        """
        now = datetime.now(timezone.utc).isoformat()
        packages = {app.package_name: app for app in apps}
        profile = DeviceProfile(
            device=device,
            packages=packages,
            last_saved=now,
        )

        path = self.get_profile_path(device)
        data = profile.to_dict()

        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.write("\n")  # trailing newline for POSIX friendliness

        print(f"[profile] Saved profile for {device.device_id} → {path}")
        return path

    def load_profile(self, device: DeviceInfo) -> Optional[DeviceProfile]:
        """Load a previously saved profile for *device*.

        Args:
            device: Device whose profile should be loaded.

        Returns:
            The loaded :class:`DeviceProfile`, or ``None`` when no
            profile file exists or the file contains invalid JSON.
        """
        path = self.get_profile_path(device)
        if not path.exists():
            return None

        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, ValueError) as exc:
            print(f"[profile] Warning: failed to decode {path}: {exc}")
            return None

        return DeviceProfile.from_dict(data)

    def has_profile(self, device: DeviceInfo) -> bool:
        """Check whether a profile file exists for *device*."""
        return self.get_profile_path(device).exists()

    def list_profiles(self) -> list[dict]:
        """Return summary metadata for every profile on disk.

        Each entry is a plain ``dict`` with keys:

        - ``device_id``
        - ``model``
        - ``brand``
        - ``serial``
        - ``last_saved``
        - ``path``

        Profiles that fail to parse are silently skipped.
        """
        summaries: list[dict] = []

        for json_file in sorted(self.profiles_dir.glob("*.json")):
            try:
                with open(json_file, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
            except (json.JSONDecodeError, ValueError):
                continue

            device_data = data.get("device", {})
            summaries.append(
                {
                    "device_id": device_data.get("device_id", ""),
                    "model": device_data.get("model", ""),
                    "brand": device_data.get("brand", ""),
                    "serial": device_data.get("serial", ""),
                    "last_saved": data.get("last_saved", ""),
                    "path": str(json_file),
                }
            )

        return summaries

    def delete_profile(self, device: DeviceInfo) -> bool:
        """Delete the profile file for *device* if it exists.

        Returns:
            ``True`` if a file was deleted, ``False`` otherwise.
        """
        path = self.get_profile_path(device)
        if path.exists():
            path.unlink()
            print(f"[profile] Deleted profile {path}")
            return True
        return False

    # ------------------------------------------------------------------
    # Diff
    # ------------------------------------------------------------------

    def diff_profiles(
        self,
        saved: DeviceProfile,
        current_apps: list[AppInfo],
    ) -> list[PermissionChange]:
        """Compare a saved profile against the current device state.

        For every package present in **both** the saved profile and
        ``current_apps``:

        * Runtime permission states are compared.
        * Appops modes are compared.

        Packages or permissions that only exist in the saved profile
        (e.g. after an uninstall) are silently skipped.  Permissions
        that only exist in the current state are noted as informational
        but **not** included in the returned changes.

        Args:
            saved: The previously saved device profile.
            current_apps: The live list of applications on the device.

        Returns:
            A list of :class:`PermissionChange` objects sorted by
            ``package_name``.
        """
        # Index saved apps by package name for O(1) lookup.
        saved_by_pkg: dict[str, AppInfo] = saved.packages

        # Index current apps by package name.
        current_by_pkg: dict[str, AppInfo] = {
            app.package_name: app for app in current_apps
        }

        changes: list[PermissionChange] = []

        for pkg_name, current_app in current_by_pkg.items():
            saved_app = saved_by_pkg.get(pkg_name)
            if saved_app is None:
                # App wasn't in the saved profile – nothing to diff.
                continue

            # --- Runtime permissions -----------------------------------
            saved_perms: dict[str, PermissionInfo] = {
                p.name: p for p in (saved_app.permissions or [])
            }
            current_perms: dict[str, PermissionInfo] = {
                p.name: p for p in (current_app.permissions or [])
            }

            for perm_name, saved_perm in saved_perms.items():
                current_perm = current_perms.get(perm_name)
                if current_perm is None:
                    # Permission removed from the app – skip.
                    continue

                if saved_perm.state != current_perm.state:
                    changes.append(
                        PermissionChange(
                            package_name=pkg_name,
                            permission_name=perm_name,
                            old_value=saved_perm.state.value
                            if isinstance(saved_perm.state, PermissionState)
                            else str(saved_perm.state),
                            new_value=current_perm.state.value
                            if isinstance(current_perm.state, PermissionState)
                            else str(current_perm.state),
                            change_type="permission",
                        )
                    )

            # --- Appops ------------------------------------------------
            saved_ops: dict[str, AppOpsInfo] = {
                op.name: op for op in (saved_app.appops or [])
            }
            current_ops: dict[str, AppOpsInfo] = {
                op.name: op for op in (current_app.appops or [])
            }

            for op_name, saved_op in saved_ops.items():
                current_op = current_ops.get(op_name)
                if current_op is None:
                    continue

                if saved_op.mode != current_op.mode:
                    changes.append(
                        PermissionChange(
                            package_name=pkg_name,
                            permission_name=op_name,
                            old_value=saved_op.mode.value
                            if isinstance(saved_op.mode, AppOpsMode)
                            else str(saved_op.mode),
                            new_value=current_op.mode.value
                            if isinstance(current_op.mode, AppOpsMode)
                            else str(current_op.mode),
                            change_type="appops",
                        )
                    )

        # Sort by package name for deterministic output.
        changes.sort(key=lambda c: (c.package_name, c.permission))
        return changes

    # ------------------------------------------------------------------
    # Import / Export
    # ------------------------------------------------------------------

    def export_profile(self, device: DeviceInfo, output_path: str) -> Path:
        """Copy a device's profile to an arbitrary path (backup/sharing).

        Args:
            device: Device whose profile should be exported.
            output_path: Destination file path.

        Returns:
            The resolved destination :class:`Path`.

        Raises:
            FileNotFoundError: If no profile exists for the device.
        """
        src = self.get_profile_path(device)
        if not src.exists():
            raise FileNotFoundError(
                f"No profile found for device {device.device_id}"
            )

        dest = Path(output_path).expanduser().resolve()
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        print(f"[profile] Exported {src} → {dest}")
        return dest

    def import_profile(self, input_path: str) -> DeviceProfile:
        """Import a profile from an external path.

        The file is validated by deserialising it into a
        :class:`DeviceProfile`.  A copy is then placed into the managed
        ``profiles_dir`` keyed by the embedded ``device_id``.

        Args:
            input_path: Path to the JSON profile to import.

        Returns:
            The loaded :class:`DeviceProfile`.

        Raises:
            FileNotFoundError: If *input_path* does not exist.
            ValueError: If the file is not valid profile JSON.
        """
        src = Path(input_path).expanduser().resolve()
        if not src.exists():
            raise FileNotFoundError(f"Profile file not found: {src}")

        try:
            with open(src, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, ValueError) as exc:
            raise ValueError(f"Invalid profile JSON in {src}: {exc}") from exc

        profile = DeviceProfile.from_dict(data)

        # Copy into managed profiles directory.
        dest = self.profiles_dir / f"{profile.device.device_id}.json"
        shutil.copy2(src, dest)
        print(f"[profile] Imported profile from {src} → {dest}")

        return profile
