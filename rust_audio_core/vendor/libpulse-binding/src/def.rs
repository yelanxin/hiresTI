// Copyright 2017 Lyndon Brown
//
// This file is part of the PulseAudio Rust language binding.
//
// Licensed under the MIT license or the Apache license (version 2.0), at your option. You may not
// copy, modify, or distribute this file except in compliance with said license. You can find copies
// of these licenses either in the LICENSE-MIT and LICENSE-APACHE files, or alternatively at
// <http://opensource.org/licenses/MIT> and <http://www.apache.org/licenses/LICENSE-2.0>
// respectively.
//
// Portions of documentation are copied from the LGPL 2.1+ licensed PulseAudio C headers on a
// fair-use basis, as discussed in the overall project readme (available in the git repository).

//! Global definitions.

use std::os::raw::c_void;
use bitflags::bitflags;
use num_derive::{FromPrimitive, ToPrimitive};
use crate::time::{MicroSeconds, UnixTs};

pub use capi::PA_INVALID_INDEX as INVALID_INDEX;
pub use capi::pa_device_type_t as Device;
pub use capi::pa_port_available_t as PortAvailable;
pub use capi::pa_device_port_type_t as DevicePortType;

/// A callback type for releasing allocations.
pub type FreeCb = extern "C" fn(p: *mut c_void);

/// PulseAudio 'quit return value' type.
pub type RetvalActual = i32;

/// A wrapper around integer ‘quit return values’ returned by PulseAudio.
#[repr(transparent)]
#[derive(Debug, Copy, Clone, PartialEq, Eq)]
pub struct Retval(pub RetvalActual);

/// Playback and record buffer metrics.
#[repr(C)]
#[derive(Debug, Default, Copy, Clone, PartialEq, Eq)]
pub struct BufferAttr {
    /* NOTE: This struct must be directly usable by the C API, thus same attributes/layout/etc */

    /// Maximum length of the buffer in bytes.
    ///
    /// Setting this to [`std::u32::MAX`] will initialize this to the maximum value supported by the
    /// server, which is recommended. In strict low-latency playback scenarios you might want to set
    /// this to a lower value, likely together with the [`stream::FlagSet::ADJUST_LATENCY`] flag. If
    /// you do so, you ensure that the latency doesn’t grow beyond what is acceptable for the use
    /// case, at the cost of getting more underruns if the latency is lower than what the server can
    /// reliably handle.
    ///
    /// [`stream::FlagSet::ADJUST_LATENCY`]: crate::stream::FlagSet::ADJUST_LATENCY
    pub maxlength: u32,

    /// Target length of the buffer (playback only). The server tries to assure that at least
    /// `tlength` bytes are always available in the per-stream server-side playback buffer. The
    /// server will only send requests for more data as long as the buffer has less than this number
    /// of bytes of data.
    ///
    /// It is recommended to set this to [`std::u32::MAX`], which will initialize this to a value
    /// that is deemed sensible by the server. However, this value will default to something like
    /// 2s; for applications that have specific latency requirements this value should be set to
    /// the maximum latency that the application can deal with.
    ///
    /// When [`stream::FlagSet::ADJUST_LATENCY`] is not set this value will influence only the
    /// per-stream playback buffer size. When [`stream::FlagSet::ADJUST_LATENCY`] is set, the
    /// overall latency of the sink plus the playback buffer size is configured to this value. Set
    /// [`stream::FlagSet::ADJUST_LATENCY`] if you are interested in adjusting the overall latency.
    /// Don’t set it if you are interested in configuring the server-side per-stream playback buffer
    /// size.
    ///
    /// [`stream::FlagSet::ADJUST_LATENCY`]: crate::stream::FlagSet::ADJUST_LATENCY
    pub tlength: u32,

    /// Pre-buffering (playback only). The server does not start with playback before at least
    /// `prebuf` bytes are available in the buffer. It is recommended to set this to
    /// [`std::u32::MAX`], which will initialize this to the same value as `tlength`, whatever that
    /// may be.
    ///
    /// Initialize to `0` to enable manual start/stop control of the stream. This means that
    /// playback will not stop on underrun and playback will not start automatically, instead
    /// [`Stream::cork()`] needs to be called explicitly. If you set this value to `0` you should
    /// also set [`stream::FlagSet::START_CORKED`]. Should underrun occur, the read index of the
    /// output buffer overtakes the write index, and hence the fill level of the buffer is negative.
    ///
    /// Start of playback can be forced using [`Stream::trigger()`] even though the prebuffer size
    /// hasn’t been reached. If a buffer underrun occurs, this prebuffering will be again enabled.
    ///
    /// [`Stream::cork()`]: crate::stream::Stream::cork
    /// [`Stream::trigger()`]: crate::stream::Stream::trigger
    /// [`stream::FlagSet::START_CORKED`]: crate::stream::FlagSet::START_CORKED
    pub prebuf: u32,

    /// Minimum request (playback only). The server does not request less than `minreq` bytes from
    /// the client, instead it waits until the buffer is free enough to request more bytes at once.
    ///
    /// It is recommended to set this to [`std::u32::MAX`], which will initialize this to a value
    /// that is deemed sensible by the server. This should be set to a value that gives PulseAudio
    /// enough time to move the data from the per-stream playback buffer into the hardware playback
    /// buffer.
    pub minreq: u32,

    /// Fragment size (recording only). The server sends data in blocks of `fragsize` bytes size.
    ///
    /// Large values diminish interactivity with other operations on the connection context but
    /// decrease control overhead. It is recommended to set this to `std::u32::MAX`, which will
    /// initialize this to a value that is deemed sensible by the server. However, this value will
    /// default to something like 2s; For applications that have specific latency requirements this
    /// value should be set to the maximum latency that the application can deal with.
    ///
    /// If [`stream::FlagSet::ADJUST_LATENCY`] is set the overall source latency will be adjusted
    /// according to this value. If it is not set the source latency is left unmodified.
    ///
    /// [`stream::FlagSet::ADJUST_LATENCY`]: crate::stream::FlagSet::ADJUST_LATENCY
    pub fragsize: u32,
}

/// Test size is equal to `sys` equivalent (duplicated here for different documentation)
#[test]
fn bufferattr_compare_capi() {
    assert_eq!(std::mem::size_of::<BufferAttr>(), std::mem::size_of::<capi::pa_buffer_attr>());
    assert_eq!(std::mem::align_of::<BufferAttr>(), std::mem::align_of::<capi::pa_buffer_attr>());
}

impl AsRef<capi::pa_buffer_attr> for BufferAttr {
    #[inline]
    fn as_ref(&self) -> &capi::pa_buffer_attr {
        unsafe { &*(self as *const Self as *const capi::pa_buffer_attr) }
    }
}
impl AsRef<BufferAttr> for capi::pa_buffer_attr {
    #[inline]
    fn as_ref(&self) -> &BufferAttr {
        unsafe { &*(self as *const Self as *const BufferAttr) }
    }
}

/// A structure for all kinds of timing information of a stream.
///
/// See [`Stream::update_timing_info()`] and [`Stream::get_timing_info()`].
///
/// The total output latency a sample that is written with [`Stream::write()`] takes to be played
/// may be estimated by:
///
/// ``
/// sink_usec + buffer_usec + transport_usec
/// ``
///
/// (Where `buffer_usec` is defined as the result of passing ``write_index - read_index`` to
/// [`Spec::bytes_to_usec()`]). The output buffer which `buffer_usec` relates to may be manipulated
/// freely (with [`Stream::write()`]’s `seek` argument, [`Stream::flush()`] and friends), the
/// buffers `sink_usec` and `source_usec` relate to are first-in first-out (FIFO) buffers which
/// cannot be flushed or manipulated in any way. The total input latency a sample that is recorded
/// takes to be delivered to the application is:
///
/// ``
/// source_usec + buffer_usec + transport_usec - sink_usec
/// ``
///
/// (Take care of sign issues!). When connected to a monitor source `sink_usec` contains the latency
/// of the owning sink. The two latency estimations described here are implemented in
/// [`Stream::get_latency()`].
///
/// All time values are in the sound card clock domain, unless noted otherwise. The sound card clock
/// usually runs at a slightly different rate than the system clock.
///
/// Please note that this structure can be extended as part of evolutionary API updates at any time
/// in any new release.
///
/// [`Spec::bytes_to_usec()`]: crate::sample::Spec::bytes_to_usec
/// [`Stream::update_timing_info()`]: crate::stream::Stream::update_timing_info
/// [`Stream::get_timing_info()`]: crate::stream::Stream::get_timing_info
/// [`Stream::write()`]: crate::stream::Stream::write
/// [`Stream::flush()`]: crate::stream::Stream::flush
/// [`Stream::get_latency()`]: crate::stream::Stream::get_latency
#[repr(C)]
#[derive(Debug, Copy, Clone, PartialEq, Eq)]
pub struct TimingInfo {
    /* NOTE: This struct must be directly usable by the C API, thus same attributes/layout/etc */

    /// The system clock time when this timing info structure was current.
    pub timestamp: UnixTs,

    /// Non-zero if the local and the remote machine have synchronized clocks. If synchronized
    /// clocks are detected `transport_usec` becomes much more reliable. However, the code that
    /// detects synchronized clocks is very limited and unreliable itself.
    pub synchronized_clocks: i32,

    /// Time in usecs a sample takes to be played on the sink. For playback streams and record
    /// streams connected to a monitor source.
    pub sink_usec: MicroSeconds,

    /// Time in usecs a sample takes from being recorded to being delivered to the application. Only
    /// for record streams.
    pub source_usec: MicroSeconds,

    /// Estimated time in usecs a sample takes to be transferred to/from the daemon. For both
    /// playback and record streams.
    pub transport_usec: MicroSeconds,

    /// Non-zero when the stream is currently not underrun and data is being passed on to the
    /// device. Only for playback streams. This field does not say whether the data is actually
    /// already being played. To determine this check whether `since_underrun` (converted to usec)
    /// is larger than `sink_usec`.
    pub playing: i32,

    /// Non-zero if `write_index` is not up-to-date because a local write command that corrupted it
    /// has been issued in the time since this latency info was current. Only write commands with
    /// [`SeekMode::RelativeOnRead`] and [`SeekMode::RelativeEnd`] can corrupt `write_index`.
    ///
    /// [`SeekMode::RelativeOnRead`]: crate::stream::SeekMode::RelativeOnRead
    /// [`SeekMode::RelativeEnd`]: crate::stream::SeekMode::RelativeEnd
    pub write_index_corrupt: i32,

    /// Current write index into the playback buffer in bytes.
    ///
    /// Think twice before using this for seeking purposes: it might be out of date at the time you
    /// want to use it. Consider using [`SeekMode::Relative`] instead.
    ///
    /// [`SeekMode::Relative`]: crate::stream::SeekMode::Relative
    pub write_index: i64,

    /// Non-zero if `read_index` is not up-to-date because a local pause or flush request that
    /// corrupted it has been issued in the time since this latency info was current.
    pub read_index_corrupt: i32,

    /// Current read index into the playback buffer in bytes.
    ///
    /// Think twice before using this for seeking purposes: it might be out of date at the time you
    /// want to use it. Consider using [`SeekMode::RelativeOnRead`] instead.
    ///
    /// [`SeekMode::RelativeOnRead`]: crate::stream::SeekMode::RelativeOnRead
    pub read_index: i64,

    /// The configured latency for the sink.
    pub configured_sink_usec: MicroSeconds,

    /// The configured latency for the source.
    pub configured_source_usec: MicroSeconds,

    /// Bytes that were handed to the sink since the last underrun happened, or since playback
    /// started again after the last underrun. `playing` will tell you which case it is.
    pub since_underrun: i64,
}

/// Test size is equal to `sys` equivalent (duplicated here for different documentation)
#[test]
fn timinginfo_compare_capi() {
    assert_eq!(std::mem::size_of::<TimingInfo>(), std::mem::size_of::<capi::pa_timing_info>());
    assert_eq!(std::mem::align_of::<TimingInfo>(), std::mem::align_of::<capi::pa_timing_info>());
}

impl AsRef<TimingInfo> for capi::pa_timing_info {
    #[inline]
    fn as_ref(&self) -> &TimingInfo {
        unsafe { &*(self as *const Self as *const TimingInfo) }
    }
}

/// A structure for the spawn API.
///
/// This may be used to integrate auto spawned daemons into your application. For more information
/// see [`Context::connect()`]. When spawning a new child process the `waitpid()` is used on the
/// child’s PID. The spawn routine will not block or ignore SIGCHLD signals, since this cannot be
/// done in a thread compatible way. You might have to do this in prefork/postfork.
///
/// [`Context::connect()`]: crate::context::Context::connect
#[repr(C)]
#[derive(Debug)]
pub struct SpawnApi {
    /* NOTE: This struct must be directly usable by the C API, thus same attributes/layout/etc */

    /// Is called just before the fork in the parent process.
    pub prefork: Option<extern "C" fn()>,

    /// Is called immediately after the fork in the parent process.
    pub postfork: Option<extern "C" fn()>,

    /// Is called immediately after the fork in the child process.
    ///
    /// It is not safe to close all file descriptors in this function unconditionally, since a UNIX
    /// socket (created using socketpair()) is passed to the new process.
    pub atfork: Option<extern "C" fn()>,
}

/// Test size is equal to `sys` equivalent (duplicated here for different documentation)
#[test]
fn spawnapi_compare_capi() {
    assert_eq!(std::mem::size_of::<SpawnApi>(), std::mem::size_of::<capi::pa_spawn_api>());
    assert_eq!(std::mem::align_of::<SpawnApi>(), std::mem::align_of::<capi::pa_spawn_api>());
}

impl AsRef<capi::pa_spawn_api> for SpawnApi {
    #[inline]
    fn as_ref(&self) -> &capi::pa_spawn_api {
        unsafe { &*(self as *const Self as *const capi::pa_spawn_api) }
    }
}

bitflags! {
    /// Set of sink flags.
    #[derive(Debug, Copy, Clone, PartialEq, Eq)]
    #[repr(transparent)]
    pub struct SinkFlagSet: u32 {
        /// Flag to pass when no specific options are needed.
        const NOFLAGS = capi::PA_SINK_NOFLAGS;

        /// Supports hardware volume control. This is a dynamic flag and may change at runtime after
        /// the sink has initialized.
        const HW_VOLUME_CTRL = capi::PA_SINK_HW_VOLUME_CTRL;

        /// Supports latency querying.
        const LATENCY = capi::PA_SINK_LATENCY;

        /// Is a hardware sink of some kind, in contrast to “virtual”/software sinks.
        const HARDWARE = capi::PA_SINK_HARDWARE;

        /// Is a networked sink of some kind.
        const NETWORK = capi::PA_SINK_NETWORK;

        /// Supports hardware mute control. This is a dynamic flag and may change at runtime after
        /// the sink has initialized.
        const HW_MUTE_CTRL = capi::PA_SINK_HW_MUTE_CTRL;

        /// Volume can be translated to dB with the `From` based conversions between [`Volume`],
        /// [`VolumeLinear`] and [`VolumeDB`] types. This is a dynamic flag and may change at
        /// runtime after the sink has initialized.
        ///
        /// [`Volume`]: crate::volume::Volume
        /// [`VolumeDB`]: crate::volume::VolumeDB
        /// [`VolumeLinear`]: crate::volume::VolumeLinear
        const DECIBEL_VOLUME = capi::PA_SINK_DECIBEL_VOLUME;

        /// This sink is in flat volume mode, i.e. always the maximum of the volume  of all
        /// connected inputs.
        const FLAT_VOLUME = capi::PA_SINK_FLAT_VOLUME;

        /// The latency can be adjusted dynamically depending on the needs of the connected streams.
        const DYNAMIC_LATENCY = capi::PA_SINK_DYNAMIC_LATENCY;

        /// The sink allows setting what formats are supported by the connected hardware. The actual
        /// functionality to do this might be provided by an extension.
        const SET_FORMATS = capi::PA_SINK_SET_FORMATS;
    }
}

/// Sink state.
#[repr(C)]
#[derive(Debug, Copy, Clone, PartialEq, Eq)]
#[derive(FromPrimitive, ToPrimitive)]
pub enum SinkState {
    /* NOTE: This enum’s variants and variant values **must** remain identical to the `sys` crate
       (C API) equivalent */

    /// This state is used when the server does not support sink state introspection.
    Invalid = -1,

    /// Running, sink is playing and used by at least one non-corked sink-input.
    Running = 0,

    /// When idle, the sink is playing but there is no non-corked sink-input attached to it.
    Idle = 1,

    /// When suspended, actual sink access can be closed, for instance.
    Suspended = 2,
}

/// Check is equal to `sys` equivalent
#[test]
fn sink_state_compare_capi() {
    assert_eq!(std::mem::size_of::<SinkState>(), std::mem::size_of::<capi::pa_sink_state_t>());
    assert_eq!(std::mem::align_of::<SinkState>(), std::mem::align_of::<capi::pa_sink_state_t>());

    // Check order and value of variants match
    // No point checking conversions in both directions since both are a transmute
    assert_eq!(SinkState::Invalid,   SinkState::from(capi::pa_sink_state_t::Invalid));
    assert_eq!(SinkState::Running,   SinkState::from(capi::pa_sink_state_t::Running));
    assert_eq!(SinkState::Idle,      SinkState::from(capi::pa_sink_state_t::Idle));
    assert_eq!(SinkState::Suspended, SinkState::from(capi::pa_sink_state_t::Suspended));
}

impl From<SinkState> for capi::pa_sink_state_t {
    #[inline]
    fn from(s: SinkState) -> Self {
        unsafe { std::mem::transmute(s) }
    }
}
impl From<capi::pa_sink_state_t> for SinkState {
    #[inline]
    fn from(s: capi::pa_sink_state_t) -> Self {
        unsafe { std::mem::transmute(s) }
    }
}

impl SinkState {
    /// Checks if sink is playing: running or idle.
    #[inline]
    pub fn is_opened(self) -> bool {
        self == SinkState::Running || self == SinkState::Idle
    }

    /// Checks if sink is running.
    #[inline]
    pub fn is_running(self) -> bool {
        self == SinkState::Running
    }
}

bitflags! {
    /// Set of source flags.
    #[derive(Debug, Copy, Clone, PartialEq, Eq)]
    #[repr(transparent)]
    pub struct SourceFlagSet: u32 {
        /// Flag to pass when no specific options are needed.
        const NOFLAGS = capi::PA_SOURCE_NOFLAGS;

        /// Supports hardware volume control. This is a dynamic flag and may change at runtime after
        /// the source has initialized.
        const HW_VOLUME_CTRL = capi::PA_SOURCE_HW_VOLUME_CTRL;

        /// Supports latency querying.
        const LATENCY = capi::PA_SOURCE_LATENCY;

        /// Is a hardware source of some kind, in contrast to “virtual”/software source.
        const HARDWARE = capi::PA_SOURCE_HARDWARE;

        /// Is a networked source of some kind.
        const NETWORK = capi::PA_SOURCE_NETWORK;

        /// Supports hardware mute control. This is a dynamic flag and may change at runtime after
        /// the source has initialized.
        const HW_MUTE_CTRL = capi::PA_SOURCE_HW_MUTE_CTRL;

        /// Volume can be translated to dB with the `From` based conversions between [`Volume`],
        /// [`VolumeLinear`] and [`VolumeDB`] types. This is a dynamic flag and may change at
        /// runtime after the source has initialized.
        ///
        /// [`Volume`]: crate::volume::Volume
        /// [`VolumeDB`]: crate::volume::VolumeDB
        /// [`VolumeLinear`]: crate::volume::VolumeLinear
        const DECIBEL_VOLUME = capi::PA_SOURCE_DECIBEL_VOLUME;

        /// The latency can be adjusted dynamically depending on the needs of the connected streams.
        const DYNAMIC_LATENCY = capi::PA_SOURCE_DYNAMIC_LATENCY;

        /// This source is in flat volume mode, i.e. always the maximum of the volume of all
        /// connected outputs.
        const FLAT_VOLUME = capi::PA_SOURCE_FLAT_VOLUME;
    }
}

/// Source state.
#[repr(C)]
#[derive(Debug, Copy, Clone, PartialEq, Eq)]
#[derive(FromPrimitive, ToPrimitive)]
pub enum SourceState {
    /* NOTE: This enum’s variants and variant values **must** remain identical to the `sys` crate
       (C API) equivalent */

    /// This state is used when the server does not support source state introspection.
    Invalid = -1,

    /// Running, source is recording and used by at least one non-corked source-output.
    Running = 0,

    /// When idle, the source is still recording but there is no non-corked source-output.
    Idle = 1,

    /// When suspended, actual source access can be closed, for instance.
    Suspended = 2,
}

/// Check is equal to `sys` equivalent
#[test]
fn source_state_compare_capi() {
    assert_eq!(std::mem::size_of::<SourceState>(), std::mem::size_of::<capi::pa_source_state_t>());
    assert_eq!(std::mem::align_of::<SourceState>(), std::mem::align_of::<capi::pa_source_state_t>());

    // Check order and value of variants match
    // No point checking conversions in both directions since both are a transmute
    assert_eq!(SourceState::Invalid,   SourceState::from(capi::pa_source_state_t::Invalid));
    assert_eq!(SourceState::Running,   SourceState::from(capi::pa_source_state_t::Running));
    assert_eq!(SourceState::Idle,      SourceState::from(capi::pa_source_state_t::Idle));
    assert_eq!(SourceState::Suspended, SourceState::from(capi::pa_source_state_t::Suspended));
}

impl From<SourceState> for capi::pa_source_state_t {
    #[inline]
    fn from(s: SourceState) -> Self {
        unsafe { std::mem::transmute(s) }
    }
}
impl From<capi::pa_source_state_t> for SourceState {
    #[inline]
    fn from(s: capi::pa_source_state_t) -> Self {
        unsafe { std::mem::transmute(s) }
    }
}

impl SourceState {
    /// Checks if source is recording: running or idle.
    #[inline]
    pub fn is_opened(self) -> bool {
        self == SourceState::Running || self == SourceState::Idle
    }

    /// Checks if source is running.
    #[inline]
    pub fn is_running(self) -> bool {
        self == SourceState::Running
    }
}
