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

//! Standard/minimal main loop implementation based on poll().
//!
//! # Overview
//!
//! This ‘standard’ (minimal) main loop implementation is based on the poll() system call. It
//! supports the functions defined in the main loop abstraction
//! ([`mainloop::api`](mod@crate::mainloop::api)) and very little else.
//!
//! This implementation is thread safe as long as you access the main loop object from a single
//! thread only.
//!
//! # Usage
//!
//! A [`Mainloop`] is created using [`Mainloop::new()`]. To get access to the main loop abstraction,
//! [`Mainloop::get_api()`] is used.
//!
//! Destruction of the [`Mainloop`] object is done automatically when the object falls out of scope.
//! (Rust’s `Drop` trait has been implemented and takes care of it).
//!
//! # Iteration
//!
//! The main loop is designed around the concept of iterations. Each iteration consists of three
//! steps that repeat during the application’s entire lifetime:
//!
//! * Prepare - Build a list of file descriptors that need to be monitored and calculate the next
//!   timeout.
//! * Poll - Execute the actual poll() system call.
//! * Dispatch - Dispatch any events that have fired.
//!
//! When using the main loop, the application can either execute each iteration, one at a time,
//! using [`Mainloop::iterate()`], or let the library iterate automatically using
//! [`Mainloop::run()`].
//!
//! # Threads
//!
//! The main loop functions are designed to be thread safe, but the objects are not. What this means
//! is that multiple main loops can be used, but only one object per thread.
//!
//! # Example
//!
//! An example program using the standard mainloop:
//!
//! ```rust
//! extern crate libpulse_binding as pulse;
//!
//! use std::sync::atomic;
//! use std::rc::Rc;
//! use std::cell::RefCell;
//! use std::ops::Deref;
//! use pulse::mainloop::standard::Mainloop;
//! use pulse::context::{Context, FlagSet as ContextFlagSet};
//! use pulse::stream::{Stream, FlagSet as StreamFlagSet};
//! use pulse::sample::{Spec, Format};
//! use pulse::proplist::Proplist;
//! use pulse::mainloop::standard::IterateResult;
//! use pulse::def::Retval;
//!
//! fn main() {
//!     let spec = Spec {
//!         format: Format::S16NE,
//!         channels: 2,
//!         rate: 44100,
//!     };
//!     assert!(spec.is_valid());
//!
//!     let mut proplist = Proplist::new().unwrap();
//!     proplist.set_str(pulse::proplist::properties::APPLICATION_NAME, "FooApp")
//!         .unwrap();
//!
//!     let mut mainloop = Rc::new(RefCell::new(Mainloop::new()
//!         .expect("Failed to create mainloop")));
//!
//!     let mut context = Rc::new(RefCell::new(Context::new_with_proplist(
//!         mainloop.borrow().deref(),
//!         "FooAppContext",
//!         &proplist
//!         ).expect("Failed to create new context")));
//!
//!     context.borrow_mut().connect(None, ContextFlagSet::NOFLAGS, None)
//!         .expect("Failed to connect context");
//!
//!     // Wait for context to be ready
//!     loop {
//!         match mainloop.borrow_mut().iterate(false) {
//!             IterateResult::Quit(_) |
//!             IterateResult::Err(_) => {
//!                 eprintln!("Iterate state was not success, quitting...");
//!                 return;
//!             },
//!             IterateResult::Success(_) => {},
//!         }
//!         match context.borrow().get_state() {
//!             pulse::context::State::Ready => { break; },
//!             pulse::context::State::Failed |
//!             pulse::context::State::Terminated => {
//!                 eprintln!("Context state failed/terminated, quitting...");
//!                 return;
//!             },
//!             _ => {},
//!         }
//!     }
//!
//!     let mut stream = Rc::new(RefCell::new(Stream::new(
//!         &mut context.borrow_mut(),
//!         "Music",
//!         &spec,
//!         None
//!         ).expect("Failed to create new stream")));
//!
//!     stream.borrow_mut().connect_playback(None, None, StreamFlagSet::START_CORKED,
//!         None, None).expect("Failed to connect playback");
//!
//!     // Wait for stream to be ready
//!     loop {
//!         match mainloop.borrow_mut().iterate(false) {
//!             IterateResult::Quit(_) |
//!             IterateResult::Err(_) => {
//!                 eprintln!("Iterate state was not success, quitting...");
//!                 return;
//!             },
//!             IterateResult::Success(_) => {},
//!         }
//!         match stream.borrow().get_state() {
//!             pulse::stream::State::Ready => { break; },
//!             pulse::stream::State::Failed |
//!             pulse::stream::State::Terminated => {
//!                 eprintln!("Stream state failed/terminated, quitting...");
//!                 return;
//!             },
//!             _ => {},
//!         }
//!     }
//!
//!     // Our main logic (to output a stream of audio data)
//! #   let mut count = 0; // For automatic unit tests, we’ll spin a few times
//!     let drained = Rc::new(RefCell::new(false));
//!     loop {
//!         match mainloop.borrow_mut().iterate(false) {
//!             IterateResult::Quit(_) |
//!             IterateResult::Err(_) => {
//!                 eprintln!("Iterate state was not success, quitting...");
//!                 return;
//!             },
//!             IterateResult::Success(_) => {},
//!         }
//!
//!         // Write some data with stream.write()
//!
//!         if stream.borrow().is_corked().unwrap() {
//!             stream.borrow_mut().uncork(None);
//!         }
//!
//!         // Wait for our data to be played
//!         let _o = {
//!             let drain_state_ref = Rc::clone(&drained);
//!             stream.borrow_mut().drain(Some(Box::new(move |_success: bool| {
//!                 *drain_state_ref.borrow_mut() = true;
//!             })))
//!         };
//!         while *drained.borrow_mut() == false {
//!             match mainloop.borrow_mut().iterate(false) {
//!                 IterateResult::Quit(_) |
//!                 IterateResult::Err(_) => {
//!                     eprintln!("Iterate state was not success, quitting...");
//!                     return;
//!                 },
//!                 IterateResult::Success(_) => {},
//!             }
//!         }
//!         *drained.borrow_mut() = false;
//!
//!         // Remember to break out of the loop once done writing all data (or whatever).
//! #
//! #       // Hack: Stop test getting stuck in infinite loop!
//! #       count += 1;
//! #       if count == 3 {
//! #           break;
//! #       }
//!     }
//!
//!     // Clean shutdown
//!     mainloop.borrow_mut().quit(Retval(0)); // uncertain whether this is necessary
//!     stream.borrow_mut().disconnect().unwrap();
//! }
//! ```

use std::os::raw::{c_ulong, c_void};
use std::rc::Rc;
#[cfg(not(windows))]
use libc::pollfd;
#[cfg(windows)]
use winapi::um::winsock2::WSAPOLLFD as pollfd;
use crate::def;
use crate::error::{Code as ErrCode, PAErr};
use crate::mainloop::api::{MainloopInternalType, MainloopInner, MainloopInnerType, MainloopApi,
                           Mainloop as MainloopTrait};
use crate::mainloop::signal::MainloopSignals;
use crate::time::MicroSeconds;

pub use capi::pa_mainloop as MainloopInternal;

impl MainloopInternalType for MainloopInternal {}

/// Generic prototype of a poll() like function.
pub type PollFn = extern "C" fn(ufds: *mut pollfd, nfds: c_ulong, timeout: i32,
    userdata: *mut c_void) -> i32;

/// Return type for [`Mainloop::iterate()`].
#[derive(Debug, Copy, Clone, PartialEq, Eq)]
pub enum IterateResult {
    /// Success, with number of sources dispatched.
    Success(u32),
    /// Quit was called, with quit’s retval.
    Quit(def::Retval),
    /// An error occurred, with error value.
    Err(PAErr),
}

impl IterateResult {
    /// Checks if the result is a `Success` value (returns `true` if so).
    #[inline]
    pub fn is_success(&self) -> bool {
        match *self {
            IterateResult::Success(_) => true,
            _ => false,
        }
    }

    /// Checks if the result is a `Quit` value (returns `true` if so).
    #[inline]
    pub fn is_quit(&self) -> bool {
        match *self {
            IterateResult::Quit(_) => true,
            _ => false,
        }
    }

    /// Checks` if the result is an `Error` value (returns `true` if so).
    #[inline]
    pub fn is_error(&self) -> bool {
        match *self {
            IterateResult::Err(_) => true,
            _ => false,
        }
    }
}

/// This acts as a safe interface to the internal PA Mainloop.
///
/// The mainloop object pointers are further enclosed here in a ref counted wrapper, allowing this
/// outer wrapper to have clean methods for creating event objects, which can cleanly pass a copy of
/// the inner ref counted mainloop object to them. Giving this to events serves two purposes,
/// firstly because they need the API pointer, secondly, it ensures that event objects do not
/// outlive the mainloop object.
pub struct Mainloop {
    /// The ref-counted inner data.
    pub _inner: Rc<MainloopInner<MainloopInternal>>,
}

impl MainloopTrait for Mainloop {
    type MI = MainloopInner<MainloopInternal>;

    #[inline(always)]
    fn inner(&self) -> Rc<super::api::MainloopInner<MainloopInternal>> {
        Rc::clone(&self._inner)
    }
}

impl MainloopSignals for Mainloop {}

impl MainloopInner<MainloopInternal> {
    #[inline(always)]
    fn drop_actual(&mut self) {
        unsafe { capi::pa_mainloop_free(self.get_ptr()) };
    }
}

impl Mainloop {
    /// Allocates a new main loop object.
    pub fn new() -> Option<Self> {
        let ptr = unsafe { capi::pa_mainloop_new() };
        if ptr.is_null() {
            return None;
        }
        let api_ptr = unsafe { capi::pa_mainloop_get_api(ptr) };
        assert!(!api_ptr.is_null());
        let ml_inner = unsafe {
            MainloopInner::<MainloopInternal>::new(ptr, std::mem::transmute(api_ptr),
                MainloopInner::<MainloopInternal>::drop_actual, true)
        };
        Some(Self { _inner: Rc::new(ml_inner) })
    }

    /// Prepares for a single iteration of the main loop.
    ///
    /// Returns `Err` on error or exit request.
    ///
    /// `timeout` specifies a maximum timeout for the subsequent poll. `None` requests blocking
    /// behaviour.
    ///
    /// Note, should the microseconds timeout value provided be too large to pass to the underlying
    /// C API (larger than [`std::i32::MAX`]), then the [`PAErr`] form of the [`Code::TooLarge`]
    /// error will be returned (within [`Result::Err`]).
    ///
    /// [`Code::TooLarge`]: crate::error::Code::TooLarge
    pub fn prepare(&mut self, timeout: Option<MicroSeconds>) -> Result<(), PAErr> {
        let t: i32 = match timeout {
            // A negative value represents a request for 'blocking' behaviour in the C API
            None => -1,
            // This is just in case we ever changed `MicroSeconds` to hold unsigned values
            #[allow(unused_comparisons)]
            Some(MicroSeconds(i)) if i < 0 => unreachable!(),
            // Check value is no larger than i32::MAX considering API takes an i32
            Some(MicroSeconds(i)) if i <= std::i32::MAX as u64 => i as i32,
            // If larger, we must error
            _ => return Err((ErrCode::TooLarge).into()),
        };
        match unsafe { capi::pa_mainloop_prepare(self._inner.get_ptr(), t) } {
            0 => Ok(()),
            e => Err(PAErr(e)),
        }
    }

    /// Executes the previously prepared poll.
    pub fn poll(&mut self) -> Result<u32, PAErr> {
        match unsafe { capi::pa_mainloop_poll(self._inner.get_ptr()) } {
            e if e >= 0 => Ok(e as u32),
            e => Err(PAErr(e)),
        }
    }

    /// Dispatchs timeout, IO and deferred events from the previously executed poll.
    ///
    /// On success returns the number of source dispatched.
    pub fn dispatch(&mut self) -> Result<u32, PAErr> {
        match unsafe { capi::pa_mainloop_dispatch(self._inner.get_ptr()) } {
            e if e >= 0 => Ok(e as u32),
            e => Err(PAErr(e)),
        }
    }

    /// Gets the return value as specified with the main loop’s [`quit()`](Self::quit) routine.
    #[inline]
    pub fn get_retval(&self) -> def::Retval {
        def::Retval(unsafe { capi::pa_mainloop_get_retval(self._inner.get_ptr()) })
    }

    /// Runs a single iteration of the main loop.
    ///
    /// This is a convenience function for [`prepare()`], [`poll()`] and [`dispatch()`].
    ///
    /// If `block` is `true`, block for events if none are queued.
    ///
    /// Returns an [`IterateResult`] variant:
    ///
    /// * On success, returns `IterateResult::Success` containing the number of sources dispatched
    ///   in this iteration.
    /// * If exit was requested, returns `IterateResult::Quit` containing quit’s retval.
    /// * On error, returns `IterateResult::Err` containing error value.
    ///
    /// [`prepare()`]: Self::prepare
    /// [`poll()`]: Self::poll
    /// [`dispatch()`]: Self::dispatch
    pub fn iterate(&mut self, block: bool) -> IterateResult {
        let mut retval: i32 = 0;
        match unsafe {
            capi::pa_mainloop_iterate(self._inner.get_ptr(), block as i32, &mut retval)
        } {
            r if r >= 0 => IterateResult::Success(r as u32),
            -2 => IterateResult::Quit(def::Retval(retval)),
            e => IterateResult::Err(PAErr(e)),
        }
    }

    /// Runs unlimited iterations of the main loop object until the main loop’s
    /// [`quit()`](Self::quit) routine is called.
    ///
    /// On success, returns `Ok` containing quit’s return value. On error returns `Err` containing a
    /// tuple of the error value and quit’s return value.
    pub fn run(&mut self) -> Result<def::Retval, (PAErr, def::Retval)> {
        let mut retval: i32 = 0;
        match unsafe { capi::pa_mainloop_run(self._inner.get_ptr(), &mut retval) } {
            r if r >= 0 => Ok(def::Retval(retval)),
            r => Err((PAErr(r), def::Retval(retval))),
        }
    }

    /// Gets the abstract main loop abstraction layer vtable for this main loop.
    ///
    /// No need to free the API as it is owned by the loop and is destroyed when the loop is freed.
    ///
    /// Talking to PA directly with C requires fetching this pointer explicitly via this function.
    /// This is actually unnecessary through this binding. The pointer is retrieved automatically
    /// upon Mainloop creation, stored internally, and automatically obtained from it by functions
    /// that need it.
    #[inline]
    pub fn get_api<'a>(&self) -> &'a MainloopApi {
        let ptr = self._inner.get_api_ptr();
        assert_eq!(false, ptr.is_null());
        unsafe { &*ptr }
    }

    /// Shuts down the main loop with the specified return value.
    #[inline]
    pub fn quit(&mut self, retval: def::Retval) {
        unsafe { capi::pa_mainloop_quit(self._inner.get_ptr(), retval.0); }
    }

    /// Interrupts a running poll (for threaded systems).
    #[inline]
    pub fn wakeup(&mut self) {
        unsafe { capi::pa_mainloop_wakeup(self._inner.get_ptr()); }
    }

    /// Changes the poll() implementation.
    #[inline]
    pub fn set_poll_func(&mut self, poll_cb: (PollFn, *mut c_void)) {
        unsafe {
            capi::pa_mainloop_set_poll_func(self._inner.get_ptr(), Some(poll_cb.0), poll_cb.1);
        }
    }
}
