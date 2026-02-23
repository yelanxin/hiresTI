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

//! Timeval.

use std::cmp::Ordering;
use std::ops::{Add, AddAssign, Div, DivAssign, Mul, MulAssign, Rem, RemAssign, Sub, SubAssign};
use std::time::Duration;
use super::{UnixTs, MonotonicTs, MicroSeconds, op_err};

#[cfg(not(windows))]
pub(crate) type TvSecs = libc::time_t;
#[cfg(not(windows))]
pub(crate) type TvUsecs = libc::suseconds_t;
#[cfg(windows)]
pub(crate) type TvSecs = libc::c_long;
#[cfg(windows)]
pub(crate) type TvUsecs = libc::c_long;

/// Wrapper for [`libc::timeval`], attaching various methods and trait implementations.
#[repr(transparent)]
#[derive(Copy, Clone)]
pub struct Timeval(pub libc::timeval); // Warning, this must remain directly transmutable with the inner libc::timeval

impl PartialEq for Timeval {
    fn eq(&self, other: &Self) -> bool {
        self.0.tv_sec == other.0.tv_sec && self.0.tv_usec == other.0.tv_usec
    }
}
impl Eq for Timeval {}

impl Ord for Timeval {
    fn cmp(&self, other: &Self) -> Ordering {
        match unsafe { capi::pa_timeval_cmp(&self.0, &other.0) } {
            0 => Ordering::Equal,
            r if r < 0 => Ordering::Less,
            _ => Ordering::Greater,
        }
    }
}

impl PartialOrd for Timeval {
    #[inline]
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        Some(self.cmp(other))
    }
}

impl Timeval {
    /// Bit to set in `tv_usec` attribute to mark that the `timeval` is in monotonic time.
    const RTCLOCK_BIT: TvUsecs = 1 << 30;

    /// Creates a new instance, with values provided.
    #[inline]
    pub const fn new(sec: TvSecs, usec: TvUsecs) -> Self {
        Self(libc::timeval { tv_sec: sec, tv_usec: usec })
    }

    /// Creates a new instance, with value of zero.
    #[inline]
    pub const fn new_zero() -> Self {
        Self::new(0, 0)
    }

    /// Calculates the difference between the two specified timeval structs.
    #[inline]
    pub fn diff(a: &Self, b: &Self) -> MicroSeconds {
        MicroSeconds(unsafe { capi::pa_timeval_diff(&a.0, &b.0) })
    }

    /// Gets the time difference between now and self.
    #[inline]
    pub fn age(&self) -> MicroSeconds {
        MicroSeconds(unsafe { capi::pa_timeval_age(&self.0) })
    }

    /// Sets to the specified (monotonic) value.
    ///
    /// The `rtclock` boolean is used for indicating support of the rtclock (monotonic time). If
    /// `true` then the conversion from `MicroSeconds` to `Timeval` is done, and a special ‘rt’ flag
    /// bit is set in `Timeval`’s inner `tv_usec` attribute. If `false`, then instead the timestamp
    /// is converted to a Unix wallclock timestamp.
    ///
    /// Asserts that `v` is not `MicroSeconds::INVALID`.
    pub(crate) fn set_rt(&mut self, v: MicroSeconds, rtclock: bool) -> &mut Self {
        /* This is a copy of PA’s internal `pa_timeval_rtstore()` function */

        assert_ne!(v, MicroSeconds::INVALID);

        *self = v.into();

        if rtclock {
            self.0.tv_usec |= Self::RTCLOCK_BIT;
        }
        else {
            self.wallclock_from_rtclock();
        }
        self
    }

    pub(crate) fn wallclock_from_rtclock(&mut self) -> &mut Self {
        /* This is a copy of PA’s internal `wallclock_from_rtclock()` function */

        let wc_now = (UnixTs::now()).0;
        let rt_now = Timeval::from((MonotonicTs::now()).0);

        let _ = match rt_now.cmp(self) {
            Ordering::Less => { wc_now.add(Self::diff(self, &rt_now)) },
            _              => { wc_now.sub(Self::diff(&rt_now, self)) },
        };

        *self = wc_now;
        self
    }

    /// Checked integer addition. Computes `self + rhs`, returning `None` if overflow occurred,
    /// using the inner integer’s `checked_add()` method.
    pub fn checked_add(self, other: Self) -> Option<Self> {
        let self_us = MicroSeconds::from(self);
        let other_us = MicroSeconds::from(other);
        self_us.checked_add(other_us).and_then(|i| Some(i.into()))
    }

    /// Checked integer addition. Computes `self + rhs`, returning `None` if overflow occurred,
    /// using the inner integer’s `checked_add()` method.
    pub fn checked_add_us(self, rhs: MicroSeconds) -> Option<Self> {
        let self_us = MicroSeconds::from(self);
        self_us.checked_add(rhs).and_then(|i| Some(i.into()))
    }

    /// Checked integer addition. Computes `self + rhs`, returning `None` if overflow occurred,
    /// using the inner integer’s `checked_add()` method.
    pub fn checked_add_duration(self, rhs: Duration) -> Option<Self> {
        let self_us = MicroSeconds::from(self);
        let rhs_us = MicroSeconds::try_from(rhs).ok()?;
        self_us.checked_add(rhs_us).and_then(|i| Some(i.into()))
    }

    /// Checked integer subtraction. Computes `self - rhs`, returning `None` if overflow occurred,
    /// using the inner integer’s `checked_sub()` method.
    pub fn checked_sub(self, other: Self) -> Option<Self> {
        let self_us = MicroSeconds::from(self);
        let other_us = MicroSeconds::from(other);
        self_us.checked_sub(other_us).and_then(|i| Some(i.into()))
    }

    /// Checked integer subtraction. Computes `self - rhs`, returning `None` if overflow occurred,
    /// using the inner integer’s `checked_sub()` method.
    pub fn checked_sub_us(self, rhs: MicroSeconds) -> Option<Self> {
        let self_us = MicroSeconds::from(self);
        self_us.checked_sub(rhs).and_then(|i| Some(i.into()))
    }

    /// Checked integer subtraction. Computes `self - rhs`, returning `None` if overflow occurred,
    /// using the inner integer’s `checked_sub()` method.
    pub fn checked_sub_duration(self, rhs: Duration) -> Option<Self> {
        let self_us = MicroSeconds::from(self);
        let rhs_us = MicroSeconds::try_from(rhs).ok()?;
        self_us.checked_sub(rhs_us).and_then(|i| Some(i.into()))
    }

    /// Checked integer multiplication. Computes `self * rhs`, returning `None` if overflow
    /// occurred, using the inner integer’s `checked_mul()` method.
    pub fn checked_mul(self, rhs: u32) -> Option<Self> {
        let self_us = MicroSeconds::from(self);
        self_us.checked_mul(rhs).and_then(|i| Some(i.into()))
    }

    /// Checked integer division. Computes `self / rhs`, returning `None` if `rhs == 0`, using the
    /// inner integer’s `checked_div()` method.
    pub fn checked_div(self, rhs: u32) -> Option<Self> {
        let self_us = MicroSeconds::from(self);
        self_us.checked_div(rhs).and_then(|i| Some(i.into()))
    }

    /// Checked integer remainder. Computes `self % rhs`, returning `None` if `rhs == 0`, using the
    /// inner integer’s `checked_rem()` method.
    pub fn checked_rem(self, rhs: u32) -> Option<Self> {
        let self_us = MicroSeconds::from(self);
        self_us.checked_rem(rhs).and_then(|i| Some(i.into()))
    }
}

impl std::fmt::Debug for Timeval {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        write!(f, "timeval {{ tv_sec: {}, tv_usec: {} }}", self.0.tv_sec, self.0.tv_usec)
    }
}

impl Add for Timeval {
    type Output = Self;

    #[track_caller]
    #[inline]
    fn add(self, other: Self) -> Self {
        self.checked_add(other).expect(op_err::ADD)
    }
}
impl AddAssign for Timeval {
    #[track_caller]
    #[inline]
    fn add_assign(&mut self, rhs: Self) {
        *self = self.add(rhs);
    }
}

impl Sub for Timeval {
    type Output = Self;

    #[track_caller]
    #[inline]
    fn sub(self, other: Self) -> Self {
        self.checked_sub(other).expect(op_err::SUB)
    }
}
impl SubAssign for Timeval {
    #[track_caller]
    #[inline]
    fn sub_assign(&mut self, rhs: Self) {
        *self = self.sub(rhs);
    }
}

////////////////////////////////////////////////////////////////////////////////////////////////////
// Operations with `MicroSeconds`
////////////////////////////////////////////////////////////////////////////////////////////////////

impl Add<MicroSeconds> for Timeval {
    type Output = Self;

    #[track_caller]
    #[inline]
    fn add(self, rhs: MicroSeconds) -> Self {
        self.checked_add_us(rhs).expect(op_err::ADD)
    }
}
impl AddAssign<MicroSeconds> for Timeval {
    #[track_caller]
    #[inline]
    fn add_assign(&mut self, rhs: MicroSeconds) {
        *self = self.add(rhs);
    }
}

impl Sub<MicroSeconds> for Timeval {
    type Output = Self;

    #[track_caller]
    #[inline]
    fn sub(self, rhs: MicroSeconds) -> Self {
        self.checked_sub_us(rhs).expect(op_err::SUB)
    }
}
impl SubAssign<MicroSeconds> for Timeval {
    #[track_caller]
    #[inline]
    fn sub_assign(&mut self, rhs: MicroSeconds) {
        *self = self.sub(rhs);
    }
}

////////////////////////////////////////////////////////////////////////////////////////////////////
// Operations with `Duration`
////////////////////////////////////////////////////////////////////////////////////////////////////

impl Add<Duration> for Timeval {
    type Output = Self;

    #[track_caller]
    #[inline]
    fn add(self, rhs: Duration) -> Self {
        self.checked_add_duration(rhs).expect(op_err::ADD)
    }
}
impl AddAssign<Duration> for Timeval {
    #[track_caller]
    #[inline]
    fn add_assign(&mut self, rhs: Duration) {
        *self = self.add(rhs);
    }
}

impl Sub<Duration> for Timeval {
    type Output = Self;

    #[track_caller]
    #[inline]
    fn sub(self, rhs: Duration) -> Self {
        self.checked_sub_duration(rhs).expect(op_err::SUB)
    }
}
impl SubAssign<Duration> for Timeval {
    #[track_caller]
    #[inline]
    fn sub_assign(&mut self, rhs: Duration) {
        *self = self.sub(rhs);
    }
}

////////////////////////////////////////////////////////////////////////////////////////////////////
// Operations with primitives
////////////////////////////////////////////////////////////////////////////////////////////////////

impl Mul<u32> for Timeval {
    type Output = Self;

    #[track_caller]
    #[inline]
    fn mul(self, rhs: u32) -> Self {
        self.checked_mul(rhs).expect(op_err::MUL)
    }
}
impl MulAssign<u32> for Timeval {
    #[track_caller]
    #[inline]
    fn mul_assign(&mut self, rhs: u32) {
        *self = self.mul(rhs);
    }
}

impl Div<u32> for Timeval {
    type Output = Self;

    #[track_caller]
    #[inline]
    fn div(self, rhs: u32) -> Self {
        self.checked_div(rhs).expect(op_err::DIV)
    }
}
impl DivAssign<u32> for Timeval {
    #[track_caller]
    #[inline]
    fn div_assign(&mut self, rhs: u32) {
        *self = self.div(rhs);
    }
}

impl Rem<u32> for Timeval {
    type Output = Self;

    #[track_caller]
    #[inline]
    fn rem(self, rhs: u32) -> Self {
        self.checked_rem(rhs).expect(op_err::REM)
    }
}
impl RemAssign<u32> for Timeval {
    #[track_caller]
    #[inline]
    fn rem_assign(&mut self, rhs: u32) {
        *self = self.rem(rhs);
    }
}
