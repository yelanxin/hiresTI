"""
D-Bus org.freedesktop.ReserveDevice1 implementation for ALSA exclusive access.

When this app owns org.freedesktop.ReserveDevice1.Audio{N} on the session bus,
PipeWire/WirePlumber releases its hold on ALSA card N, allowing direct hw:N,0
exclusive access without EBUSY errors.

Reference: https://git.0pointer.net/reserve.git/tree/reserve.h
"""

import logging
import re
import time

from gi.repository import Gio, GLib

logger = logging.getLogger(__name__)

# Priority for this app's reservation.
# WirePlumber defaults to 0; we use a higher value so it defers to us.
_PRIORITY = 20

_IFACE_XML = """\
<node>
  <interface name="org.freedesktop.ReserveDevice1">
    <method name="RequestRelease">
      <arg name="priority" type="i" direction="in"/>
      <arg name="result" type="b" direction="out"/>
    </method>
    <property name="Priority" type="i" access="read"/>
    <property name="ApplicationName" type="s" access="read"/>
    <property name="ApplicationDeviceName" type="s" access="read"/>
  </interface>
</node>"""

# org.freedesktop.DBus.RequestName reply codes
_NAME_REPLY_PRIMARY_OWNER = 1
_NAME_REPLY_ALREADY_OWNER = 4

# org.freedesktop.DBus.RequestName flags
_NAME_FLAG_ALLOW_REPLACEMENT = 0x1
_NAME_FLAG_REPLACE_EXISTING = 0x2


def parse_alsa_card_num(device_id: str) -> "int | None":
    """Extract card number from 'hw:N' or 'hw:N,M' style device IDs."""
    if not device_id:
        return None
    m = re.match(r"hw:(\d+)", str(device_id).strip())
    return int(m.group(1)) if m else None


class AlsaDeviceReservation:
    """
    Claims org.freedesktop.ReserveDevice1.Audio{card_num} on the D-Bus session
    bus.  This causes PipeWire/WirePlumber to release the ALSA card, making
    hw:N,0 available for exclusive access.

    All D-Bus calls are synchronous (call_sync), so this class is safe to use
    from any background thread without needing the GLib main loop.

    Usage:
        res = AlsaDeviceReservation(card_num=2)
        ok = res.acquire()          # blocks up to ~1 s
        if ok:
            # open hw:2,0 here
            ...
        res.release()               # PipeWire reclaims the device
    """

    def __init__(self, card_num: int, app_name: str = "hiresTI"):
        self._card_num = int(card_num)
        self._app_name = str(app_name)
        self._bus: "Gio.DBusConnection | None" = None
        self._reg_id = 0
        self._node_info: "Gio.DBusNodeInfo | None" = None
        self.acquired = False

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def acquire(self, timeout_ms: int = 800) -> bool:
        """
        Synchronously acquire the D-Bus device reservation.

        1. Politely asks the current owner (PipeWire) to release via RequestRelease.
        2. Registers our object so we can answer future RequestRelease calls.
        3. Claims the service name with REPLACE_EXISTING.
        4. Waits briefly for PipeWire to finalise closing the ALSA device.

        Returns True if we now hold the reservation.
        """
        try:
            bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        except Exception as exc:
            logger.warning("AlsaReserve: cannot connect to D-Bus session bus: %s", exc)
            return False

        self._bus = bus

        # Step 1 — ask any current owner to release.
        self._request_release_from_owner(timeout_ms // 4)

        # Step 2 — register our introspection object.
        try:
            self._node_info = Gio.DBusNodeInfo.new_for_xml(_IFACE_XML)
            self._reg_id = bus.register_object(
                self._object_path,
                self._node_info.interfaces[0],
                self._on_method_call,
                self._on_get_property,
                None,
            )
        except Exception as exc:
            logger.warning("AlsaReserve: failed to register D-Bus object: %s", exc)
            return False

        # Step 3 — own the service name (take it over from PipeWire).
        flags = _NAME_FLAG_ALLOW_REPLACEMENT | _NAME_FLAG_REPLACE_EXISTING
        try:
            result = bus.call_sync(
                "org.freedesktop.DBus",
                "/org/freedesktop/DBus",
                "org.freedesktop.DBus",
                "RequestName",
                GLib.Variant("(su)", (self._service_name, flags)),
                GLib.VariantType("(u)"),
                Gio.DBusCallFlags.NONE,
                timeout_ms,
                None,
            )
            reply = result[0]
        except Exception as exc:
            logger.warning("AlsaReserve: RequestName failed: %s", exc)
            self._unregister_object()
            return False

        if reply not in (_NAME_REPLY_PRIMARY_OWNER, _NAME_REPLY_ALREADY_OWNER):
            logger.warning("AlsaReserve: RequestName unexpected reply %d", reply)
            self._unregister_object()
            return False

        self.acquired = True
        logger.info(
            "AlsaReserve: acquired %s (reply=%d)", self._service_name, reply
        )

        # Step 4 — give PipeWire time to close the ALSA device.
        time.sleep(0.18)
        return True

    def release(self):
        """Release the reservation; PipeWire will reclaim the ALSA device."""
        if not self.acquired:
            return
        self.acquired = False
        bus = self._bus
        if bus is None:
            return
        try:
            bus.call_sync(
                "org.freedesktop.DBus",
                "/org/freedesktop/DBus",
                "org.freedesktop.DBus",
                "ReleaseName",
                GLib.Variant("(s)", (self._service_name,)),
                GLib.VariantType("(u)"),
                Gio.DBusCallFlags.NONE,
                1000,
                None,
            )
        except Exception as exc:
            logger.debug("AlsaReserve: ReleaseName failed: %s", exc)
        self._unregister_object()
        logger.info("AlsaReserve: released %s", self._service_name)

    # ------------------------------------------------------------------ #
    # Properties                                                           #
    # ------------------------------------------------------------------ #

    @property
    def _service_name(self) -> str:
        return f"org.freedesktop.ReserveDevice1.Audio{self._card_num}"

    @property
    def _object_path(self) -> str:
        return f"/org/freedesktop/ReserveDevice1/Audio{self._card_num}"

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _request_release_from_owner(self, timeout_ms: int):
        """Ask the current D-Bus name owner (PipeWire) to release the device."""
        bus = self._bus
        if bus is None:
            return
        try:
            result = bus.call_sync(
                "org.freedesktop.DBus",
                "/org/freedesktop/DBus",
                "org.freedesktop.DBus",
                "GetNameOwner",
                GLib.Variant("(s)", (self._service_name,)),
                GLib.VariantType("(s)"),
                Gio.DBusCallFlags.NONE,
                timeout_ms,
                None,
            )
            owner = result[0]
        except Exception:
            return  # Nobody owns it — nothing to request

        try:
            bus.call_sync(
                owner,
                self._object_path,
                "org.freedesktop.ReserveDevice1",
                "RequestRelease",
                GLib.Variant("(i)", (_PRIORITY,)),
                GLib.VariantType("(b)"),
                Gio.DBusCallFlags.NONE,
                timeout_ms,
                None,
            )
            logger.info(
                "AlsaReserve: asked owner %s to release %s", owner, self._service_name
            )
        except Exception as exc:
            logger.debug("AlsaReserve: RequestRelease to owner failed: %s", exc)

    def _unregister_object(self):
        if self._reg_id and self._bus:
            try:
                self._bus.unregister_object(self._reg_id)
            except Exception:
                pass
            self._reg_id = 0

    # ------------------------------------------------------------------ #
    # D-Bus method/property handlers                                       #
    # ------------------------------------------------------------------ #

    def _on_method_call(
        self, connection, sender, path, iface, method, params, invocation
    ):
        if method == "RequestRelease":
            priority = params[0]
            if priority > _PRIORITY:
                # Higher-priority requester — yield gracefully.
                logger.info(
                    "AlsaReserve: yielding %s to higher-priority requester (priority=%d)",
                    self._service_name,
                    priority,
                )
                self.release()
                invocation.return_value(GLib.Variant("(b)", (True,)))
            else:
                invocation.return_value(GLib.Variant("(b)", (False,)))
        else:
            invocation.return_dbus_error(
                "org.freedesktop.DBus.Error.UnknownMethod",
                f"Unknown method: {method}",
            )

    def _on_get_property(self, connection, sender, path, iface, prop):
        if prop == "Priority":
            return GLib.Variant("i", _PRIORITY)
        if prop == "ApplicationName":
            return GLib.Variant("s", self._app_name)
        if prop == "ApplicationDeviceName":
            return GLib.Variant("s", f"Audio{self._card_num}")
        return None
