"""Permission applier module.

Applies permission changes to an Android device via ADB,
using pm grant/revoke with appops fallback when pm commands fail.
"""

from dataclasses import dataclass, field
from typing import Optional

from models import PermissionChange, PermissionState, AppOpsMode
from adb_client import ADBClient


@dataclass
class ApplyResult:
    """Result of applying a single permission change."""

    change: PermissionChange
    success: bool
    method: str  # "pm" or "appops" or "pm+appops_fallback"
    error: str = ""


class PermissionApplier:
    """Applies permission changes to a device via ADB.

    Supports pm grant/revoke as the primary mechanism and falls back
    to appops set when pm commands fail for supported permissions.
    """

    def __init__(self, adb: ADBClient) -> None:
        self._adb = adb

        # Mapping of Android permission names to their appops operation names.
        self._perm_to_appops: dict[str, str] = {
            "android.permission.CAMERA": "CAMERA",
            "android.permission.RECORD_AUDIO": "RECORD_AUDIO",
            "android.permission.ACCESS_FINE_LOCATION": "FINE_LOCATION",
            "android.permission.ACCESS_COARSE_LOCATION": "COARSE_LOCATION",
            "android.permission.ACCESS_BACKGROUND_LOCATION": "BACKGROUND_LOCATION",
            "android.permission.READ_CONTACTS": "READ_CONTACTS",
            "android.permission.WRITE_CONTACTS": "WRITE_CONTACTS",
            "android.permission.READ_CALENDAR": "READ_CALENDAR",
            "android.permission.WRITE_CALENDAR": "WRITE_CALENDAR",
            "android.permission.READ_SMS": "READ_SMS",
            "android.permission.SEND_SMS": "SEND_SMS",
            "android.permission.RECEIVE_SMS": "RECEIVE_SMS",
            "android.permission.READ_CALL_LOG": "READ_CALL_LOG",
            "android.permission.WRITE_CALL_LOG": "WRITE_CALL_LOG",
            "android.permission.READ_PHONE_STATE": "READ_PHONE_STATE",
            "android.permission.CALL_PHONE": "CALL_PHONE",
            "android.permission.READ_EXTERNAL_STORAGE": "READ_EXTERNAL_STORAGE",
            "android.permission.WRITE_EXTERNAL_STORAGE": "WRITE_EXTERNAL_STORAGE",
            "android.permission.BODY_SENSORS": "BODY_SENSORS",
            "android.permission.POST_NOTIFICATIONS": "POST_NOTIFICATIONS",
        }

    def apply_changes(
        self,
        changes: list[PermissionChange],
        dry_run: bool = False,
    ) -> list[ApplyResult]:
        """Apply a list of permission changes to the device.

        Args:
            changes: Permission changes to apply.
            dry_run: If True, return what would be done without executing.

        Returns:
            List of ApplyResult for each change.
        """
        results: list[ApplyResult] = []
        total = len(changes)

        for idx, change in enumerate(changes, start=1):
            if dry_run:
                # Determine the method that would be used without executing.
                if change.change_type == "appops":
                    method = "appops"
                elif change.permission_name in self._perm_to_appops:
                    method = "pm (appops fallback available)"
                else:
                    method = "pm"

                action = "GRANT" if change.is_grant else "REVOKE"
                print(
                    f"[{idx}/{total}] DRY RUN: Would {action} "
                    f"{change.permission_name} for {change.package_name} via {method}"
                )
                results.append(
                    ApplyResult(
                        change=change,
                        success=True,
                        method=method,
                    )
                )
            else:
                action = "GRANT" if change.is_grant else "REVOKE"
                print(
                    f"[{idx}/{total}] Applying {action} "
                    f"{change.permission_name} for {change.package_name}..."
                )
                result = self.apply_single_change(change)
                status = "OK" if result.success else f"FAILED: {result.error}"
                print(f"  -> {status}")
                results.append(result)

        return results

    def apply_single_change(self, change: PermissionChange) -> ApplyResult:
        """Apply a single permission change.

        For appops-type changes, uses appops directly. For permission-type
        changes, tries pm grant/revoke first, falling back to appops on failure.

        Args:
            change: The permission change to apply.

        Returns:
            ApplyResult describing the outcome.
        """
        if change.change_type == "appops":
            mode = "allow" if change.is_grant else "deny"
            success, error = self._apply_appops(
                change.package_name, change.permission_name, mode
            )
            return ApplyResult(
                change=change,
                success=success,
                method="appops",
                error=error,
            )

        # change_type == "permission": try pm first, then appops fallback.
        success, error = self._apply_pm(
            change.package_name, change.permission_name, change.is_grant
        )
        if success:
            return ApplyResult(
                change=change,
                success=True,
                method="pm",
            )

        # pm failed — attempt appops fallback.
        fb_success, fb_error = self._apply_appops_fallback(
            change.package_name, change.permission_name, change.is_grant
        )
        if fb_success:
            return ApplyResult(
                change=change,
                success=True,
                method="pm+appops_fallback",
            )

        # Both paths failed; report the original pm error plus fallback error.
        combined_error = f"pm: {error}; appops fallback: {fb_error}"
        return ApplyResult(
            change=change,
            success=False,
            method="pm+appops_fallback",
            error=combined_error,
        )

    def _apply_pm(
        self, package: str, permission: str, grant: bool
    ) -> tuple[bool, str]:
        """Grant or revoke a permission using pm.

        Args:
            package: Application package name.
            permission: Fully-qualified Android permission.
            grant: True to grant, False to revoke.

        Returns:
            Tuple of (success, error_message).
        """
        try:
            if grant:
                return self._adb.pm_grant(package, permission)
            else:
                return self._adb.pm_revoke(package, permission)
        except Exception as exc:
            return False, str(exc)

    def _apply_appops(
        self, package: str, op_name: str, mode: str
    ) -> tuple[bool, str]:
        """Set an appops operation mode.

        Args:
            package: Application package name.
            op_name: The appops operation name (e.g. "CAMERA").
            mode: The mode to set (e.g. "allow", "deny", "ignore").

        Returns:
            Tuple of (success, error_message).
        """
        try:
            return self._adb.appops_set(package, op_name, mode)
        except Exception as exc:
            return False, str(exc)

    def _apply_appops_fallback(
        self, package: str, permission: str, grant: bool
    ) -> tuple[bool, str]:
        """Attempt to apply a permission change via appops as a fallback.

        Looks up the permission in the perm-to-appops mapping and, if found,
        sets the corresponding appops operation to "allow" or "deny".

        Args:
            package: Application package name.
            permission: Fully-qualified Android permission.
            grant: True to grant (allow), False to revoke (deny).

        Returns:
            Tuple of (success, error_message).
        """
        op_name = self._perm_to_appops.get(permission)
        if op_name is None:
            return False, f"No appops fallback available for {permission}"

        mode = "allow" if grant else "deny"
        return self._apply_appops(package, op_name, mode)

    def generate_preview(self, changes: list[PermissionChange]) -> str:
        """Generate a human-readable preview of pending changes.

        Groups changes by package and shows grant/revoke actions with
        fallback indicators where applicable.

        Args:
            changes: Permission changes to preview.

        Returns:
            Formatted preview string.
        """
        if not changes:
            return "No changes to apply."

        # Group changes by package, preserving insertion order.
        by_package: dict[str, list[PermissionChange]] = {}
        for change in changes:
            by_package.setdefault(change.package_name, []).append(change)

        grant_count = 0
        revoke_count = 0
        lines: list[str] = []

        for package, pkg_changes in by_package.items():
            lines.append(f"{package}:")
            for change in pkg_changes:
                if change.is_grant:
                    grant_count += 1
                    marker = "✓"
                    action = "GRANT "
                else:
                    revoke_count += 1
                    marker = "✗"
                    action = "REVOKE"

                suffix = ""
                if change.change_type == "appops":
                    suffix = " (via appops)"
                elif change.permission_name in self._perm_to_appops:
                    suffix = " (via appops fallback)"

                lines.append(f"  {marker} {action} {change.permission_name}{suffix}")

        total = grant_count + revoke_count
        lines.append("")
        lines.append(
            f"Total: {total} change{'s' if total != 1 else ''} "
            f"({grant_count} grant, {revoke_count} revoke)"
        )

        return "\n".join(lines)

    def generate_summary(self, results: list[ApplyResult]) -> str:
        """Generate a summary of applied changes.

        Args:
            results: Apply results to summarise.

        Returns:
            Formatted summary string with success/failure counts
            and details of any failures.
        """
        if not results:
            return "No changes were applied."

        succeeded = [r for r in results if r.success]
        failed = [r for r in results if not r.success]

        lines: list[str] = [
            f"Results: {len(succeeded)} succeeded, {len(failed)} failed "
            f"out of {len(results)} total"
        ]

        if failed:
            lines.append("")
            lines.append("Failures:")
            for r in failed:
                action = "GRANT" if r.change.is_grant else "REVOKE"
                lines.append(
                    f"  ✗ {r.change.package_name} — {action} "
                    f"{r.change.permission_name}: {r.error}"
                )

        return "\n".join(lines)
