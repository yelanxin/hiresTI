// Copyright The pipewire-rs Contributors.
// SPDX-License-Identifier: MIT

use std::{
    ffi::{CStr, CString},
    mem::MaybeUninit,
    ptr,
    rc::{Rc, Weak},
};

use crate::{
    error::Error,
    loop_::{IsLoopRc, LoopRef},
};

/// A wrapper around the pipewire threaded loop interface. ThreadLoops are a higher level
/// of abstraction around the loop interface. A ThreadLoop can be used to spawn a new thread
/// that runs the wrapped loop.
#[derive(Debug, Clone)]
pub struct ThreadLoop {
    inner: Rc<ThreadLoopInner>,
}

impl ThreadLoop {
    /// Initialize Pipewire and create a new `ThreadLoop` with the given `name` and optional properties.
    ///
    /// # Safety
    /// TODO
    pub unsafe fn new(
        name: Option<&str>,
        properties: Option<&spa::utils::dict::DictRef>,
    ) -> Result<Self, Error> {
        let name = name.map(|name| CString::new(name).unwrap());

        ThreadLoop::new_cstr(name.as_deref(), properties)
    }

    /// Initialize Pipewire and create a new `ThreadLoop` with the given `name` as Cstr
    ///
    /// # Safety
    /// TODO
    pub unsafe fn new_cstr(
        name: Option<&CStr>,
        properties: Option<&spa::utils::dict::DictRef>,
    ) -> Result<Self, Error> {
        super::init();

        unsafe {
            let props = properties.map_or(ptr::null(), |props| props.as_raw_ptr());
            let l = pw_sys::pw_thread_loop_new(
                name.map_or(ptr::null(), |p| p.as_ptr() as *const _),
                props,
            );
            let ptr = ptr::NonNull::new(l).ok_or(Error::CreationFailed)?;

            Ok(Self {
                inner: Rc::new(ThreadLoopInner::from_raw(ptr)),
            })
        }
    }

    pub fn downgrade(&self) -> WeakThreadLoop {
        let weak = Rc::downgrade(&self.inner);
        WeakThreadLoop { weak }
    }

    pub fn as_raw_ptr(&self) -> *mut pw_sys::pw_thread_loop {
        self.inner.ptr.as_ptr()
    }

    pub fn loop_(&self) -> &LoopRef {
        unsafe {
            let thread_loop = pw_sys::pw_thread_loop_get_loop(self.as_raw_ptr());
            &*(thread_loop.cast::<LoopRef>())
        }
    }

    /// Lock the Loop
    ///
    /// This ensures that the loop thread will not access objects associated
    /// with the loop while the lock is held, `lock()` can be used multiple times
    /// from the same thread.
    ///
    /// The lock needs to be held whenever you call any PipeWire function that
    /// uses an object associated with this loop. Make sure to not hold
    /// on to the lock more than necessary though, as the threaded loop stops
    /// while the lock is held.
    pub fn lock(&self) -> ThreadLoopLockGuard {
        ThreadLoopLockGuard::new(self)
    }

    /// Start the ThreadLoop
    pub fn start(&self) {
        unsafe {
            pw_sys::pw_thread_loop_start(self.as_raw_ptr());
        }
    }

    /// Stop the ThreadLoop
    ///
    /// Stopping the ThreadLoop must be called without the lock
    pub fn stop(&self) {
        unsafe {
            pw_sys::pw_thread_loop_stop(self.as_raw_ptr());
        }
    }

    /// Signal all threads waiting with [`wait()`](`Self::wait`)
    pub fn signal(&self, signal: bool) {
        unsafe {
            pw_sys::pw_thread_loop_signal(self.as_raw_ptr(), signal);
        }
    }

    /// Release the lock and wait
    ///
    /// Release the lock and wait until some thread calls [`signal()`](`Self::signal`)
    pub fn wait(&self) {
        unsafe {
            pw_sys::pw_thread_loop_wait(self.as_raw_ptr());
        }
    }

    /// Release the lock and wait a maximum of `wait_max_sec` seconds
    /// until some thread calls [`signal()`](`Self::signal`) or time out
    pub fn timed_wait(&self, wait_max_sec: std::time::Duration) {
        unsafe {
            let wait_max_sec: i32 = wait_max_sec
                .as_secs()
                .try_into()
                .expect("Provided timeout does not fit in a i32");
            pw_sys::pw_thread_loop_timed_wait(self.as_raw_ptr(), wait_max_sec);
        }
    }

    /// Get a timespec suitable for [`timed_wait_full()`](`Self::timed_wait_full`)
    pub fn get_time(&self, timeout: i64) -> nix::sys::time::TimeSpec {
        unsafe {
            let mut abstime: MaybeUninit<pw_sys::timespec> = std::mem::MaybeUninit::uninit();
            pw_sys::pw_thread_loop_get_time(self.as_raw_ptr(), abstime.as_mut_ptr(), timeout);
            let abstime = abstime.assume_init();
            nix::sys::time::TimeSpec::new(abstime.tv_sec, abstime.tv_nsec)
        }
    }

    /// Release the lock and wait up to abs seconds until some
    /// thread calls [`signal()`](`Self::signal`). Use [`get_time()`](`Self::get_time`)
    /// to get a suitable timespec
    pub fn timed_wait_full(&self, abstime: nix::sys::time::TimeSpec) {
        unsafe {
            let mut abstime = pw_sys::timespec {
                tv_sec: abstime.tv_sec(),
                tv_nsec: abstime.tv_nsec(),
            };
            pw_sys::pw_thread_loop_timed_wait_full(
                self.as_raw_ptr(),
                &mut abstime as *mut pw_sys::timespec,
            );
        }
    }

    /// Signal all threads executing [`signal()`](`Self::signal`) with `wait_for_accept`
    pub fn accept(&self) {
        unsafe {
            pw_sys::pw_thread_loop_accept(self.as_raw_ptr());
        }
    }

    /// Check if inside the thread
    pub fn in_thread(&self) {
        unsafe {
            pw_sys::pw_thread_loop_in_thread(self.as_raw_ptr());
        }
    }
}

// Safety: The pw_loop is guaranteed to remain valid while any clone of the `ThreadLoop` is held,
//         because we use an internal Rc to keep the pw_thread_loop containing the pw_loop alive.
unsafe impl IsLoopRc for ThreadLoop {}

impl std::convert::AsRef<LoopRef> for ThreadLoop {
    fn as_ref(&self) -> &LoopRef {
        self.loop_()
    }
}

pub struct WeakThreadLoop {
    weak: Weak<ThreadLoopInner>,
}

impl WeakThreadLoop {
    pub fn upgrade(&self) -> Option<ThreadLoop> {
        self.weak.upgrade().map(|inner| ThreadLoop { inner })
    }
}

pub struct ThreadLoopLockGuard<'a> {
    thread_loop: &'a ThreadLoop,
}

impl<'a> ThreadLoopLockGuard<'a> {
    fn new(thread_loop: &'a ThreadLoop) -> Self {
        unsafe {
            pw_sys::pw_thread_loop_lock(thread_loop.as_raw_ptr());
        }
        ThreadLoopLockGuard { thread_loop }
    }

    /// Unlock the loop
    ///
    /// Unlocking the loop will call `drop()`
    pub fn unlock(self) {
        drop(self);
    }
}

impl<'a> Drop for ThreadLoopLockGuard<'a> {
    fn drop(&mut self) {
        unsafe {
            pw_sys::pw_thread_loop_unlock(self.thread_loop.as_raw_ptr());
        }
    }
}

#[derive(Debug)]
struct ThreadLoopInner {
    ptr: ptr::NonNull<pw_sys::pw_thread_loop>,
}

impl ThreadLoopInner {
    pub unsafe fn from_raw(ptr: ptr::NonNull<pw_sys::pw_thread_loop>) -> Self {
        Self { ptr }
    }
}

impl Drop for ThreadLoopInner {
    fn drop(&mut self) {
        unsafe { pw_sys::pw_thread_loop_destroy(self.ptr.as_ptr()) }
    }
}
