// Copyright The pipewire-rs Contributors.
// SPDX-License-Identifier: MIT

use libc::{c_char, c_void};
use std::fmt;
use std::mem;
use std::pin::Pin;
use std::{ffi::CStr, ptr};

use crate::{types::ObjectType, Error};

pub struct Proxy {
    ptr: ptr::NonNull<pw_sys::pw_proxy>,
}

// Wrapper around a proxy pointer
impl Proxy {
    pub(crate) fn new(ptr: ptr::NonNull<pw_sys::pw_proxy>) -> Self {
        Proxy { ptr }
    }

    pub(crate) fn as_ptr(&self) -> *mut pw_sys::pw_proxy {
        self.ptr.as_ptr()
    }

    pub fn add_listener_local(&self) -> ProxyListenerLocalBuilder {
        ProxyListenerLocalBuilder {
            proxy: self,
            cbs: ListenerLocalCallbacks::default(),
        }
    }

    pub fn id(&self) -> u32 {
        unsafe { pw_sys::pw_proxy_get_id(self.as_ptr()) }
    }

    /// Get the type of the proxy as well as it's version.
    pub fn get_type(&self) -> (ObjectType, u32) {
        unsafe {
            let mut version = 0;
            let proxy_type = pw_sys::pw_proxy_get_type(self.as_ptr(), &mut version);
            let proxy_type = CStr::from_ptr(proxy_type);

            (
                ObjectType::from_str(proxy_type.to_str().expect("invalid proxy type")),
                version,
            )
        }
    }

    /// Attempt to downcast the proxy to the provided type.
    ///
    /// The downcast will fail if the type that the proxy represents does not match the provided type. \
    /// In that case, the function returns `(self, Error::WrongProxyType)` so that the proxy is not lost.
    pub(crate) fn downcast<P: ProxyT>(self) -> Result<P, (Self, Error)> {
        // Make sure the proxy we got has the type that is requested
        if P::type_() == self.get_type().0 {
            unsafe { Ok(P::from_proxy_unchecked(self)) }
        } else {
            Err((self, Error::WrongProxyType))
        }
    }
}

impl Drop for Proxy {
    fn drop(&mut self) {
        unsafe {
            pw_sys::pw_proxy_destroy(self.as_ptr());
        }
    }
}

impl fmt::Debug for Proxy {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let (proxy_type, version) = self.get_type();

        f.debug_struct("Proxy")
            .field("id", &self.id())
            .field("type", &proxy_type)
            .field("version", &version)
            .finish()
    }
}

// Trait implemented by high level proxy wrappers
pub trait ProxyT {
    // Add Sized restriction on those methods so it can be used as a
    // trait object, see E0038
    fn type_() -> ObjectType
    where
        Self: Sized;

    fn upcast(self) -> Proxy;
    fn upcast_ref(&self) -> &Proxy;

    /// Downcast the provided proxy to `Self` without checking that the type matches.
    ///
    /// This function should not be used by applications.
    /// If you really do need a way to downcast a proxy to it's type, please open an issue.
    ///
    /// # Safety
    /// It must be manually ensured that the provided proxy is actually a proxy representing the created type. \
    /// Otherwise, undefined behaviour may occur.
    unsafe fn from_proxy_unchecked(proxy: Proxy) -> Self
    where
        Self: Sized;
}

// Trait implemented by listener on high level proxy wrappers.
pub trait Listener {}

pub struct ProxyListener {
    // Need to stay allocated while the listener is registered
    #[allow(dead_code)]
    events: Pin<Box<pw_sys::pw_proxy_events>>,
    listener: Pin<Box<spa_sys::spa_hook>>,
    #[allow(dead_code)]
    data: Box<ListenerLocalCallbacks>,
}

impl Listener for ProxyListener {}

impl Drop for ProxyListener {
    fn drop(&mut self) {
        spa::utils::hook::remove(*self.listener);
    }
}
#[derive(Default)]
struct ListenerLocalCallbacks {
    destroy: Option<Box<dyn Fn()>>,
    bound: Option<Box<dyn Fn(u32)>>,
    removed: Option<Box<dyn Fn()>>,
    done: Option<Box<dyn Fn(i32)>>,
    #[allow(clippy::type_complexity)]
    error: Option<Box<dyn Fn(i32, i32, &str)>>, // TODO: return a proper Error enum?
}

pub struct ProxyListenerLocalBuilder<'a> {
    proxy: &'a Proxy,
    cbs: ListenerLocalCallbacks,
}

impl<'a> ProxyListenerLocalBuilder<'a> {
    #[must_use]
    pub fn destroy<F>(mut self, destroy: F) -> Self
    where
        F: Fn() + 'static,
    {
        self.cbs.destroy = Some(Box::new(destroy));
        self
    }

    #[must_use]
    pub fn bound<F>(mut self, bound: F) -> Self
    where
        F: Fn(u32) + 'static,
    {
        self.cbs.bound = Some(Box::new(bound));
        self
    }

    #[must_use]
    pub fn removed<F>(mut self, removed: F) -> Self
    where
        F: Fn() + 'static,
    {
        self.cbs.removed = Some(Box::new(removed));
        self
    }

    #[must_use]
    pub fn done<F>(mut self, done: F) -> Self
    where
        F: Fn(i32) + 'static,
    {
        self.cbs.done = Some(Box::new(done));
        self
    }

    #[must_use]
    pub fn error<F>(mut self, error: F) -> Self
    where
        F: Fn(i32, i32, &str) + 'static,
    {
        self.cbs.error = Some(Box::new(error));
        self
    }

    #[must_use]
    pub fn register(self) -> ProxyListener {
        unsafe extern "C" fn proxy_destroy(data: *mut c_void) {
            let callbacks = (data as *mut ListenerLocalCallbacks).as_ref().unwrap();
            callbacks.destroy.as_ref().unwrap()();
        }

        unsafe extern "C" fn proxy_bound(data: *mut c_void, global_id: u32) {
            let callbacks = (data as *mut ListenerLocalCallbacks).as_ref().unwrap();
            callbacks.bound.as_ref().unwrap()(global_id);
        }

        unsafe extern "C" fn proxy_removed(data: *mut c_void) {
            let callbacks = (data as *mut ListenerLocalCallbacks).as_ref().unwrap();
            callbacks.removed.as_ref().unwrap()();
        }

        unsafe extern "C" fn proxy_done(data: *mut c_void, seq: i32) {
            let callbacks = (data as *mut ListenerLocalCallbacks).as_ref().unwrap();
            callbacks.done.as_ref().unwrap()(seq);
        }

        unsafe extern "C" fn proxy_error(
            data: *mut c_void,
            seq: i32,
            res: i32,
            message: *const c_char,
        ) {
            let callbacks = (data as *mut ListenerLocalCallbacks).as_ref().unwrap();
            let message = CStr::from_ptr(message).to_str().unwrap();
            callbacks.error.as_ref().unwrap()(seq, res, message);
        }

        let e = unsafe {
            let mut e: Pin<Box<pw_sys::pw_proxy_events>> = Box::pin(mem::zeroed());
            e.version = pw_sys::PW_VERSION_PROXY_EVENTS;

            if self.cbs.destroy.is_some() {
                e.destroy = Some(proxy_destroy);
            }

            if self.cbs.bound.is_some() {
                e.bound = Some(proxy_bound);
            }

            if self.cbs.removed.is_some() {
                e.removed = Some(proxy_removed);
            }

            if self.cbs.done.is_some() {
                e.done = Some(proxy_done);
            }

            if self.cbs.error.is_some() {
                e.error = Some(proxy_error);
            }

            e
        };

        let (listener, data) = unsafe {
            let proxy = &self.proxy.as_ptr();

            let data = Box::into_raw(Box::new(self.cbs));
            let mut listener: Pin<Box<spa_sys::spa_hook>> = Box::pin(mem::zeroed());
            let listener_ptr: *mut spa_sys::spa_hook = listener.as_mut().get_unchecked_mut();
            let funcs: *const pw_sys::pw_proxy_events = e.as_ref().get_ref();

            pw_sys::pw_proxy_add_listener(
                proxy.cast(),
                listener_ptr.cast(),
                funcs.cast(),
                data as *mut _,
            );

            (listener, Box::from_raw(data))
        };

        ProxyListener {
            events: e,
            listener,
            data,
        }
    }
}
