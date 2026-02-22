// Copyright The pipewire-rs Contributors.
// SPDX-License-Identifier: MIT

//! The `libspa` crate provides a high-level API to interact with
//! [libspa](https://gitlab.freedesktop.org/pipewire/pipewire/-/tree/master/doc/spa).

pub mod buffer;
pub mod param;
pub mod pod;
pub mod support;
pub mod utils;

pub use spa_sys as sys;

/// prelude module re-exporing all the traits providing public API.
pub mod prelude {}
