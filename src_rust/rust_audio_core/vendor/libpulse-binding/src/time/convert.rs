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

//! Implementation of conversions between the types.

use super::*;

// To `MicroSeconds`

impl TryFrom<Duration> for MicroSeconds {
    type Error = ();

    #[inline]
    fn try_from(t: Duration) -> Result<Self, Self::Error> {
        let secs_as_micros = t.as_secs().checked_mul(MICROS_PER_SEC).ok_or(())?;
        let total_micros = secs_as_micros.checked_add(t.subsec_micros() as u64).ok_or(())?;
        Ok(MicroSeconds(total_micros))
    }
}

impl From<Timeval> for MicroSeconds {
    #[inline]
    fn from(t: Timeval) -> Self {
        MicroSeconds(unsafe { capi::pa_timeval_load(&t.0) })
    }
}

// To `Duration`

impl From<MicroSeconds> for Duration {
    #[inline]
    fn from(t: MicroSeconds) -> Self {
        Duration::from_micros(t.0)
    }
}

impl From<Timeval> for Duration {
    #[inline]
    fn from(t: Timeval) -> Self {
        Duration::from_micros((MicroSeconds::from(t)).0)
    }
}

// To `Timeval`

impl From<MicroSeconds> for Timeval {
    #[inline]
    fn from(t: MicroSeconds) -> Self {
        let secs = (t.0 / MICROS_PER_SEC) as super::timeval::TvSecs;
        let micros = (t.0 % MICROS_PER_SEC) as super::timeval::TvUsecs;
        Timeval::new(secs, micros)
    }
}

impl From<Duration> for Timeval {
    #[inline]
    fn from(t: Duration) -> Self {
        let secs = t.as_secs() as super::timeval::TvSecs;
        let micros = t.subsec_micros() as super::timeval::TvUsecs;
        Timeval::new(secs, micros)
    }
}

#[test]
fn tests() {
    let micro = MicroSeconds(2_700_000);
    let duration = Duration::from_micros(2_700_000);
    let timeval = Timeval::new(2, 700_000);

    assert_eq!(MicroSeconds::try_from(duration).unwrap(), micro);
    assert_eq!(MicroSeconds::from(timeval), micro);

    assert_eq!(Duration::from(micro), duration);
    assert_eq!(Duration::from(timeval), duration);

    assert_eq!(Timeval::from(micro), timeval);
    assert_eq!(Timeval::from(duration), timeval);
}
