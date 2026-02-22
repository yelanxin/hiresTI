// Copyright The pipewire-rs Contributors.
// SPDX-License-Identifier: MIT

use std::ptr::{self, NonNull};
use std::rc::{Rc, Weak};

use crate::{
    error::Error,
    loop_::{IsLoopRc, LoopRef},
};

#[derive(Debug, Clone)]
pub struct MainLoop {
    inner: Rc<MainLoopInner>,
}

impl MainLoop {
    /// Initialize Pipewire and create a new `MainLoop`
    pub fn new(properties: Option<&spa::utils::dict::DictRef>) -> Result<Self, Error> {
        super::init();

        unsafe {
            let props = properties
                .map_or(ptr::null(), |props| props.as_raw())
                .cast_mut();
            let l = pw_sys::pw_main_loop_new(props);
            let ptr = ptr::NonNull::new(l).ok_or(Error::CreationFailed)?;

            Ok(Self::from_raw(ptr))
        }
    }

    /// Create a new main loop from a raw [`pw_main_loop`](`pw_sys::pw_main_loop`), taking ownership of it.
    ///
    /// # Safety
    /// The provided pointer must point to a valid, well aligned [`pw_main_loop`](`pw_sys::pw_main_loop`).
    ///
    /// The raw loop should not be manually destroyed or moved, as the new [`MainLoop`] takes ownership of it.
    pub unsafe fn from_raw(ptr: NonNull<pw_sys::pw_main_loop>) -> Self {
        Self {
            inner: Rc::new(MainLoopInner::from_raw(ptr)),
        }
    }

    pub fn as_raw_ptr(&self) -> *mut pw_sys::pw_main_loop {
        self.inner.ptr.as_ptr()
    }

    pub fn downgrade(&self) -> WeakMainLoop {
        let weak = Rc::downgrade(&self.inner);
        WeakMainLoop { weak }
    }

    pub fn loop_(&self) -> &LoopRef {
        unsafe {
            let pw_loop = pw_sys::pw_main_loop_get_loop(self.as_raw_ptr());
            // FIXME: Make sure pw_loop is not null
            &*(pw_loop.cast::<LoopRef>())
        }
    }

    pub fn run(&self) {
        unsafe {
            pw_sys::pw_main_loop_run(self.as_raw_ptr());
        }
    }

    pub fn quit(&self) {
        unsafe {
            pw_sys::pw_main_loop_quit(self.as_raw_ptr());
        }
    }
}

// Safety: The pw_loop is guaranteed to remain valid while any clone of the `MainLoop` is held,
//         because we use an internal Rc to keep the pw_main_loop containing the pw_loop alive.
unsafe impl IsLoopRc for MainLoop {}

impl std::convert::AsRef<LoopRef> for MainLoop {
    fn as_ref(&self) -> &LoopRef {
        self.loop_()
    }
}

pub struct WeakMainLoop {
    weak: Weak<MainLoopInner>,
}

impl WeakMainLoop {
    pub fn upgrade(&self) -> Option<MainLoop> {
        self.weak.upgrade().map(|inner| MainLoop { inner })
    }
}

#[derive(Debug)]
struct MainLoopInner {
    ptr: ptr::NonNull<pw_sys::pw_main_loop>,
}

impl MainLoopInner {
    pub unsafe fn from_raw(ptr: NonNull<pw_sys::pw_main_loop>) -> Self {
        Self { ptr }
    }
}

impl Drop for MainLoopInner {
    fn drop(&mut self) {
        unsafe { pw_sys::pw_main_loop_destroy(self.ptr.as_ptr()) }
    }
}
