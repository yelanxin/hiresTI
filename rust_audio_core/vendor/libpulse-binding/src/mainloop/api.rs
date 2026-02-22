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

//! Main loop abstraction layer API.

use std::os::raw::c_void;
use std::rc::Rc;
use libc::timeval;
use crate::def;
use super::events;
use super::events::io::{IoEvent, IoEventRef, IoEventInternal, FlagSet as IoEventFlagSet};
use super::events::timer::{TimeEvent, TimeEventRef, TimeEventInternal};
use super::events::deferred::{DeferEvent, DeferEventRef, DeferEventInternal};
use crate::time::{UnixTs, MonotonicTs, Timeval, MicroSeconds};
use crate::callbacks::{get_su_capi_params, get_su_callback};

pub(crate) use capi::pa_mainloop_api as ApiInternal;

/// This enables generic type enforcement with the opaque C objects.
pub trait MainloopInternalType {}

/// This enables generic type enforcement with MainloopInner objects, and describes mandatory
/// accessors for the internal pointers, allowing access to these pointers across the generic
/// implementations to work.
pub trait MainloopInnerType {
    /// Internal mainloop type.
    type I: MainloopInternalType;

    /// Create a new instance
    #[inline(always)]
    unsafe fn new(ptr: *mut Self::I, api: *const MainloopApi,
        dropfn: fn(&mut MainloopInner<Self::I>), supports_rtclock: bool)
        -> MainloopInner::<Self::I>
    {
        MainloopInner::<Self::I> { ptr, api, dropfn, supports_rtclock }
    }

    /// Return opaque main loop object pointer.
    ///
    /// **Warning**: The pointer is only valid for the lifetime of this object.
    fn get_ptr(&self) -> *mut Self::I;

    /// Return raw API object pointer.
    ///
    /// **Warning**: The pointer is only valid for the lifetime of this object.
    fn get_api_ptr(&self) -> *const MainloopApi;

    /// Return main loop API object pointer.
    fn get_api(&self) -> &MainloopApi;

    /// Returns `true` if the mainloop implementation supports monotonic based time events.
    fn supports_rtclock(&self) -> bool;
}

/// Mainloop inner wrapper.
///
/// This contains the actual main loop object pointers, holding both the pointer to the actual
/// opaque main loop C object, and the pointer to the associated API vtable.
///
/// An instance of this type will be held, in an `Rc` ref counted wrapper both in an outer Mainloop
/// wrapper, and by all event objects. With event objects holding a ref-counted copy, this both
/// gives event objects access to the API pointer, which they need, and also it allows us to ensure
/// that event objects do not outlive the main loop object (which internally owns the API object),
/// and thus ensures correct destruction order of event and main loop objects.
pub struct MainloopInner<T>
    where T: MainloopInternalType
{
    /// An opaque main loop object.
    ptr: *mut T,

    /// The abstract main loop API vtable for the GLIB main loop object. No need to free this API as
    /// it is owned by the loop and is destroyed when the loop is freed.
    api: *const MainloopApi,

    /// All implementations must provide a drop method, to be called from an actual drop call, which
    /// should free the mainloop object.
    dropfn: fn(&mut MainloopInner<T>),

    /// Whether or not the implementation supports monotonic based time events. (`true` if so).
    supports_rtclock: bool,
}

impl<T> Drop for MainloopInner<T>
    where T: MainloopInternalType
{
    fn drop(&mut self) {
        (self.dropfn)(self);
        self.ptr = std::ptr::null_mut::<<MainloopInner<T> as MainloopInnerType>::I>();
        self.api = std::ptr::null::<MainloopApi>();
    }
}

/// This is the actual implementation of the ‘inner type’ trait.
///
/// It is not possible to replace this with ‘default’ method implementations within the trait itself
/// since the trait does not know about the existence of the struct attributes being accessed.
impl<T> MainloopInnerType for MainloopInner<T>
    where T: MainloopInternalType
{
    type I = T;

    /// Gets opaque main loop object pointer.
    ///
    /// **Warning**: The pointer is only valid for the lifetime of this object.
    #[inline(always)]
    fn get_ptr(&self) -> *mut T {
        self.ptr
    }

    /// Gets raw API object pointer.
    ///
    /// **Warning**: The pointer is only valid for the lifetime of this object.
    #[inline(always)]
    fn get_api_ptr(&self) -> *const MainloopApi {
        self.api
    }

    /// Gets main loop API object pointer.
    #[inline(always)]
    fn get_api(&self) -> &MainloopApi {
        assert!(!self.api.is_null());
        unsafe { &*self.api }
    }

    #[inline(always)]
    fn supports_rtclock(&self) -> bool {
        self.supports_rtclock
    }
}

/// Mainloop trait, to be implemented by the different types of mainloops.
pub trait Mainloop {
    /// Inner mainloop type.
    type MI: MainloopInnerType;

    /// Get inner mainloop.
    fn inner(&self) -> Rc<Self::MI>;

    /// Creates a new IO event.
    ///
    /// **Note**: You must ensure that the returned event object lives for as long as you want its
    /// event(s) to fire, as its `Drop` implementation destroys the event source. I.e. if you create
    /// a new event, but then immediately drop the object returned here, no event will fire!
    ///
    /// The given callback must accept three parameters, an [`IoEventRef`] object, a copy of the
    /// given file descriptor, and an event flag set, indicating the event(s) that occurred. The
    /// [`DeferEventRef`] object gives you some opportunity to manage the event source from within
    /// it’s callback execution.
    fn new_io_event(&mut self, fd: i32, events: IoEventFlagSet,
        mut callback: Box<dyn FnMut(IoEventRef<Self::MI>, i32, IoEventFlagSet) + 'static>)
        -> Option<IoEvent<Self::MI>>
    {
        let inner_for_wrapper = self.inner();
        let wrapper_cb = Box::new(move |ptr, fd, flags| {
            let ref_obj = IoEventRef::<Self::MI>::from_raw(ptr, Rc::clone(&inner_for_wrapper));
            callback(ref_obj, fd, flags);
        });

        let to_save = events::io::EventCb::new(Some(wrapper_cb));
        let (cb_fn, cb_data) = to_save.get_capi_params(events::io::event_cb_proxy);

        let inner = self.inner();
        let api = inner.get_api();
        let fn_ptr = api.io_new.unwrap();
        let ptr = fn_ptr(api, fd, events, cb_fn, cb_data);
        match ptr.is_null() {
            false => Some(IoEvent::<Self::MI>::from_raw(ptr, Rc::clone(&inner), to_save)),
            true => None,
        }
    }

    /// Creates a new timer event.
    ///
    /// **Note**: You must ensure that the returned event object lives for as long as you want its
    /// event(s) to fire, as its `Drop` implementation destroys the event source. I.e. if you create
    /// a new event, but then immediately drop the object returned here, no event will fire!
    ///
    /// The callback must take a [`TimeEventRef`] object, which gives you some opportunity to
    /// manage the event source from within it’s callback execution.
    ///
    /// Example event set to fire in five seconds time:
    ///
    /// ```rust,ignore
    /// use libpulse_binding::time::{UnixTs, MicroSeconds};
    /// let _t_event = mainloop.new_timer_event(
    ///     &(UnixTs::now() + MicroSeconds::from_secs(5).unwrap()),
    ///     Box::new(|_| { println!("Timer event fired!"); }));
    /// ```
    fn new_timer_event(&mut self, tv: &UnixTs,
        mut callback: Box<dyn FnMut(TimeEventRef<Self::MI>) + 'static>)
        -> Option<TimeEvent<Self::MI>>
    {
        let inner_for_wrapper = self.inner();
        let wrapper_cb = Box::new(move |ptr| {
            let ref_obj = TimeEventRef::<Self::MI>::from_raw(ptr, Rc::clone(&inner_for_wrapper));
            callback(ref_obj);
        });

        let to_save = events::timer::EventCb::new(Some(wrapper_cb));
        let (cb_fn, cb_data) = to_save.get_capi_params(events::timer::event_cb_proxy);

        let inner = self.inner();
        let api = inner.get_api();
        let fn_ptr = api.time_new.unwrap();
        let ptr = fn_ptr(api, &(tv.0).0, cb_fn, cb_data);
        match ptr.is_null() {
            false => Some(TimeEvent::<Self::MI>::from_raw(ptr, Rc::clone(&inner), to_save)),
            true => None,
        }
    }

    /// Creates a new monotonic-based timer event.
    ///
    /// Asserts that `t` is not `MicroSeconds::INVALID`.
    ///
    /// This is an alternative to the `new_timer_event` method, taking a monotonic based time value.
    ///
    /// **Note**: You must ensure that the returned event object lives for as long as you want its
    /// event(s) to fire, as its `Drop` implementation destroys the event source. I.e. if you create
    /// a new event, but then immediately drop the object returned here, no event will fire!
    ///
    /// The callback must take a [`TimeEventRef`] object, which gives you some opportunity to
    /// manage the event source from within it’s callback execution.
    ///
    /// Example event set to fire in five seconds time:
    ///
    /// ```rust,ignore
    /// use libpulse_binding::time::{MonotonicTs, MicroSeconds};
    /// let _t_event = mainloop.new_timer_event_rt(
    ///     MonotonicTs::now() + MicroSeconds::from_secs(5).unwrap(),
    ///     Box::new(|_| { println!("Timer event fired!"); }));
    /// ```
    fn new_timer_event_rt(&mut self, t: MonotonicTs,
        mut callback: Box<dyn FnMut(TimeEventRef<Self::MI>) + 'static>)
        -> Option<TimeEvent<Self::MI>>
    {
        assert_ne!(t.0, MicroSeconds::INVALID);

        let inner_for_wrapper = self.inner();
        let wrapper_cb = Box::new(move |ptr| {
            let ref_obj = TimeEventRef::<Self::MI>::from_raw(ptr, Rc::clone(&inner_for_wrapper));
            callback(ref_obj);
        });

        let to_save = events::timer::EventCb::new(Some(wrapper_cb));
        let (cb_fn, cb_data) = to_save.get_capi_params(events::timer::event_cb_proxy);

        let inner = self.inner();

        let mut tv = Timeval::new_zero();
        tv.set_rt(t.0, inner.supports_rtclock());

        let api = inner.get_api();
        let fn_ptr = api.time_new.unwrap();
        let ptr = fn_ptr(api, &tv.0, cb_fn, cb_data);
        match ptr.is_null() {
            false => Some(TimeEvent::<Self::MI>::from_raw(ptr, Rc::clone(&inner), to_save)),
            true => None,
        }
    }

    /// Creates a new deferred event.
    ///
    /// **Note**: You must ensure that the returned event object lives for as long as you want its
    /// event(s) to fire, as its `Drop` implementation destroys the event source. I.e. if you create
    /// a new event, but then immediately drop the object returned here, no event will fire!
    ///
    /// The callback must take a [`DeferEventRef`] object, which gives you some opportunity to
    /// manage the event source from within it’s callback execution.
    fn new_deferred_event(&mut self,
        mut callback: Box<dyn FnMut(DeferEventRef<Self::MI>) + 'static>)
        -> Option<DeferEvent<Self::MI>>
    {
        let inner_for_wrapper = self.inner();
        let wrapper_cb = Box::new(move |ptr| {
            let ref_obj = DeferEventRef::<Self::MI>::from_raw(ptr, Rc::clone(&inner_for_wrapper));
            callback(ref_obj);
        });

        let to_save = events::deferred::EventCb::new(Some(wrapper_cb));
        let (cb_fn, cb_data) = to_save.get_capi_params(events::deferred::event_cb_proxy);

        let inner = self.inner();
        let api = inner.get_api();
        let fn_ptr = api.defer_new.unwrap();
        let ptr = fn_ptr(api, cb_fn, cb_data);
        match ptr.is_null() {
            false => Some(DeferEvent::<Self::MI>::from_raw(ptr, Rc::clone(&inner), to_save)),
            true => None,
        }
    }

    /// Runs the specified callback once from the main loop using an anonymous defer event.
    ///
    /// If the mainloop runs in a different thread, you need to follow the mainloop implementation’s
    /// rules regarding how to safely create defer events. In particular, if you’re using
    /// [`mainloop::threaded`](mod@crate::mainloop::threaded), you must lock the mainloop before
    /// calling this function.
    fn once_event(&mut self, callback: Box<dyn FnMut() + 'static>) {
        let (cb_fn, cb_data): (Option<extern "C" fn(_, _)>, _) =
            get_su_capi_params::<_, _>(Some(callback), once_cb_proxy);

        let inner = self.inner();
        let api = inner.get_api();
        unsafe { capi::pa_mainloop_api_once(api.as_ref(), cb_fn, cb_data) };
    }

    /// Calls quit
    fn quit(&mut self, retval: def::Retval) {
        let inner = self.inner();
        let api = inner.get_api();
        let fn_ptr = api.quit.unwrap();
        fn_ptr(api, retval.0);
    }
}

/// An IO event callback prototype.
pub type IoEventCb = extern "C" fn(a: *const MainloopApi, e: *mut IoEventInternal, fd: i32,
    events: IoEventFlagSet, userdata: *mut c_void);
/// A IO event destroy callback prototype.
pub type IoEventDestroyCb = extern "C" fn(a: *const MainloopApi, e: *mut IoEventInternal,
    userdata: *mut c_void);

/// A time event callback prototype.
pub type TimeEventCb = extern "C" fn(a: *const MainloopApi, e: *mut TimeEventInternal,
    tv: *const timeval, userdata: *mut c_void);
/// A time event destroy callback prototype.
pub type TimeEventDestroyCb = extern "C" fn(a: *const MainloopApi, e: *mut TimeEventInternal,
    userdata: *mut c_void);

/// A defer event callback prototype.
pub type DeferEventCb = extern "C" fn(a: *const MainloopApi, e: *mut DeferEventInternal,
    userdata: *mut c_void);
/// A defer event destroy callback prototype.
pub type DeferEventDestroyCb = extern "C" fn(a: *const MainloopApi, e: *mut DeferEventInternal,
    userdata: *mut c_void);

/// An abstract mainloop API vtable
#[repr(C)]
pub struct MainloopApi {
    /* NOTE: This struct must be directly usable by the C API, thus same attributes/layout/etc */

    /// A pointer to some private, arbitrary data of the main loop implementation.
    pub userdata: *mut c_void,

    /// Creates a new IO event source object.
    pub io_new: Option<extern "C" fn(a: *const MainloopApi, fd: i32, events: IoEventFlagSet,
        cb: Option<IoEventCb>, userdata: *mut c_void) -> *mut IoEventInternal>,
    /// Enables or disables IO events on this object.
    pub io_enable: Option<extern "C" fn(e: *mut IoEventInternal, events: IoEventFlagSet)>,
    /// Frees a IO event source object.
    pub io_free: Option<extern "C" fn(e: *mut IoEventInternal)>,
    /// Sets a function that is called when the IO event source is destroyed. Use this to free the
    /// `userdata` argument if required.
    pub io_set_destroy: Option<extern "C" fn(e: *mut IoEventInternal, cb: Option<IoEventDestroyCb>)>,

    /// Creates a new timer event source object for the specified Unix time.
    pub time_new: Option<extern "C" fn(a: *const MainloopApi, tv: *const timeval,
        cb: Option<TimeEventCb>, userdata: *mut c_void) -> *mut TimeEventInternal>,
    /// Restarts a running or expired timer event source with a new Unix time.
    pub time_restart: Option<extern "C" fn(e: *mut TimeEventInternal, tv: *const timeval)>,
    /// Frees a deferred timer event source object.
    pub time_free: Option<extern "C" fn(e: *mut TimeEventInternal)>,
    /// Sets a function that is called when the timer event source is destroyed. Use this to free
    /// the `userdata` argument if required.
    pub time_set_destroy: Option<extern "C" fn(e: *mut TimeEventInternal,
        cb: Option<TimeEventDestroyCb>)>,

    /// Creates a new deferred event source object.
    pub defer_new: Option<extern "C" fn(a: *const MainloopApi, cb: Option<DeferEventCb>,
        userdata: *mut c_void) -> *mut DeferEventInternal>,
    /// Enables or disables a deferred event source temporarily.
    pub defer_enable: Option<extern "C" fn(e: *mut DeferEventInternal, b: i32)>,
    /// Frees a deferred event source object.
    pub defer_free: Option<extern "C" fn(e: *mut DeferEventInternal)>,
    /// Sets a function that is called when the deferred event source is
    /// destroyed. Use this to free the `userdata` argument if required.
    pub defer_set_destroy: Option<extern "C" fn(e: *mut DeferEventInternal,
        cb: Option<DeferEventDestroyCb>)>,

    /// Exits the main loop and return the specified retval.
    pub quit: Option<extern "C" fn(a: *const MainloopApi, retval: def::RetvalActual)>,
}

/// Test size is equal to `sys` equivalent (duplicated here for different documentation)
#[test]
fn api_compare_capi() {
    assert_eq!(std::mem::size_of::<ApiInternal>(), std::mem::size_of::<capi::pa_mainloop_api>());
    assert_eq!(std::mem::align_of::<ApiInternal>(), std::mem::align_of::<capi::pa_mainloop_api>());
}

impl AsRef<capi::pa_mainloop_api> for MainloopApi {
    #[inline]
    fn as_ref(&self) -> &capi::pa_mainloop_api {
        unsafe { &*(self as *const Self as *const capi::pa_mainloop_api) }
    }
}

impl<'a> From<*const ApiInternal> for &'a MainloopApi {
    #[inline]
    fn from(a: *const ApiInternal) -> Self {
        unsafe { std::mem::transmute(a) }
    }
}
impl<'a> From<&'a MainloopApi> for *const ApiInternal {
    #[inline]
    fn from(a: &'a MainloopApi) -> Self {
        unsafe { std::mem::transmute(a) }
    }
}

/// Proxy for anonymous ‘once’ deferred event callbacks.
///
/// Warning: This is for single-use cases only! It destroys the actual closure callback.
extern "C"
fn once_cb_proxy(_: *const ApiInternal, userdata: *mut c_void) {
    let _ = std::panic::catch_unwind(|| {
        // Note, destroys closure callback after use - restoring outer box means it gets dropped
        let mut callback = get_su_callback::<dyn FnMut()>(userdata);
        (callback)();
    });
}
