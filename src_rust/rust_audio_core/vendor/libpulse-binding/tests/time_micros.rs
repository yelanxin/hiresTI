// Copyright 2020 Lyndon Brown
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

//! Testing `MicroSeconds` operations
//!
//! (Covering stuff not already done in doc tests).

extern crate libpulse_binding as pulse;

use std::time::Duration;
use pulse::time::MicroSeconds;

// Check basic addition / subtraction implementations
#[test]
fn math() {
    let mut a = MicroSeconds(30);
    let b = MicroSeconds(10);
    assert_eq!(a + b, MicroSeconds(40));
    assert_eq!(a - b, MicroSeconds(20));
    a += b;
    assert_eq!(a, MicroSeconds(40));
    a -= b;
    assert_eq!(a, MicroSeconds(30));
}

// Test that basic addition overflow panics
#[test]
#[should_panic]
fn add_overflow() {
    let _ = MicroSeconds::MAX + MicroSeconds(10);
}

// Test that basic subtraction overflow panics
#[test]
#[should_panic]
fn sub_overflow() {
    let _ = MicroSeconds(10) - MicroSeconds(20);
}

////////////////////////////////////////////////////////////////////////////////////////////////////
// Operations with `Duration`
////////////////////////////////////////////////////////////////////////////////////////////////////

#[test]
fn duration_math() {
    assert_eq!(MicroSeconds(300_000) + Duration::new(2, 0), MicroSeconds(2_300_000));
    assert_eq!(MicroSeconds(3_500_000) - Duration::new(2, 0), MicroSeconds(1_500_000));
    let mut x = MicroSeconds(300_000);
    x += Duration::new(2, 0);
    assert_eq!(x, MicroSeconds(2_300_000));
    x -= Duration::new(2, 0);
    assert_eq!(x, MicroSeconds(300_000));

    assert_eq!(Duration::new(2, 0) + MicroSeconds(300_000), Duration::new(2, 300_000_000));
    assert_eq!(Duration::new(2, 0) - MicroSeconds(1_500_000), Duration::new(0, 500_000_000));
    let mut x = Duration::new(2, 0);
    x += MicroSeconds(300_000);
    assert_eq!(x, Duration::new(2, 300_000_000));
    x -= MicroSeconds(1_500_000);
    assert_eq!(x, Duration::new(0, 800_000_000));
}

// Test that basic addition overflow panics
#[test]
#[should_panic]
fn duration_add_overflow_to_micros() {
    let _ = MicroSeconds::MAX + Duration::new(2, 0);
}

// Test that basic addition overflow panics
#[test]
#[should_panic]
fn duration_add_overflow_to_duration() {
    let _ = Duration::new(std::u64::MAX, 0) + MicroSeconds::MAX;
}

// Test that basic subtraction overflow panics
#[test]
#[should_panic]
fn duration_sub_overflow_to_micros() {
    let _ = MicroSeconds(10) - Duration::new(1, 0);
}

// Test that basic subtraction overflow panics
#[test]
#[should_panic]
fn duration_sub_overflow_to_duration() {
    let _ = Duration::new(1, 0) - MicroSeconds(2_000_000);
}

////////////////////////////////////////////////////////////////////////////////////////////////////
// Operations with primitives
////////////////////////////////////////////////////////////////////////////////////////////////////

#[test]
fn primitives() {
    assert_eq!(MicroSeconds::SECOND * 2, MicroSeconds(2_000_000));
    assert_eq!(2 * MicroSeconds::SECOND, MicroSeconds(2_000_000));
    let mut x = MicroSeconds::SECOND;
    x *= 2;
    assert_eq!(x, MicroSeconds(2_000_000));

    assert_eq!(MicroSeconds::SECOND / 2, MicroSeconds(500_000));
    let mut x = MicroSeconds::SECOND;
    x /= 2;
    assert_eq!(x, MicroSeconds(500_000));

    assert_eq!(MicroSeconds(200_000) % 7, MicroSeconds(3));
    let mut x = MicroSeconds(200_000);
    x %= 7;
    assert_eq!(x, MicroSeconds(3));
}
