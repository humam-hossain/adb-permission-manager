"""Human-readable descriptions for Android permissions and AppOps.

Used by the TUI to show contextual help for the currently highlighted item.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Runtime permissions (keyed by short name, without "android.permission.")
# ---------------------------------------------------------------------------

_PERMISSION_DESCRIPTIONS: dict[str, str] = {
    # Camera
    "CAMERA": "Take photos and record video using the device camera",

    # Microphone
    "RECORD_AUDIO": "Record audio using the microphone",

    # Location
    "ACCESS_FINE_LOCATION": "Access precise GPS location (within ~10m)",
    "ACCESS_COARSE_LOCATION": "Access approximate location via cell towers and WiFi (~1km)",
    "ACCESS_BACKGROUND_LOCATION": "Access location while running in the background",

    # Contacts
    "READ_CONTACTS": "Read names, numbers, and emails from the address book",
    "WRITE_CONTACTS": "Add, modify, or delete contacts",
    "GET_ACCOUNTS": "List accounts configured on the device",

    # Calendar
    "READ_CALENDAR": "Read calendar events and details",
    "WRITE_CALENDAR": "Create, modify, or delete calendar events",

    # SMS
    "SEND_SMS": "Send SMS messages (may incur charges)",
    "RECEIVE_SMS": "Receive and read incoming SMS messages",
    "READ_SMS": "Read stored SMS messages",
    "RECEIVE_WAP_PUSH": "Receive WAP push messages",
    "RECEIVE_MMS": "Receive MMS messages",

    # Phone
    "READ_PHONE_STATE": "Read phone number, IMEI, call state, and network info",
    "READ_PHONE_NUMBERS": "Read the device phone number(s)",
    "CALL_PHONE": "Initiate phone calls without the dialer UI",
    "ANSWER_PHONE_CALLS": "Automatically answer incoming calls",
    "ADD_VOICEMAIL": "Add voicemail messages",
    "USE_SIP": "Make or receive SIP (internet) calls",
    "READ_CALL_LOG": "Read the call history",
    "WRITE_CALL_LOG": "Modify or delete the call history",
    "PROCESS_OUTGOING_CALLS": "See and redirect outgoing calls",

    # Sensors
    "BODY_SENSORS": "Access heart rate, step counter, and other body sensors",
    "BODY_SENSORS_BACKGROUND": "Access body sensors in the background",

    # Storage
    "READ_EXTERNAL_STORAGE": "Read files from shared storage (photos, downloads, etc.)",
    "WRITE_EXTERNAL_STORAGE": "Write or delete files on shared storage",
    "READ_MEDIA_IMAGES": "Read photos and images from the media store",
    "READ_MEDIA_VIDEO": "Read video files from the media store",
    "READ_MEDIA_AUDIO": "Read music and audio files from the media store",
    "MANAGE_EXTERNAL_STORAGE": "Full access to all files on shared storage (broad file manager access)",

    # Bluetooth / Nearby
    "BLUETOOTH_SCAN": "Discover nearby Bluetooth devices",
    "BLUETOOTH_ADVERTISE": "Make the device visible to other Bluetooth devices",
    "BLUETOOTH_CONNECT": "Connect to paired Bluetooth devices",
    "NEARBY_WIFI_DEVICES": "Discover and connect to nearby WiFi devices",
    "UWB_RANGING": "Determine precise distance to nearby UWB devices",

    # Notifications
    "POST_NOTIFICATIONS": "Show notifications in the status bar and notification shade",

    # Network (not a runtime permission but commonly managed via AppOps)
    "INTERNET": "Access the internet — all network communication",
}


# ---------------------------------------------------------------------------
# AppOps operations (keyed by op name)
# ---------------------------------------------------------------------------

_APPOPS_DESCRIPTIONS: dict[str, str] = {
    # Location
    "COARSE_LOCATION": "Approximate location access (AppOps-level control)",
    "FINE_LOCATION": "Precise GPS location access (AppOps-level control)",
    "MONITOR_LOCATION": "Continuously monitor device location",
    "MONITOR_HIGH_POWER_LOCATION": "Continuous GPS monitoring (high battery drain)",
    "ACCESS_MEDIA_LOCATION": "Read GPS coordinates embedded in photos and videos",
    "MOCK_LOCATION": "Provide fake location data to other apps",

    # Camera / Mic
    "CAMERA": "Camera access (AppOps-level control)",
    "RECORD_AUDIO": "Microphone access (AppOps-level control)",

    # Background / Foreground
    "START_FOREGROUND": "Start a visible foreground service (shows notification)",
    "RUN_IN_BACKGROUND": "Run in the background (battery-managed)",
    "RUN_ANY_IN_BACKGROUND": "Run any operation in the background without restrictions",

    # Notifications
    "POST_NOTIFICATION": "Show notifications (AppOps-level control)",

    # Network
    "INTERNET": "Network access — block to cut off all internet connectivity",

    # Storage
    "READ_EXTERNAL_STORAGE": "Read shared storage files (AppOps-level)",
    "WRITE_EXTERNAL_STORAGE": "Write to shared storage (AppOps-level)",
    "READ_MEDIA_IMAGES": "Read photos from media store (AppOps-level)",
    "READ_MEDIA_VIDEO": "Read videos from media store (AppOps-level)",
    "READ_MEDIA_AUDIO": "Read audio from media store (AppOps-level)",
    "WRITE_MEDIA_AUDIO": "Modify or delete audio files in the media store",
    "WRITE_MEDIA_IMAGES": "Modify or delete photos in the media store",
    "WRITE_MEDIA_VIDEO": "Modify or delete video files in the media store",
    "MANAGE_EXTERNAL_STORAGE": "Full file system access (AppOps-level)",
    "NO_ISOLATED_STORAGE": "Bypass Android scoped storage restrictions (legacy access)",

    # Contacts
    "READ_CONTACTS": "Read contacts (AppOps-level control)",
    "WRITE_CONTACTS": "Modify contacts (AppOps-level control)",
    "GET_ACCOUNTS": "List device accounts (AppOps-level)",

    # SMS / Phone
    "READ_SMS": "Read SMS messages (AppOps-level)",
    "SEND_SMS": "Send SMS messages (AppOps-level)",
    "RECEIVE_SMS": "Intercept incoming SMS (AppOps-level)",
    "READ_CALL_LOG": "Read call history (AppOps-level)",
    "WRITE_CALL_LOG": "Modify call history (AppOps-level)",
    "READ_PHONE_STATE": "Read phone/device identifiers (AppOps-level)",
    "CALL_PHONE": "Make phone calls (AppOps-level)",

    # Clipboard / Display
    "READ_CLIPBOARD": "Read text from the clipboard",
    "WRITE_CLIPBOARD": "Write text to the clipboard",
    "SYSTEM_ALERT_WINDOW": "Draw overlays on top of other apps",
    "TOAST_WINDOW": "Show toast messages",
    "PICTURE_IN_PICTURE": "Show picture-in-picture window",

    # Power / System
    "WAKE_LOCK": "Keep the device awake / prevent sleep",
    "VIBRATE": "Vibrate the device",
    "REQUEST_INSTALL_PACKAGES": "Request to install APK files",
    "REQUEST_DELETE_PACKAGES": "Request to uninstall apps",
    "CHANGE_WIFI_STATE": "Turn WiFi on/off and connect to networks",
    "BLUETOOTH_SCAN": "Scan for Bluetooth devices (AppOps-level)",
    "BLUETOOTH_CONNECT": "Connect to Bluetooth devices (AppOps-level)",

    # Usage / Stats
    "GET_USAGE_STATS": "Read app usage statistics and screen time",
    "LOADER_USAGE_STATS": "Read loader/download statistics",

    # Sensors
    "BODY_SENSORS": "Body sensor access (AppOps-level)",
    "ACTIVITY_RECOGNITION": "Detect physical activity (walking, running, driving)",

    # Calendar
    "READ_CALENDAR": "Read calendar events (AppOps-level)",
    "WRITE_CALENDAR": "Modify calendar events (AppOps-level)",
}


def get_description(name: str) -> str:
    """Return a human-readable description for a permission or appops name.

    Tries the short permission name first (``CAMERA``), then the full name
    (``android.permission.CAMERA``), then the AppOps name.

    Returns an empty string if no description is available.
    """
    # Strip android.permission. prefix if present
    short = name.replace("android.permission.", "")

    return (
        _PERMISSION_DESCRIPTIONS.get(short)
        or _APPOPS_DESCRIPTIONS.get(short)
        or _PERMISSION_DESCRIPTIONS.get(name)
        or _APPOPS_DESCRIPTIONS.get(name)
        or ""
    )
