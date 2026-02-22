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

//! A binding for the PulseAudio system library (`libpulse`).
//!
//! # About
//!
//! This binding enables Rust projects to make use of the [PulseAudio] client system library. It
//! builds upon the [separate raw FFI crate][sys] to provide a more “Rusty” interface.
//!
//! The documentation below and throughout this crate has been largely copied (under fair-use terms)
//! from those in the PulseAudio C API header files, and adjusted where appropriate to fit any
//! differences, thus it should not be too unfamiliar to those of you already familiar with the C
//! API.
//!
//! <div style="border-left:#bda000aa 5px solid; padding:0.5em 1em; margin:1em 0 0.6em 0; background-color:#aaa2">
//! <h3 style="color:#bfa800; margin-top:0.2em">
//! <span aria-hidden="true">
//! <svg style="width:1em; height:1em; margin-bottom:-0.15em; fill:currentColor" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 576 512"><path d="M569.517 440.013C587.975 472.007 564.806 512 527.94 512H48.054c-36.937 0-59.999-40.055-41.577-71.987L246.423 23.985c18.467-32.009 64.72-31.951 83.154 0l239.94 416.028zM288 354c-25.405 0-46 20.595-46 46s20.595 46 46 46 46-20.595 46-46-20.595-46-46-46zm-43.673-165.346l7.418 136c.347 6.364 5.609 11.346 11.982 11.346h48.546c6.373 0 11.635-4.982 11.982-11.346l7.418-136c.375-6.874-5.098-12.654-11.982-12.654h-63.383c-6.884 0-12.356 5.78-11.981 12.654z"></path></svg>
//! </span>
//! Warning
//! </h3>
//! <p>
//! The PulseAudio API, even in this Rust-ified form, is not the easiest thing to understand how to
//! make use of. Furthermore, the somewhat complex underlying C API imposes certain limitations upon
//! just how safe and simple an interface this binding can reasonably offer. One particularly
//! notable example is the threaded mainloop locking mechanism, which uses a perfectly legitimate
//! design, but one that happens to conflict with what is typically used in Rust code; it does not
//! fit perfectly with the Rust borrow checking mechanism and thus you cannot rely upon the borrow
//! checker to prevent unsafe use as much as is typical.
//! </p>
//! </div>
//!
//! # Introduction
//!
//! The PulseAudio API comes in two flavours to accommodate different styles of applications and
//! different needs in complexity:
//!
//! * The complete but somewhat complicated to use asynchronous API.
//! * The simplified, easy to use, but limited synchronous API.
//!
//! ## Simple API
//!
//! Use this if you develop your program in synchronous style and just need a way to play or record
//! data on the sound server. This functionality is kept in the separate [`libpulse-simple-binding`]
//! crate. See that for details.
//!
//! ## Asynchronous API
//!
//! Use this if you develop your programs in asynchronous, event loop based style or if you want to
//! use the advanced features of the PulseAudio API. A guide can be found in the
//! [`mainloop`](mod@mainloop) module.
//!
//! By using the built-in threaded main loop, it is possible to achieve a pseudo-synchronous API,
//! which can be useful in synchronous applications where the simple API is insufficient.
//!
//! ## Threads
//!
//! The PulseAudio client libraries are not designed to be directly thread-safe. They are however
//! designed to be re-entrant and thread-aware.
//!
//! To use the libraries in a threaded environment, you must assure that all objects are only used
//! in one thread at a time. Normally, this means that all objects belonging to a single context
//! must be accessed from the same thread.
//!
//! The included main loop implementation is also not thread safe. Take care to make sure event
//! objects are not manipulated when any other code is using the main loop.
//!
//! Note that some objects implement the `Sync` trait, despite not truly being thread-safe. The
//! reason for this is that when the threaded mainloop is used (the most common one), its lock
//! provides the thread safety, and when such types are used behind that lock, they are then `Sync`
//! safe. If you use the standard mainloop though, then you would have to add an `Arc` wrapper to
//! make them safe. Not having `Sync` would force the threaded mainloop case to require unnecessary
//! and undesirable `Arc` wrappers. This is an unfortunate compromise resulting from the
//! complication of needing to support multiple mainloop designs, and the threaded mainloop design
//! being built upon a non-wrapper lock that is not typical of Rust code.
//!
//! ## Logging
//!
//! You can configure different logging parameters for the PulseAudio client libraries. The
//! following environment variables are recognized:
//!
//! * `PULSE_LOG`: Maximum log level required. Bigger values result in a more verbose logging
//!   output. The following values are recognized:
//!   * `0`: Error messages
//!   * `1`: Warning messages
//!   * `2`: Notice messages
//!   * `3`: Info messages
//!   * `4`: Debug messages
//! * `PULSE_LOG_SYSLOG`: If defined, force all client libraries to log their output using the
//!   `syslog(3)` mechanism. Default behavior is to log all output to `stderr`.
//! * `PULSE_LOG_JOURNAL`: If defined, force all client libraries to log their output using the
//!   systemd journal. If both `PULSE_LOG_JOURNAL` and `PULSE_LOG_SYSLOG` are defined, logging to
//!   the systemd journal takes a higher precedence. Each message originating library file name and
//!   function are included by default through the journal fields `CODE_FILE`, `CODE_FUNC`, and
//!   `CODE_LINE`. Any backtrace attached to the logging message is sent through the
//!   PulseAudio-specific journal field `PULSE_BACKTRACE`. This environment variable has no effect
//!   if PulseAudio was compiled without systemd journal support.
//! * `PULSE_LOG_COLORS`: If defined, enables colored logging output.
//! * `PULSE_LOG_TIME`: If defined, include timestamps with each message.
//! * `PULSE_LOG_FILE`: If defined, include each message originating file name.
//! * `PULSE_LOG_META`: If defined, include each message originating file name and path relative to
//!   the PulseAudio source tree root.
//! * `PULSE_LOG_LEVEL`: If defined, include a log level prefix with each message. Respectively, the
//!   prefixes "E", "W", "N", "I", "D" stands for Error, Warning, Notice, Info, and Debugging.
//! * `PULSE_LOG_BACKTRACE`: Number of functions to display in the backtrace. If this variable is
//!   not defined, or has a value of zero, no backtrace is shown.
//! * `PULSE_LOG_BACKTRACE_SKIP`: Number of backtrace levels to skip, from the function printing the
//!   log message downwards.
//! * `PULSE_LOG_NO_RATE_LIMIT`: If defined, do not rate limit the logging output. Rate limiting
//!   skips certain log messages when their frequency is considered too high.
//!
//! # Usage
//!
//! Start by adding a dependency on the crate in your program’s `Cargo.toml` file. Note that it is
//! recommended that you rename the crate such that you can refer to it by a shorter name within
//! your code (such as `pulse`, as used within examples within this crate’s documentation). Such
//! renaming can be done [within your `Cargo.toml` file][rename] with cargo version 1.31 or newer,
//! or otherwise with `extern crate` statements.
//!
//! See sub-modules for further information.
//!
//! Note that establishing a connection with PulseAudio involves creation of [context](mod@context)
//! and [mainloop](mod@mainloop) objects and both of these must live for the entire duration that
//! your program wishes to communicate with PulseAudio. The context object represents the actual
//! communicaiton channel with PA. The mainloop object is used for controlled processing of messages
//! sent to your client program from PA and execution of your callbacks. This detail can be ignored
//! if you use the 'simple' binding interface.
//!
//! <div style="border-left:#bda000aa 5px solid; padding:0.5em 1em; margin:1em 0 0.6em 0; background-color:#aaa2">
//! <h3 style="color:#bfa800; margin-top:0.2em">
//! <span aria-hidden="true">
//! <svg style="width:1em; height:1em; margin-bottom:-0.15em; fill:currentColor" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 576 512"><path d="M569.517 440.013C587.975 472.007 564.806 512 527.94 512H48.054c-36.937 0-59.999-40.055-41.577-71.987L246.423 23.985c18.467-32.009 64.72-31.951 83.154 0l239.94 416.028zM288 354c-25.405 0-46 20.595-46 46s20.595 46 46 46 46-20.595 46-46-20.595-46-46-46zm-43.673-165.346l7.418 136c.347 6.364 5.609 11.346 11.982 11.346h48.546c6.373 0 11.635-4.982 11.982-11.346l7.418-136c.375-6.874-5.098-12.654-11.982-12.654h-63.383c-6.884 0-12.356 5.78-11.981 12.654z"></path></svg>
//! </span>
//! Warning
//! </h3>
//! <p>
//! It is important that you read the <code>COMPATIBILITY.md</code> guide available in the
//! <a href="https://github.com/jnqnfe/pulse-binding-rust">code repository</a> to understand the
//! topic of compatibility with different versions of PulseAudio.
//! </p>
//! </div>
//!
//! [sys]: https://docs.rs/libpulse-sys
//! [`libpulse-simple-binding`]: https://docs.rs/libpulse-simple-binding
//! [PulseAudio]: https://en.wikipedia.org/wiki/PulseAudio
//! [rename]: https://doc.rust-lang.org/1.31.0/cargo/reference/specifying-dependencies.html#renaming-dependencies-in-cargotoml
//! [code repository]: https://github.com/jnqnfe/pulse-binding-rust

#![doc(
    html_logo_url = "https://github.com/jnqnfe/pulse-binding-rust/raw/master/logo.svg",
    html_favicon_url = "https://github.com/jnqnfe/pulse-binding-rust/raw/master/favicon.ico"
)]

#![warn(missing_docs)]

#![cfg_attr(docsrs, feature(doc_cfg))]

extern crate libpulse_sys as capi;

pub mod callbacks;
pub mod channelmap;
pub mod context;
pub mod def;
pub mod direction;
pub mod error;
pub mod format;
pub mod mainloop;
pub mod operation;
pub mod proplist;
pub mod sample;
pub mod stream;
pub mod time;
pub mod utf8;
pub mod util;
pub mod version;
pub mod volume;
