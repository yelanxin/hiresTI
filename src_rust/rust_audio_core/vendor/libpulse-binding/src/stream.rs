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

//! Audio streams for input, output and sample upload.
//!
//! # Overview
//!
//! Audio streams form the central functionality of the sound server. Data is routed, converted and
//! mixed from several sources before it is passed along to a final output. Currently, there are
//! three forms of audio streams:
//!
//! * Playback streams: Data flows from the client to the server.
//! * Record streams: Data flows from the server to the client.
//! * Upload streams: Similar to playback streams, but the data is stored in the sample cache. See
//!   [`context::scache`] for more information about controlling the sample cache.
//!
//! # Creating
//!
//! To access a stream, a [`Stream`] object must be created using [`Stream::new()`] or
//! [`Stream::new_extended()`]. `new` is for PCM streams only, while `new_extended` can be used for
//! both PCM and compressed audio streams. At this point the application must specify what stream
//! format(s) it supports. See [`sample`] and [`channelmap`] for more information on the stream
//! format parameters.
//!
//! **FIXME**: Those references only talk about PCM parameters, we should also have an overview
//! page for how the [`Info`] based stream format configuration works.
//! [Bug filed](https://bugs.freedesktop.org/show_bug.cgi?id=72265).
//!
//! This first step will only create a client-side object, representing the stream. To use the
//! stream, a server-side object must be created and associated with the local object. Depending on
//! which type of stream is desired, a different function is needed:
//!
//! * Playback stream: [`Stream::connect_playback()`]
//! * Record stream: [`Stream::connect_record()`]
//! * Upload stream: [`Stream::connect_upload()`] \(see [`context::scache`])
//!
//! Similar to how connections are done in contexts, connecting a stream will not generate an
//! [`Operation`] object. Also like contexts, the application should register a state change
//! callback, using [`Stream::set_state_callback()`], and wait for the stream to enter an active
//! state.
//!
//! Note: there is a user-controllable slider in mixer applications such as pavucontrol
//! corresponding to each of the created streams. Multiple (especially identically named) volume
//! sliders for the same application might confuse the user. Also, the server supports only a
//! limited number of simultaneous streams. Because of this, it is not always appropriate to create
//! multiple streams in one application that needs to output multiple sounds. The rough guideline
//! is: if there is no use case that would require separate user-initiated volume changes for each
//! stream, perform the mixing inside the application.
//!
//! # Buffer Attributes
//!
//! Playback and record streams always have a server-side buffer as part of the data flow. The size
//! of this buffer needs to be chosen in a compromise between low latency and sensitivity for buffer
//! overflows/underruns.
//!
//! The buffer metrics may be controlled by the application. They are described with a
//! [`BufferAttr`] structure.
//!
//! If [`FlagSet::ADJUST_LATENCY`] is set, then the `tlength`/`fragsize` parameters of this
//! structure will be interpreted slightly differently than otherwise when passed to
//! [`Stream::connect_record()`] and [`Stream::connect_playback()`]: the overall latency that is
//! comprised of both the server side playback buffer length, the hardware playback buffer length
//! and additional latencies will be adjusted in a way that it matches `tlength` resp. `fragsize`.
//! Set [`FlagSet::ADJUST_LATENCY`] if you want to control the overall playback latency for your
//! stream. Unset it if you want to control only the latency induced by the server-side, rewritable
//! playback buffer. The server will try to fulfill the client’s latency requests as good as
//! possible. However if the underlying hardware cannot change the hardware buffer length or only in
//! a limited range, the actually resulting latency might be different from what the client
//! requested. Thus, for synchronization clients always need to check the actual measured latency
//! via [`Stream::get_latency()`] or a similar call, and not make any assumptions about the latency
//! available. The function [`Stream::get_buffer_attr()`] will always return the actual size of the
//! server-side per-stream buffer in `tlength`/`fragsize`, regardless whether
//! [`FlagSet::ADJUST_LATENCY`] is set or not.
//!
//! The server-side per-stream playback buffers are indexed by a write and a read index. The
//! application writes to the write index and the sound device reads from the read index. The read
//! index is increased monotonically, while the write index may be freely controlled by the
//! application. Subtracting the read index from the write index will give you the current fill
//! level of the buffer. The read/write indexes are 64bit values and measured in bytes, they will
//! never wrap. The current read/write index may be queried using [`Stream::get_timing_info()`]
//! \(see below for more information). In case of a buffer underrun the read index is equal or
//! larger than the write index. Unless the `prebuf` value is `0`, PulseAudio will temporarily pause
//! playback in such a case, and wait until the buffer is filled up to `prebuf` bytes again. If
//! `prebuf` is `0`, the read index may be larger than the write index, in which case silence is
//! played. If the application writes data to indexes lower than the read index, the data is
//! immediately lost.
//!
//! # Transferring Data
//!
//! Once the stream is up, data can start flowing between the client and the server. Two different
//! access models can be used to transfer the data:
//!
//! * Asynchronous: The application registers a callback using [`Stream::set_write_callback()`] and
//!   [`Stream::set_read_callback()`] to receive notifications that data can either be written or
//!   read.
//! * Polled: Query the library for available data/space using [`Stream::writable_size()`] and
//!   [`Stream::readable_size()`] and transfer data as needed. The sizes are stored locally, in the
//!   client end, so there is no delay when reading them.
//!
//! It is also possible to mix the two models freely.
//!
//! Once there is data/space available, it can be transferred using either [`Stream::write()`] for
//! playback, or [`Stream::peek()`] / [`Stream::discard()`] for record. Make sure you do not
//! overflow the playback buffers as data will be dropped.
//!
//! # Buffer Control
//!
//! The transfer buffers can be controlled through a number of operations:
//!
//! * [`Stream::cork()`]: Stop the playback or recording.
//! * [`Stream::uncork()`]: Start the playback or recording.
//! * [`Stream::trigger()`]: Start playback immediately and do not wait for the buffer to fill up to
//!   the set trigger level.
//! * [`Stream::prebuf()`]: Re-enable the playback trigger level.
//! * [`Stream::drain()`]: Wait for the playback buffer to go empty. Will return an [`Operation`]
//!   object that will indicate when the buffer is completely drained.
//! * [`Stream::flush()`]: Drop all data from the playback or record buffer. Do not wait for it to
//!   finish playing.
//!
//! # Seeking in the Playback Buffer
//!
//! A client application may freely seek in the playback buffer. To accomplish that the
//! [`Stream::write()`] function takes a seek mode and an offset argument. The seek mode is one of:
//!
//! * [`SeekMode::Relative`]: seek relative to the current write index.
//! * [`SeekMode::Absolute`]: seek relative to the beginning of the playback buffer, (i.e. the first
//!   that was ever played in the stream).
//! * [`SeekMode::RelativeOnRead`]: seek relative to the current read index. Use this to write data
//!   to the output buffer that should be played as soon as possible.
//! * [`SeekMode::RelativeEnd`]: seek relative to the last byte ever written.
//!
//! If an application just wants to append some data to the output buffer, [`SeekMode::Relative`]
//! and an offset of `0` should be used.
//!
//! After a call to [`Stream::write()`] the write index will be left at the position right after the
//! last byte of the written data.
//!
//! # Latency
//!
//! A major problem with networked audio is the increased latency caused by the network. To remedy
//! this, PulseAudio supports an advanced system of monitoring the current latency.
//!
//! To get the raw data needed to calculate latencies, call [`Stream::get_timing_info()`]. This will
//! give you a [`TimingInfo`] structure that contains everything that is known about the server side
//! buffer transport delays and the backend active in the server. (Besides other things it contains
//! the write and read index values mentioned above.)
//!
//! This structure is updated every time a [`Stream::update_timing_info()`] operation is executed.
//! (i.e. before the first call to this function the timing information structure is not available!)
//! Since it is a lot of work to keep this structure up-to-date manually, PulseAudio can do that
//! automatically for you: if [`FlagSet::AUTO_TIMING_UPDATE`] is passed when connecting the stream
//! PulseAudio will automatically update the structure every 100ms and every time a function is
//! called that might invalidate the previously known timing data (such as [`Stream::write()`] or
//! [`Stream::flush()`]). Please note however, that there always is a short time window when the
//! data in the timing information structure is out-of-date. PulseAudio tries to mark these
//! situations by setting the `write_index_corrupt` and `read_index_corrupt` fields accordingly.
//!
//! The raw timing data in the [`TimingInfo`] structure is usually hard to deal with. Therefore a
//! simpler interface is available: you can call [`Stream::get_time()`] or
//! [`Stream::get_latency()`]. The former will return the current playback time of the hardware
//! since the stream has been started. The latter returns the overall time a sample that you write
//! now takes to be played by the hardware. These two functions base their calculations on the same
//! data that is returned by [`Stream::get_timing_info()`]. Hence the same rules for keeping the
//! timing data up-to-date apply here. In case the write or read index is corrupted, these two
//! functions will fail.
//!
//! Since updating the timing info structure usually requires a full network round trip and some
//! applications monitor the timing very often PulseAudio offers a timing interpolation system. If
//! [`FlagSet::INTERPOLATE_TIMING`] is passed when connecting the stream, [`Stream::get_time()`] and
//! [`Stream::get_latency()`] will try to interpolate the current playback time/latency by
//! estimating the number of samples that have been played back by the hardware since the last
//! regular timing update. It is especially useful to combine this option with
//! [`FlagSet::AUTO_TIMING_UPDATE`], which will enable you to monitor the current playback
//! time/latency very precisely and very frequently without requiring a network round trip every
//! time.
//!
//! # Overflow and underflow
//!
//! Even with the best precautions, buffers will sometime over - or underflow. To handle this
//! gracefully, the application can be notified when this happens. Callbacks are registered using
//! [`Stream::set_overflow_callback()`] and [`Stream::set_underflow_callback()`].
//!
//! # Synchronizing Multiple Playback Streams
//!
//! PulseAudio allows applications to fully synchronize multiple playback streams that are connected
//! to the same output device. That means the streams will always be played back sample-by-sample
//! synchronously. If stream operations like [`Stream::cork()`] are issued on one of the
//! synchronized streams, they are simultaneously issued on the others.
//!
//! To synchronize a stream to another, just pass the “master” stream as the last argument to
//! [`Stream::connect_playback()`]. To make sure that the freshly created stream doesn’t start
//! playback right-away, make sure to pass [`FlagSet::START_CORKED`] and, after all streams have
//! been created, uncork them all with a single call to [`Stream::uncork()`] for the master stream.
//!
//! To make sure that a particular stream doesn’t stop to play when a server side buffer underrun
//! happens on it while the other synchronized streams continue playing and hence deviate, you need
//! to pass a [`BufferAttr`] with `prebuf` set to `0` when connecting.
//!
//! # Disconnecting
//!
//! When a stream has served is purpose it must be disconnected with [`Stream::disconnect()`]. If
//! you only unreference it, then it will live on and eat resources both locally and on the server
//! until you disconnect the context. This is done automatically upon drop of the stream object.
//!
//! [`context::scache`]: mod@crate::context::scache
//! [`sample`]: mod@crate::sample
//! [`channelmap`]: mod@crate::channelmap
//! [`Info`]: crate::format::Info
//! [`BufferAttr`]: crate::def::BufferAttr
//! [`TimingInfo`]: crate::def::TimingInfo

use std::os::raw::{c_char, c_void};
use std::ffi::{CStr, CString};
use std::ptr::{null, null_mut};
use std::borrow::Cow;
use bitflags::bitflags;
use num_derive::{FromPrimitive, ToPrimitive};
use capi::pa_stream as StreamInternal;
use crate::{channelmap, format, def, proplist, sample};
use crate::callbacks::{self, box_closure_get_capi_ptr, get_su_capi_params, get_su_callback};
use crate::error::{self, PAErr};
use crate::format::InfoInternal;
use crate::proplist::{Proplist, ProplistInternal};
use crate::{context::Context, volume::ChannelVolumes, operation::Operation, time::MicroSeconds};

pub use capi::pa_seek_mode_t as SeekMode;
pub use capi::pa_stream_direction_t as Direction;

/// An opaque stream for playback or recording.
///
/// Note: Saves a copy of active multi-use closure callbacks, which it frees on drop.
pub struct Stream {
    /// The actual C object.
    ptr: *mut StreamInternal,
    /// Multi-use callback closure pointers.
    cb_ptrs: CallbackPointers,
}

unsafe impl Send for Stream {}
unsafe impl Sync for Stream {}

/// Holds copies of callback closure pointers, for those that are “multi-use” (may be fired multiple
/// times), for freeing at the appropriate time.
#[derive(Default)]
struct CallbackPointers {
    read: RequestCb,
    write: RequestCb,
    set_state: NotifyCb,
    overflow: NotifyCb,
    underflow: NotifyCb,
    started: NotifyCb,
    latency_update: NotifyCb,
    moved: NotifyCb,
    suspended: NotifyCb,
    buffer_attr: NotifyCb,
    event: EventCb,
}

type RequestCb = callbacks::MultiUseCallback<dyn FnMut(usize),
    extern "C" fn(*mut StreamInternal, usize, *mut c_void)>;

type NotifyCb = callbacks::MultiUseCallback<dyn FnMut(),
    extern "C" fn(*mut StreamInternal, *mut c_void)>;

type EventCb = callbacks::MultiUseCallback<dyn FnMut(String, Proplist),
    extern "C" fn(*mut StreamInternal, name: *const c_char, pl: *mut ProplistInternal, *mut c_void)>;

/// Stream state.
#[repr(C)]
#[derive(Debug, Copy, Clone, PartialEq, Eq)]
#[derive(FromPrimitive, ToPrimitive)]
pub enum State {
    /* NOTE: This enum’s variants and variant values **must** remain identical to the `sys` crate
       (C API) equivalent */

    /// The stream is not yet connected to any sink or source.
    Unconnected,
    /// The stream is being created.
    Creating,
    /// The stream is established, you may pass audio data to it now.
    Ready,
    /// An error occurred that made the stream invalid.
    Failed,
    /// The stream has been terminated cleanly.
    Terminated,
}

/// Check is equal to `sys` equivalent
#[test]
fn state_compare_capi() {
    assert_eq!(std::mem::size_of::<State>(), std::mem::size_of::<capi::pa_stream_state_t>());
    assert_eq!(std::mem::align_of::<State>(), std::mem::align_of::<capi::pa_stream_state_t>());

    // Check order and value of variants match
    // No point checking conversions in both directions since both are a transmute
    assert_eq!(State::Unconnected, State::from(capi::pa_stream_state_t::Unconnected));
    assert_eq!(State::Creating,    State::from(capi::pa_stream_state_t::Creating));
    assert_eq!(State::Ready,       State::from(capi::pa_stream_state_t::Ready));
    assert_eq!(State::Failed,      State::from(capi::pa_stream_state_t::Failed));
    assert_eq!(State::Terminated,  State::from(capi::pa_stream_state_t::Terminated));
}

impl From<State> for capi::pa_stream_state_t {
    #[inline]
    fn from(s: State) -> Self {
        unsafe { std::mem::transmute(s) }
    }
}
impl From<capi::pa_stream_state_t> for State {
    #[inline]
    fn from(s: capi::pa_stream_state_t) -> Self {
        unsafe { std::mem::transmute(s) }
    }
}

impl State {
    /// Checks if the passed state is one of the connected states.
    #[inline]
    pub fn is_good(self) -> bool {
        self == State::Creating || self == State::Ready
    }
}

bitflags! {
    /// Flag set.
    #[derive(Debug, Copy, Clone, PartialEq, Eq)]
    #[repr(transparent)]
    pub struct FlagSet: u32 {
        /// Flag to pass when no specific options are needed.
        const NOFLAGS = capi::PA_STREAM_NOFLAGS;

        /// Create the stream corked, requiring an explicit [`Stream::uncork()`] call to uncork it.
        const START_CORKED = capi::PA_STREAM_START_CORKED;

        /// Interpolate the latency for this stream. When enabled, [`Stream::get_latency()`] and
        /// [`Stream::get_time()`] will try to estimate the current record/playback time based on
        /// the local time that passed since the last timing info update. Using this option has the
        /// advantage of not requiring a whole round trip when the current playback/recording time
        /// is needed. Consider using this option when requesting latency information frequently.
        /// This is especially useful on long latency network connections. It makes a lot of sense
        /// to combine this option with [`AUTO_TIMING_UPDATE`].
        ///
        /// [`AUTO_TIMING_UPDATE`]: Self::AUTO_TIMING_UPDATE
        const INTERPOLATE_TIMING = capi::PA_STREAM_INTERPOLATE_TIMING;

        /// Don’t force the time to increase monotonically. If this option is enabled,
        /// [`Stream::get_time()`] will not necessarily return always monotonically increasing time
        /// values on each call. This may confuse applications which cannot deal with time going
        /// ‘backwards’, but has the advantage that bad transport latency estimations that caused
        /// the time to jump ahead can be corrected quickly, without the need to wait.
        const NOT_MONOTONIC = capi::PA_STREAM_NOT_MONOTONIC;

        /// If set timing update requests are issued periodically automatically. Combined with
        /// [`INTERPOLATE_TIMING`] you will be able to query the current time and latency with
        /// [`Stream::get_time()`] and [`Stream::get_latency()`] at all times without a packet round
        /// trip.
        ///
        /// [`INTERPOLATE_TIMING`]: Self::INTERPOLATE_TIMING
        const AUTO_TIMING_UPDATE = capi::PA_STREAM_AUTO_TIMING_UPDATE;

        /// Don’t remap channels by their name, instead map them simply by their index. Implies
        /// [`NO_REMIX_CHANNELS`](Self::NO_REMIX_CHANNELS).
        const NO_REMAP_CHANNELS = capi::PA_STREAM_NO_REMAP_CHANNELS;

        /// When remapping channels by name, don’t upmix or downmix them to related channels. Copy
        /// them into matching channels of the device 1:1.
        const NO_REMIX_CHANNELS = capi::PA_STREAM_NO_REMIX_CHANNELS;

        /// Use the sample format of the sink/device this stream is being connected to, and possibly
        /// ignore the format the sample spec contains -- but you still have to pass a valid value
        /// in it as a hint to PulseAudio what would suit your stream best. If this is used you
        /// should query the used sample format after creating the stream by using
        /// [`Stream::get_sample_spec()`]. Also, if you specified manual buffer metrics it is
        /// recommended to update them with [`Stream::set_buffer_attr()`] to compensate for the
        /// changed frame sizes.
        ///
        /// When creating streams with [`Stream::new_extended()`], this flag has no effect. If you
        /// specify a format with PCM encoding, and you want the server to choose the sample format,
        /// then you should leave the sample format unspecified in the [`Info`] object. This also
        /// means that you can’t use [`Info::new_from_sample_spec()`], because that function always
        /// sets the sample format.
        ///
        /// [`Info`]: crate::format::Info
        /// [`Info::new_from_sample_spec()`]: crate::format::Info::new_from_sample_spec
        const FIX_FORMAT = capi::PA_STREAM_FIX_FORMAT;

        /// Use the sample rate of the sink, and possibly ignore the rate the sample spec contains.
        /// Usage similar to [`FIX_FORMAT`].
        ///
        /// When creating streams with [`Stream::new_extended()`], this flag has no effect. If you
        /// specify a format with PCM encoding, and you want the server to choose the sample rate,
        /// then you should leave the rate unspecified in the [`Info`] object. This also means that
        /// you can’t use [`Info::new_from_sample_spec()`], because that function always sets the
        /// sample rate.
        ///
        /// [`FIX_FORMAT`]: Self::FIX_FORMAT
        /// [`Info`]: crate::format::Info
        /// [`Info::new_from_sample_spec()`]: crate::format::Info::new_from_sample_spec
        const FIX_RATE = capi::PA_STREAM_FIX_RATE;

        /// Use the number of channels and the channel map of the sink, and possibly ignore the number
        /// of channels and the map the sample spec and the passed channel map contains. Usage similar
        /// to [`FIX_FORMAT`].
        ///
        /// When creating streams with [`Stream::new_extended()`], this flag has no effect. If you
        /// specify a format with PCM encoding, and you want the server to choose the channel count
        /// and/or channel map, then you should leave the channels and/or the channel map
        /// unspecified in the [`Info`] object. This also means that you can’t use
        /// [`Info::new_from_sample_spec()`], because that function always sets the channel count
        /// (but if you only want to leave the channel map unspecified, then
        /// [`Info::new_from_sample_spec()`] works, because the channel map parameter is optional).
        ///
        /// [`FIX_FORMAT`]: Self::FIX_FORMAT
        /// [`Info`]: crate::format::Info
        /// [`Info::new_from_sample_spec()`]: crate::format::Info::new_from_sample_spec
        const FIX_CHANNELS = capi::PA_STREAM_FIX_CHANNELS;

        /// Don’t allow moving of this stream to another sink/device. Useful if you use any of the
        /// `Fix*` flags and want to make sure that resampling never takes place -- which might
        /// happen if the stream is moved to another sink/source with a different sample
        /// spec/channel map.
        const DONT_MOVE = capi::PA_STREAM_DONT_MOVE;

        /// Allow dynamic changing of the sampling rate during playback with
        /// [`Stream::update_sample_rate()`].
        const VARIABLE_RATE = capi::PA_STREAM_VARIABLE_RATE;

        /// Find peaks instead of resampling.
        const PEAK_DETECT = capi::PA_STREAM_PEAK_DETECT;

        /// Create in muted state. If neither [`START_UNMUTED`] nor this is specified, it is left to
        /// the server to decide whether to create the stream in muted or in un-muted state.
        ///
        /// [`START_UNMUTED`]: Self::START_UNMUTED
        const START_MUTED = capi::PA_STREAM_START_MUTED;

        /// Try to adjust the latency of the sink/source based on the requested buffer metrics and
        /// adjust buffer metrics accordingly. Also see [`BufferAttr`]. This option may not be
        /// specified at the same time as [`EARLY_REQUESTS`].
        ///
        /// [`EARLY_REQUESTS`]: Self::EARLY_REQUESTS
        /// [`BufferAttr`]: crate::def::BufferAttr
        const ADJUST_LATENCY = capi::PA_STREAM_ADJUST_LATENCY;

        /// Enable compatibility mode for legacy clients that rely on a “classic” hardware device
        /// fragment-style playback model. If this option is set, the `minreq` value of the buffer
        /// metrics gets a new meaning: instead of just specifying that no requests asking for less
        /// new data than this value will be made to the client it will also guarantee that requests
        /// are generated as early as this limit is reached. This flag should only be set in very
        /// few situations where compatibility with a fragment-based playback model needs to be kept
        /// and the client applications cannot deal with data requests that are delayed to the
        /// latest moment possible. (Usually these are programs that use usleep() or a similar call
        /// in their playback loops instead of sleeping on the device itself.) Also see
        /// [`BufferAttr`]. This option may not be specified at the same time as [`ADJUST_LATENCY`].
        ///
        /// [`ADJUST_LATENCY`]: Self::ADJUST_LATENCY
        /// [`BufferAttr`]: crate::def::BufferAttr
        const EARLY_REQUESTS = capi::PA_STREAM_EARLY_REQUESTS;

        /// If set this stream won’t be taken into account when it is checked whether the device
        /// this stream is connected to should auto-suspend.
        const DONT_INHIBIT_AUTO_SUSPEND = capi::PA_STREAM_DONT_INHIBIT_AUTO_SUSPEND;

        /// Create in unmuted state. If neither [`START_MUTED`] nor this is specified, it is left to
        /// the server to decide whether to create the stream in muted or in unmuted state.
        ///
        /// [`START_MUTED`]: Self::START_MUTED
        const START_UNMUTED = capi::PA_STREAM_START_UNMUTED;

        /// If the sink/source this stream is connected to is suspended during the creation of this
        /// stream, cause it to fail. If the sink/source is being suspended during creation of this
        /// stream, make sure this stream is terminated.
        const FAIL_ON_SUSPEND = capi::PA_STREAM_FAIL_ON_SUSPEND;

        /// If a volume is passed when this stream is created, consider it relative to the sink’s
        /// current volume, never as absolute device volume. If this is not specified the volume
        /// will be consider absolute when the sink is in flat volume mode, relative otherwise.
        const RELATIVE_VOLUME = capi::PA_STREAM_RELATIVE_VOLUME;

        /// Used to tag content that will be rendered by passthrough sinks. The data will be left as
        /// is and not reformatted, resampled.
        const PASSTHROUGH = capi::PA_STREAM_PASSTHROUGH;
    }
}

impl Default for FlagSet {
    fn default() -> Self {
        Self::NOFLAGS
    }
}

/// Common event names supplied to the [`Stream::set_event_callback()`] callback.
pub mod event_names {
    use capi;

    /// A stream policy/meta event requesting that an application should cork a specific stream.
    pub const EVENT_REQUEST_CORK: &str = capi::PA_STREAM_EVENT_REQUEST_CORK;

    /// A stream policy/meta event requesting that an application should cork a specific stream.
    pub const EVENT_REQUEST_UNCORK: &str = capi::PA_STREAM_EVENT_REQUEST_UNCORK;

    /// A stream event notifying that the stream is going to be disconnected because the underlying
    /// sink changed and no longer supports the format that was originally negotiated. Clients need
    /// to connect a new stream to renegotiate a format and continue playback.
    pub const EVENT_FORMAT_LOST: &str = capi::PA_STREAM_EVENT_FORMAT_LOST;
}

/// Result type for the [`Stream::peek()`] method. See documentation of the method itself for more
/// information.
#[derive(Debug)]
pub enum PeekResult<'a> {
    /// No data (Null data pointer and size of 0 returned by PA).
    Empty,
    /// Data hole with given size (Null pointer with non-zero size returned by PA).
    Hole(usize),
    /// Data available, with slice into memory returned by PA.
    Data(&'a [u8]),
}

/// Result type for [`Stream::get_latency()`].
#[derive(Debug, Copy, Clone, PartialEq, Eq)]
pub enum Latency {
    /// No latency.
    None,
    /// A positive (greater than zero) amount of latency.
    Positive(MicroSeconds),
    /// A negative (less than zero) amount of latency.
    Negative(MicroSeconds),
}

impl Stream {
    /// Creates a new, unconnected stream with the specified name and sample type.
    ///
    /// It is recommended to use [`new_with_proplist()`] instead and specify some initial
    /// properties.
    ///
    /// # Params
    ///
    /// * `ctx`: The context to create this stream in
    /// * `name`: A name for this stream
    /// * `ss`: The desired sample format
    /// * `map`: The desired channel map, or `None` for default
    ///
    /// [`new_with_proplist()`]: Self::new_with_proplist
    pub fn new(ctx: &mut Context, name: &str, ss: &sample::Spec, map: Option<&channelmap::Map>)
        -> Option<Self>
    {
        // Warning: New CStrings will be immediately freed if not bound to a variable, leading to
        // as_ptr() giving dangling pointers!
        let c_name = CString::new(name).unwrap();

        let p_map = map.map_or(null::<capi::pa_channel_map>(), |m| m.as_ref());

        let ptr = unsafe { capi::pa_stream_new(ctx.ptr, c_name.as_ptr(), ss.as_ref(), p_map) };
        match ptr.is_null() {
            false => Some(Self::from_raw(ptr)),
            true => None,
        }
    }

    /// Creates a new, unconnected stream with the specified name and sample type, and specify the
    /// initial stream property list.
    ///
    /// # Params
    ///
    /// * `ctx`: The context to create this stream in
    /// * `name`: A name for this stream
    /// * `ss`: The desired sample format
    /// * `map`: The desired channel map, or `None` for default
    /// * `proplist`: The initial property list
    pub fn new_with_proplist(ctx: &mut Context, name: &str, ss: &sample::Spec,
        map: Option<&channelmap::Map>, proplist: &mut Proplist) -> Option<Self>
    {
        // Warning: New CStrings will be immediately freed if not bound to a variable, leading to
        // as_ptr() giving dangling pointers!
        let c_name = CString::new(name).unwrap();

        let p_map = map.map_or(null::<capi::pa_channel_map>(), |m| m.as_ref());

        let ptr = unsafe {
            capi::pa_stream_new_with_proplist(ctx.ptr, c_name.as_ptr(), ss.as_ref(),
                p_map, proplist.0.ptr)
        };
        match ptr.is_null() {
            false => Some(Self::from_raw(ptr)),
            true => None,
        }
    }

    /// Creates a new, unconnected stream with the specified name, the set of formats this client
    /// can provide, and an initial list of properties.
    ///
    /// While connecting, the server will select the most appropriate format which the client must
    /// then provide.
    ///
    /// Will panic if the `formats` array is longer than can be communicated to the C function.
    ///
    /// # Params
    ///
    /// * `ctx`: The context to create this stream in
    /// * `name`: A name for this stream
    /// * `formats`: The list of formats that can be provided
    /// * `proplist`: The initial property list
    pub fn new_extended(ctx: &mut Context, name: &str, formats: &[&format::Info],
        proplist: &mut Proplist) -> Option<Self>
    {
        assert!(formats.len() <= u32::MAX as usize);
        // Warning: New CStrings will be immediately freed if not bound to a variable, leading to
        // as_ptr() giving dangling pointers!
        let c_name = CString::new(name).unwrap();

        // Create array of format::InfoInternal pointers from provided array of `Info` pointers.
        let mut info_ptrs: Vec<*const capi::pa_format_info> = Vec::with_capacity(formats.len());
        for format in formats {
            info_ptrs.push(format.ptr as *const capi::pa_format_info);
        }

        let ptr = unsafe {
            capi::pa_stream_new_extended(ctx.ptr, c_name.as_ptr(), info_ptrs.as_ptr(),
                info_ptrs.len() as u32, proplist.0.ptr)
        };
        match ptr.is_null() {
            false => Some(Self::from_raw(ptr)),
            true => None,
        }
    }

    /// Creates a new `Stream` from an existing [`StreamInternal`] pointer.
    #[inline]
    fn from_raw(ptr: *mut StreamInternal) -> Self {
        assert_eq!(false, ptr.is_null());
        Self { ptr: ptr, cb_ptrs: Default::default() }
    }

    /// Gets the current state of the stream.
    #[inline]
    pub fn get_state(&self) -> State {
        unsafe { capi::pa_stream_get_state(self.ptr).into() }
    }

    /// Gets the sink input resp. source output index this stream is identified in the server with.
    ///
    /// This is useful with the introspection functions such as
    /// [`Introspector::get_sink_input_info()`] or [`Introspector::get_source_output_info()`].
    ///
    /// [`Introspector::get_sink_input_info()`]: crate::context::introspect::Introspector::get_sink_input_info
    /// [`Introspector::get_source_output_info()`]: crate::context::introspect::Introspector::get_source_output_info
    pub fn get_index(&self) -> Option<u32> {
        match unsafe { capi::pa_stream_get_index(self.ptr) } {
            def::INVALID_INDEX => None,
            r => Some(r),
        }
    }

    /// Gets the index of the sink or source this stream is connected to in the server.
    ///
    /// This is useful with the introspection functions such as
    /// [`Introspector::get_sink_info_by_index()`] or [`Introspector::get_source_info_by_index()`].
    ///
    /// Please note that streams may be moved between sinks/sources and thus it is recommended to
    /// use [`set_moved_callback()`] to be notified about this.
    ///
    /// [`set_moved_callback()`]: Self::set_moved_callback
    /// [`Introspector::get_sink_info_by_index()`]: crate::context::introspect::Introspector::get_sink_info_by_index
    /// [`Introspector::get_source_info_by_index()`]: crate::context::introspect::Introspector::get_source_info_by_index
    pub fn get_device_index(&self) -> Option<u32> {
        match unsafe { capi::pa_stream_get_device_index(self.ptr) } {
            def::INVALID_INDEX => None,
            r => Some(r),
        }
    }

    /// Gets the name of the sink or source this stream is connected to in the server.
    ///
    /// This is useful with the introspection functions such as
    /// [`Introspector::get_sink_info_by_name()`] or [`Introspector::get_source_info_by_name()`].
    ///
    /// Please note that streams may be moved between sinks/sources and thus it is recommended to
    /// use [`set_moved_callback()`] to be notified about this.
    ///
    /// [`set_moved_callback()`]: Self::set_moved_callback
    /// [`Introspector::get_sink_info_by_name()`]: crate::context::introspect::Introspector::get_sink_info_by_name
    /// [`Introspector::get_source_info_by_name()`]: crate::context::introspect::Introspector::get_source_info_by_name
    pub fn get_device_name(&self) -> Option<Cow<'static, str>> {
        let ptr: *const c_char = unsafe { capi::pa_stream_get_device_name(self.ptr) };
        match ptr.is_null() {
            false => Some(unsafe { CStr::from_ptr(ptr).to_string_lossy() }),
            true => None,
        }
    }

    /// Checks whether or not the sink or source this stream is connected to has been suspended.
    pub fn is_suspended(&self) -> Result<bool, PAErr> {
        match unsafe { capi::pa_stream_is_suspended(self.ptr) } {
            0 => Ok(false),
            1 => Ok(true),
            e => Err(PAErr(e)),
        }
    }

    /// Checks whether or not this stream has been corked.
    pub fn is_corked(&self) -> Result<bool, PAErr> {
        match unsafe { capi::pa_stream_is_corked(self.ptr) } {
            0 => Ok(false),
            1 => Ok(true),
            e => Err(PAErr(e)),
        }
    }

    /// Connects the stream to a sink.
    ///
    /// It is strongly recommended to pass `None` in both `dev` and `volume` and to set neither
    /// [`FlagSet::START_MUTED`] nor [`FlagSet::START_UNMUTED`] -- unless these options are directly
    /// dependent on user input or configuration.
    ///
    /// If you follow this rule then the sound server will have the full flexibility to choose the
    /// device, volume and mute status automatically, based on server-side policies, heuristics and
    /// stored information from previous uses. Also the server may choose to reconfigure audio
    /// devices to make other sinks/sources or capabilities available to be able to accept the
    /// stream.
    ///
    /// Before PA 0.9.20 it was not defined whether the ‘volume’ parameter was interpreted relative
    /// to the sink’s current volume or treated as an absolute device volume. Since PA 0.9.20 it is
    /// an absolute volume when the sink is in flat volume mode, and relative otherwise, thus making
    /// sure the volume passed here has always the same semantics as the volume passed to
    /// [`Introspector::set_sink_input_volume()`]. It is possible to figure out whether flat volume
    /// mode is in effect for a given sink by calling [`Introspector::get_sink_info_by_name()`].
    ///
    /// Since PA 5.0, it’s possible to specify a single-channel volume even if the stream has
    /// multiple channels. In that case the same volume is applied to all channels.
    ///
    /// # Params
    ///
    /// * `dev`: Name of the sink to connect to, or `None` to let the server decide
    /// * `attr`: Buffering attributes, or `None` for default
    /// * `flags`: Additional flags, or `0` for default
    /// * `volume`: Initial volume, or `None` for default
    /// * `sync_stream`: Synchronize this stream with the specified one, or `None` for a standalone
    ///   stream.
    ///
    /// [`Introspector::set_sink_input_volume()`]: crate::context::introspect::Introspector::set_sink_input_volume
    /// [`Introspector::get_sink_info_by_name()`]: crate::context::introspect::Introspector::get_sink_info_by_name
    pub fn connect_playback(&mut self, dev: Option<&str>, attr: Option<&def::BufferAttr>,
        flags: FlagSet, volume: Option<&ChannelVolumes>, sync_stream: Option<&mut Self>)
        -> Result<(), PAErr>
    {
        // Warning: New CStrings will be immediately freed if not bound to a variable, leading to
        // as_ptr() giving dangling pointers!
        let c_dev = match dev {
            Some(dev) => CString::new(dev).unwrap(),
            None => CString::new("").unwrap(),
        };

        let p_attr = attr.map_or(null::<capi::pa_buffer_attr>(), |a| a.as_ref());
        let p_vol = volume.map_or(null::<capi::pa_cvolume>(), |v| v.as_ref());
        let p_sync = sync_stream.map_or(null_mut::<StreamInternal>(), |s| s.ptr);
        let p_dev = dev.map_or(null::<c_char>(), |_| c_dev.as_ptr() as *const c_char);

        let r = unsafe {
            capi::pa_stream_connect_playback(self.ptr, p_dev, p_attr, flags.bits(), p_vol, p_sync)
        };
        match r {
            0 => Ok(()),
            e => Err(PAErr(e)),
        }
    }

    /// Connects the stream to a source.
    ///
    /// # Params
    ///
    /// * `dev`: Name of the source to connect to, or `None` to let the server decide
    /// * `attr`: Buffering attributes, or `None` for default
    /// * `flags`: Additional flags, or `0` for default
    pub fn connect_record(&mut self, dev: Option<&str>, attr: Option<&def::BufferAttr>,
        flags: FlagSet) -> Result<(), PAErr>
    {
        // Warning: New CStrings will be immediately freed if not bound to a variable, leading to
        // as_ptr() giving dangling pointers!
        let c_dev = match dev {
            Some(dev) => CString::new(dev).unwrap(),
            None => CString::new("").unwrap(),
        };

        let p_attr = attr.map_or(null::<capi::pa_buffer_attr>(), |a| a.as_ref());
        let p_dev = dev.map_or(null::<c_char>(), |_| c_dev.as_ptr() as *const c_char);

        match unsafe { capi::pa_stream_connect_record(self.ptr, p_dev, p_attr, flags.bits()) } {
            0 => Ok(()),
            e => Err(PAErr(e)),
        }
    }

    /// Makes this stream a sample upload stream.
    ///
    /// (See [`scache`](mod@crate::context::scache)).
    pub fn connect_upload(&mut self, length: usize) -> Result<(), PAErr> {
        match unsafe { capi::pa_stream_connect_upload(self.ptr, length) } {
            0 => Ok(()),
            e => Err(PAErr(e)),
        }
    }

    /// Finishes the sample upload, the stream name will become the sample name.
    ///
    /// You cancel a sample upload by issuing [`disconnect()`](Self::disconnect).
    pub fn finish_upload(&mut self) -> Result<(), PAErr> {
        match unsafe { capi::pa_stream_finish_upload(self.ptr) } {
            0 => Ok(()),
            e => Err(PAErr(e)),
        }
    }

    /// Disconnects a stream from a source/sink.
    pub fn disconnect(&mut self) -> Result<(), PAErr> {
        match unsafe { capi::pa_stream_disconnect(self.ptr) } {
            0 => Ok(()),
            e => Err(PAErr(e)),
        }
    }

    /// Prepares writing data to the server (for playback streams).
    ///
    /// This function may be used to optimize the number of memory copies when doing playback
    /// (“zero-copy”). It is recommended to call this function before each call to [`write()`]. It
    /// is used to obtain a chunk of PA internally allocated memory, into which you can directly
    /// write your data before calling [`write()`] to actually execute the write.
    ///
    /// This function should be called with `nbytes` set to the number of bytes you want to write,
    /// or `None`, in which case the size will be chosen automatically (which is recommended).
    ///
    /// The return value is a `Result` type, with the `Ok` variant wrapping an `Option`. `Err` will
    /// be returned if PA encountered an error; `Ok(None)` will be  returned if it appeared to be
    /// successful, but the pointer returned was `NULL`, otherwise the buffer will be returned as
    /// `Ok(Some(_))`.
    ///
    /// After placing your data in the memory area returned, call [`write()`] with a sub-slice of
    /// it, to actually execute the write. **Note**, the buffer may only be used once, i.e. if you
    /// were thinking of getting a large buffer, placing a large chunk of data into it, then perform
    /// multiple small writes from it, you **cannot** do this. Any attempt at accessing the memory
    /// returned after the following [`write()`] or [`cancel_write()`] is invalid.
    ///
    /// If you want to cancel a previously called `begin_write()` without calling [`write()`] use
    /// [`cancel_write()`].
    ///
    /// The memory should **not** be explicitly freed by the caller.
    ///
    /// An invocation of [`write()`] should “quickly” follow a `begin_write()`. It is not
    /// recommended letting an unbounded amount of time pass after calling `begin_write()` and
    /// before calling [`write()`]. Calling `begin_write()` twice without calling [`write()`] or
    /// [`cancel_write()`] in between will return exactly the same `data` pointer and `nbytes`
    /// values.
    ///
    /// [`write()`]: Self::write
    /// [`cancel_write()`]: Self::cancel_write
    pub fn begin_write<'a>(&mut self, nbytes: Option<usize>)
        -> Result<Option<&'a mut [u8]>, PAErr>
    {
        let mut data_ptr = null_mut::<c_void>();
        // If user asks for size to be automatically chosen by PA, we pass in std::usize::MAX
        // (-1 as size_t) to signal this.
        let mut nbytes_tmp = nbytes.unwrap_or(std::usize::MAX);
        match unsafe { capi::pa_stream_begin_write(self.ptr, &mut data_ptr, &mut nbytes_tmp) } {
            0 => match data_ptr.is_null() {
                true => Ok(None),
                false => {
                    let slice =
                        unsafe { std::slice::from_raw_parts_mut(data_ptr as *mut u8, nbytes_tmp) };
                    Ok(Some(slice))
                },
            },
            e => Err(PAErr(e)),
        }
    }

    /// Reverses the effect of [`begin_write()`] dropping any data that has already been placed in
    /// the memory area returned by [`begin_write()`].
    ///
    /// Only valid to call after a call to [`begin_write()`] has been made, and neither
    /// `cancel_write()` nor [`write()`] have been called yet. Accessing the memory previously
    /// returned by [`begin_write()`] after calling this function is invalid.
    ///
    /// [`write()`]: Self::write
    /// [`begin_write()`]: Self::begin_write
    pub fn cancel_write(&mut self) -> Result<(), PAErr> {
        match unsafe { capi::pa_stream_cancel_write(self.ptr) } {
            0 => Ok(()),
            e => Err(PAErr(e)),
        }
    }

    /// Writes some data to the server (for playback streams).
    ///
    /// If `free_cb` is provided, this routine is called when all data has been written out. An
    /// internal reference to the specified data is kept, the data is not copied. If `None`, the
    /// data is copied into an internal buffer.
    ///
    /// The client may freely seek around in the output buffer. For most applications it is typical
    /// to pass `0` and [`SeekMode::Relative`] as values for the arguments `offset` and `seek`
    /// respectively. After a successful write call the write index will be at the position after
    /// where this chunk of data has been written to.
    ///
    /// As an optimization for avoiding needless memory copies you may call [`begin_write()`] before
    /// this call and then place your audio data directly in the memory area returned by that call.
    /// Then, pass a pointer to that memory area to `write()`. After the invocation of `write()` the
    /// memory area may no longer be accessed. Any further explicit freeing of the memory area is
    /// not necessary. It is OK to write to the memory area returned by [`begin_write()`] only
    /// partially with this call, skipping bytes both at the end and at the beginning of the
    /// reserved memory area.
    ///
    /// # Params
    ///
    /// * `data`: The data to write. The length must be in multiples of the stream’s sample spec
    ///   frame size.
    /// * `free_cb`: A cleanup routine for the data or `None` to request an internal copy of the
    ///   data.
    /// * `offset`: Offset for seeking. Must be `0` for upload streams. Must be in multiples of the
    ///   stream’s sample spec frame size.
    /// * `seek`: Seek mode. Must be [`SeekMode::Relative`] for upload streams.
    ///
    /// [`begin_write()`]: Self::begin_write
    pub fn write(&mut self, data: &[u8], free_cb: Option<def::FreeCb>, offset: i64,
        seek: SeekMode) -> Result<(), PAErr>
    {
        debug_assert_eq!(0, data.len().checked_rem(self.get_sample_spec().unwrap().frame_size())
            .unwrap());
        let r = unsafe {
            capi::pa_stream_write(self.ptr, data.as_ptr() as *const c_void, data.len(), free_cb,
                offset, seek)
        };
        match r {
            0 => Ok(()),
            e => Err(PAErr(e)),
        }
    }

    /// Writes some data to the server (for playback streams).
    ///
    /// This function does exactly the same as [`write()`] as though `None` had been specified for
    /// the `free_cb` param. I.e. an internal copy will be made of the provided data.
    ///
    /// # Params
    ///
    /// * `data`: The data to write. The length must be in multiples of the stream’s sample spec
    ///   frame size.
    /// * `offset`: Offset for seeking. Must be `0` for upload streams. Must be in multiples of the
    ///   stream’s sample spec frame size.
    /// * `seek`: Seek mode. Must be [`SeekMode::Relative`] for upload streams.
    ///
    /// [`write()`]: Self::write
    #[inline(always)]
    pub fn write_copy(&mut self, data: &[u8], offset: i64, seek: SeekMode) -> Result<(), PAErr> {
        self.write(data, None, offset, seek)
    }

    /// Writes some data to the server (for playback streams).
    ///
    /// This function does exactly the same as [`write()`] with the only difference being that a
    /// void pointer is provided along with the `free_cb` callback pointer, and this void pointer
    /// will be passed to the callback instead of the `data` pointer.
    ///
    /// # Params
    ///
    /// * `data`: The data to write. The length must be in multiples of the stream’s sample spec
    ///   frame size.
    /// * `free_cb`: A cleanup routine for the data or `None` to request an internal copy of the
    ///   data. If provided, the accompanying data pointer will be supplied to the callback.
    /// * `offset`: Offset for seeking. Must be `0` for upload streams.
    /// * `seek`: Seek mode, must be [`SeekMode::Relative`] for upload streams.
    ///
    /// [`write()`]: Self::write
    #[cfg(any(doc, feature = "pa_v6"))]
    #[cfg_attr(docsrs, doc(cfg(feature = "pa_v6")))]
    pub fn write_ext_free(&mut self, data: &[u8], free_cb: Option<(def::FreeCb, *mut c_void)>,
        offset: i64, seek: SeekMode) -> Result<(), PAErr>
    {
        let (cb_f, cb_d) = match free_cb {
            Some((f, d)) => (Some(f), d),
            None => (None, null_mut::<c_void>()),
        };
        debug_assert_eq!(0, data.len().checked_rem(self.get_sample_spec().unwrap().frame_size())
            .unwrap());
        let r = unsafe {
            capi::pa_stream_write_ext_free(self.ptr, data.as_ptr() as *const c_void, data.len(),
                cb_f, cb_d, offset, seek.into())
        };
        match r {
            0 => Ok(()),
            e => Err(PAErr(e)),
        }
    }

    /// Reads the next fragment from the buffer (for recording streams).
    ///
    /// This function returns one of the [`PeekResult`] variants - either [`Empty`], [`Hole`] or
    /// [`Data`]:
    ///
    ///  * If there is data at the current read index, the [`Data`] variant will be returned, which
    ///    contains a slice giving a view of the data. (The length of this slice can be less or more
    ///    than a complete fragment). This is pointing into an internal buffer, so obviously you
    ///    must make a copy of it if you want to keep it.
    ///  * If there is no data at the current read index, it means that either the buffer is empty
    ///    or it contains a hole (that is, the write index is ahead of the read index but there’s no
    ///    data where the read index points at). If the buffer is empty, the [`Empty`] result
    ///    variant will be returned. If there is a hole, the [`Hole`] variant will be returned,
    ///    containing the length of the hole in bytes.
    ///
    /// Use [`discard()`] to actually remove the data from the buffer and move the read index
    /// forward. [`discard()`] should not be called if the buffer is empty, but it should be called
    /// if there is a hole.
    ///
    /// [`Empty`]: PeekResult::Empty
    /// [`Hole`]: PeekResult::Hole
    /// [`Data`]: PeekResult::Data
    /// [`discard()`]: Self::discard
    pub fn peek<'a>(&mut self) -> Result<PeekResult<'a>, PAErr> {
        let mut data_ptr = null::<c_void>();
        let mut nbytes: usize = 0;
        // Note, C function returns an i32, but documentation does not mention any use of it, so we
        // discard it.
        match unsafe { capi::pa_stream_peek(self.ptr, &mut data_ptr, &mut nbytes) } {
            0 => {
                if data_ptr.is_null() {
                    match nbytes {
                        0 => Ok(PeekResult::Empty),
                        _ => Ok(PeekResult::Hole(nbytes)),
                    }
                }
                else {
                    let slice =
                        unsafe { std::slice::from_raw_parts(data_ptr as *const u8, nbytes) };
                    Ok(PeekResult::Data(slice))
                }
            },
            e => Err(PAErr(e)),
        }
    }

    /// Removes the current fragment on record streams.
    ///
    /// It is invalid to do this without first calling [`peek()`](Self::peek).
    ///
    /// Note: The original C function name used the term `drop`; We instead use `discard` here to
    /// avoid conflict with the Rust `Drop` trait!
    pub fn discard(&mut self) -> Result<(), PAErr> {
        match unsafe { capi::pa_stream_drop(self.ptr) } {
            0 => Ok(()),
            e => Err(PAErr(e)),
        }
    }

    /// Gets the number of bytes requested by the server that have not yet been written.
    ///
    /// It is possible to write more than this amount, up to the stream’s [`buffer_attr.maxlength`]
    /// bytes. This is usually not desirable, though, as it would increase stream latency to be
    /// higher than requested ([`buffer_attr.tlength`]).
    ///
    /// [`buffer_attr.maxlength`]: crate::def::BufferAttr.maxlength
    /// [`buffer_attr.tlength`]: crate::def::BufferAttr.tlength
    pub fn writable_size(&self) -> Option<usize> {
        match unsafe { capi::pa_stream_writable_size(self.ptr) } {
            std::usize::MAX => None,
            r => Some(r),
        }
    }

    /// Gets the number of bytes that may be read using [`peek()`](Self::peek).
    ///
    /// Returns `None` on error.
    pub fn readable_size(&self) -> Option<usize> {
        match unsafe { capi::pa_stream_readable_size(self.ptr) } {
            std::usize::MAX => None,
            r => Some(r),
        }
    }

    /// Drains a playback stream.
    ///
    /// Use this for notification when the playback buffer is empty after playing all the audio in
    /// the buffer. Please note that only one drain operation per stream may be issued at a time.
    ///
    /// The optional callback must accept a `bool`, which indicates success.
    ///
    /// Panics if the underlying C function returns a null pointer.
    pub fn drain(&mut self, callback: Option<Box<dyn FnMut(bool) + 'static>>)
        -> Operation<dyn FnMut(bool)>
    {
        let (cb_fn, cb_data): (Option<extern "C" fn(_, _, _)>, _) =
            get_su_capi_params::<_, _>(callback, success_cb_proxy);
        let ptr = unsafe { capi::pa_stream_drain(self.ptr, cb_fn, cb_data) };
        Operation::from_raw(ptr, cb_data as *mut Box<dyn FnMut(bool)>)
    }

    /// Requests a timing info structure update for a stream.
    ///
    /// Use [`get_timing_info()`] to get access to the raw timing data, or [`get_time()`] or
    /// [`get_latency()`] to get cleaned up values.
    ///
    /// The optional callback must accept a `bool`, which indicates success.
    ///
    /// Panics if the underlying C function returns a null pointer.
    ///
    /// [`get_timing_info()`]: Self::get_timing_info
    /// [`get_time()`]: Self::get_time
    /// [`get_latency()`]: Self::get_latency
    pub fn update_timing_info(&mut self, callback: Option<Box<dyn FnMut(bool) + 'static>>)
        -> Operation<dyn FnMut(bool)>
    {
        let (cb_fn, cb_data): (Option<extern "C" fn(_, _, _)>, _) =
            get_su_capi_params::<_, _>(callback, success_cb_proxy);
        let ptr = unsafe { capi::pa_stream_update_timing_info(self.ptr, cb_fn, cb_data) };
        Operation::from_raw(ptr, cb_data as *mut Box<dyn FnMut(bool)>)
    }

    /// Sets the callback function that is called whenever the state of the stream changes.
    pub fn set_state_callback(&mut self, callback: Option<Box<dyn FnMut() + 'static>>) {
        let saved = &mut self.cb_ptrs.set_state;
        *saved = NotifyCb::new(callback);
        let (cb_fn, cb_data) = saved.get_capi_params(notify_cb_proxy);
        unsafe { capi::pa_stream_set_state_callback(self.ptr, cb_fn, cb_data); }
    }

    /// Sets the callback function that is called when new data may be written to the stream.
    ///
    /// The callback accepts an argument giving the number of bytes.
    pub fn set_write_callback(&mut self, callback: Option<Box<dyn FnMut(usize) + 'static>>) {
        let saved = &mut self.cb_ptrs.write;
        *saved = RequestCb::new(callback);
        let (cb_fn, cb_data) = saved.get_capi_params(request_cb_proxy);
        unsafe { capi::pa_stream_set_write_callback(self.ptr, cb_fn, cb_data); }
    }

    /// Sets the callback function that is called when new data is available from the stream.
    ///
    /// The callback accepts an argument giving the number of bytes.
    pub fn set_read_callback(&mut self, callback: Option<Box<dyn FnMut(usize) + 'static>>) {
        let saved = &mut self.cb_ptrs.read;
        *saved = RequestCb::new(callback);
        let (cb_fn, cb_data) = saved.get_capi_params(request_cb_proxy);
        unsafe { capi::pa_stream_set_read_callback(self.ptr, cb_fn, cb_data); }
    }

    /// Sets the callback function that is called when a buffer overflow happens. (Only for playback
    /// streams).
    pub fn set_overflow_callback(&mut self, callback: Option<Box<dyn FnMut() + 'static>>) {
        let saved = &mut self.cb_ptrs.overflow;
        *saved = NotifyCb::new(callback);
        let (cb_fn, cb_data) = saved.get_capi_params(notify_cb_proxy);
        unsafe { capi::pa_stream_set_overflow_callback(self.ptr, cb_fn, cb_data); }
    }

    /// Gets at what position the latest underflow occurred.
    ///
    /// `None` is returned if this information is not known (e.g. if no underflow has occurred).
    ///
    /// This can be used inside the underflow callback to get information about the current
    /// underflow. (Only for playback streams).
    pub fn get_underflow_index(&self) -> Option<u64> {
        match unsafe { capi::pa_stream_get_underflow_index(self.ptr) } {
            r if r < 0 => None,
            r => Some(r as u64),
        }
    }

    /// Sets the callback function that is called when a buffer underflow happens.
    ///
    /// (Only for playback streams).
    pub fn set_underflow_callback(&mut self, callback: Option<Box<dyn FnMut() + 'static>>) {
        let saved = &mut self.cb_ptrs.underflow;
        *saved = NotifyCb::new(callback);
        let (cb_fn, cb_data) = saved.get_capi_params(notify_cb_proxy);
        unsafe { capi::pa_stream_set_underflow_callback(self.ptr, cb_fn, cb_data); }
    }

    /// Sets the callback function that is called when the server starts playback after an underrun
    /// or on initial startup.
    ///
    /// This only informs that audio is flowing again, it is no indication that audio started to
    /// reach the speakers already. (Only for playback streams).
    pub fn set_started_callback(&mut self, callback: Option<Box<dyn FnMut() + 'static>>) {
        let saved = &mut self.cb_ptrs.started;
        *saved = NotifyCb::new(callback);
        let (cb_fn, cb_data) = saved.get_capi_params(notify_cb_proxy);
        unsafe { capi::pa_stream_set_started_callback(self.ptr, cb_fn, cb_data); }
    }

    /// Sets the callback function that is called whenever a latency information update happens.
    ///
    /// Useful on [`FlagSet::AUTO_TIMING_UPDATE`] streams only.
    pub fn set_latency_update_callback(&mut self, callback: Option<Box<dyn FnMut() + 'static>>) {
        let saved = &mut self.cb_ptrs.latency_update;
        *saved = NotifyCb::new(callback);
        let (cb_fn, cb_data) = saved.get_capi_params(notify_cb_proxy);
        unsafe { capi::pa_stream_set_latency_update_callback(self.ptr, cb_fn, cb_data); }
    }

    /// Sets the callback function that is called whenever the stream is moved to a different
    /// sink/source.
    ///
    /// Use [`get_device_name()`] or [`get_device_index()`] to query the new sink/source.
    ///
    /// [`get_device_name()`]: Self::get_device_name
    /// [`get_device_index()`]: Self::get_device_index
    pub fn set_moved_callback(&mut self, callback: Option<Box<dyn FnMut() + 'static>>) {
        let saved = &mut self.cb_ptrs.moved;
        *saved = NotifyCb::new(callback);
        let (cb_fn, cb_data) = saved.get_capi_params(notify_cb_proxy);
        unsafe { capi::pa_stream_set_moved_callback(self.ptr, cb_fn, cb_data); }
    }

    /// Sets the callback function that is called whenever the sink/source this stream is connected
    /// to is suspended or resumed.
    ///
    /// Use [`is_suspended()`] to query the new suspend status. Please note that the suspend status
    /// might also change when the stream is moved between devices. Thus if you call this function
    /// you very likely want to call [`set_moved_callback()`] too.
    ///
    /// [`is_suspended()`]: Self::is_suspended
    /// [`set_moved_callback()`]: Self::set_moved_callback
    pub fn set_suspended_callback(&mut self, callback: Option<Box<dyn FnMut() + 'static>>) {
        let saved = &mut self.cb_ptrs.suspended;
        *saved = NotifyCb::new(callback);
        let (cb_fn, cb_data) = saved.get_capi_params(notify_cb_proxy);
        unsafe { capi::pa_stream_set_suspended_callback(self.ptr, cb_fn, cb_data); }
    }

    /// Sets the callback function that is called whenever a meta/policy control event is received.
    ///
    /// The callback is given a name which represents what event occurred. The set of defined events
    /// can be extended at any time. Also, server modules may introduce additional message types so
    /// make sure that your callback function ignores messages it doesn’t know. Some well known
    /// event names can be found in the [`event_names`](mod@self::event_names) submodule. It is also
    /// given an (owned) property list.
    pub fn set_event_callback(&mut self,
        callback: Option<Box<dyn FnMut(String, Proplist) + 'static>>)
    {
        let saved = &mut self.cb_ptrs.event;
        *saved = EventCb::new(callback);
        let (cb_fn, cb_data) = saved.get_capi_params(event_cb_proxy);
        unsafe { capi::pa_stream_set_event_callback(self.ptr, cb_fn, cb_data); }
    }

    /// Sets the callback function that is called whenever the buffer attributes on the server side
    /// change.
    ///
    /// Please note that the buffer attributes can change when moving a stream to a different
    /// sink/source too, hence if you use this callback you should use [`set_moved_callback()`] as
    /// well.
    ///
    /// [`set_moved_callback()`]: Self::set_moved_callback
    pub fn set_buffer_attr_callback(&mut self, callback: Option<Box<dyn FnMut() + 'static>>) {
        let saved = &mut self.cb_ptrs.buffer_attr;
        *saved = NotifyCb::new(callback);
        let (cb_fn, cb_data) = saved.get_capi_params(notify_cb_proxy);
        unsafe { capi::pa_stream_set_buffer_attr_callback(self.ptr, cb_fn, cb_data); }
    }

    /// Pauses playback of this stream temporarily.
    ///
    /// This simply calls [`set_corked_state()`] with a value of `true`.
    ///
    /// [`set_corked_state()`]: Self::set_corked_state
    #[inline(always)]
    pub fn cork(&mut self, callback: Option<Box<dyn FnMut(bool) + 'static>>)
        -> Operation<dyn FnMut(bool)>
    {
        self.set_corked_state(true, callback)
    }

    /// Resumes playback of this stream.
    ///
    /// This simply calls [`set_corked_state()`] with a value of `false`.
    ///
    /// [`set_corked_state()`]: Self::set_corked_state
    #[inline(always)]
    pub fn uncork(&mut self, callback: Option<Box<dyn FnMut(bool) + 'static>>)
        -> Operation<dyn FnMut(bool)>
    {
        self.set_corked_state(false, callback)
    }

    /// Pauses or resumes playback of this stream.
    ///
    /// Available on both playback and recording streams.
    ///
    /// Set state to `true` to cork (pause) the stream. Set state to `false` to uncork (resume) the
    /// stream. Alternatively [`cork()`] and [`uncork()`] helper functions can be used.
    ///
    /// The operation is executed as quickly as possible. If a cork is very quickly followed by an
    /// uncork, or vice versa, this might not actually have any effect on the stream that is output.
    /// You can use [`is_corked()`] to find out whether the stream is currently paused or not.
    /// Normally a stream will be created in uncorked state. If you pass [`FlagSet::START_CORKED`]
    /// as a flag when connecting the stream, it will be created in corked state.
    ///
    /// The optional callback must accept a `bool`, which indicates success.
    ///
    /// Panics if the underlying C function returns a null pointer.
    ///
    /// [`is_corked()`]: Self::is_corked
    /// [`cork()`]: Self::cork
    /// [`uncork()`]: Self::uncork
    pub fn set_corked_state(&mut self, state: bool, callback: Option<Box<dyn FnMut(bool) + 'static>>)
        -> Operation<dyn FnMut(bool)>
    {
        let (cb_fn, cb_data): (Option<extern "C" fn(_, _, _)>, _) =
            get_su_capi_params::<_, _>(callback, success_cb_proxy);
        let ptr = unsafe { capi::pa_stream_cork(self.ptr, state as i32, cb_fn, cb_data) };
        Operation::from_raw(ptr, cb_data as *mut Box<dyn FnMut(bool)>)
    }

    /// Flushes the playback or record buffer of this stream.
    ///
    /// This discards any audio data in the buffer. Most of the time you’re better off using the
    /// parameter `seek` of [`write()`](Self::write) instead of this function.
    ///
    /// The optional callback must accept a `bool`, which indicates success.
    ///
    /// Panics if the underlying C function returns a null pointer.
    pub fn flush(&mut self, callback: Option<Box<dyn FnMut(bool) + 'static>>)
        -> Operation<dyn FnMut(bool)>
    {
        let (cb_fn, cb_data): (Option<extern "C" fn(_, _, _)>, _) =
            get_su_capi_params::<_, _>(callback, success_cb_proxy);
        let ptr = unsafe { capi::pa_stream_flush(self.ptr, cb_fn, cb_data) };
        Operation::from_raw(ptr, cb_data as *mut Box<dyn FnMut(bool)>)
    }

    /// Re-enables prebuffering if specified in the [`BufferAttr`] structure.
    ///
    /// Available for playback streams only.
    ///
    /// The optional callback must accept a `bool`, which indicates success.
    ///
    /// Panics if the underlying C function returns a null pointer.
    ///
    /// [`BufferAttr`]: crate::def::BufferAttr
    pub fn prebuf(&mut self, callback: Option<Box<dyn FnMut(bool) + 'static>>)
        -> Operation<dyn FnMut(bool)>
    {
        let (cb_fn, cb_data): (Option<extern "C" fn(_, _, _)>, _) =
            get_su_capi_params::<_, _>(callback, success_cb_proxy);
        let ptr = unsafe { capi::pa_stream_prebuf(self.ptr, cb_fn, cb_data) };
        Operation::from_raw(ptr, cb_data as *mut Box<dyn FnMut(bool)>)
    }

    /// Requests immediate start of playback on this stream.
    ///
    /// This disables prebuffering temporarily if specified in the [`BufferAttr`] structure.
    /// Available for playback streams only.
    ///
    /// The optional callback must accept a `bool`, which indicates success.
    ///
    /// Panics if the underlying C function returns a null pointer.
    ///
    /// [`BufferAttr`]: crate::def::BufferAttr
    pub fn trigger(&mut self, callback: Option<Box<dyn FnMut(bool) + 'static>>)
        -> Operation<dyn FnMut(bool)>
    {
        let (cb_fn, cb_data): (Option<extern "C" fn(_, _, _)>, _) =
            get_su_capi_params::<_, _>(callback, success_cb_proxy);
        let ptr = unsafe { capi::pa_stream_trigger(self.ptr, cb_fn, cb_data) };
        Operation::from_raw(ptr, cb_data as *mut Box<dyn FnMut(bool)>)
    }

    /// Renames the stream.
    ///
    /// The optional callback must accept a `bool`, which indicates success.
    ///
    /// Panics if the underlying C function returns a null pointer.
    pub fn set_name(&mut self, name: &str, callback: Option<Box<dyn FnMut(bool) + 'static>>)
        -> Operation<dyn FnMut(bool)>
    {
        // Warning: New CStrings will be immediately freed if not bound to a
        // variable, leading to as_ptr() giving dangling pointers!
        let c_name = CString::new(name).unwrap();

        let (cb_fn, cb_data): (Option<extern "C" fn(_, _, _)>, _) =
            get_su_capi_params::<_, _>(callback, success_cb_proxy);
        let ptr = unsafe { capi::pa_stream_set_name(self.ptr, c_name.as_ptr(), cb_fn, cb_data) };
        Operation::from_raw(ptr, cb_data as *mut Box<dyn FnMut(bool)>)
    }

    /// Gets the current playback/recording time.
    ///
    /// This is based on the data in the timing info structure returned by [`get_timing_info()`].
    /// The returned time is in the sound card clock domain, which usually runs at a slightly
    /// different rate than the system clock.
    ///
    /// This function will usually only return new data if a timing info update has been received.
    /// Only if timing interpolation has been requested ([`FlagSet::INTERPOLATE_TIMING`]) the data
    /// from the last timing update is used for an estimation of the current playback/recording time
    /// based on the local time that passed since the timing info structure has been acquired.
    ///
    /// The time value returned by this function is guaranteed to increase monotonically (the
    /// returned value is always greater or equal to the value returned by the last call). This
    /// behaviour can be disabled by using [`FlagSet::NOT_MONOTONIC`]. This may be desirable to
    /// better deal with bad estimations of transport latencies, but may have strange effects if the
    /// application is not able to deal with time going ‘backwards’.
    ///
    /// The time interpolator activated by [`FlagSet::INTERPOLATE_TIMING`] favours ‘smooth’ time
    /// graphs over accurate ones to improve the smoothness of UI operations that are tied to the
    /// audio clock. If accuracy is more important to you, you might need to estimate your timing
    /// based on the data from [`get_timing_info()`] yourself or not work with interpolated timing
    /// at all and instead always query the server side for the most up to date timing with
    /// [`update_timing_info()`].
    ///
    /// If no timing information has been received yet this call will return `Ok(None)`. For more
    /// details see [`get_timing_info()`].
    ///
    /// [`get_timing_info()`]: Self::get_timing_info
    /// [`update_timing_info()`]: Self::update_timing_info
    pub fn get_time(&self) -> Result<Option<MicroSeconds>, PAErr> {
        let mut r_usecs = MicroSeconds(0);
        match unsafe { capi::pa_stream_get_time(self.ptr, &mut r_usecs.0) } {
            0 => Ok(Some(r_usecs)),
            e if e == PAErr::from(error::Code::NoData).0 => Ok(None),
            e => Err(PAErr(e)),
        }
    }

    /// Determines the total stream latency.
    ///
    /// This function is based on [`get_time()`]. The returned time is in the sound card clock
    /// domain, which usually runs at a slightly different rate than the system clock.
    ///
    /// In case the stream is a monitoring stream the result can be negative, i.e. the captured
    /// samples are not yet played, in which case `Ok(Latency::Negative(usecs))` will be returned
    /// instead of `Ok(Latency::Positive(usecs))`
    ///
    /// If no timing information has been received yet, this call will return `Ok(Latency::None)`.
    ///
    /// For more details see [`get_timing_info()`] and [`get_time()`].
    ///
    /// [`get_time()`]: Self::get_time
    /// [`get_timing_info()`]: Self::get_timing_info
    pub fn get_latency(&self) -> Result<Latency, PAErr> {
        let mut r_usecs = MicroSeconds(0);
        let mut negative: i32 = 0;
        match unsafe { capi::pa_stream_get_latency(self.ptr, &mut r_usecs.0, &mut negative) } {
            0 => match negative {
                1 => Ok(Latency::Negative(r_usecs)),
                _ => Ok(Latency::Positive(r_usecs)),
            },
            e if e == PAErr::from(error::Code::NoData).0 => Ok(Latency::None),
            e => Err(PAErr(e)),
        }
    }

    /// Gets the latest raw timing data structure.
    ///
    /// The returned pointer refers to an internal read-only instance of the timing structure. The
    /// user should make a copy of this structure if wanting to modify it. An in-place update to
    /// this data structure may be requested using [`update_timing_info()`].
    ///
    /// If no timing information has been received before (i.e. by requesting
    /// [`update_timing_info()`] or by using [`FlagSet::AUTO_TIMING_UPDATE`]), this function will
    /// return `None` (as it will also if an error occurs).
    ///
    /// Please note that the `write_index` member field (and only this field) is updated on each
    /// [`write()`] call, not just when a timing update has been received.
    ///
    /// [`update_timing_info()`]: Self::update_timing_info
    /// [`write()`]: Self::write
    pub fn get_timing_info<'a>(&mut self) -> Option<&'a def::TimingInfo> {
        unsafe {
            let ptr = capi::pa_stream_get_timing_info(self.ptr);
            ptr.as_ref().map(|r| r.as_ref())
        }
    }

    /// Gets a pointer to the stream’s sample specification.
    pub fn get_sample_spec<'a>(&mut self) -> Option<&'a sample::Spec> {
        unsafe {
            let ptr = capi::pa_stream_get_sample_spec(self.ptr);
            ptr.as_ref().map(|r| r.as_ref())
        }
    }

    /// Gets a pointer to the stream’s channel map.
    pub fn get_channel_map<'a>(&mut self) -> Option<&'a channelmap::Map> {
        unsafe {
            let ptr = capi::pa_stream_get_channel_map(self.ptr);
            ptr.as_ref().map(|r| r.as_ref())
        }
    }

    /// Gets a pointer to the stream’s format.
    pub fn get_format_info(&self) -> Option<format::Info> {
        let ptr = unsafe { capi::pa_stream_get_format_info(self.ptr) };
        match ptr.is_null() {
            false => Some(format::Info::from_raw_weak(ptr as *mut InfoInternal)),
            true => None,
        }
    }

    /// Gets the per-stream server-side buffer metrics of the stream.
    ///
    /// Only valid after the stream has been connected successfully. This will return the actual
    /// configured buffering metrics, which may differ from what was requested during
    /// [`connect_record()`] or [`connect_playback()`]. This call will always return the actual
    /// per-stream server-side buffer metrics, regardless whether [`FlagSet::ADJUST_LATENCY`] is set
    /// or not.
    ///
    /// [`connect_record()`]: Self::connect_record
    /// [`connect_playback()`]: Self::connect_playback
    pub fn get_buffer_attr<'a>(&mut self) -> Option<&'a def::BufferAttr> {
        unsafe {
            let ptr = capi::pa_stream_get_buffer_attr(self.ptr);
            ptr.as_ref().map(|r| r.as_ref())
        }
    }

    /// Changes the buffer metrics of the stream during playback.
    ///
    /// The server might have chosen different buffer metrics then requested. The selected metrics
    /// may be queried with [`get_buffer_attr()`] as soon as the callback is called. Only valid
    /// after the stream has been connected successfully. Please be aware of the slightly different
    /// semantics of the call depending whether [`FlagSet::ADJUST_LATENCY`] is set or not.
    ///
    /// The callback must accept a `bool`, which indicates success.
    ///
    /// Panics if the underlying C function returns a null pointer.
    ///
    /// [`get_buffer_attr()`]: Self::get_buffer_attr
    pub fn set_buffer_attr<F>(&mut self, attr: &def::BufferAttr, callback: F)
        -> Operation<dyn FnMut(bool)>
        where F: FnMut(bool) + 'static
    {
        let cb_data = box_closure_get_capi_ptr::<dyn FnMut(bool)>(Box::new(callback));
        let ptr = unsafe { capi::pa_stream_set_buffer_attr(self.ptr, attr.as_ref(),
            Some(success_cb_proxy), cb_data) };
        Operation::from_raw(ptr, cb_data as *mut Box<dyn FnMut(bool)>)
    }

    /// Changes the stream sampling rate during playback.
    ///
    /// You need to pass [`FlagSet::VARIABLE_RATE`] in the flags parameter of [`connect_playback()`]
    /// if you plan to use this function. Only valid after the stream has been connected
    /// successfully.
    ///
    /// The callback must accept a `bool`, which indicates success.
    ///
    /// Panics if the underlying C function returns a null pointer.
    ///
    /// [`connect_playback()`]: Self::connect_playback
    pub fn update_sample_rate<F>(&mut self, rate: u32, callback: F) -> Operation<dyn FnMut(bool)>
        where F: FnMut(bool) + 'static
    {
        let cb_data = box_closure_get_capi_ptr::<dyn FnMut(bool)>(Box::new(callback));
        let ptr = unsafe { capi::pa_stream_update_sample_rate(self.ptr, rate,
            Some(success_cb_proxy), cb_data) };
        Operation::from_raw(ptr, cb_data as *mut Box<dyn FnMut(bool)>)
    }

    /// Updates the property list of the sink input/source output of this stream, adding new
    /// entries.
    ///
    /// Please note that it is highly recommended to set as many properties initially via
    /// [`new_with_proplist()`] as possible instead a posteriori with this function, since that
    /// information may be used to route this stream to the right device.
    ///
    /// The callback must accept a `bool`, which indicates success.
    ///
    /// Panics if the underlying C function returns a null pointer.
    ///
    /// [`new_with_proplist()`]: Self::new_with_proplist
    pub fn update_proplist<F>(&mut self, mode: proplist::UpdateMode, proplist: &mut Proplist,
        callback: F) -> Operation<dyn FnMut(bool)>
        where F: FnMut(bool) + 'static
    {
        let cb_data = box_closure_get_capi_ptr::<dyn FnMut(bool)>(Box::new(callback));
        let ptr = unsafe { capi::pa_stream_proplist_update(self.ptr, mode, proplist.0.ptr,
            Some(success_cb_proxy), cb_data) };
        Operation::from_raw(ptr, cb_data as *mut Box<dyn FnMut(bool)>)
    }

    /// Updates the property list of the sink input/source output of this stream, removing entries.
    ///
    /// The callback must accept a `bool`, which indicates success.
    ///
    /// Panics if the underlying C function returns a null pointer.
    pub fn remove_proplist<F>(&mut self, keys: &[&str], callback: F) -> Operation<dyn FnMut(bool)>
        where F: FnMut(bool) + 'static
    {
        // Warning: New CStrings will be immediately freed if not bound to a variable, leading to
        // as_ptr() giving dangling pointers!
        let mut c_keys: Vec<CString> = Vec::with_capacity(keys.len());
        for key in keys {
            c_keys.push(CString::new(*key).unwrap());
        }

        // Capture array of pointers to the above CString values
        // We also add a null pointer entry on the end, as expected by the C function called here.
        let mut c_key_ptrs: Vec<*const c_char> = Vec::with_capacity(c_keys.len() + 1);
        for c_key in &c_keys {
            c_key_ptrs.push(c_key.as_ptr());
        }
        c_key_ptrs.push(null());

        let cb_data = box_closure_get_capi_ptr::<dyn FnMut(bool)>(Box::new(callback));
        let ptr = unsafe {
            capi::pa_stream_proplist_remove(self.ptr, c_key_ptrs.as_ptr(),
                Some(success_cb_proxy), cb_data)
        };
        Operation::from_raw(ptr, cb_data as *mut Box<dyn FnMut(bool)>)
    }

    /// For record streams connected to a monitor source: monitors only a very specific sink input
    /// of the sink.
    ///
    /// This function needs to be called before [`connect_record()`](Self::connect_record) is
    /// called.
    pub fn set_monitor_stream(&mut self, sink_input_index: u32) -> Result<(), PAErr> {
        match unsafe { capi::pa_stream_set_monitor_stream(self.ptr, sink_input_index) } {
            0 => Ok(()),
            e => Err(PAErr(e)),
        }
    }

    /// Gets the sink input index previously set with [`set_monitor_stream()`].
    ///
    /// [`set_monitor_stream()`]: Self::set_monitor_stream
    pub fn get_monitor_stream(&self) -> Option<u32> {
        match unsafe { capi::pa_stream_get_monitor_stream(self.ptr) } {
            def::INVALID_INDEX => None,
            r => Some(r),
        }
    }
}

impl Drop for Stream {
    fn drop(&mut self) {
        // Throw away the `Result` from disconnecting, it may legitimately be bad if stream failed.
        // See https://github.com/jnqnfe/pulse-binding-rust/issues/11
        let _ = self.disconnect();
        unsafe { capi::pa_stream_unref(self.ptr) };
        self.ptr = null_mut::<StreamInternal>();
    }
}

/// Proxy for completion success callbacks.
///
/// Warning: This is for single-use cases only! It destroys the actual closure callback.
extern "C"
fn success_cb_proxy(_: *mut StreamInternal, success: i32, userdata: *mut c_void) {
    let success_actual = match success { 0 => false, _ => true };
    let _ = std::panic::catch_unwind(|| {
        // Note, destroys closure callback after use - restoring outer box means it gets dropped
        let mut callback = get_su_callback::<dyn FnMut(bool)>(userdata);
        (callback)(success_actual);
    });
}

/// Proxy for request callbacks.
///
/// Warning: This is for multi-use cases! It does **not** destroy the actual closure callback, which
/// must be accomplished separately to avoid a memory leak.
extern "C"
fn request_cb_proxy(_: *mut StreamInternal, nbytes: usize, userdata: *mut c_void) {
    let _ = std::panic::catch_unwind(|| {
        let callback = RequestCb::get_callback(userdata);
        (callback)(nbytes);
    });
}

/// Proxy for notify callbacks.
///
/// Warning: This is for multi-use cases! It does **not** destroy the actual closure callback, which
/// must be accomplished separately to avoid a memory leak.
extern "C"
fn notify_cb_proxy(_: *mut StreamInternal, userdata: *mut c_void) {
    let _ = std::panic::catch_unwind(|| {
        let callback = NotifyCb::get_callback(userdata);
        (callback)();
    });
}

/// Proxy for event callbacks.
///
/// Warning: This is for multi-use cases! It does **not** destroy the actual closure callback, which
/// must be accomplished separately to avoid a memory leak.
extern "C"
fn event_cb_proxy(_: *mut StreamInternal, name: *const c_char, proplist: *mut ProplistInternal,
    userdata: *mut c_void)
{
    let _ = std::panic::catch_unwind(|| {
        assert!(!name.is_null());
        let n = {
            let tmp = unsafe { CStr::from_ptr(name) };
            tmp.to_string_lossy().into_owned()
        };
        let pl = Proplist::from_raw_weak(proplist);

        let callback = EventCb::get_callback(userdata);
        (callback)(n, pl);
    });
}
