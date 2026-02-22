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

//! Daemon introspection event subscription subsystem.
//!
//! # Overview
//!
//! The application can be notified, asynchronously, whenever the internal layout of the server
//! changes. The set of facilities and operations for which notifications are generated are
//! enumerated in [`Facility`] and [`Operation`].
//!
//! The application sets the notification mask using [`Context::subscribe()`] and the callback
//! function that will be called whenever a notification occurs using
//! [`Context::set_subscribe_callback()`].
//!
//! The mask provided to [`Context::subscribe()`] can be created by binary ORing a set of values,
//! either produced with [`Facility::to_interest_mask()`], or more simply with the provided
//! constants in the [`subscription_masks`](mod@subscription_masks) submodule.
//!
//! The callback will be called with event type information representing the event that caused the
//! callback, detailing *facility* and *operation*, where for instance [`Facility::Source`] with
//! [`Operation::New`] indicates that a new source was added.
//!
//! # Example
//!
//! Subscribe (declare interest):
//!
//! ```rust,ignore
//! use libpulse_binding::context::subscribe::subscription_masks;
//!
//! let interest = subscription_masks::SINK |
//!     subscription_masks::SOURCE;
//!
//! let op = my_context.subscribe(
//!     interest,   // Our interest mask
//!     |_| {}      // We won’t bother doing anything in the success callback in this example
//! );
//! ```

use std::os::raw::c_void;
use bitflags::bitflags;
use num_derive::{FromPrimitive, ToPrimitive};
use super::{ContextInternal, Context};
use crate::operation;
use crate::callbacks::{box_closure_get_capi_ptr, MultiUseCallback};

pub use capi::context::subscribe::pa_subscription_event_type_t as EventType;

bitflags! {
    /// A set of facility masks, to be passed to [`Context::subscribe()`].
    ///
    /// Note that you can convert a [`Facility`] to a mask with [`Facility::to_interest_mask()`].
    #[derive(Debug, Copy, Clone, PartialEq, Eq)]
    #[repr(transparent)]
    pub struct InterestMaskSet: u32 {
        /// No facility (null selection; zero).
        const NULL = capi::PA_SUBSCRIPTION_MASK_NULL;
        /// Sink facility.
        const SINK = capi::PA_SUBSCRIPTION_MASK_SINK;
        /// Source facility.
        const SOURCE = capi::PA_SUBSCRIPTION_MASK_SOURCE;
        /// Sink input facility.
        const SINK_INPUT = capi::PA_SUBSCRIPTION_MASK_SINK_INPUT;
        /// Source output facility.
        const SOURCE_OUTPUT = capi::PA_SUBSCRIPTION_MASK_SOURCE_OUTPUT;
        /// Module facility.
        const MODULE = capi::PA_SUBSCRIPTION_MASK_MODULE;
        /// Client facility.
        const CLIENT = capi::PA_SUBSCRIPTION_MASK_CLIENT;
        /// Sample cache facility.
        const SAMPLE_CACHE = capi::PA_SUBSCRIPTION_MASK_SAMPLE_CACHE;
        /// Server facility.
        const SERVER = capi::PA_SUBSCRIPTION_MASK_SERVER;
        /// Card facility.
        const CARD = capi::PA_SUBSCRIPTION_MASK_CARD;
        /// All facilities.
        const ALL = capi::PA_SUBSCRIPTION_MASK_ALL;
    }
}

/// Facility component of an event.
#[repr(u32)]
#[derive(Debug, Copy, Clone, PartialEq, Eq)]
#[derive(FromPrimitive, ToPrimitive)]
pub enum Facility {
    /// Sink.
    Sink         = 0,
    /// Source.
    Source       = 1,
    /// Sink-input.
    SinkInput    = 2,
    /// Source-output.
    SourceOutput = 3,
    /// Module.
    Module       = 4,
    /// Client.
    Client       = 5,
    /// Sample-cache.
    SampleCache  = 6,
    /// Global server change, only occurring with [`Operation::Changed`].
    Server       = 7,
    /* NOTE: value `8` previously assigned, obsoleted */
    /// Card.
    Card         = 9,
}

/// Operation component of an event.
#[repr(u32)]
#[derive(Debug, Copy, Clone, PartialEq, Eq)]
#[derive(FromPrimitive, ToPrimitive)]
pub enum Operation {
    /// A new object was created
    New     = 0,
    /// A property of the object was modified
    Changed = 0x10,
    /// An object was removed
    Removed = 0x20,
}

impl Facility {
    /// Mask to extract facility value from the event type passed to the user callback.
    pub const MASK: EventType = capi::PA_SUBSCRIPTION_EVENT_FACILITY_MASK;

    fn from_event(value: EventType) -> Option<Facility> {
        match value & Self::MASK {
            0 => Some(Facility::Sink),
            1 => Some(Facility::Source),
            2 => Some(Facility::SinkInput),
            3 => Some(Facility::SourceOutput),
            4 => Some(Facility::Module),
            5 => Some(Facility::Client),
            6 => Some(Facility::SampleCache),
            7 => Some(Facility::Server),
            /* NOTE: value `8` previously assigned, obsoleted */
            9 => Some(Facility::Card),
            _ => None,
        }
    }

    /// Converts to an interest mask.
    #[inline(always)]
    pub const fn to_interest_mask(self) -> InterestMaskSet {
        InterestMaskSet::from_bits_truncate(1u32 << (self as u32))
    }
}

impl Operation {
    /// Mask to extract operation value from the event type passed to the user callback.
    pub const MASK: EventType = capi::PA_SUBSCRIPTION_EVENT_TYPE_MASK;

    fn from_event(value: EventType) -> Option<Operation> {
        match value & Self::MASK {
            0 => Some(Operation::New),
            0x10 => Some(Operation::Changed),
            0x20 => Some(Operation::Removed),
            _ => None,
        }
    }
}

pub(super) type Callback = MultiUseCallback<dyn FnMut(Option<Facility>, Option<Operation>, u32),
    extern "C" fn(*mut ContextInternal, EventType, u32, *mut c_void)>;

impl Context {
    /// Enables event notification.
    ///
    /// The `mask` parameter is used to specify which facilities you are interested in being
    /// modified about. Use [`set_subscribe_callback()`] to set the actual callback that will be
    /// called when an event occurs.
    ///
    /// The callback must accept a `bool`, which indicates success.
    ///
    /// Panics if the underlying C function returns a null pointer.
    ///
    /// [`set_subscribe_callback()`]: Self::set_subscribe_callback
    pub fn subscribe<F>(&mut self, mask: InterestMaskSet, callback: F)
        -> operation::Operation<dyn FnMut(bool)>
        where F: FnMut(bool) + 'static
    {
        let cb_data = box_closure_get_capi_ptr::<dyn FnMut(bool)>(Box::new(callback));
        let ptr = unsafe { capi::pa_context_subscribe(self.ptr, mask.bits(),
            Some(super::success_cb_proxy), cb_data) };
        operation::Operation::from_raw(ptr, cb_data as *mut Box<dyn FnMut(bool)>)
    }

    /// Sets the context specific call back function that is called whenever a subscribed-to event
    /// occurs.
    ///
    /// Use [`subscribe()`] to set the facilities you are interested in receiving notifications for,
    /// and thus to start receiving notifications with the callback set here.
    ///
    /// The callback must take three parameters. The first two are the facility and operation
    /// components of the event type respectively (the underlying C API provides this information
    /// combined into a single integer, here we extract the two component parts for you); these are
    /// wrapped in `Option` wrappers should the given values ever not map to the enum variants, but
    /// it’s probably safe to always just `unwrap()` them). The third parameter is an associated
    /// index value.
    ///
    /// [`subscribe()`]: Self::subscribe
    pub fn set_subscribe_callback(&mut self,
        callback: Option<Box<dyn FnMut(Option<Facility>, Option<Operation>, u32) + 'static>>)
    {
        let saved = &mut self.cb_ptrs.subscribe;
        *saved = Callback::new(callback);
        let (cb_fn, cb_data) = saved.get_capi_params(cb_proxy);
        unsafe { capi::pa_context_set_subscribe_callback(self.ptr, cb_fn, cb_data); }
    }
}

/// Proxy for callbacks.
///
/// Warning: This is for multi-use cases! It does **not** destroy the actual closure callback, which
/// must be accomplished separately to avoid a memory leak.
extern "C"
fn cb_proxy(_: *mut ContextInternal, et: EventType, index: u32, userdata: *mut c_void) {
    let _ = std::panic::catch_unwind(|| {
        let facility = Facility::from_event(et);
        let operation = Operation::from_event(et);
        let callback = Callback::get_callback(userdata);
        (callback)(facility, operation, index);
    });
}
