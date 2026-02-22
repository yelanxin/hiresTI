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

//! Constants and routines for volume handling.
//!
//! # Overview
//!
//! Sinks, sources, sink inputs, source outputs and samples can all have their own volumes. To deal
//! with these, The PulseAudio library contains a number of functions that ease handling.
//!
//! The basic volume type in PulseAudio is the [`Volume`] type. Most of the time, applications will
//! use the aggregated [`ChannelVolumes`] structure that can store the volume of all channels at
//! once.
//!
//! Volumes commonly span between muted (0%), and normal (100%). It is possible to set volumes to
//! higher than 100%, but clipping might occur.
//!
//! There is no single well-defined meaning attached to the 100% volume for a sink input. In fact,
//! it depends on the server configuration. With flat volumes enabled, it means the maximum volume
//! that the sound hardware is capable of, which is usually so high that you absolutely must not set
//! sink input volume to 100% unless the user explicitly requests that (note that usually you
//! shouldn’t set the volume anyway if the user doesn’t explicitly request it, instead, let
//! PulseAudio decide the volume for the sink input). With flat volumes disabled the sink input
//! volume is relative to the sink volume, so 100% sink input volume means that the sink input is
//! played at the current sink volume level. In this case 100% is often a good default volume for a
//! sink input, although you still should let PulseAudio decide the default volume. It is possible
//! to figure out whether flat volume mode is in effect for a given sink by calling
//! [`Introspector::get_sink_info_by_name()`].
//!
//! # Calculations
//!
//! The [`Volume`]s in PulseAudio are cubic in nature and applications should not perform
//! calculations with them directly. Instead, they should be converted to and from either dB or a
//! linear scale.
//!
//! The [`VolumeDB`] type represents decibel (dB) converted values, and [`VolumeLinear`], linear.
//! The `From` trait has been implemented for your convenience, allowing such conversions.
//!
//! For simple multiplication, [`Volume::multiply()`] and [`ChannelVolumes::sw_multiply()`] can be
//! used.
//!
//! It’s often unknown what scale hardware volumes relate to. Don’t use the above functions on sink
//! and source volumes, unless the sink or source in question has the
//! [`SinkFlagSet::DECIBEL_VOLUME`] or [`SourceFlagSet::DECIBEL_VOLUME`] flag set. The conversion
//! functions are rarely needed anyway, most of the time it’s sufficient to treat all volumes as
//! opaque with a range from [`Volume::MUTED`] \(0%) to [`Volume::NORMAL`] \(100%).
//!
//! [`Introspector::get_sink_info_by_name()`]: crate::context::introspect::Introspector::get_sink_info_by_name
//! [`SinkFlagSet::DECIBEL_VOLUME`]: crate::def::SinkFlagSet::DECIBEL_VOLUME
//! [`SourceFlagSet::DECIBEL_VOLUME`]: crate::def::SourceFlagSet::DECIBEL_VOLUME

use std::borrow::{Borrow, BorrowMut};
use std::ffi::CStr;
use std::ptr::null;
use crate::sample;
use crate::channelmap::{Map, Position, PositionMask, POSITION_MASK_ALL};

/// Software volume expressed as an integer.
#[derive(Debug, Copy, Clone, PartialEq, Eq, PartialOrd, Ord)]
pub struct Volume(pub capi::pa_volume_t);

impl Default for Volume {
    fn default() -> Self {
        Self::NORMAL
    }
}

/// Software volume expressed in decibels (dBs).
#[derive(Debug, Copy, Clone, PartialEq, PartialOrd)]
pub struct VolumeDB(pub f64);

impl Default for VolumeDB {
    fn default() -> Self {
        VolumeDB(0.0)
    }
}

/// Software volume expressed as linear factor.
#[derive(Debug, Copy, Clone, PartialEq, PartialOrd)]
pub struct VolumeLinear(pub f64);

impl Default for VolumeLinear {
    fn default() -> Self {
        VolumeLinear(0.0)
    }
}

/// A structure encapsulating a per-channel volume
#[repr(C)]
#[derive(Debug, Copy, Clone, Default)]
pub struct ChannelVolumes {
    /* NOTE: This struct must be directly usable by the C API, thus same attributes/layout/etc */
    /// Number of channels.
    channels: u8,
    /// Per-channel volume.
    values: [Volume; Self::CHANNELS_MAX as usize],
}

/// Test size is equal to `sys` equivalent
#[test]
fn set_compare_capi() {
    assert_eq!(std::mem::size_of::<ChannelVolumes>(), std::mem::size_of::<capi::pa_cvolume>());
    assert_eq!(std::mem::align_of::<ChannelVolumes>(), std::mem::align_of::<capi::pa_cvolume>());
}

impl Borrow<[Volume]> for ChannelVolumes {
    fn borrow(&self) -> &[Volume] {
        &self.values[..self.channels as usize]
    }
}

impl BorrowMut<[Volume]> for ChannelVolumes {
    fn borrow_mut(&mut self) -> &mut [Volume] {
        &mut self.values[..self.channels as usize]
    }
}

impl AsRef<capi::pa_cvolume> for ChannelVolumes {
    #[inline]
    fn as_ref(&self) -> &capi::pa_cvolume {
        unsafe { &*(self as *const Self as *const capi::pa_cvolume) }
    }
}
impl AsMut<capi::pa_cvolume> for ChannelVolumes {
    #[inline]
    fn as_mut(&mut self) -> &mut capi::pa_cvolume {
        unsafe { &mut *(self as *mut Self as *mut capi::pa_cvolume) }
    }
}

impl From<capi::pa_cvolume> for ChannelVolumes {
    #[inline]
    fn from(cv: capi::pa_cvolume) -> Self {
        unsafe { std::mem::transmute(cv) }
    }
}

impl PartialEq for ChannelVolumes {
    #[inline]
    fn eq(&self, other: &Self) -> bool {
        unsafe { capi::pa_cvolume_equal(self.as_ref(), other.as_ref()) != 0 }
    }
}

impl PartialEq<Volume> for ChannelVolumes {
    /// Returns `true` if the volume of all channels are equal to the specified value.
    #[inline]
    fn eq(&self, v: &Volume) -> bool {
        unsafe { capi::pa_cvolume_channels_equal_to(self.as_ref(), v.0) != 0 }
    }
}

/// Converts a decibel value to a volume (amplitude, not power).
///
/// This is only valid for software volumes!
impl From<VolumeDB> for Volume {
    #[inline]
    fn from(v: VolumeDB) -> Self {
        Volume(unsafe { capi::pa_sw_volume_from_dB(v.0) })
    }
}
/// Converts a volume to a decibel value (amplitude, not power).
///
/// This is only valid for software volumes!
impl From<Volume> for VolumeDB {
    #[inline]
    fn from(v: Volume) -> Self {
        VolumeDB(unsafe { capi::pa_sw_volume_to_dB(v.0) })
    }
}

/// Converts a linear factor to a volume.
///
/// `0.0` and less is muted while `1.0` is [`Volume::NORMAL`].
///
/// This is only valid for software volumes!
///
/// [`Volume::NORMAL`]: struct.Volume.html#associatedconstant.NORMAL
impl From<VolumeLinear> for Volume {
    #[inline]
    fn from(v: VolumeLinear) -> Self {
        Volume(unsafe { capi::pa_sw_volume_from_linear(v.0) })
    }
}
/// Converts a volume to a linear factor.
///
/// This is only valid for software volumes!
impl From<Volume> for VolumeLinear {
    #[inline]
    fn from(v: Volume) -> Self {
        VolumeLinear(unsafe { capi::pa_sw_volume_to_linear(v.0) })
    }
}

/// Converts a linear factor to a decibel value (amplitude, not power).
///
/// `0.0` and less is muted while `1.0` is [`Volume::NORMAL`].
///
/// This is only valid for software volumes!
///
/// [`Volume::NORMAL`]: struct.Volume.html#associatedconstant.NORMAL
impl From<VolumeLinear> for VolumeDB {
    #[inline]
    fn from(v: VolumeLinear) -> Self {
        VolumeDB::from(Volume::from(v))
    }
}
/// Converts a decibel value (amplitude, not power) to a linear factor.
///
/// This is only valid for software volumes!
impl From<VolumeDB> for VolumeLinear {
    #[inline]
    fn from(v: VolumeDB) -> Self {
        VolumeLinear::from(Volume::from(v))
    }
}

impl VolumeLinear {
    /// Is a muted volume level.
    #[inline]
    pub fn is_muted(&self) -> bool {
        self.0 <= 0.0
    }

    /// Is a “normal” volume level.
    #[inline]
    pub fn is_normal(&self) -> bool {
        self.0 == 1.0
    }
}

impl Volume {
    /// A “normal” volume level.
    pub const NORMAL:  Self = Self(capi::PA_VOLUME_NORM);
    /// A muted volume level.
    pub const MUTED:   Self = Self(capi::PA_VOLUME_MUTED);
    /// A maximum volume level.
    pub const MAX:     Self = Self(capi::PA_VOLUME_MAX);
    /// An invalid volume level.
    pub const INVALID: Self = Self(capi::PA_VOLUME_INVALID);

    /// Is a muted volume level.
    #[inline]
    pub fn is_muted(&self) -> bool {
        *self == Self::MUTED
    }

    /// Is a “normal” volume level.
    #[inline]
    pub fn is_normal(&self) -> bool {
        *self == Self::NORMAL
    }

    /// Is a maximum volume level.
    #[inline]
    pub fn is_max(&self) -> bool {
        *self == Self::MAX
    }

    /// Get the recommended maximum volume to show in user facing UIs.
    ///
    /// Note: UIs should deal gracefully with volumes greater than this value and not cause feedback
    /// loops etc. - i.e. if the volume is more than this, the UI should not limit it and push the
    /// limited value back to the server.
    #[inline]
    pub fn ui_max() -> Self {
        Volume(capi::pa_volume_ui_max())
    }

    /// Checks if volume is valid.
    #[inline]
    pub const fn is_valid(&self) -> bool {
        capi::pa_volume_is_valid(self.0)
    }

    /// Clamps volume to the permitted range.
    #[inline]
    pub fn clamp(&mut self) {
        self.0 = capi::pa_clamp_volume(self.0)
    }

    /// Multiplies two software volumes, returning the result.
    ///
    /// This uses [`Volume::NORMAL`] as neutral element of multiplication.
    ///
    /// This is only valid for software volumes!
    ///
    /// [`Volume::NORMAL`]: struct.Volume.html#associatedconstant.NORMAL
    #[inline]
    pub fn multiply(a: Self, b: Self) -> Self {
        Volume(unsafe { capi::pa_sw_volume_multiply(a.0, b.0) })
    }

    /// Divides two software volumes, returning the result.
    ///
    /// This uses [`Volume::NORMAL`] as neutral element of division. If a division by zero is tried
    /// the result will be `0`.
    ///
    /// This is only valid for software volumes!
    ///
    /// [`Volume::NORMAL`]: struct.Volume.html#associatedconstant.NORMAL
    #[inline]
    pub fn divide(a: Self, b: Self) -> Self {
        Volume(unsafe { capi::pa_sw_volume_divide(a.0, b.0) })
    }

    /// Pretty prints a volume.
    pub fn print(&self) -> String {
        const PRINT_MAX: usize = capi::PA_VOLUME_SNPRINT_MAX;
        let mut tmp = Vec::with_capacity(PRINT_MAX);
        unsafe {
            capi::pa_volume_snprint(tmp.as_mut_ptr(), PRINT_MAX, self.0);
            CStr::from_ptr(tmp.as_mut_ptr()).to_string_lossy().into_owned()
        }
    }

    /// Pretty prints a volume but showing dB values.
    pub fn print_db(&self) -> String {
        const PRINT_DB_MAX: usize = capi::PA_SW_VOLUME_SNPRINT_DB_MAX;
        let mut tmp = Vec::with_capacity(PRINT_DB_MAX);
        unsafe {
            capi::pa_sw_volume_snprint_dB(tmp.as_mut_ptr(), PRINT_DB_MAX, self.0);
            CStr::from_ptr(tmp.as_mut_ptr()).to_string_lossy().into_owned()
        }
    }

    /// Pretty prints a volume in a verbose way.
    ///
    /// The volume is printed in several formats: the raw volume value, percentage, and if
    /// `print_db` is true, also the dB value.
    pub fn print_verbose(&self, print_db: bool) -> String {
        const PRINT_VERBOSE_MAX: usize = capi::PA_VOLUME_SNPRINT_VERBOSE_MAX;
        let mut tmp = Vec::with_capacity(PRINT_VERBOSE_MAX);
        unsafe {
            capi::pa_volume_snprint_verbose(tmp.as_mut_ptr(), PRINT_VERBOSE_MAX, self.0,
                print_db as i32);
            CStr::from_ptr(tmp.as_mut_ptr()).to_string_lossy().into_owned()
        }
    }
}

impl std::fmt::Display for Volume {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        write!(f, "{}", &self.print())
    }
}

impl VolumeDB {
    /// Minus Infinity.
    ///
    /// This floor value is used / can be used, when using converting between integer software
    /// volume and decibel (dB, floating point) software volume.
    pub const MINUS_INFINITY: Self = Self(capi::PA_DECIBEL_MININFTY);
}

impl ChannelVolumes {
    /// Maximum number of allowed channels.
    pub const CHANNELS_MAX: u8 = capi::PA_CHANNELS_MAX;

    /// Initializes the specified volume and return a pointer to it.
    ///
    /// The sample spec will have a defined state but [`is_valid()`](Self::is_valid) will fail for
    /// it.
    #[inline]
    pub fn init(&mut self) -> &Self {
        unsafe { capi::pa_cvolume_init(self.as_mut()) };
        self
    }

    /// Checks if the `ChannelVolumes` structure is valid.
    #[inline]
    pub fn is_valid(&self) -> bool {
        unsafe { capi::pa_cvolume_valid(self.as_ref()) != 0 }
    }

    /// Gets the number of active channels.
    #[inline]
    pub fn len(&self) -> u8 {
        self.channels
    }

    /// Sets the number of active channels.
    ///
    /// Volumes for up to [`Self::CHANNELS_MAX`] channels can be held. This sets the portion of
    /// the internal array considered “active” and thus available for reading/writing (i.e. when
    /// borrowing `self` as a slice).
    ///
    /// **Panics** if the number of channels specified is greater than [`Self::CHANNELS_MAX`].
    #[inline]
    pub fn set_len(&mut self, channels: u8) {
        assert!(channels <= Self::CHANNELS_MAX);
        self.channels = channels;
    }

    /// Gets an immutable slice of the set of “active” channels.
    #[inline]
    pub fn get(&self) -> &[Volume] {
        self.borrow()
    }

    /// Gets a mutable slice of the set of “active” channels.
    #[inline]
    pub fn get_mut(&mut self) -> &mut [Volume] {
        self.borrow_mut()
    }

    /// Sets the volume of the specified number of channels to the supplied volume.
    #[inline]
    pub fn set(&mut self, channels: u8, v: Volume) -> &Self {
        unsafe { capi::pa_cvolume_set(self.as_mut(), channels as u32, v.0) };
        self
    }

    /// Sets the volume of the first n channels to [`Volume::NORMAL`].
    #[inline]
    pub fn reset(&mut self, channels: u8) -> &Self {
        self.set(channels, Volume::NORMAL)
    }

    /// Sets the volume of the first n channels to [`Volume::MUTED`].
    #[inline]
    pub fn mute(&mut self, channels: u8) -> &Self {
        self.set(channels, Volume::MUTED)
    }

    /// Checks if all channels are muted.
    #[inline]
    pub fn is_muted(&self) -> bool {
        self.eq(&Volume::MUTED)
    }

    /// Checks if all channels are at normal volume level.
    #[inline]
    pub fn is_norm(&self) -> bool {
        self.eq(&Volume::NORMAL)
    }

    /// Gets the average volume of all channels.
    #[inline]
    pub fn avg(&self) -> Volume {
        Volume(unsafe { capi::pa_cvolume_avg(self.as_ref()) })
    }

    /// Returns the average volume of all channels that are included in the specified channel map
    /// with the specified channel position mask.
    ///
    /// If no channel is selected the returned value will be [`Volume::MUTED`]. If `mask` is `None`,
    /// has the same effect as passing [`POSITION_MASK_ALL`].
    #[inline]
    pub fn avg_mask(&self, cm: &Map, mask: Option<PositionMask>) -> Volume {
        let mask_actual = mask.unwrap_or(POSITION_MASK_ALL);
        Volume(unsafe { capi::pa_cvolume_avg_mask(self.as_ref(), cm.as_ref(), mask_actual) })
    }

    /// Gets the maximum volume of all channels.
    #[inline]
    pub fn max(&self) -> Volume {
        Volume(unsafe { capi::pa_cvolume_max(self.as_ref()) })
    }

    /// Gets the maximum volume of all channels that are included in the specified channel map
    /// with the specified channel position mask.
    ///
    /// If no channel is selected the returned value will be [`Volume::MUTED`]. If `mask` is `None`,
    /// has the same effect as passing [`POSITION_MASK_ALL`].
    #[inline]
    pub fn max_mask(&self, cm: &Map, mask: Option<PositionMask>) -> Volume {
        let mask_actual = mask.unwrap_or(POSITION_MASK_ALL);
        Volume(unsafe { capi::pa_cvolume_max_mask(self.as_ref(), cm.as_ref(), mask_actual) })
    }

    /// Gets the minimum volume of all channels.
    #[inline]
    pub fn min(&self) -> Volume {
        Volume(unsafe { capi::pa_cvolume_min(self.as_ref()) })
    }

    /// Gets the minimum volume of all channels that are included in the specified channel map
    /// with the specified channel position mask.
    ///
    /// If no channel is selected the returned value will be [`Volume::MUTED`]. If `mask` is `None`,
    /// has the same effect as passing [`POSITION_MASK_ALL`].
    #[inline]
    pub fn min_mask(&self, cm: &Map, mask: Option<PositionMask>) -> Volume {
        let mask_actual = mask.unwrap_or(POSITION_MASK_ALL);
        Volume(unsafe { capi::pa_cvolume_min_mask(self.as_ref(), cm.as_ref(), mask_actual) })
    }

    /// Multiplies two per-channel volumes.
    ///
    /// If `with` is `None`, multiplies with itself. This is only valid for software volumes!
    /// Returns pointer to self.
    #[inline]
    pub fn sw_multiply(&mut self, with: Option<&Self>) -> &mut Self {
        unsafe { capi::pa_sw_cvolume_multiply(self.as_mut(), self.as_mut(),
            with.unwrap_or(self).as_ref()) };
        self
    }

    /// Multiplies a per-channel volume with a scalar volume.
    ///
    /// This is only valid for software volumes! Returns pointer to self.
    #[inline]
    pub fn sw_multiply_scalar(&mut self, with: Volume) -> &mut Self {
        unsafe { capi::pa_sw_cvolume_multiply_scalar(self.as_mut(), self.as_ref(), with.0) };
        self
    }

    /// Divides two per-channel volumes.
    ///
    /// If `with` is `None`, divides with itself. This is only valid for software volumes! Returns
    /// pointer to self.
    #[inline]
    pub fn sw_divide(&mut self, with: Option<&Self>) -> &mut Self {
        unsafe { capi::pa_sw_cvolume_divide(self.as_mut(), self.as_mut(),
            with.unwrap_or(self).as_ref()) };
        self
    }

    /// Divides a per-channel volume by a scalar volume.
    ///
    /// This is only valid for software volumes! Returns pointer to self.
    #[inline]
    pub fn sw_divide_scalar(&mut self, with: Volume) -> &mut Self {
        unsafe { capi::pa_sw_cvolume_divide_scalar(self.as_mut(), self.as_ref(), with.0) };
        self
    }

    /// Remaps a volume from one channel mapping to a different channel mapping.
    ///
    /// Returns pointer to self.
    #[inline]
    pub fn remap(&mut self, from: &Map, to: &Map) -> &mut Self {
        unsafe { capi::pa_cvolume_remap(self.as_mut(), from.as_ref(), to.as_ref()) };
        self
    }

    /// Checks if the specified volume is compatible with the specified sample spec.
    #[inline]
    pub fn is_compatible_with_ss(&self, ss: &sample::Spec) -> bool {
        unsafe { capi::pa_cvolume_compatible(self.as_ref(), ss.as_ref()) != 0 }
    }

    /// Checks if the specified volume is compatible with the specified channel map.
    #[inline]
    pub fn is_compatible_with_cm(&self, cm: &Map) -> bool {
        unsafe { capi::pa_cvolume_compatible_with_channel_map(self.as_ref(), cm.as_ref()) != 0 }
    }

    /// Calculates a ‘balance’ value for the specified volume with the specified channel map.
    ///
    /// The return value will range from `-1.0` (left) to `+1.0` (right). If no balance value is
    /// applicable to this channel map the return value will always be `0.0`. See
    /// [`Map::can_balance()`].
    #[inline]
    pub fn get_balance(&self, map: &Map) -> f32 {
        unsafe { capi::pa_cvolume_get_balance(self.as_ref(), map.as_ref()) }
    }

    /// Adjusts the ‘balance’ value for the specified volume with the specified channel map.
    ///
    /// The balance is a value between `-1.0` and `+1.0`. This operation might not be reversible!
    /// Also, after this call [`get_balance()`](Self::get_balance) is not guaranteed to actually
    /// return the requested balance value (e.g. when the input volume was zero anyway for all
    /// channels). If no balance value is applicable to this channel map the volume will not be
    /// modified. See [`Map::can_balance()`].
    ///
    /// Returns pointer to self, or `None` on error.
    #[inline]
    pub fn set_balance(&mut self, map: &Map, new_balance: f32) -> Option<&mut Self> {
        let ptr = unsafe { capi::pa_cvolume_set_balance(self.as_mut(), map.as_ref(), new_balance) };
        match ptr.is_null() {
            false => Some(self),
            true => None,
        }
    }

    /// Calculates a ‘fade’ value (i.e. ‘balance’ between front and rear) for the specified volume
    /// with the specified channel map.
    ///
    /// The return value will range from -1.0f (rear) to +1.0f (left). If no fade value is
    /// applicable to this channel map the return value will always be `0.0`. See
    /// [`Map::can_fade()`].
    #[inline]
    pub fn get_fade(&self, map: &Map) -> f32 {
        unsafe { capi::pa_cvolume_get_fade(self.as_ref(), map.as_ref()) }
    }

    /// Adjusts the ‘fade’ value (i.e. ‘balance’ between front and rear) for the specified volume
    /// with the specified channel map.
    ///
    /// The balance is a value between `-1.0` and `+1.0`. This operation might not be reversible!
    /// Also, after this call [`get_fade()`](Self::get_fade) is not guaranteed to actually return
    /// the requested fade value (e.g. when the input volume was zero anyway for all channels). If
    /// no fade value is applicable to this channel map the volume will not be modified. See
    /// [`Map::can_fade()`].
    ///
    /// Returns pointer to self, or `None` on error.
    #[inline]
    pub fn set_fade(&mut self, map: &Map, new_fade: f32) -> Option<&mut Self> {
        let ptr = unsafe { capi::pa_cvolume_set_fade(self.as_mut(), map.as_ref(), new_fade) };
        match ptr.is_null() {
            false => Some(self),
            true => None,
        }
    }

    /// Calculates a ‘lfe balance’ value for the specified volume with the specified channel map.
    ///
    /// The return value will range from `-1.0` (no lfe) to `+1.0` (only lfe), where `0.0` is
    /// balanced. If no value is applicable to this channel map the return value will always be
    /// `0.0`. See [`Map::can_lfe_balance()`].
    #[inline]
    #[cfg(any(doc, feature = "pa_v8"))]
    #[cfg_attr(docsrs, doc(cfg(feature = "pa_v8")))]
    pub fn get_lfe_balance(&self, map: &Map) -> f32 {
        unsafe { capi::pa_cvolume_get_lfe_balance(self.as_ref(), map.as_ref()) }
    }

    /// Adjusts the ‘LFE balance’ value for the specified volume with the specified channel map.
    ///
    /// The balance is a value between `-1.0` (no lfe) and `+1.0` (only lfe). This operation might
    /// not be reversible! Also, after this call [`get_lfe_balance()`] is not guaranteed to actually
    /// return the requested value (e.g. when the input volume was zero anyway for all channels). If
    /// no lfe balance value is applicable to this channel map the volume will not be modified. See
    /// [`Map::can_lfe_balance()`].
    ///
    /// Returns pointer to self, or `None` on error.
    ///
    /// [`get_lfe_balance()`]: Self::get_lfe_balance
    #[inline]
    #[cfg(any(doc, feature = "pa_v8"))]
    #[cfg_attr(docsrs, doc(cfg(feature = "pa_v8")))]
    pub fn set_lfe_balance(&mut self, map: &Map, new_balance: f32) -> Option<&mut Self> {
        let ptr =
            unsafe { capi::pa_cvolume_set_lfe_balance(self.as_mut(), map.as_ref(), new_balance) };
        match ptr.is_null() {
            false => Some(self),
            true => None,
        }
    }

    /// Scales so that the maximum volume of all channels equals `max`.
    ///
    /// The proportions between the channel volumes are kept.
    ///
    /// Returns pointer to self, or `None` on error.
    #[inline]
    pub fn scale(&mut self, max: Volume) -> Option<&mut Self> {
        let ptr = unsafe { capi::pa_cvolume_scale(self.as_mut(), max.0) };
        match ptr.is_null() {
            false => Some(self),
            true => None,
        }
    }

    /// Scales so that the maximum volume of all channels selected via `cm`/`mask` equals `max`.
    ///
    /// This also modifies the volume of those channels that are unmasked. The proportions between
    /// the channel volumes are kept.
    ///
    /// If `mask` is `None`, has the same effect as passing [`POSITION_MASK_ALL`].
    ///
    /// Returns pointer to self, or `None` on error.
    #[inline]
    pub fn scale_mask(&mut self, max: Volume, cm: &mut Map, mask: Option<PositionMask>)
        -> Option<&mut Self>
    {
        let mask_actual = mask.unwrap_or(POSITION_MASK_ALL);
        let ptr =
            unsafe { capi::pa_cvolume_scale_mask(self.as_mut(), max.0, cm.as_ref(), mask_actual) };
        match ptr.is_null() {
            false => Some(self),
            true => None,
        }
    }

    /// Sets the passed volume to all channels at the specified channel position.
    ///
    /// Returns `None` if either invalid data was provided, or if there is no channel at the
    /// position specified. You can check if a channel map includes a specific position by calling
    /// [`Map::has_position()`]. On success, returns pointer to self.
    #[inline]
    pub fn set_position(&mut self, map: &Map, p: Position, v: Volume) -> Option<&mut Self> {
        // Note: C function returns NULL on invalid data or no channel at position specified (no
        // change needed). We could ignore failure and always return self ptr, but it does not seem
        // ideal to leave callers unaware should they be passing in invalid data.
        let ptr =
            unsafe { capi::pa_cvolume_set_position(self.as_mut(), map.as_ref(), p.into(), v.0) };
        match ptr.is_null() {
            false => Some(self),
            true => None,
        }
    }

    /// Gets the maximum volume of all channels at the specified channel position.
    ///
    /// Will return `0` if there is no channel at the position specified. You can check if a channel
    /// map includes a specific position by calling [`Map::has_position()`].
    #[inline]
    pub fn get_position(&self, map: &Map, p: Position) -> Volume {
        Volume(unsafe { capi::pa_cvolume_get_position(self.as_ref(), map.as_ref(), p.into()) })
    }

    /// Merges one set of channel volumes with another.
    ///
    /// The channel count is set to the minimum between that of self and that of `with`. Only this
    /// number of channels are processed. For each channel processed, volume is set to the greatest
    /// of the values from self and from `with`. I.e if one set has three channels and the other has
    /// two, the number of channels will be set to two, and only the first two channels will be
    /// compared, with the greatest values of these two channels being stored. The third channel in
    /// the one set will be ignored.
    ///
    /// Returns pointer to self, or `None` on error.
    #[inline]
    pub fn merge(&mut self, with: &Self) -> Option<&mut Self> {
        let ptr = unsafe { capi::pa_cvolume_merge(self.as_mut(), self.as_ref(), with.as_ref()) };
        match ptr.is_null() {
            false => Some(self),
            true => None,
        }
    }

    /// Increases the volume passed in by `inc`, but not exceeding `limit`.
    ///
    /// The proportions between the channels are kept.
    ///
    /// Returns pointer to self, or `None` on error.
    #[inline]
    pub fn inc_clamp(&mut self, inc: Volume, limit: Volume) -> Option<&mut Self> {
        let ptr = unsafe { capi::pa_cvolume_inc_clamp(self.as_mut(), inc.0, limit.0) };
        match ptr.is_null() {
            false => Some(self),
            true => None,
        }
    }

    /// Increases the volume passed in by `inc`.
    ///
    /// The proportions between the channels are kept.
    ///
    /// Returns pointer to self, or `None` on error.
    #[inline]
    pub fn increase(&mut self, inc: Volume) -> Option<&mut Self> {
        let ptr = unsafe { capi::pa_cvolume_inc(self.as_mut(), inc.0) };
        match ptr.is_null() {
            false => Some(self),
            true => None,
        }
    }

    /// Decreases the volume passed in by `dec`.
    ///
    /// The proportions between the channels are kept.
    ///
    /// Returns pointer to self, or `None` on error.
    #[inline]
    pub fn decrease(&mut self, dec: Volume) -> Option<&mut Self> {
        let ptr = unsafe { capi::pa_cvolume_dec(self.as_mut(), dec.0) };
        match ptr.is_null() {
            false => Some(self),
            true => None,
        }
    }

    /// Pretty prints a volume structure.
    pub fn print(&self) -> String {
        const PRINT_MAX: usize = capi::PA_CVOLUME_SNPRINT_MAX;
        let mut tmp = Vec::with_capacity(PRINT_MAX);
        unsafe {
            capi::pa_cvolume_snprint(tmp.as_mut_ptr(), PRINT_MAX, self.as_ref());
            CStr::from_ptr(tmp.as_mut_ptr()).to_string_lossy().into_owned()
        }
    }

    /// Pretty prints a volume structure but show dB values.
    pub fn print_db(&self) -> String {
        const PRINT_DB_MAX: usize = capi::PA_SW_CVOLUME_SNPRINT_DB_MAX;
        let mut tmp = Vec::with_capacity(PRINT_DB_MAX);
        unsafe {
            capi::pa_sw_cvolume_snprint_dB(tmp.as_mut_ptr(), PRINT_DB_MAX, self.as_ref());
            CStr::from_ptr(tmp.as_mut_ptr()).to_string_lossy().into_owned()
        }
    }

    /// Pretty prints a volume structure in a verbose way.
    ///
    /// The volume for each channel is printed in several formats: the raw volume value,
    /// percentage, and if `print_db` is non-zero, also the dB value. If `map` is provided, the
    /// channel names will be printed.
    pub fn print_verbose(&self, map: Option<&Map>, print_db: bool) -> String {
        const PRINT_VERBOSE_MAX: usize = capi::PA_CVOLUME_SNPRINT_VERBOSE_MAX;

        let p_map = map.map_or(null::<capi::pa_channel_map>(), |m| m.as_ref());

        let mut tmp = Vec::with_capacity(PRINT_VERBOSE_MAX);
        unsafe {
            capi::pa_cvolume_snprint_verbose(tmp.as_mut_ptr(), PRINT_VERBOSE_MAX, self.as_ref(),
                p_map, print_db as i32);
            CStr::from_ptr(tmp.as_mut_ptr()).to_string_lossy().into_owned()
        }
    }
}

impl std::fmt::Display for ChannelVolumes {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        write!(f, "{}", &self.print())
    }
}
