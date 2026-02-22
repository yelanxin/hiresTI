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

//! Monotonic timestamps.

use std::ops::{Add, AddAssign, Sub, SubAssign};
use std::time::Duration;
use super::{MicroSeconds, op_err};

/// A monotonic timestamp.
#[derive(Copy, Clone, Debug, Default, Eq, PartialEq, Ord, PartialOrd)]
pub struct MonotonicTs(pub(crate) MicroSeconds);

impl MonotonicTs {
    /// Gets the current monotonic system time in microseconds.
    ///
    /// Note, if such a clock is not available then this will actually fall back to the wallclock
    /// time instead. No indication is available for whether or not this is the case, and the
    /// return value is still a `MonotonicTs` type.
    #[inline]
    pub fn now() -> Self {
        Self(MicroSeconds(unsafe { capi::pa_rtclock_now() }))
    }

    /// Returns `true` so long as inner value is not [`MicroSeconds::INVALID`].
    #[inline]
    pub fn is_valid(&self) -> bool {
        self.0.is_valid()
    }

    /// Checked integer addition. Computes `self + rhs`, returning `None` if overflow occurred,
    /// using the inner [`MicroSeconds`]’s [`checked_add()`](MicroSeconds::checked_add) method.
    #[inline]
    pub fn checked_add(self, rhs: MicroSeconds) -> Option<Self> {
        self.0.checked_add(rhs).and_then(|us| Some(Self(us)))
    }

    /// Checked integer addition. Computes `self + rhs`, returning `None` if overflow occurred,
    /// using the inner integer’s `checked_add()` method.
    #[inline]
    pub fn checked_add_duration(self, rhs: Duration) -> Option<Self> {
        self.0.checked_add_duration(rhs).and_then(|i| Some(Self(i)))
    }

    /// Checked integer subtraction. Computes `self - rhs`, returning `None` if overflow occurred,
    /// using the inner [`MicroSeconds`]’s [`checked_sub()`](MicroSeconds::checked_sub) method.
    #[inline]
    pub fn checked_sub(self, rhs: MicroSeconds) -> Option<Self> {
        self.0.checked_sub(rhs).and_then(|us| Some(Self(us)))
    }

    /// Checked integer subtraction. Computes `self - rhs`, returning `None` if overflow occurred,
    /// using the inner integer’s `checked_sub()` method.
    #[inline]
    pub fn checked_sub_duration(self, rhs: Duration) -> Option<Self> {
        self.0.checked_sub_duration(rhs).and_then(|i| Some(Self(i)))
    }
}

impl std::fmt::Display for MonotonicTs {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        write!(f, "{}", self.0)
    }
}

impl Add<MicroSeconds> for MonotonicTs {
    type Output = Self;

    #[track_caller]
    #[inline]
    fn add(self, rhs: MicroSeconds) -> Self {
        self.checked_add(rhs).expect(op_err::ADD)
    }
}
impl AddAssign<MicroSeconds> for MonotonicTs {
    #[track_caller]
    #[inline]
    fn add_assign(&mut self, rhs: MicroSeconds) {
        *self = self.add(rhs);
    }
}

impl Sub<MicroSeconds> for MonotonicTs {
    type Output = Self;

    #[track_caller]
    #[inline]
    fn sub(self, rhs: MicroSeconds) -> Self {
        self.checked_sub(rhs).expect(op_err::SUB)
    }
}
impl SubAssign<MicroSeconds> for MonotonicTs {
    #[track_caller]
    #[inline]
    fn sub_assign(&mut self, rhs: MicroSeconds) {
        *self = self.sub(rhs);
    }
}

impl Add<Duration> for MonotonicTs {
    type Output = Self;

    #[track_caller]
    #[inline]
    fn add(self, rhs: Duration) -> Self {
        Self(self.0.add(rhs))
    }
}
impl AddAssign<Duration> for MonotonicTs {
    #[track_caller]
    #[inline]
    fn add_assign(&mut self, rhs: Duration) {
        *self = self.add(rhs);
    }
}

impl Sub<Duration> for MonotonicTs {
    type Output = Self;

    #[track_caller]
    #[inline]
    fn sub(self, rhs: Duration) -> Self {
        Self(self.0.sub(rhs))
    }
}
impl SubAssign<Duration> for MonotonicTs {
    #[track_caller]
    #[inline]
    fn sub_assign(&mut self, rhs: Duration) {
        *self = self.sub(rhs);
    }
}
