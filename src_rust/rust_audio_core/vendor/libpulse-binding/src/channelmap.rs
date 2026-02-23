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

//! Constants and routines for handing channel mapping.
//!
//! # Overview
//!
//! Channel maps provide a way to associate channels in a stream with a specific speaker position.
//! This relieves applications of having to make sure their channel order is identical to the final
//! output.
//!
//! # Initialisation
//!
//! A channel map consists of an array of [`Position`] values, one for each channel. This array is
//! stored together with a channel count in a [`Map`] structure.
//!
//! Before filling the structure, the application must initialise it using [`Map::init()`]. There
//! are also a number of convenience functions for standard channel mappings:
//!
//! * [`Map::init_mono()`]: Create a channel map with only mono audio.
//! * [`Map::init_stereo()`]: Create a standard stereo mapping.
//! * [`Map::init_auto()`]: Create a standard channel map for a specific number of channels.
//! * [`Map::init_extend()`]: Similar to [`Map::init_auto()`] but synthesize a channel map if no
//!   predefined one is known for the specified number of channels.

use std::borrow::{Borrow, BorrowMut};
use std::ffi::{CStr, CString};
use std::borrow::Cow;
use num_derive::{FromPrimitive, ToPrimitive};
use crate::sample;

pub use capi::pa_channel_map_def_t as MapDef;

/// A mask of channel positions.
pub type PositionMask = capi::channelmap::pa_channel_position_mask_t;

/// Position mask covering all positions.
pub const POSITION_MASK_ALL: PositionMask = 0xffffffffffffffffu64;

/// A list of channel labels.
///
/// Note, certain aliases, specifically `Left`, `Right`, `Center` and `Subwoofer`, available in the
/// equivalent C enum are not provided here, since Rust does not allow aliases.
#[repr(C)]
#[derive(Debug, Default, Copy, Clone, PartialEq, Eq)]
#[derive(FromPrimitive, ToPrimitive)]
pub enum Position {
    /* NOTE: This enum’s variants and variant values **must** remain identical to the `sys` crate
       (C API) equivalent */

    /// Invalid.
    #[default]
    Invalid = -1,

    /// Mono.
    Mono = 0,

    /// Apple, Dolby call this ‘Left’.
    FrontLeft,
    /// Apple, Dolby call this ‘Right’.
    FrontRight,
    /// Apple, Dolby call this ‘Center’.
    FrontCenter,

    /// Microsoft calls this ‘Back Center’, Apple calls this ‘Center Surround’,
    /// Dolby calls this ‘Surround Rear Center’.
    RearCenter,
    /// Microsoft calls this ‘Back Left’, Apple calls this ‘Left Surround’,
    /// Dolby calls this ‘Surround Rear Left’.
    RearLeft,
    /// Microsoft calls this ‘Back Right’, Apple calls this ‘Right Surround’,
    /// Dolby calls this ‘Surround Rear Right’.
    RearRight,

    /// Aka subwoofer. Microsoft calls this ‘Low Frequency’,
    /// Apple calls this ‘LFEScreen’.
    Lfe,

    /// Apple, Dolby call this ‘Left Center’.
    FrontLeftOfCenter,
    /// Apple, Dolby call this ‘Right Center’.
    FrontRightOfCenter,

    /// Apple calls this ‘Left Surround Direct’,
    /// Dolby calls this ‘Surround Left’.
    SideLeft,
    /// Apple calls this ‘Right Surround Direct’,
    /// Dolby calls this ‘Surround Right’.
    SideRight,

    /// Auxillary 0.
    Aux0,
    /// Auxillary 1.
    Aux1,
    /// Auxillary 2.
    Aux2,
    /// Auxillary 3.
    Aux3,
    /// Auxillary 4.
    Aux4,
    /// Auxillary 5.
    Aux5,
    /// Auxillary 6.
    Aux6,
    /// Auxillary 7.
    Aux7,
    /// Auxillary 8.
    Aux8,
    /// Auxillary 9.
    Aux9,
    /// Auxillary 10.
    Aux10,
    /// Auxillary 11.
    Aux11,
    /// Auxillary 12.
    Aux12,
    /// Auxillary 13.
    Aux13,
    /// Auxillary 14.
    Aux14,
    /// Auxillary 15.
    Aux15,
    /// Auxillary 16.
    Aux16,
    /// Auxillary 17.
    Aux17,
    /// Auxillary 18.
    Aux18,
    /// Auxillary 19.
    Aux19,
    /// Auxillary 20.
    Aux20,
    /// Auxillary 21.
    Aux21,
    /// Auxillary 22.
    Aux22,
    /// Auxillary 23.
    Aux23,
    /// Auxillary 24.
    Aux24,
    /// Auxillary 25.
    Aux25,
    /// Auxillary 26.
    Aux26,
    /// Auxillary 27.
    Aux27,
    /// Auxillary 28.
    Aux28,
    /// Auxillary 29.
    Aux29,
    /// Auxillary 30.
    Aux30,
    /// Auxillary 31.
    Aux31,

    /// Apple calls this ‘Top Center Surround’.
    TopCenter,

    /// Apple calls this ‘Vertical Height Left’.
    TopFrontLeft,
    /// Apple calls this ‘Vertical Height Right’.
    TopFrontRight,
    /// Apple calls this ‘Vertical Height Center’.
    TopFrontCenter,

    /// Microsoft and Apple call this ‘Top Back Left’.
    TopRearLeft,
    /// Microsoft and Apple call this ‘Top Back Right’.
    TopRearRight,
    /// Microsoft and Apple call this ‘Top Back Center’.
    TopRearCenter,
}

/// Check is equal to `sys` equivalent
#[test]
fn pos_compare_capi() {
    assert_eq!(std::mem::size_of::<Position>(), std::mem::size_of::<capi::pa_channel_position_t>());
    assert_eq!(std::mem::align_of::<Position>(), std::mem::align_of::<capi::pa_channel_position_t>());

    // Check order and value of variants match
    // No point checking conversions in both directions since both are a transmute
    assert_eq!(Position::Invalid,            Position::from(capi::pa_channel_position_t::Invalid));
    assert_eq!(Position::Mono,               Position::from(capi::pa_channel_position_t::Mono));
    assert_eq!(Position::FrontLeft,          Position::from(capi::pa_channel_position_t::FrontLeft));
    assert_eq!(Position::FrontRight,         Position::from(capi::pa_channel_position_t::FrontRight));
    assert_eq!(Position::FrontCenter,        Position::from(capi::pa_channel_position_t::FrontCenter));
    assert_eq!(Position::RearCenter,         Position::from(capi::pa_channel_position_t::RearCenter));
    assert_eq!(Position::RearLeft,           Position::from(capi::pa_channel_position_t::RearLeft));
    assert_eq!(Position::RearRight,          Position::from(capi::pa_channel_position_t::RearRight));
    assert_eq!(Position::Lfe,                Position::from(capi::pa_channel_position_t::Lfe));
    assert_eq!(Position::FrontLeftOfCenter,  Position::from(capi::pa_channel_position_t::FrontLeftOfCenter));
    assert_eq!(Position::FrontRightOfCenter, Position::from(capi::pa_channel_position_t::FrontRightOfCenter));
    assert_eq!(Position::SideLeft,           Position::from(capi::pa_channel_position_t::SideLeft));
    assert_eq!(Position::SideRight,          Position::from(capi::pa_channel_position_t::SideRight));
    assert_eq!(Position::Aux0,               Position::from(capi::pa_channel_position_t::Aux0));
    assert_eq!(Position::Aux1,               Position::from(capi::pa_channel_position_t::Aux1));
    assert_eq!(Position::Aux2,               Position::from(capi::pa_channel_position_t::Aux2));
    assert_eq!(Position::Aux3,               Position::from(capi::pa_channel_position_t::Aux3));
    assert_eq!(Position::Aux4,               Position::from(capi::pa_channel_position_t::Aux4));
    assert_eq!(Position::Aux5,               Position::from(capi::pa_channel_position_t::Aux5));
    assert_eq!(Position::Aux6,               Position::from(capi::pa_channel_position_t::Aux6));
    assert_eq!(Position::Aux7,               Position::from(capi::pa_channel_position_t::Aux7));
    assert_eq!(Position::Aux8,               Position::from(capi::pa_channel_position_t::Aux8));
    assert_eq!(Position::Aux9,               Position::from(capi::pa_channel_position_t::Aux9));
    assert_eq!(Position::Aux10,              Position::from(capi::pa_channel_position_t::Aux10));
    assert_eq!(Position::Aux11,              Position::from(capi::pa_channel_position_t::Aux11));
    assert_eq!(Position::Aux12,              Position::from(capi::pa_channel_position_t::Aux12));
    assert_eq!(Position::Aux13,              Position::from(capi::pa_channel_position_t::Aux13));
    assert_eq!(Position::Aux14,              Position::from(capi::pa_channel_position_t::Aux14));
    assert_eq!(Position::Aux15,              Position::from(capi::pa_channel_position_t::Aux15));
    assert_eq!(Position::Aux16,              Position::from(capi::pa_channel_position_t::Aux16));
    assert_eq!(Position::Aux17,              Position::from(capi::pa_channel_position_t::Aux17));
    assert_eq!(Position::Aux18,              Position::from(capi::pa_channel_position_t::Aux18));
    assert_eq!(Position::Aux19,              Position::from(capi::pa_channel_position_t::Aux19));
    assert_eq!(Position::Aux20,              Position::from(capi::pa_channel_position_t::Aux20));
    assert_eq!(Position::Aux21,              Position::from(capi::pa_channel_position_t::Aux21));
    assert_eq!(Position::Aux22,              Position::from(capi::pa_channel_position_t::Aux22));
    assert_eq!(Position::Aux23,              Position::from(capi::pa_channel_position_t::Aux23));
    assert_eq!(Position::Aux24,              Position::from(capi::pa_channel_position_t::Aux24));
    assert_eq!(Position::Aux25,              Position::from(capi::pa_channel_position_t::Aux25));
    assert_eq!(Position::Aux26,              Position::from(capi::pa_channel_position_t::Aux26));
    assert_eq!(Position::Aux27,              Position::from(capi::pa_channel_position_t::Aux27));
    assert_eq!(Position::Aux28,              Position::from(capi::pa_channel_position_t::Aux28));
    assert_eq!(Position::Aux29,              Position::from(capi::pa_channel_position_t::Aux29));
    assert_eq!(Position::Aux30,              Position::from(capi::pa_channel_position_t::Aux30));
    assert_eq!(Position::Aux31,              Position::from(capi::pa_channel_position_t::Aux31));
    assert_eq!(Position::TopCenter,          Position::from(capi::pa_channel_position_t::TopCenter));
    assert_eq!(Position::TopFrontLeft,       Position::from(capi::pa_channel_position_t::TopFrontLeft));
    assert_eq!(Position::TopFrontRight,      Position::from(capi::pa_channel_position_t::TopFrontRight));
    assert_eq!(Position::TopFrontCenter,     Position::from(capi::pa_channel_position_t::TopFrontCenter));
    assert_eq!(Position::TopRearLeft,        Position::from(capi::pa_channel_position_t::TopRearLeft));
    assert_eq!(Position::TopRearRight,       Position::from(capi::pa_channel_position_t::TopRearRight));
    assert_eq!(Position::TopRearCenter,      Position::from(capi::pa_channel_position_t::TopRearCenter));
}

impl From<Position> for capi::pa_channel_position_t {
    #[inline]
    fn from(p: Position) -> Self {
        unsafe { std::mem::transmute(p) }
    }
}
impl From<capi::pa_channel_position_t> for Position {
    #[inline]
    fn from(p: capi::pa_channel_position_t) -> Self {
        unsafe { std::mem::transmute(p) }
    }
}

/// A channel map which can be used to attach labels to specific channels of a stream.
///
/// These values are relevant for conversion and mixing of streams.
#[repr(C)]
#[derive(Debug, Copy, Clone)]
pub struct Map {
    /* NOTE: This struct must be directly usable by the C API, thus same attributes/layout/etc */
    /// Number of channels mapped.
    channels: u8,
    /// Channel labels.
    map: [Position; Self::CHANNELS_MAX as usize],
}

impl Borrow<[Position]> for Map {
    fn borrow(&self) -> &[Position] {
        &self.map[..self.channels as usize]
    }
}

impl BorrowMut<[Position]> for Map {
    fn borrow_mut(&mut self) -> &mut [Position] {
        &mut self.map[..self.channels as usize]
    }
}

/// Test size is equal to `sys` equivalent
#[test]
fn map_compare_capi() {
    assert_eq!(std::mem::size_of::<Map>(), std::mem::size_of::<capi::pa_channel_map>());
    assert_eq!(std::mem::align_of::<Map>(), std::mem::align_of::<capi::pa_channel_map>());
}

impl AsRef<capi::pa_channel_map> for Map {
    #[inline]
    fn as_ref(&self) -> &capi::pa_channel_map {
        unsafe { &*(self as *const Self as *const capi::pa_channel_map) }
    }
}
impl AsMut<capi::pa_channel_map> for Map {
    #[inline]
    fn as_mut(&mut self) -> &mut capi::pa_channel_map {
        unsafe { &mut *(self as *mut Self as *mut capi::pa_channel_map) }
    }
}
impl AsRef<Map> for capi::pa_channel_map {
    #[inline]
    fn as_ref(&self) -> &Map {
        unsafe { &*(self as *const Self as *const Map) }
    }
}

impl From<capi::pa_channel_map> for Map {
    #[inline]
    fn from(m: capi::pa_channel_map) -> Self {
        unsafe { std::mem::transmute(m) }
    }
}

impl Default for Map {
    fn default() -> Self {
        Self { channels: 0, map: [Position::Invalid; Self::CHANNELS_MAX as usize] }
    }
}

impl PartialEq for Map {
    #[inline]
    fn eq(&self, other: &Self) -> bool {
        unsafe { capi::pa_channel_map_equal(self.as_ref(), other.as_ref()) == 1 }
    }
}

impl Position {
    /// Makes a bit mask from a channel position.
    pub const fn to_mask(self) -> PositionMask {
        match self {
            Position::Invalid => 0,
            _ => (1 as PositionMask) << (self as PositionMask),
        }
    }

    /// Gets a text label for the specified channel position.
    pub fn to_string(pos: Self) -> Option<Cow<'static, str>> {
        let ptr = unsafe { capi::pa_channel_position_to_string(pos.into()) };
        match ptr.is_null() {
            false => Some(unsafe { CStr::from_ptr(ptr).to_string_lossy() }),
            true => None,
        }
    }

    /// Gets a human readable text label for the specified channel position.
    pub fn to_pretty_string(pos: Self) -> Option<String> {
        let ptr = unsafe { capi::pa_channel_position_to_pretty_string(pos.into()) };
        match ptr.is_null() {
            false => Some(unsafe { CStr::from_ptr(ptr).to_string_lossy().into_owned() }),
            true => None,
        }
    }

    /// Creates a new instance from a string representation, as given by
    /// [`to_string()`](Self::to_string).
    pub fn from_string(s: &str) -> Self {
        // Warning: New CStrings will be immediately freed if not bound to a variable, leading to
        // as_ptr() giving dangling pointers!
        let c_str = CString::new(s).unwrap();
        unsafe { capi::pa_channel_position_from_string(c_str.as_ptr()).into() }
    }
}

impl Map {
    /// Maximum number of allowed channels.
    pub const CHANNELS_MAX: u8 = capi::PA_CHANNELS_MAX;

    /// Parses a channel position list or well-known mapping name into a channel map structure.
    ///
    /// This turns the output of [`print()`](Self::print) and [`to_name()`](Self::to_name) back into
    /// a `Map`.
    pub fn new_from_string(s: &str) -> Result<Self, ()> {
        // Warning: New CStrings will be immediately freed if not bound to a variable, leading to
        // as_ptr() giving dangling pointers!
        let c_str = CString::new(s).unwrap();
        let mut map: Self = Self::default();
        unsafe {
            if capi::pa_channel_map_parse((&mut map).as_mut(), c_str.as_ptr()).is_null() {
                return Err(());
            }
        }
        Ok(map)
    }

    /// Initializes the specified channel map and returns a pointer to it.
    ///
    /// The map will have a defined state but [`is_valid()`](Self::is_valid) will fail for it.
    #[inline]
    pub fn init(&mut self) -> &mut Self {
        unsafe { capi::pa_channel_map_init(self.as_mut()) };
        self
    }

    /// Initializes the specified channel map for monaural audio and returns a pointer to it.
    #[inline]
    pub fn init_mono(&mut self) -> &mut Self {
        unsafe { capi::pa_channel_map_init_mono(self.as_mut()) };
        self
    }

    /// Initializes the specified channel map for stereophonic audio and returns a pointer to it.
    #[inline]
    pub fn init_stereo(&mut self) -> &mut Self {
        unsafe { capi::pa_channel_map_init_stereo(self.as_mut()) };
        self
    }

    /// Initializes the specified channel map for the specified number of channels using default
    /// labels and returns a pointer to it.
    ///
    /// This call will fail (return `None`) if there is no default channel map known for this
    /// specific number of channels and mapping.
    pub fn init_auto(&mut self, channels: u8, def: MapDef) -> Option<&mut Self> {
        debug_assert!(channels <= Self::CHANNELS_MAX);
        unsafe {
            if capi::pa_channel_map_init_auto(self.as_mut(), channels as u32, def).is_null() {
                return None;
            }
        }
        Some(self)
    }

    /// Similar to [`init_auto()`](Self::init_auto) but instead of failing if no default mapping is
    /// known with the specified parameters it will synthesize a mapping based on a known mapping
    /// with fewer channels and fill up the rest with AUX0...AUX31 channels.
    pub fn init_extend(&mut self, channels: u8, def: MapDef) -> &mut Self {
        debug_assert!(channels <= Self::CHANNELS_MAX);
        unsafe { capi::pa_channel_map_init_extend(self.as_mut(), channels as u32, def) };
        self
    }

    /// Checks whether or not the map is considered valid.
    #[inline]
    pub fn is_valid(&self) -> bool {
        unsafe { capi::pa_channel_map_valid(self.as_ref()) != 0 }
    }

    /// Gets the number of active channels.
    #[inline]
    pub const fn len(&self) -> u8 {
        self.channels
    }

    /// Sets the number of active channels.
    ///
    /// Positions for up to [`Self::CHANNELS_MAX`] channels can be held. This sets the portion of
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
    pub fn get(&self) -> &[Position] {
        self.borrow()
    }

    /// Gets a mutable slice of the set of “active” channels.
    #[inline]
    pub fn get_mut(&mut self) -> &mut [Position] {
        self.borrow_mut()
    }

    /// Makes a human readable string from the map.
    pub fn print(&self) -> String {
        const PRINT_MAX: usize = capi::PA_CHANNEL_MAP_SNPRINT_MAX;
        let mut tmp = Vec::with_capacity(PRINT_MAX);
        unsafe {
            capi::pa_channel_map_snprint(tmp.as_mut_ptr(), PRINT_MAX, self.as_ref());
            CStr::from_ptr(tmp.as_mut_ptr()).to_string_lossy().into_owned()
        }
    }

    /// Checks whether or not the specified map is compatible with the specified sample spec.
    #[inline]
    pub fn is_compatible_with_sample_spec(&self, ss: &sample::Spec) -> bool {
        unsafe { capi::pa_channel_map_compatible(self.as_ref(), ss.as_ref()) != 0 }
    }

    /// Checks whether every channel defined in `of` is also defined in self.
    #[inline]
    pub fn is_superset_of(&self, of: &Self) -> bool {
        unsafe { capi::pa_channel_map_superset(self.as_ref(), of.as_ref()) != 0 }
    }

    /// Checks whether or not it makes sense to apply a volume “balance” with this mapping, i.e. if
    /// there are left/right channels available.
    #[inline]
    pub fn can_balance(&self) -> bool {
        unsafe { capi::pa_channel_map_can_balance(self.as_ref()) != 0 }
    }

    /// Checks whether or not it makes sense to apply a volume “fade” (i.e. “balance” between front
    /// and rear) with this mapping, i.e. if there are front/rear channels available.
    #[inline]
    pub fn can_fade(&self) -> bool {
        unsafe { capi::pa_channel_map_can_fade(self.as_ref()) != 0 }
    }

    /// Checks whether or not it makes sense to apply a volume “LFE balance” (i.e. “balance” between
    /// LFE and non-LFE channels) with this mapping, i.e. if there are LFE and non-LFE channels
    /// available.
    #[inline]
    #[cfg(any(doc, feature = "pa_v8"))]
    #[cfg_attr(docsrs, doc(cfg(feature = "pa_v8")))]
    pub fn can_lfe_balance(&self) -> bool {
        unsafe { capi::pa_channel_map_can_lfe_balance(self.as_ref()) != 0 }
    }

    /// Tries to find a well-known channel mapping name for this channel mapping, i.e. “stereo”,
    /// “surround-71” and so on. This name can be parsed with
    /// [`new_from_string()`](Self::new_from_string).
    pub fn to_name(&self) -> Option<Cow<'static, str>> {
        let ptr = unsafe { capi::pa_channel_map_to_name(self.as_ref()) };
        match ptr.is_null() {
            false => Some(unsafe { CStr::from_ptr(ptr).to_string_lossy() }),
            true => None,
        }
    }

    /// Similar to [`to_name()`](Self::to_name), but returning prettier, human readable text labels,
    /// i.e. “Stereo”, “Surround 7.1” and so on.
    pub fn to_pretty_name(&self) -> Option<String> {
        let ptr = unsafe { capi::pa_channel_map_to_pretty_name(self.as_ref()) };
        match ptr.is_null() {
            false => Some(unsafe { CStr::from_ptr(ptr).to_string_lossy().into_owned() }),
            true => None,
        }
    }

    /// Checks whether or not the specified channel position is available at least once in the map.
    #[inline]
    pub fn has_position(&self, p: Position) -> bool {
        unsafe { capi::pa_channel_map_has_position(self.as_ref(), p.into()) != 0 }
    }

    /// Generates a bit mask from a map.
    #[inline]
    pub fn get_mask(&self) -> PositionMask {
        unsafe { capi::pa_channel_map_mask(self.as_ref()) }
    }
}
