// Copyright The pipewire-rs Contributors.
// SPDX-License-Identifier: MIT

#![allow(non_upper_case_globals)]
#![allow(non_camel_case_types)]
#![allow(non_snake_case)]

#[allow(clippy::all)]
// FIXME: Remove when https://github.com/rust-lang/rust-bindgen/issues/1651 is closed
#[allow(deref_nullptr)]
mod bindings {
    include!(concat!(env!("OUT_DIR"), "/bindings.rs"));
}
pub use bindings::*;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn init() {
        unsafe {
            pw_init(std::ptr::null_mut(), std::ptr::null_mut());
            pw_deinit();
        }
    }
}
