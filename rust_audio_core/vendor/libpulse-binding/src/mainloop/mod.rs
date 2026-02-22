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

//! Main loop abstraction layer.
//!
//! # Main Loop Abstraction
//!
//! Both the PulseAudio core and the PulseAudio client library use a main loop abstraction layer.
//! Due to this it is possible to embed PulseAudio into other applications easily.
//!
//! This abstraction contains three basic elements:
//!
//! * Deferred events: Events that will trigger as soon as possible. Note that some implementations
//!   may block all other events when a deferred event is active.
//! * I/O events: Events that trigger on file descriptor activities.
//! * Timer events: Events that trigger after a fixed amount of time.
//!
//! The abstraction is represented as a number of function pointers in the
//! [`MainloopApi`](self::api::MainloopApi) structure.
//!
//! To actually be able to use these functions, an implementation needs to be coupled to the
//! abstraction. There are three of these shipped with PulseAudio, but any other can be used with a
//! minimal amount of work, provided it supports the three basic events listed above.
//!
//! The implementations shipped with PulseAudio are:
//!
//! * [Standard](mod@standard): A minimal but fast implementation based on the C library’s poll()
//!   function.
//! * [Threaded](mod@threaded): A special version of the previous implementation where all of
//!   PulseAudio’s internal handling runs in a separate thread.
//! * ‘Glib’: A wrapper around GLib’s main loop. This is provided in the separate
//!   `libpulse_glib_binding` crate.
//!
//! UNIX signals may be hooked to a main loop using the functionality from the
//! [`signal`](mod@signal) mod. This relies only on the main loop abstraction and can therefore be
//! used with any of the implementations.
//!
//! # Callback Notes
//!
//! ## Execution
//!
//! As described in the [standard mainloop] documentation], there are three phases to mainloop
//! execution, and the third - ‘dispatch’ - is when user callbacks get executed.
//!
//! It is important to understand that while it is *typical* that user callbacks are executed
//! by the mainloop’s dispatcher, callback execution is not exclusively done there; in some cases
//! callbacks get executed directly in synchronous function execution. For instance, if you set up
//! a context state change callback, then try to connect the context object, execution of the
//! ‘connect’ function call involves (internally within the PulseAudio client library) direct
//! execution of this callback in setting the initial connection state. After returning, the
//! callback is then on only executed asynchronously from the mainloop’s dispatcher.
//!
//! While execution using the [standard mainloop] is entirely synchronous, the [threaded mainloop]
//! implementation runs the standard mainloop in a separate thread and callback execution occurs
//! asynchronously, requiring careful use of the mainloop’s [`lock()`] method. When writing
//! callbacks with the threaded mainloop, users must beware the potential that in a few cases the
//! callback may be executed in two different scenarios, and with different threads. Note that the
//! threaded mainloop has an [`in_thread()`] method for determining whether or not the thread it is
//! executed from is the special event loop thread.
//!
//! ## Queued Events and Changing Callbacks
//!
//! It is also worth understanding that any events that get queued for dispatch do **not** hold
//! cached copies of user callback parameters. Where applicable, you can thus freely and safely
//! change the set callback, with that change taking effect immediately to all future event
//! dispatching.
//!
//! ## Threading and `Rc`
//!
//! Normally when holding multiple references to objects across threads in Rust you would use an
//! [`Arc`] wrapper. However, with the [threaded mainloop], you may be able to get away with using
//! just an `Rc` wrapper. Remember that with the [threaded mainloop] you **must** use its
//! [`lock()`] method to synchronise access to objects, and so you know that at any one moment
//! either your thread (when you take the lock) **or** the event loop thread hold the lock, never
//! both, and thus only one thread is ever working with objects at any one time, and since Rust
//! actually has no idea that more than one thread is involved (hidden in the C library’s
//! implementation), you can safely get away with using `Rc`.
//!
//! [standard mainloop]: mod@standard
//! [threaded mainloop]: mod@self::threaded
//! [`lock()`]: self::threaded::Mainloop::lock
//! [`in_thread()`]: self::threaded::Mainloop::in_thread
//! [`Arc`]: std::sync::Arc

pub mod api;
pub mod events;
pub mod signal;
pub mod standard;
pub mod threaded;
