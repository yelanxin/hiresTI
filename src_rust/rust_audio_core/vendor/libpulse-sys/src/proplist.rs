// Copyright 2017 Lyndon Brown
//
// This file is part of the PulseAudio Rust language linking library.
//
// Licensed under the MIT license or the Apache license (version 2.0), at your option. You may not
// copy, modify, or distribute this file except in compliance with said license. You can find copies
// of these licenses either in the LICENSE-MIT and LICENSE-APACHE files, or alternatively at
// <http://opensource.org/licenses/MIT> and <http://www.apache.org/licenses/LICENSE-2.0>
// respectively.
//
// Portions of documentation are copied from the LGPL 2.1+ licensed PulseAudio C headers on a
// fair-use basis, as discussed in the overall project readme (available in the git repository).

//! Property list constants and functions.

use std::os::raw::{c_char, c_void};
use num_derive::{FromPrimitive, ToPrimitive};

/// For streams: localized media name, formatted as UTF-8. E.g. "Guns'N'Roses: Civil War".
pub const PA_PROP_MEDIA_NAME: &str = "media.name";

/// For streams: localized media title if applicable, formatted as UTF-8. E.g. "Civil War".
pub const PA_PROP_MEDIA_TITLE: &str = "media.title";

/// For streams: localized media artist if applicable, formatted as UTF-8. E.g. "Guns'N'Roses".
pub const PA_PROP_MEDIA_ARTIST: &str = "media.artist";

/// For streams: localized media copyright string if applicable, formatted as UTF-8.
/// E.g. "Evil Record Corp.".
pub const PA_PROP_MEDIA_COPYRIGHT: &str = "media.copyright";

/// For streams: localized media generator software string if applicable, formatted as UTF-8.
/// E.g. "Foocrop AudioFrobnicator".
pub const PA_PROP_MEDIA_SOFTWARE: &str = "media.software";

/// For streams: media language if applicable, in standard POSIX format. E.g. "de_DE".
pub const PA_PROP_MEDIA_LANGUAGE: &str = "media.language";

/// For streams: source filename if applicable, in URI format or local path.
/// E.g. "/home/lennart/music/foobar.ogg".
pub const PA_PROP_MEDIA_FILENAME: &str = "media.filename";

/// For streams: icon for the media. A binary blob containing PNG image data.
pub const PA_PROP_MEDIA_ICON: &str = "media.icon";

/// For streams: an XDG icon name for the media. E.g. "audio-x-mp3".
pub const PA_PROP_MEDIA_ICON_NAME: &str = "media.icon_name";

/// For streams: logic role of this media.
/// One of the strings "video", "music", "game", "event", "phone", "animation", "production",
/// "a11y", "test".
pub const PA_PROP_MEDIA_ROLE: &str = "media.role";

/// For streams: the name of a filter that is desired, e.g. "echo-cancel" or "equalizer-sink".
/// PulseAudio may choose to not apply the filter if it does not make sense (for example, applying
/// echo-cancellation on a Bluetooth headset probably does not make sense.
pub const PA_PROP_FILTER_WANT: &str = "filter.want";

/// For streams: the name of a filter that is desired, e.g. "echo-cancel" or "equalizer-sink".
/// Differs from PA_PROP_FILTER_WANT in that it forces PulseAudio to apply the filter, regardless of
/// whether PulseAudio thinks it makes sense to do so or not. If this is set, PA_PROP_FILTER_WANT
/// is ignored. In other words, you almost certainly do not want to use this.
pub const PA_PROP_FILTER_APPLY: &str = "filter.apply";

/// For streams: the name of a filter that should specifically be suppressed (i.e. overrides
/// PA_PROP_FILTER_WANT). Useful for the times that PA_PROP_FILTER_WANT is automatically added (e.g.
/// echo-cancellation for phone streams when $VOIP_APP does its own, internal AEC).
pub const PA_PROP_FILTER_SUPPRESS: &str = "filter.suppress";

/// For event sound streams: XDG event sound name. e.g. "message-new-email" (Event sound streams are
/// those with media.role set to "event").
pub const PA_PROP_EVENT_ID: &str = "event.id";

/// For event sound streams: localized human readable one-line description of the event, formatted
/// as UTF-8. E.g. "Email from lennart\@example.com received."
pub const PA_PROP_EVENT_DESCRIPTION: &str = "event.description";

/// For event sound streams: absolute horizontal mouse position on the screen if the event sound was
/// triggered by a mouse click, integer formatted as text string. E.g. "865".
pub const PA_PROP_EVENT_MOUSE_X: &str = "event.mouse.x";

/// For event sound streams: absolute vertical mouse position on the screen if the event sound was
/// triggered by a mouse click, integer formatted as text string. E.g. "432".
pub const PA_PROP_EVENT_MOUSE_Y: &str = "event.mouse.y";

/// For event sound streams: relative horizontal mouse position on the screen if the event sound was
/// triggered by a mouse click, float formatted as text string, ranging from 0.0 (left side of the
/// screen) to 1.0 (right side of the screen). E.g. "0.65".
pub const PA_PROP_EVENT_MOUSE_HPOS: &str = "event.mouse.hpos";

/// For event sound streams: relative vertical mouse position on the screen if the event sound was
/// triggered by a mouse click, float formatted as text string, ranging from 0.0 (top of the screen)
/// to 1.0 (bottom of the screen). E.g. "0.43".
pub const PA_PROP_EVENT_MOUSE_VPOS: &str = "event.mouse.vpos";

/// For event sound streams: mouse button that triggered the event if applicable, integer formatted
/// as string with 0=left, 1=middle, 2=right. E.g. "0".
pub const PA_PROP_EVENT_MOUSE_BUTTON: &str = "event.mouse.button";

/// For streams that belong to a window on the screen: localized window title.
/// E.g. "Totem Music Player".
pub const PA_PROP_WINDOW_NAME: &str = "window.name";

/// For streams that belong to a window on the screen: a textual id for identifying a window
/// logically. E.g. "org.gnome.Totem.MainWindow".
pub const PA_PROP_WINDOW_ID: &str = "window.id";

/// For streams that belong to a window on the screen: window icon. A binary blob containing PNG
/// image data.
pub const PA_PROP_WINDOW_ICON: &str = "window.icon";

/// For streams that belong to a window on the screen: an XDG icon name for the window. E.g.
/// "totem".
pub const PA_PROP_WINDOW_ICON_NAME: &str = "window.icon_name";

/// For streams that belong to a window on the screen: absolute horizontal window position on the
/// screen, integer formatted as text string. E.g. "865".
pub const PA_PROP_WINDOW_X: &str = "window.x";

/// For streams that belong to a window on the screen: absolute vertical window position on the
/// screen, integer formatted as text string. E.g. "343".
pub const PA_PROP_WINDOW_Y: &str = "window.y";

/// For streams that belong to a window on the screen: window width on the screen, integer
/// formatted as text string. e.g. "365".
pub const PA_PROP_WINDOW_WIDTH: &str = "window.width";

/// For streams that belong to a window on the screen: window height on the screen, integer
/// formatted as text string. E.g. "643".
pub const PA_PROP_WINDOW_HEIGHT: &str = "window.height";

/// For streams that belong to a window on the screen: relative position of the window center on the
/// screen, float formatted as text string, ranging from 0.0 (left side of the screen) to 1.0 (right
/// side of the screen). E.g. "0.65".
pub const PA_PROP_WINDOW_HPOS: &str = "window.hpos";

/// For streams that belong to a window on the screen: relative position of the window center on the
/// screen, float formatted as text string, ranging from 0.0 (top of the screen) to 1.0 (bottom of
/// the screen). E.g. "0.43".
pub const PA_PROP_WINDOW_VPOS: &str = "window.vpos";

/// For streams that belong to a window on the screen: if the windowing system supports multiple
/// desktops, a comma separated list of indexes of the desktops this window is visible on. If this
/// property is an empty string, it is visible on all desktops (i.e. ‘sticky’). The first desktop is
/// zero. E.g. "0,2,3".
pub const PA_PROP_WINDOW_DESKTOP: &str = "window.desktop";

/// For streams that belong to an X11 window on the screen: the X11 display string. E.g. ":0.0".
pub const PA_PROP_WINDOW_X11_DISPLAY: &str = "window.x11.display";

/// For streams that belong to an X11 window on the screen: the X11 screen the window is on, an
/// integer formatted as string. E.g. "0".
pub const PA_PROP_WINDOW_X11_SCREEN: &str = "window.x11.screen";

/// For streams that belong to an X11 window on the screen: the X11 monitor the window is on, an
/// integer formatted as string. E.g. "0".
pub const PA_PROP_WINDOW_X11_MONITOR: &str = "window.x11.monitor";

/// For streams that belong to an X11 window on the screen: the window XID, an integer formatted as
/// string. E.g. "25632".
pub const PA_PROP_WINDOW_X11_XID: &str = "window.x11.xid";

/// For clients/streams: localized human readable application name. E.g. "Totem Music Player".
pub const PA_PROP_APPLICATION_NAME: &str = "application.name";

/// For clients/streams: a textual id for identifying an application logically.
/// E.g. "org.gnome.Totem".
pub const PA_PROP_APPLICATION_ID: &str = "application.id";

/// For clients/streams: a version string, e.g. "0.6.88".
pub const PA_PROP_APPLICATION_VERSION: &str = "application.version";

/// For clients/streams: application icon. A binary blob containing PNG image data.
pub const PA_PROP_APPLICATION_ICON: &str = "application.icon";

/// For clients/streams: an XDG icon name for the application. E.g. "totem".
pub const PA_PROP_APPLICATION_ICON_NAME: &str = "application.icon_name";

/// For clients/streams: application language if applicable, in standard POSIX format. E.g. "de_DE".
pub const PA_PROP_APPLICATION_LANGUAGE: &str = "application.language";

/// For clients/streams on UNIX: application process PID, an integer formatted as string. E.g.
/// "4711".
pub const PA_PROP_APPLICATION_PROCESS_ID: &str = "application.process.id";

/// For clients/streams: application process name. E.g. "totem".
pub const PA_PROP_APPLICATION_PROCESS_BINARY: &str = "application.process.binary";

/// For clients/streams: application user name. E.g. "lennart".
pub const PA_PROP_APPLICATION_PROCESS_USER: &str = "application.process.user";

/// For clients/streams: host name the application runs on. E.g. "omega".
pub const PA_PROP_APPLICATION_PROCESS_HOST: &str = "application.process.host";

/// For clients/streams: the D-Bus host id the application runs on.
/// E.g. "543679e7b01393ed3e3e650047d78f6e".
pub const PA_PROP_APPLICATION_PROCESS_MACHINE_ID: &str = "application.process.machine_id";

/// For clients/streams: an id for the login session the application runs in. On Unix the value of
/// $XDG_SESSION_ID. E.g. "5".
pub const PA_PROP_APPLICATION_PROCESS_SESSION_ID: &str = "application.process.session_id";

/// For devices: device string in the underlying audio layer’s format. E.g. "surround51:0".
pub const PA_PROP_DEVICE_STRING: &str = "device.string";

/// For devices: API this device is accessed with. E.g. "alsa".
pub const PA_PROP_DEVICE_API: &str = "device.api";

/// For devices: localized human readable device one-line description.
/// E.g. "Foobar Industries USB Headset 2000+ Ultra".
pub const PA_PROP_DEVICE_DESCRIPTION: &str = "device.description";

/// For devices: bus path to the device in the OS’ format.
/// E.g. "/sys/bus/pci/devices/0000:00:1f.2".
pub const PA_PROP_DEVICE_BUS_PATH: &str = "device.bus_path";

/// For devices: serial number if applicable. E.g. "4711-0815-1234".
pub const PA_PROP_DEVICE_SERIAL: &str = "device.serial";

/// For devices: vendor ID if applicable. E.g. 1274.
pub const PA_PROP_DEVICE_VENDOR_ID: &str = "device.vendor.id";

/// For devices: vendor name if applicable. E.g. "Foocorp Heavy Industries".
pub const PA_PROP_DEVICE_VENDOR_NAME: &str = "device.vendor.name";

/// For devices: product ID if applicable. E.g. 4565.
pub const PA_PROP_DEVICE_PRODUCT_ID: &str = "device.product.id";

/// For devices: product name if applicable. E.g. "SuperSpeakers 2000 Pro".
pub const PA_PROP_DEVICE_PRODUCT_NAME: &str = "device.product.name";

/// For devices: device class. One of "sound", "modem", "monitor", "filter".
pub const PA_PROP_DEVICE_CLASS: &str = "device.class";

/// For devices: form factor if applicable. One of "internal", "speaker", "handset", "tv", "webcam",
/// "microphone", "headset", "headphone", "hands-free", "car", "hifi", "computer", "portable".
pub const PA_PROP_DEVICE_FORM_FACTOR: &str = "device.form_factor";

/// For devices: bus of the device if applicable. One of "isa", "pci", "usb", "firewire",
/// "bluetooth".
pub const PA_PROP_DEVICE_BUS: &str = "device.bus";

/// For devices: icon for the device. A binary blob containing PNG image data.
pub const PA_PROP_DEVICE_ICON: &str = "device.icon";

/// For devices: an XDG icon name for the device. E.g. "sound-card-speakers-usb".
pub const PA_PROP_DEVICE_ICON_NAME: &str = "device.icon_name";

/// For devices: access mode of the device if applicable. One of "mmap", "mmap_rewrite", "serial".
pub const PA_PROP_DEVICE_ACCESS_MODE: &str = "device.access_mode";

/// For filter devices: master device id if applicable.
pub const PA_PROP_DEVICE_MASTER_DEVICE: &str = "device.master_device";

/// For devices: buffer size in bytes, integer formatted as string.
pub const PA_PROP_DEVICE_BUFFERING_BUFFER_SIZE: &str = "device.buffering.buffer_size";

/// For devices: fragment size in bytes, integer formatted as string.
pub const PA_PROP_DEVICE_BUFFERING_FRAGMENT_SIZE: &str = "device.buffering.fragment_size";

/// For devices: profile identifier for the profile this devices is in.
/// E.g. "analog-stereo", "analog-surround-40", "iec958-stereo", ...
pub const PA_PROP_DEVICE_PROFILE_NAME: &str = "device.profile.name";

/// For devices: intended use. A space separated list of roles (see PA_PROP_MEDIA_ROLE) this device
/// is particularly well suited for, due to latency, quality or form factor.
pub const PA_PROP_DEVICE_INTENDED_ROLES: &str = "device.intended_roles";

/// For devices: human readable one-line description of the profile this device is in. E.g.
/// "Analog Stereo", ...
pub const PA_PROP_DEVICE_PROFILE_DESCRIPTION: &str = "device.profile.description";

/// For modules: the author’s name, formatted as UTF-8 string. E.g. "Lennart Poettering".
pub const PA_PROP_MODULE_AUTHOR: &str = "module.author";

/// For modules: a human readable one-line description of the module’s purpose formatted as UTF-8.
/// E.g. "Frobnicate sounds with a flux compensator".
pub const PA_PROP_MODULE_DESCRIPTION: &str = "module.description";

/// For modules: a human readable usage description of the module’s arguments formatted as UTF-8.
pub const PA_PROP_MODULE_USAGE: &str = "module.usage";

/// For modules: a version string for the module. E.g. "0.9.15".
pub const PA_PROP_MODULE_VERSION: &str = "module.version";

/// For PCM formats: the sample format used as returned by `pa_sample_format_to_string`.
pub const PA_PROP_FORMAT_SAMPLE_FORMAT: &str = "format.sample_format";

/// For all formats: the sample rate (unsigned integer).
pub const PA_PROP_FORMAT_RATE: &str = "format.rate";

/// For all formats: the number of channels (unsigned integer).
pub const PA_PROP_FORMAT_CHANNELS: &str = "format.channels";

/// For PCM formats: the channel map of the stream as returned by `pa_channel_map_snprint`.
pub const PA_PROP_FORMAT_CHANNEL_MAP: &str = "format.channel_map";

/// For context: whether to forcefully disable data transfer via POSIX or memfd shared memory.
/// This property overrides any other client configuration which would otherwise enable SHM
/// communication channels.
//TODO: enable this feature gate once the passing of `--cfg doc` to dependencies is fixed (https://github.com/rust-lang/cargo/issues/8811)
//#[cfg(any(doc, feature = "pa_v15"))]
#[cfg_attr(docsrs, doc(cfg(feature = "pa_v15")))]
pub const PA_PROP_CONTEXT_FORCE_DISABLE_SHM: &str = "context.force.disable.shm";

/// For a bluez device: the currently selected codec name.
//TODO: enable this feature gate once the passing of `--cfg doc` to dependencies is fixed (https://github.com/rust-lang/cargo/issues/8811)
//#[cfg(any(doc, feature = "pa_v15"))]
#[cfg_attr(docsrs, doc(cfg(feature = "pa_v15")))]
pub const PA_PROP_BLUETOOTH_CODEC: &str = "bluetooth.codec";

/// A property list object. Basically a dictionary with ASCII strings as keys and arbitrary data as
/// values.
#[repr(C)] pub struct pa_proplist { _private: [u8; 0] }

/// Update mode.
#[repr(C)]
#[derive(Debug, Copy, Clone, PartialEq, Eq)]
#[derive(FromPrimitive, ToPrimitive)]
pub enum pa_update_mode_t {
    /// Replace the entire property list with the new one. Don’t keep any of the old data around.
    Set,

    /// Merge new property list into the existing one, not replacing any old entries if they share a
    /// common key with the new property list.
    Merge,

    /// Merge new property list into the existing one, replacing all old entries that share a common
    /// key with the new property list.
    Replace,
}

pub const PA_UPDATE_SET:     pa_update_mode_t = pa_update_mode_t::Set;
pub const PA_UPDATE_MERGE:   pa_update_mode_t = pa_update_mode_t::Merge;
pub const PA_UPDATE_REPLACE: pa_update_mode_t = pa_update_mode_t::Replace;

#[rustfmt::skip]
#[link(name = "pulse")]
extern "C" {
    pub fn pa_proplist_new() -> *mut pa_proplist;
    pub fn pa_proplist_free(p: *mut pa_proplist);
    pub fn pa_proplist_key_valid(key: *const c_char) -> i32;
    pub fn pa_proplist_sets(p: *mut pa_proplist, key: *const c_char, value: *const c_char) -> i32;
    pub fn pa_proplist_setp(p: *mut pa_proplist, pair: *const c_char) -> i32;
    pub fn pa_proplist_setf(p: *mut pa_proplist, key: *const c_char, format: *const c_char, ...) -> i32;
    pub fn pa_proplist_set(p: *mut pa_proplist, key: *const c_char, data: *const c_void, nbytes: usize) -> i32;
    pub fn pa_proplist_gets(p: *const pa_proplist, key: *const c_char) -> *const c_char;
    pub fn pa_proplist_get(p: *const pa_proplist, key: *const c_char, data: *mut *const c_void, nbytes: *mut usize) -> i32;
    pub fn pa_proplist_update(p: *mut pa_proplist, mode: pa_update_mode_t, other: *const pa_proplist);
    pub fn pa_proplist_unset(p: *mut pa_proplist, key: *const c_char) -> i32;
    pub fn pa_proplist_unset_many(p: *mut pa_proplist, keys: *const *const c_char) -> i32;
    pub fn pa_proplist_iterate(p: *const pa_proplist, state: *mut *mut c_void) -> *const c_char;
    pub fn pa_proplist_to_string(p: *const pa_proplist) -> *mut c_char;
    pub fn pa_proplist_to_string_sep(p: *const pa_proplist, sep: *const c_char) -> *mut c_char;
    pub fn pa_proplist_from_string(s: *const c_char) -> *mut pa_proplist;
    pub fn pa_proplist_contains(p: *const pa_proplist, key: *const c_char) -> i32;
    pub fn pa_proplist_clear(p: *mut pa_proplist);
    pub fn pa_proplist_copy(p: *const pa_proplist) -> *mut pa_proplist;
    pub fn pa_proplist_size(p: *const pa_proplist) -> u32;
    pub fn pa_proplist_isempty(p: *const pa_proplist) -> i32;
    pub fn pa_proplist_equal(a: *const pa_proplist, b: *const pa_proplist) -> i32;
}
