// Copyright 2017 Lyndon Brown
//
// This file is part of the PulseAudio Rust language linking library.
//
// Licensed under the MIT license or the Apache license (version 2.0), at your option. You may not
// copy, modify, or distribute this file except in compliance with said license. You can find copies
// of these licenses either in the LICENSE-MIT and LICENSE-APACHE files, or alternatively at
// <http://opensource.org/licenses/MIT> and <http://www.apache.org/licenses/LICENSE-2.0>
// respectively.
//
// Portions of documentation are copied from the LGPL 2.1+ licensed PulseAudio C headers on a
// fair-use basis, as discussed in the overall project readme (available in the git repository).

//! Daemon introspection event subscription subsystem.

use std::os::raw::c_void;
use crate::operation::pa_operation;

/// The base integer type passed to the callback, from which the facility and operation components
/// can be extracted.
pub type pa_subscription_event_type_t = u32;

/// Used to express what facilities you are interested in when subscribing.
pub type pa_subscription_mask_t = u32;

/// Mask to extract facility value from the event type passed to the user callback.
pub const PA_SUBSCRIPTION_EVENT_FACILITY_MASK: pa_subscription_event_type_t = 0xf;
/// Mask to extract operation value from the event type passed to the user callback.
pub const PA_SUBSCRIPTION_EVENT_TYPE_MASK:     pa_subscription_event_type_t = 0x30;

pub use self::subscription_masks::*;

/// A set of masks used for expressing which facilities you are interested in when subscribing.
pub mod subscription_masks {
    use super::pa_subscription_mask_t;

    pub const PA_SUBSCRIPTION_MASK_NULL:          pa_subscription_mask_t = 0;
    pub const PA_SUBSCRIPTION_MASK_SINK:          pa_subscription_mask_t = 1 << 0;
    pub const PA_SUBSCRIPTION_MASK_SOURCE:        pa_subscription_mask_t = 1 << 1;
    pub const PA_SUBSCRIPTION_MASK_SINK_INPUT:    pa_subscription_mask_t = 1 << 2;
    pub const PA_SUBSCRIPTION_MASK_SOURCE_OUTPUT: pa_subscription_mask_t = 1 << 3;
    pub const PA_SUBSCRIPTION_MASK_MODULE:        pa_subscription_mask_t = 1 << 4;
    pub const PA_SUBSCRIPTION_MASK_CLIENT:        pa_subscription_mask_t = 1 << 5;
    pub const PA_SUBSCRIPTION_MASK_SAMPLE_CACHE:  pa_subscription_mask_t = 1 << 6;
    pub const PA_SUBSCRIPTION_MASK_SERVER:        pa_subscription_mask_t = 1 << 7;
    /* NOTE: value `0x100` previously assigned, obsoleted */
    pub const PA_SUBSCRIPTION_MASK_CARD:          pa_subscription_mask_t = 1 << 9;
    pub const PA_SUBSCRIPTION_MASK_ALL:           pa_subscription_mask_t = 0x2ff;
}

pub use self::event_facilities::*;

/// Possible facility variants that could be extracted from an event type.
pub mod event_facilities {
    use super::pa_subscription_event_type_t;

    pub const PA_SUBSCRIPTION_EVENT_SINK:          pa_subscription_event_type_t = 0;
    pub const PA_SUBSCRIPTION_EVENT_SOURCE:        pa_subscription_event_type_t = 1;
    pub const PA_SUBSCRIPTION_EVENT_SINK_INPUT:    pa_subscription_event_type_t = 2;
    pub const PA_SUBSCRIPTION_EVENT_SOURCE_OUTPUT: pa_subscription_event_type_t = 3;
    pub const PA_SUBSCRIPTION_EVENT_MODULE:        pa_subscription_event_type_t = 4;
    pub const PA_SUBSCRIPTION_EVENT_CLIENT:        pa_subscription_event_type_t = 5;
    pub const PA_SUBSCRIPTION_EVENT_SAMPLE_CACHE:  pa_subscription_event_type_t = 6;
    /// Global server change, only occurring with a change operation.
    pub const PA_SUBSCRIPTION_EVENT_SERVER:        pa_subscription_event_type_t = 7;
    /* NOTE: value `8` previously assigned, obsoleted */
    pub const PA_SUBSCRIPTION_EVENT_CARD:          pa_subscription_event_type_t = 9;
}

pub use self::event_operations::*;

/// Possible operation variants that could be extracted from an event type.
pub mod event_operations {
    use super::pa_subscription_event_type_t;

    pub const PA_SUBSCRIPTION_EVENT_NEW:    pa_subscription_event_type_t = 0;
    pub const PA_SUBSCRIPTION_EVENT_CHANGE: pa_subscription_event_type_t = 0x10;
    pub const PA_SUBSCRIPTION_EVENT_REMOVE: pa_subscription_event_type_t = 0x20;
}

/// Checks if event type `t` matches an event mask bitfield (returns `true` if so).
pub const fn pa_subscription_match_flags(m: pa_subscription_mask_t, t: pa_subscription_event_type_t)
    -> bool
{
    (m & (1 << (t & PA_SUBSCRIPTION_EVENT_FACILITY_MASK))) != 0
}

#[rustfmt::skip]
pub type pa_context_subscribe_cb_t = Option<extern "C" fn(c: *mut super::pa_context, t: pa_subscription_event_type_t, idx: u32, userdata: *mut c_void)>;

#[rustfmt::skip]
#[link(name = "pulse")]
extern "C" {
    pub fn pa_context_subscribe(c: *mut super::pa_context, m: pa_subscription_mask_t, cb: super::pa_context_success_cb_t, userdata: *mut c_void) -> *mut pa_operation;
    pub fn pa_context_set_subscribe_callback(c: *mut super::pa_context, cb: pa_context_subscribe_cb_t, userdata: *mut c_void);
}
