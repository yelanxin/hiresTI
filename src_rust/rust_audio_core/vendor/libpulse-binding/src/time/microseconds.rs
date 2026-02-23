// Copyright 2018 Lyndon Brown
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

//! MicroSeconds.

use std::ops::{Add, AddAssign, Div, DivAssign, Mul, MulAssign, Rem, RemAssign, Sub, SubAssign};
use std::time::Duration;
use super::op_err;

/// Microseconds. Represents a span of time like [`std::time::Duration`].
///
/// This is an unsigned 64-bit type, and thus represents absolute values only.
#[repr(transparent)]
#[derive(Copy, Clone, Debug, Default, Eq, PartialEq, Ord, PartialOrd)]
pub struct MicroSeconds(pub u64);

impl MicroSeconds {
    /// `MicroSeconds` value representing an ‘invalid’ time.
    ///
    /// # Examples
    ///
    /// ```rust
    /// # use libpulse_binding::time::MicroSeconds;
    /// assert_eq!(MicroSeconds::INVALID, MicroSeconds(std::u64::MAX));
    /// ```
    pub const INVALID: Self = Self(capi::PA_USEC_INVALID);

    /// One second in microseconds.
    ///
    /// # Examples
    ///
    /// ```rust
    /// # use libpulse_binding::time::MicroSeconds;
    /// assert_eq!(MicroSeconds::SECOND, MicroSeconds(1_000_000));
    /// ```
    pub const SECOND: Self = Self(super::MICROS_PER_SEC);

    /// One millisecond in microseconds.
    ///
    /// # Examples
    ///
    /// ```rust
    /// # use libpulse_binding::time::MicroSeconds;
    /// assert_eq!(MicroSeconds::MILLISECOND, MicroSeconds(1_000));
    /// ```
    pub const MILLISECOND: Self = Self(super::MICROS_PER_MILLI);

    /// Zero value.
    ///
    /// # Examples
    ///
    /// ```rust
    /// # use libpulse_binding::time::MicroSeconds;
    /// assert_eq!(MicroSeconds::ZERO, MicroSeconds(0));
    /// ```
    pub const ZERO: Self = Self(0);

    /// Smallest _valid_ time value (zero).
    ///
    /// # Examples
    ///
    /// ```rust
    /// # use libpulse_binding::time::MicroSeconds;
    /// assert_eq!(MicroSeconds::MIN, MicroSeconds(0));
    /// ```
    pub const MIN: Self = Self(0);

    /// Largest _valid_ time value (largest integer value is reserved for representing ‘invalid’).
    ///
    /// Roughly equal to 5,124,095,576 hours, 213,503,982 days, or 584,542 years.
    ///
    /// # Examples
    ///
    /// ```rust
    /// # use libpulse_binding::time::MicroSeconds;
    /// assert_eq!(MicroSeconds::MAX, MicroSeconds(std::u64::MAX - 1));
    /// ```
    pub const MAX: Self = Self(capi::PA_USEC_MAX);

    /// Get the inner `u64` value.
    ///
    /// # Examples
    ///
    /// ```rust
    /// # use libpulse_binding::time::MicroSeconds;
    /// assert_eq!(MicroSeconds(100).inner(), 100);
    /// ```
    #[inline]
    pub const fn inner(&self) -> u64 {
        self.0
    }

    /// Returns `true` so long as inner value is not [`Self::INVALID`].
    ///
    /// # Examples
    ///
    /// ```rust
    /// # use libpulse_binding::time::{MicroSeconds, MICROS_PER_SEC};
    /// assert_eq!(MicroSeconds::MIN.is_valid(), true);
    /// assert_eq!(MicroSeconds::MAX.is_valid(), true);
    /// assert_eq!(MicroSeconds::INVALID.is_valid(), false);
    /// assert_eq!(MicroSeconds::ZERO.is_valid(), true);
    /// assert_eq!(MicroSeconds(60 * MICROS_PER_SEC).is_valid(), true);
    /// ```
    #[inline]
    pub const fn is_valid(&self) -> bool {
        self.0 != Self::INVALID.0
    }

    /// Returns `true` so long as inner value is zero.
    ///
    /// # Examples
    ///
    /// ```rust
    /// # use libpulse_binding::time::MicroSeconds;
    /// assert_eq!(MicroSeconds::ZERO.is_zero(), true);
    /// assert_eq!(MicroSeconds(0).is_zero(), true);
    /// assert_eq!(MicroSeconds(1).is_zero(), false);
    /// ```
    #[inline]
    pub const fn is_zero(&self) -> bool {
        self.0 == 0
    }

    /// Creates a new `MicroSeconds` from the specified number of whole seconds. Returns `None` on
    /// overflow.
    ///
    /// # Examples
    ///
    /// ```rust
    /// # use libpulse_binding::time::MicroSeconds;
    /// assert_eq!(MicroSeconds::from_secs(2), Some(MicroSeconds(2_000_000)));
    /// assert_eq!(MicroSeconds::from_secs(0xffff_ffff_0000_0000), None);
    /// ```
    #[inline]
    pub fn from_secs(secs: u64) -> Option<Self> {
        secs.checked_mul(super::MICROS_PER_SEC).and_then(|i| Some(Self(i)))
    }

    /// Creates a new `MicroSeconds` from the specified number of whole milliseconds. Returns `None`
    /// on overflow.
    ///
    /// # Examples
    ///
    /// ```rust
    /// # use libpulse_binding::time::MicroSeconds;
    /// assert_eq!(MicroSeconds::from_millis(23), Some(MicroSeconds(23_000)));
    /// assert_eq!(MicroSeconds::from_millis(0xffff_ffff_0000_0000), None);
    /// ```
    #[inline]
    pub fn from_millis(millis: u64) -> Option<Self> {
        millis.checked_mul(super::MICROS_PER_MILLI).and_then(|i| Some(Self(i)))
    }

    /// Returns the absolute difference with `other`.
    ///
    /// # Examples
    ///
    /// ```rust
    /// # use libpulse_binding::time::MicroSeconds;
    /// assert_eq!(MicroSeconds(0).diff(MicroSeconds(0)), MicroSeconds(0));
    /// assert_eq!(MicroSeconds(100).diff(MicroSeconds(100)), MicroSeconds(0));
    /// assert_eq!(MicroSeconds(200).diff(MicroSeconds(150)), MicroSeconds(50));
    /// assert_eq!(MicroSeconds(150).diff(MicroSeconds(200)), MicroSeconds(50));
    /// ```
    #[inline]
    pub fn diff(self, other: Self) -> Self {
        match self >= other {
            true => Self(self.0 - other.0),
            false => Self(other.0 - self.0),
        }
    }

    /// Returns the total number of whole seconds.
    ///
    /// # Examples
    ///
    /// ```rust
    /// # use libpulse_binding::time::MicroSeconds;
    /// assert_eq!(MicroSeconds(2_300_000).as_secs(), 2);
    /// assert_eq!(MicroSeconds(2_800_000).as_secs(), 2);
    /// ```
    #[inline]
    pub const fn as_secs(&self) -> u64 {
        self.0 / super::MICROS_PER_SEC
    }

    /// Returns the total number of whole milliseconds.
    ///
    /// # Examples
    ///
    /// ```rust
    /// # use libpulse_binding::time::MicroSeconds;
    /// assert_eq!(MicroSeconds(23_000_300).as_millis(), 23_000);
    /// assert_eq!(MicroSeconds(23_000_800).as_millis(), 23_000);
    /// ```
    #[inline]
    pub const fn as_millis(&self) -> u64 {
        self.0 / super::MICROS_PER_MILLI
    }

    /// Creates a new `MicroSeconds` from the specified number of seconds represented as `f64`.
    ///
    /// **Panics** if `secs` is not finite, is negative, or the value overflows.
    ///
    /// # Examples
    ///
    /// ```rust
    /// # use libpulse_binding::time::MicroSeconds;
    /// assert_eq!(MicroSeconds::from_secs_f64(0.5), MicroSeconds(500_000));
    /// assert_eq!(MicroSeconds::from_secs_f64(2.3), MicroSeconds(2_300_000));
    /// ```
    ///
    /// These should panic.
    ///
    /// ```rust,should_panic
    /// # use libpulse_binding::time::MicroSeconds;
    /// MicroSeconds::from_secs_f64(std::f64::INFINITY);
    /// ```
    ///
    /// ```rust,should_panic
    /// # use libpulse_binding::time::MicroSeconds;
    /// MicroSeconds::from_secs_f64(-0.5);
    /// ```
    ///
    /// ```rust,should_panic
    /// # use libpulse_binding::time::MicroSeconds;
    /// MicroSeconds::from_secs_f64(std::f64::MAX);
    /// ```
    ///
    /// ```rust,should_panic
    /// # use libpulse_binding::time::MicroSeconds;
    /// MicroSeconds::from_secs_f64(std::f64::NAN);
    /// ```
    #[inline]
    pub fn from_secs_f64(secs: f64) -> Self {
        let duration = Duration::from_secs_f64(secs);
        Self::try_from(duration).expect("overflow during microseconds conversion")
    }

    /// Creates a new `MicroSeconds` from the specified number of seconds represented as `f32`.
    ///
    /// **Panics** if `secs` is not finite, is negative, or the value overflows.
    ///
    /// # Examples
    ///
    /// ```rust
    /// # use libpulse_binding::time::MicroSeconds;
    /// assert_eq!(MicroSeconds::from_secs_f32(0.5), MicroSeconds(500_000));
    /// assert_eq!(MicroSeconds::from_secs_f32(2.3), MicroSeconds(2_299_999));
    /// ```
    ///
    /// These should panic.
    ///
    /// ```rust,should_panic
    /// # use libpulse_binding::time::MicroSeconds;
    /// MicroSeconds::from_secs_f32(std::f32::INFINITY);
    /// ```
    ///
    /// ```rust,should_panic
    /// # use libpulse_binding::time::MicroSeconds;
    /// MicroSeconds::from_secs_f32(-0.5);
    /// ```
    ///
    /// ```rust,should_panic
    /// # use libpulse_binding::time::MicroSeconds;
    /// MicroSeconds::from_secs_f32(std::f32::MAX);
    /// ```
    ///
    /// ```rust,should_panic
    /// # use libpulse_binding::time::MicroSeconds;
    /// MicroSeconds::from_secs_f32(std::f32::NAN);
    /// ```
    #[inline]
    pub fn from_secs_f32(secs: f32) -> Self {
        let duration = Duration::from_secs_f32(secs);
        Self::try_from(duration).expect("overflow during microseconds conversion")
    }

    /// Returns the number of seconds as `f64`.
    ///
    /// # Examples
    ///
    /// ```rust
    /// # use libpulse_binding::time::MicroSeconds;
    /// assert_eq!(MicroSeconds(2_300_000).as_secs_f64(), 2.3);
    /// assert_eq!(MicroSeconds(500_000).as_secs_f64(), 0.5);
    /// ```
    #[inline]
    pub fn as_secs_f64(&self) -> f64 {
        (self.0 as f64) / (super::MICROS_PER_SEC as f64)
    }

    /// Returns the number of seconds as `f32`.
    ///
    /// # Examples
    ///
    /// ```rust
    /// # use libpulse_binding::time::MicroSeconds;
    /// assert_eq!(MicroSeconds(2_300_000).as_secs_f32(), 2.3);
    /// assert_eq!(MicroSeconds(500_000).as_secs_f32(), 0.5);
    /// ```
    #[inline]
    pub fn as_secs_f32(&self) -> f32 {
        (self.0 as f32) / (super::MICROS_PER_SEC as f32)
    }

    /// Checked integer addition. Computes `self + rhs`, returning `None` if overflow occurred,
    /// using the inner integer’s [`checked_add()`](u64::checked_add) method.
    ///
    /// # Examples
    ///
    /// ```rust
    /// # use libpulse_binding::time::{MicroSeconds, MICROS_PER_SEC};
    /// let quater_minute = MicroSeconds(15 * MICROS_PER_SEC);
    /// let half_minute = MicroSeconds(30 * MICROS_PER_SEC);
    /// let three_quater_minute = MicroSeconds(45 * MICROS_PER_SEC);
    ///
    /// assert_eq!(half_minute.checked_add(quater_minute), Some(three_quater_minute));
    /// assert_eq!(MicroSeconds::MAX.checked_add(half_minute), None);
    /// ```
    #[inline]
    pub fn checked_add(self, other: Self) -> Option<Self> {
        self.0.checked_add(other.0).and_then(|i| Some(Self(i)))
    }

    /// Checked integer addition. Computes `self + rhs`, returning `None` if overflow occurred,
    /// using the inner integer’s [`checked_add()`](u64::checked_add) method.
    ///
    /// # Examples
    ///
    /// ```rust
    /// # use std::time::Duration;
    /// # use libpulse_binding::time::{MicroSeconds, MICROS_PER_SEC, NANOS_PER_MICRO};
    /// let half_minute = MicroSeconds(30 * MICROS_PER_SEC);
    /// let duration1 = Duration::new(2, 5 * NANOS_PER_MICRO + 20); // 2s + 5us + 20ns
    /// let duration2 = Duration::new(MicroSeconds::MAX.inner() / MICROS_PER_SEC, 0);
    ///
    /// assert_eq!(half_minute.checked_add_duration(duration1), Some(MicroSeconds(32_000_005)));
    /// assert_eq!(half_minute.checked_add_duration(duration2), None);
    /// ```
    #[inline]
    pub fn checked_add_duration(self, rhs: Duration) -> Option<Self> {
        let usecs = Self::try_from(rhs).ok()?;
        self.0.checked_add(usecs.0).and_then(|i| Some(Self(i)))
    }

    /// Checked integer subtraction. Computes `self - rhs`, returning `None` if overflow occurred,
    /// using the inner integer’s [`checked_sub()`](u64::checked_sub) method.
    ///
    /// # Examples
    ///
    /// ```rust
    /// # use libpulse_binding::time::{MicroSeconds, MICROS_PER_SEC};
    /// let quater_minute = MicroSeconds(15 * MICROS_PER_SEC);
    /// let three_quater_minute = MicroSeconds(45 * MICROS_PER_SEC);
    /// let whole_minute = MicroSeconds(60 * MICROS_PER_SEC);
    ///
    /// assert_eq!(whole_minute.checked_sub(quater_minute), Some(three_quater_minute));
    /// assert_eq!(quater_minute.checked_sub(whole_minute), None);
    /// ```
    #[inline]
    pub fn checked_sub(self, other: Self) -> Option<Self> {
        self.0.checked_sub(other.0).and_then(|i| Some(Self(i)))
    }

    /// Checked integer subtraction. Computes `self - rhs`, returning `None` if overflow occurred,
    /// using the inner integer’s [`checked_sub()`](u64::checked_sub) method.
    ///
    /// # Examples
    ///
    /// ```rust
    /// # use std::time::Duration;
    /// # use libpulse_binding::time::{MicroSeconds, MICROS_PER_SEC, NANOS_PER_MICRO};
    /// let half_minute = MicroSeconds(30 * MICROS_PER_SEC);
    /// let duration1 = Duration::new(2, 5 * NANOS_PER_MICRO + 20); // 2s + 5us + 20ns
    /// let duration2 = Duration::new(45, 0);
    ///
    /// assert_eq!(half_minute.checked_sub_duration(duration1), Some(MicroSeconds(27_999_995)));
    /// assert_eq!(half_minute.checked_sub_duration(duration2), None);
    /// ```
    #[inline]
    pub fn checked_sub_duration(self, rhs: Duration) -> Option<Self> {
        let usecs = Self::try_from(rhs).ok()?;
        self.0.checked_sub(usecs.0).and_then(|i| Some(Self(i)))
    }

    /// Checked integer multiplication. Computes `self * rhs`, returning `None` if overflow
    /// occurred, using the inner integer’s [`checked_mul()`](u64::checked_mul) method.
    ///
    /// # Examples
    ///
    /// ```rust
    /// # use libpulse_binding::time::{MicroSeconds, MICROS_PER_SEC};
    /// let quater_minute = MicroSeconds(15 * MICROS_PER_SEC);
    /// let whole_minute = MicroSeconds(60 * MICROS_PER_SEC);
    ///
    /// assert_eq!(quater_minute.checked_mul(4), Some(whole_minute));
    /// assert_eq!(MicroSeconds::MAX.checked_mul(2), None);
    /// ```
    #[inline]
    pub fn checked_mul(self, rhs: u32) -> Option<Self> {
        self.0.checked_mul(rhs as u64).and_then(|i| Some(Self(i)))
    }

    /// Checked integer division. Computes `self / rhs`, returning `None` if `rhs == 0`, using the
    /// inner integer’s [`checked_div()`](u64::checked_div) method.
    ///
    /// # Examples
    ///
    /// ```rust
    /// # use libpulse_binding::time::{MicroSeconds, MICROS_PER_SEC};
    /// let quater_minute = MicroSeconds(15 * MICROS_PER_SEC);
    /// let whole_minute = MicroSeconds(60 * MICROS_PER_SEC);
    ///
    /// assert_eq!(whole_minute.checked_div(4), Some(quater_minute));
    /// assert_eq!(whole_minute.checked_div(0), None);
    /// ```
    #[inline]
    pub fn checked_div(self, rhs: u32) -> Option<Self> {
        self.0.checked_div(rhs as u64).and_then(|i| Some(Self(i)))
    }

    /// Checked integer remainder. Computes `self % rhs`, returning `None` if `rhs == 0`, using the
    /// inner integer’s [`checked_rem()`](u64::checked_rem) method.
    ///
    /// # Examples
    ///
    /// ```rust
    /// # use libpulse_binding::time::{MicroSeconds, MICROS_PER_SEC};
    /// let quater_minute = MicroSeconds(15 * MICROS_PER_SEC);
    /// let whole_minute = MicroSeconds(60 * MICROS_PER_SEC);
    ///
    /// assert_eq!(whole_minute.checked_rem(4), Some(MicroSeconds::ZERO));
    /// assert_eq!(whole_minute.checked_rem(7), Some(MicroSeconds(4)));
    /// assert_eq!(whole_minute.checked_rem(0), None);
    /// ```
    #[inline]
    pub fn checked_rem(self, rhs: u32) -> Option<Self> {
        self.0.checked_rem(rhs as u64).and_then(|i| Some(Self(i)))
    }

    /// Multiplies `MicroSeconds` by `f64`.
    ///
    /// Converts to an `f64` representing seconds, multiplies by the given factor, then converts
    /// back to microseconds.
    ///
    /// **Panics** if `rhs` is not finite, is negative, or the value overflows.
    ///
    /// # Examples
    ///
    /// ```rust
    /// # use libpulse_binding::time::{MicroSeconds, MICROS_PER_SEC};
    /// let micros = MicroSeconds(2_700_000_000);
    ///
    /// assert_eq!(micros.mul_f64(3.14), MicroSeconds(8_478_000_000));
    /// assert_eq!(micros.mul_f64(3.14e5), MicroSeconds(847_800_000_000_000));
    /// ```
    ///
    /// These should panic.
    ///
    /// ```rust,should_panic
    /// # use libpulse_binding::time::MicroSeconds;
    /// MicroSeconds::SECOND.mul_f64(std::f64::INFINITY);
    /// ```
    ///
    /// ```rust,should_panic
    /// # use libpulse_binding::time::MicroSeconds;
    /// MicroSeconds::SECOND.mul_f64(-0.5);
    /// ```
    ///
    /// ```rust,should_panic
    /// # use libpulse_binding::time::{MicroSeconds, MICROS_PER_SEC};
    /// MicroSeconds(2 * MICROS_PER_SEC).mul_f64(std::f64::MAX / 10.0);
    /// ```
    ///
    /// ```rust,should_panic
    /// # use libpulse_binding::time::MicroSeconds;
    /// MicroSeconds::SECOND.mul_f64(std::f64::NAN);
    /// ```
    #[inline]
    pub fn mul_f64(self, rhs: f64) -> Self {
        // It is expected that overflow in the initial multiplication would result in `NaN`.
        // We rely upon the underlying `Duration::from_secs_f64()` to panic appropriately for
        // unsupported input and result values.
        Self::from_secs_f64(rhs * self.as_secs_f64())
    }

    /// Multiplies `MicroSeconds` by `f32`.
    ///
    /// Converts to an `f32` representing seconds, multiplies by the given factor, then converts
    /// back to microseconds.
    ///
    /// **Panics** if `rhs` is not finite, is negative, or the value overflows.
    ///
    /// # Examples
    ///
    /// ```rust
    /// # use libpulse_binding::time::{MicroSeconds, MICROS_PER_SEC};
    /// let micros = MicroSeconds(2_700_000_000);
    ///
    /// // Note the rounding errors that are clear here.
    /// assert_eq!(micros.mul_f32(3.14), MicroSeconds(8_478_000_000));
    /// assert_eq!(micros.mul_f32(3.14e5), MicroSeconds(847_800_000_000_000));
    /// ```
    ///
    /// These should panic.
    ///
    /// ```rust,should_panic
    /// # use libpulse_binding::time::MicroSeconds;
    /// MicroSeconds::SECOND.mul_f32(std::f32::INFINITY);
    /// ```
    ///
    /// ```rust,should_panic
    /// # use libpulse_binding::time::MicroSeconds;
    /// MicroSeconds::SECOND.mul_f32(-0.5);
    /// ```
    ///
    /// ```rust,should_panic
    /// # use libpulse_binding::time::{MicroSeconds, MICROS_PER_SEC};
    /// MicroSeconds(2 * MICROS_PER_SEC).mul_f32(std::f32::MAX / 10.0);
    /// ```
    ///
    /// ```rust,should_panic
    /// # use libpulse_binding::time::MicroSeconds;
    /// MicroSeconds::SECOND.mul_f32(std::f32::NAN);
    /// ```
    #[inline]
    pub fn mul_f32(self, rhs: f32) -> Self {
        // It is expected that overflow in the initial multiplication would result in `NaN`.
        // We rely upon the underlying `Duration::from_secs_f64()` to panic appropriately for
        // unsupported input and result values.
        Self::from_secs_f32(rhs * self.as_secs_f32())
    }

    /// Divides `MicroSeconds` by `f64`.
    ///
    /// Converts to an `f64` representing seconds, divides by the given factor, then converts back
    /// to microseconds.
    ///
    /// **Panics** if `rhs` is not finite, is negative, or the value overflows.
    ///
    /// # Examples
    ///
    /// ```rust
    /// # use libpulse_binding::time::{MicroSeconds, MICROS_PER_SEC};
    /// let micros = MicroSeconds(2_700_000_000);
    ///
    /// assert_eq!(micros.div_f64(3.14), MicroSeconds(859_872_611));
    /// assert_eq!(micros.div_f64(3.14e5), MicroSeconds(8_598));
    /// ```
    ///
    /// These should panic.
    ///
    /// ```rust,should_panic
    /// # use libpulse_binding::time::MicroSeconds;
    /// MicroSeconds::SECOND.div_f64(-2.0);
    /// ```
    ///
    /// ```rust,should_panic
    /// # use libpulse_binding::time::{MicroSeconds, MICROS_PER_SEC};
    /// MicroSeconds::MAX.div_f64(0.5);
    /// ```
    ///
    /// ```rust,should_panic
    /// # use libpulse_binding::time::MicroSeconds;
    /// MicroSeconds::SECOND.div_f64(std::f64::NAN);
    /// ```
    #[inline]
    pub fn div_f64(self, rhs: f64) -> Self {
        // Note that division by zero results in a ∞ or −∞ value, which will be handled by the
        // underlying `Duration::from_secs_f64()` which we rely upon to panic appropriately.
        Self::from_secs_f64(self.as_secs_f64() / rhs)
    }

    /// Divides `MicroSeconds` by `f32`.
    ///
    /// Converts to an `f32` representing seconds, divides by the given factor, then converts back
    /// to microseconds.
    ///
    /// **Panics** if `rhs` is not finite, is negative, or the value overflows.
    ///
    /// # Examples
    ///
    /// ```rust
    /// # use libpulse_binding::time::{MicroSeconds, MICROS_PER_SEC};
    /// let micros = MicroSeconds(2_700_000_000);
    ///
    /// assert_eq!(micros.div_f32(3.14), MicroSeconds(859_872_558));
    /// assert_eq!(micros.div_f32(3.14e5), MicroSeconds(8_598));
    /// ```
    ///
    /// These should panic.
    ///
    /// ```rust,should_panic
    /// # use libpulse_binding::time::MicroSeconds;
    /// MicroSeconds::SECOND.div_f32(-2.0);
    /// ```
    ///
    /// ```rust,should_panic
    /// # use libpulse_binding::time::{MicroSeconds, MICROS_PER_SEC};
    /// MicroSeconds::MAX.div_f32(0.5);
    /// ```
    ///
    /// ```rust,should_panic
    /// # use libpulse_binding::time::MicroSeconds;
    /// MicroSeconds::SECOND.div_f32(std::f32::NAN);
    /// ```
    #[inline]
    pub fn div_f32(self, rhs: f32) -> Self {
        // Note that division by zero results in a ∞ or −∞ value, which will be handled by the
        // underlying `Duration::from_secs_f64()` which we rely upon to panic appropriately.
        Self::from_secs_f32(self.as_secs_f32() / rhs)
    }
}

impl std::fmt::Display for MicroSeconds {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        write!(f, "{} µs", self.0)
    }
}

impl Add for MicroSeconds {
    type Output = Self;

    #[track_caller]
    #[inline]
    fn add(self, other: Self) -> Self {
        self.checked_add(other).expect(op_err::ADD)
    }
}
impl AddAssign for MicroSeconds {
    #[track_caller]
    #[inline]
    fn add_assign(&mut self, rhs: Self) {
        *self = self.add(rhs);
    }
}

impl Sub for MicroSeconds {
    type Output = Self;

    #[track_caller]
    #[inline]
    fn sub(self, other: Self) -> Self {
        self.checked_sub(other).expect(op_err::SUB)
    }
}
impl SubAssign for MicroSeconds {
    #[track_caller]
    #[inline]
    fn sub_assign(&mut self, rhs: Self) {
        *self = self.sub(rhs);
    }
}

////////////////////////////////////////////////////////////////////////////////////////////////////
// Operations with `Duration`
////////////////////////////////////////////////////////////////////////////////////////////////////

impl Add<Duration> for MicroSeconds {
    type Output = Self;

    #[track_caller]
    #[inline]
    fn add(self, rhs: Duration) -> Self {
        self.checked_add_duration(rhs).expect(op_err::ADD)
    }
}
impl AddAssign<Duration> for MicroSeconds {
    #[track_caller]
    #[inline]
    fn add_assign(&mut self, rhs: Duration) {
        *self = self.add(rhs);
    }
}

impl Add<MicroSeconds> for Duration {
    type Output = Self;

    #[track_caller]
    #[inline]
    fn add(self, rhs: MicroSeconds) -> Self {
        self.checked_add(Duration::from_micros(rhs.0)).expect(op_err::ADD)
    }
}
impl AddAssign<MicroSeconds> for Duration {
    #[track_caller]
    #[inline]
    fn add_assign(&mut self, rhs: MicroSeconds) {
        *self = self.add(rhs);
    }
}

impl Sub<Duration> for MicroSeconds {
    type Output = Self;

    #[track_caller]
    #[inline]
    fn sub(self, rhs: Duration) -> Self {
        self.checked_sub_duration(rhs).expect(op_err::SUB)
    }
}
impl SubAssign<Duration> for MicroSeconds {
    #[track_caller]
    #[inline]
    fn sub_assign(&mut self, rhs: Duration) {
        *self = self.sub(rhs);
    }
}

impl Sub<MicroSeconds> for Duration {
    type Output = Self;

    #[track_caller]
    #[inline]
    fn sub(self, rhs: MicroSeconds) -> Self {
        self.checked_sub(Duration::from_micros(rhs.0)).expect(op_err::SUB)
    }
}
impl SubAssign<MicroSeconds> for Duration {
    #[track_caller]
    #[inline]
    fn sub_assign(&mut self, rhs: MicroSeconds) {
        *self = self.sub(rhs);
    }
}

////////////////////////////////////////////////////////////////////////////////////////////////////
// Operations with primitives
//
// NOTE 1: We only implement `u32` here because:
//  - We do not expect operations will be needed for the larger `u64` range, otherwise we should
//    switch to that.
//  - Although implementing for the set of { `u8`, `u16`, `u32`, `u64 } is very easy with a macro,
//    and may avoid possible need for `as u32` for non-`u32` variables, it introduces ambiguity such
//    that the compiler does not know which type the `2` should be in the example use case of `2 *
//    MicroSeconds::SECOND` and so it goes with `i32`, and since we don't implement the ops for
//    `i32`, the user thus gets an error, forcing them to write instead `2u32 *
//    MicroSeconds::SECOND`.
//
// NOTE 2: Addition and subtraction deliberately not implemented, since allowing arbitrary such
// operations would allow mistakes to be made that the `MicroSeconds` type exists to prevent. I.e.
// allowing the following:
//
// ```rust
// let a = 10u32;
// let b = MicroSeconds(1) + a;
// ```
//
// ...would allow mistakes to be made around the form of `a`. We must force `a` to be wrapped in
// `MicroSeconds`.
//
// NOTE 3: We support an integer being the Lhs of the operation for multiplicaton (for example
// `2 * MicroSeconds`), but not for division/remainder, because dividing a generic integer by an
// amount of microseconds makes no sense.
//
////////////////////////////////////////////////////////////////////////////////////////////////////

impl Mul<u32> for MicroSeconds {
    type Output = Self;

    #[track_caller]
    #[inline]
    fn mul(self, rhs: u32) -> Self {
        Self(self.0.checked_mul(rhs as u64).expect(op_err::MUL))
    }
}
impl MulAssign<u32> for MicroSeconds {
    #[track_caller]
    #[inline]
    fn mul_assign(&mut self, rhs: u32) {
        *self = self.mul(rhs);
    }
}

impl Mul<MicroSeconds> for u32 {
    type Output = MicroSeconds;

    #[track_caller]
    #[inline]
    fn mul(self, rhs: MicroSeconds) -> MicroSeconds {
        rhs.mul(self)
    }
}

impl Div<u32> for MicroSeconds {
    type Output = Self;

    #[track_caller]
    #[inline]
    fn div(self, rhs: u32) -> Self {
        Self(self.0.checked_div(rhs as u64).expect(op_err::DIV))
    }
}
impl DivAssign<u32> for MicroSeconds {
    #[track_caller]
    #[inline]
    fn div_assign(&mut self, rhs: u32) {
        *self = self.div(rhs);
    }
}

impl Rem<u32> for MicroSeconds {
    type Output = Self;

    #[track_caller]
    #[inline]
    fn rem(self, rhs: u32) -> Self {
        Self(self.0.checked_rem(rhs as u64).expect(op_err::REM))
    }
}
impl RemAssign<u32> for MicroSeconds {
    #[track_caller]
    #[inline]
    fn rem_assign(&mut self, rhs: u32) {
        *self = self.rem(rhs);
    }
}
