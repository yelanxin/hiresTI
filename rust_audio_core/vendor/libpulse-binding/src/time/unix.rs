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

//! Unix timestamps.

use std::ops::{Add, AddAssign, Sub, SubAssign};
use super::{Timeval, MicroSeconds, op_err};

/// A Unix timestamp.
#[repr(transparent)]
#[derive(Copy, Clone, Debug, Eq, PartialEq, Ord, PartialOrd)]
pub struct UnixTs(pub(crate) Timeval);

impl UnixTs {
    /// Gets the current ‘time of day’.
    pub fn now() -> Self {
        let mut tv = Timeval::new_zero();
        unsafe { capi::pa_gettimeofday(&mut tv.0) };
        Self(tv)
    }

    /// Calculates the difference between the two specified timestamps.
    #[inline]
    pub fn diff(a: &Self, b: &Self) -> MicroSeconds {
        MicroSeconds(unsafe { capi::pa_timeval_diff(&(a.0).0, &(b.0).0) })
    }

    /// Gets the time difference between now and self.
    #[inline]
    pub fn age(&self) -> MicroSeconds {
        MicroSeconds(unsafe { capi::pa_timeval_age(&(self.0).0) })
    }

    /// Checked integer addition. Computes `self + rhs`, returning `None` if overflow occurred,
    /// using the inner integer’s [`checked_add()`](Timeval::checked_add) method.
    #[inline]
    pub fn checked_add(self, rhs: MicroSeconds) -> Option<Self> {
        self.0.checked_add_us(rhs).and_then(|us| Some(Self(us)))
    }

    /// Checked integer subtraction. Computes `self - rhs`, returning `None` if overflow occurred,
    /// using the inner integer’s [`checked_sub()`](Timeval::checked_sub) method.
    #[inline]
    pub fn checked_sub(self, rhs: MicroSeconds) -> Option<Self> {
        self.0.checked_sub_us(rhs).and_then(|us| Some(Self(us)))
    }
}

impl std::fmt::Display for UnixTs {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        write!(f, "{:?}", self.0)
    }
}

impl Add<MicroSeconds> for UnixTs {
    type Output = Self;

    #[track_caller]
    #[inline]
    fn add(self, rhs: MicroSeconds) -> Self {
        self.checked_add(rhs).expect(op_err::ADD)
    }
}
impl AddAssign<MicroSeconds> for UnixTs {
    #[track_caller]
    #[inline]
    fn add_assign(&mut self, rhs: MicroSeconds) {
        *self = self.add(rhs);
    }
}

impl Sub<MicroSeconds> for UnixTs {
    type Output = Self;

    #[track_caller]
    #[inline]
    fn sub(self, rhs: MicroSeconds) -> Self {
        self.checked_sub(rhs).expect(op_err::SUB)
    }
}
impl SubAssign<MicroSeconds> for UnixTs {
    #[track_caller]
    #[inline]
    fn sub_assign(&mut self, rhs: MicroSeconds) {
        *self = self.sub(rhs);
    }
}
