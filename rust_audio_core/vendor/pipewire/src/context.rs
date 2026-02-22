// Copyright The pipewire-rs Contributors.
// SPDX-License-Identifier: MIT

use std::{
    fmt,
    ops::Deref,
    os::unix::prelude::{IntoRawFd, OwnedFd},
    ptr,
    rc::Rc,
};

use crate::core::Core;
use crate::error::Error;
use crate::loop_::{IsLoopRc, LoopRef};
use crate::properties::{Properties, PropertiesRef};

#[repr(transparent)]
pub struct ContextRef(pw_sys::pw_context);

impl ContextRef {
    pub fn as_raw(&self) -> &pw_sys::pw_context {
        &self.0
    }

    pub fn as_raw_ptr(&self) -> *mut pw_sys::pw_context {
        std::ptr::addr_of!(self.0).cast_mut()
    }

    pub fn properties(&self) -> &PropertiesRef {
        unsafe {
            let props = pw_sys::pw_context_get_properties(self.as_raw_ptr());
            let props = ptr::NonNull::new(props.cast_mut()).expect("context properties is NULL");
            props.cast().as_ref()
        }
    }
    pub fn update_properties(&self, properties: &spa::utils::dict::DictRef) {
        unsafe {
            pw_sys::pw_context_update_properties(self.as_raw_ptr(), properties.as_raw_ptr());
        }
    }
}

#[derive(Clone, Debug)]
pub struct Context {
    inner: Rc<ContextInner>,
}

pub struct ContextInner {
    ptr: ptr::NonNull<pw_sys::pw_context>,
    /// Store the loop here, so that the loop is not dropped before the context, which may lead to
    /// undefined behaviour.
    _loop: Box<dyn AsRef<LoopRef>>,
}

impl fmt::Debug for ContextInner {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("ContextInner")
            .field("ptr", &self.ptr)
            .finish()
    }
}

impl Context {
    fn new_internal<T: IsLoopRc>(loop_: &T, properties: Option<Properties>) -> Result<Self, Error> {
        let loop_: Box<dyn AsRef<LoopRef>> = Box::new(loop_.clone());
        let props = properties.map_or(ptr::null(), |props| props.into_raw()) as *mut _;
        let context = unsafe {
            pw_sys::pw_context_new((*loop_).as_ref().as_raw() as *const _ as *mut _, props, 0)
        };
        let context = ptr::NonNull::new(context).ok_or(Error::CreationFailed)?;

        Ok(Context {
            inner: Rc::new(ContextInner {
                ptr: context,
                _loop: loop_,
            }),
        })
    }

    pub fn new<T: IsLoopRc>(loop_: &T) -> Result<Self, Error> {
        Self::new_internal(loop_, None)
    }

    pub fn with_properties<T: IsLoopRc>(loop_: &T, properties: Properties) -> Result<Self, Error> {
        Self::new_internal(loop_, Some(properties))
    }

    pub fn connect(&self, properties: Option<Properties>) -> Result<Core, Error> {
        let properties = properties.map_or(ptr::null_mut(), |p| p.into_raw());

        unsafe {
            let core = pw_sys::pw_context_connect(self.as_raw_ptr(), properties, 0);
            let ptr = ptr::NonNull::new(core).ok_or(Error::CreationFailed)?;

            Ok(Core::from_ptr(ptr, self.clone()))
        }
    }

    pub fn connect_fd(&self, fd: OwnedFd, properties: Option<Properties>) -> Result<Core, Error> {
        let properties = properties.map_or(ptr::null_mut(), |p| p.into_raw());

        unsafe {
            let raw_fd = fd.into_raw_fd();
            let core = pw_sys::pw_context_connect_fd(self.as_raw_ptr(), raw_fd, properties, 0);
            let ptr = ptr::NonNull::new(core).ok_or(Error::CreationFailed)?;

            Ok(Core::from_ptr(ptr, self.clone()))
        }
    }
}

impl std::convert::AsRef<ContextRef> for Context {
    fn as_ref(&self) -> &ContextRef {
        self.deref()
    }
}

impl std::ops::Deref for Context {
    type Target = ContextInner;

    fn deref(&self) -> &Self::Target {
        &self.inner
    }
}

impl std::convert::AsRef<ContextRef> for ContextInner {
    fn as_ref(&self) -> &ContextRef {
        self.deref()
    }
}

impl std::ops::Deref for ContextInner {
    type Target = ContextRef;

    fn deref(&self) -> &Self::Target {
        unsafe { &*(self.ptr.as_ptr() as *mut ContextRef) }
    }
}

impl Drop for ContextInner {
    fn drop(&mut self) {
        unsafe { pw_sys::pw_context_destroy(self.ptr.as_ptr()) }
    }
}
