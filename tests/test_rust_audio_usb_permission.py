import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from _rust import audio as rust_audio

_Adapter = rust_audio.RustAudioPlayerAdapter


def _classifier_self():
    """Minimal stand-in exposing only the keyword tuples used by the classifier."""
    return SimpleNamespace(
        _ERR_USB_PERMISSION_KEYS=_Adapter._ERR_USB_PERMISSION_KEYS,
        _ERR_DEVICE_KEYS=_Adapter._ERR_DEVICE_KEYS,
        _ERR_ALSA_FAULT_KEYS=_Adapter._ERR_ALSA_FAULT_KEYS,
        _ERR_NETWORK_KEYS=_Adapter._ERR_NETWORK_KEYS,
        _ERR_CODEC_KEYS=_Adapter._ERR_CODEC_KEYS,
    )


def test_eacces_open_failure_classifies_as_usb_permission_not_codec():
    # The libusb EACCES message is wrapped with "decode error" by the native
    # transport; it must NOT be misread as a codec fault.
    msg = (
        "native-transport decode error: native-transport: USB open failed after "
        "3 retries: open 06cb:1595: Access denied (insufficient permissions)"
    )
    assert _Adapter._classify_rust_error(_classifier_self(), msg) == "usb_permission"


def test_disconnect_still_classifies_as_device():
    msg = "native-transport: device has been disconnected"
    assert _Adapter._classify_rust_error(_classifier_self(), msg) == "device"


def test_plain_codec_error_still_classifies_as_codec():
    msg = "flac decode error: not-negotiated"
    assert _Adapter._classify_rust_error(_classifier_self(), msg) == "codec"


def test_usb_permission_policy_sets_error_state_and_preserves_message():
    stopped = []
    recover_calls = []
    player = SimpleNamespace(
        _ERR_USB_PERMISSION_KEYS=_Adapter._ERR_USB_PERMISSION_KEYS,
        output_state="switching",
        output_error=None,
        _cached_is_playing=True,
        limiter_enabled=False,
        _limiter_negotiation_retry_pending=False,
        _rust_disconnect_recovering=False,
        _rust=SimpleNamespace(stop=lambda: stopped.append(True)),
        _recover_after_disconnect=lambda: recover_calls.append(True),
        exclusive_lock_mode=False,
        current_driver="USB Rawlink v2",
    )
    msg = "open 06cb:1595: Access denied (insufficient permissions)"

    _Adapter._apply_rust_error_policy(player, "usb_permission", msg)

    # Surfaced as an actionable error, NOT a silent disconnect/fallback rebind.
    assert player.output_state == "error"
    assert "Access denied" in player.output_error
    assert player._cached_is_playing is False
    assert stopped == [True]
    assert recover_calls == []
