use std::{
    ffi::{c_void, CStr},
    fmt, mem,
    ops::Deref,
    pin::Pin,
    ptr,
};

use bitflags::bitflags;
use spa::spa_interface_call_method;

use crate::{
    proxy::{Listener, Proxy, ProxyT},
    types::ObjectType,
};

#[derive(Debug)]
pub struct Link {
    proxy: Proxy,
}

impl ProxyT for Link {
    fn type_() -> ObjectType {
        ObjectType::Link
    }

    fn upcast(self) -> Proxy {
        self.proxy
    }

    fn upcast_ref(&self) -> &Proxy {
        &self.proxy
    }

    unsafe fn from_proxy_unchecked(proxy: Proxy) -> Self
    where
        Self: Sized,
    {
        Self { proxy }
    }
}

impl Link {
    #[must_use]
    pub fn add_listener_local(&self) -> LinkListenerLocalBuilder {
        LinkListenerLocalBuilder {
            link: self,
            cbs: ListenerLocalCallbacks::default(),
        }
    }
}

pub struct LinkListener {
    // Need to stay allocated while the listener is registered
    #[allow(dead_code)]
    events: Pin<Box<pw_sys::pw_link_events>>,
    listener: Pin<Box<spa_sys::spa_hook>>,
    #[allow(dead_code)]
    data: Box<ListenerLocalCallbacks>,
}

impl Listener for LinkListener {}

impl Drop for LinkListener {
    fn drop(&mut self) {
        spa::utils::hook::remove(*self.listener);
    }
}

#[derive(Default)]
struct ListenerLocalCallbacks {
    #[allow(clippy::type_complexity)]
    info: Option<Box<dyn Fn(&LinkInfoRef)>>,
}

pub struct LinkListenerLocalBuilder<'link> {
    link: &'link Link,
    cbs: ListenerLocalCallbacks,
}

impl<'a> LinkListenerLocalBuilder<'a> {
    #[must_use]
    pub fn info<F>(mut self, info: F) -> Self
    where
        F: Fn(&LinkInfoRef) + 'static,
    {
        self.cbs.info = Some(Box::new(info));
        self
    }

    #[must_use]
    pub fn register(self) -> LinkListener {
        unsafe extern "C" fn link_events_info(
            data: *mut c_void,
            info: *const pw_sys::pw_link_info,
        ) {
            let callbacks = (data as *mut ListenerLocalCallbacks).as_ref().unwrap();
            let info = ptr::NonNull::new(info as *mut pw_sys::pw_link_info).expect("info is NULL");
            let info = info.cast::<LinkInfoRef>().as_ref();
            callbacks.info.as_ref().unwrap()(info);
        }

        let e = unsafe {
            let mut e: Pin<Box<pw_sys::pw_link_events>> = Box::pin(mem::zeroed());
            e.version = pw_sys::PW_VERSION_LINK_EVENTS;

            if self.cbs.info.is_some() {
                e.info = Some(link_events_info);
            }

            e
        };

        let (listener, data) = unsafe {
            let link = &self.link.proxy.as_ptr();

            let data = Box::into_raw(Box::new(self.cbs));
            let mut listener: Pin<Box<spa_sys::spa_hook>> = Box::pin(mem::zeroed());
            let listener_ptr: *mut spa_sys::spa_hook = listener.as_mut().get_unchecked_mut();

            spa_interface_call_method!(
                link,
                pw_sys::pw_link_methods,
                add_listener,
                listener_ptr.cast(),
                e.as_ref().get_ref(),
                data as *mut _
            );

            (listener, Box::from_raw(data))
        };

        LinkListener {
            events: e,
            listener,
            data,
        }
    }
}

#[repr(transparent)]
pub struct LinkInfoRef(pw_sys::pw_link_info);

impl LinkInfoRef {
    pub fn as_raw(&self) -> &pw_sys::pw_link_info {
        &self.0
    }

    pub fn as_raw_ptr(&self) -> *mut pw_sys::pw_link_info {
        std::ptr::addr_of!(self.0).cast_mut()
    }

    pub fn id(&self) -> u32 {
        self.0.id
    }

    pub fn output_node_id(&self) -> u32 {
        self.0.output_node_id
    }

    pub fn output_port_id(&self) -> u32 {
        self.0.output_port_id
    }

    pub fn input_node_id(&self) -> u32 {
        self.0.input_node_id
    }

    pub fn input_port_id(&self) -> u32 {
        self.0.input_port_id
    }

    pub fn state(&self) -> LinkState {
        let raw_state = self.0.state;
        match raw_state {
            pw_sys::pw_link_state_PW_LINK_STATE_ERROR => {
                let error = unsafe { CStr::from_ptr(self.0.error).to_str().unwrap() };
                LinkState::Error(error)
            }
            pw_sys::pw_link_state_PW_LINK_STATE_UNLINKED => LinkState::Unlinked,
            pw_sys::pw_link_state_PW_LINK_STATE_INIT => LinkState::Init,
            pw_sys::pw_link_state_PW_LINK_STATE_NEGOTIATING => LinkState::Negotiating,
            pw_sys::pw_link_state_PW_LINK_STATE_ALLOCATING => LinkState::Allocating,
            pw_sys::pw_link_state_PW_LINK_STATE_PAUSED => LinkState::Paused,
            pw_sys::pw_link_state_PW_LINK_STATE_ACTIVE => LinkState::Active,
            _ => panic!("Invalid link state: {}", raw_state),
        }
    }

    pub fn change_mask(&self) -> LinkChangeMask {
        LinkChangeMask::from_bits_retain(self.0.change_mask)
    }

    pub fn format(&self) -> Option<&spa::pod::Pod> {
        let format = self.0.format;
        if format.is_null() {
            None
        } else {
            Some(unsafe { spa::pod::Pod::from_raw(format) })
        }
    }

    pub fn props(&self) -> Option<&spa::utils::dict::DictRef> {
        let props_ptr: *mut spa::utils::dict::DictRef = self.0.props.cast();
        ptr::NonNull::new(props_ptr).map(|ptr| unsafe { ptr.as_ref() })
    }
}

impl fmt::Debug for LinkInfoRef {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("LinkInfoRef")
            .field("id", &self.id())
            .field("output_node_id", &self.output_node_id())
            .field("output_port_id", &self.output_port_id())
            .field("input_node_id", &self.input_node_id())
            .field("input_port_id", &self.input_port_id())
            .field("change-mask", &self.change_mask())
            .field("state", &self.state())
            .field("props", &self.props())
            // TODO: .field("format", &self.format())
            .finish()
    }
}

pub struct LinkInfo {
    ptr: ptr::NonNull<pw_sys::pw_link_info>,
}

impl LinkInfo {
    pub fn new(ptr: ptr::NonNull<pw_sys::pw_link_info>) -> Self {
        Self { ptr }
    }

    pub fn from_raw(raw: *mut pw_sys::pw_link_info) -> Self {
        Self {
            ptr: ptr::NonNull::new(raw).expect("Provided pointer is null"),
        }
    }

    pub fn into_raw(self) -> *mut pw_sys::pw_link_info {
        std::mem::ManuallyDrop::new(self).ptr.as_ptr()
    }
}

impl Drop for LinkInfo {
    fn drop(&mut self) {
        unsafe { pw_sys::pw_link_info_free(self.ptr.as_ptr()) }
    }
}

impl std::ops::Deref for LinkInfo {
    type Target = LinkInfoRef;

    fn deref(&self) -> &Self::Target {
        unsafe { self.ptr.cast::<LinkInfoRef>().as_ref() }
    }
}

impl AsRef<LinkInfoRef> for LinkInfo {
    fn as_ref(&self) -> &LinkInfoRef {
        self.deref()
    }
}

bitflags! {
    #[derive(Debug, PartialEq, Eq, Clone, Copy)]
    pub struct LinkChangeMask: u64 {
        const STATE = pw_sys::PW_LINK_CHANGE_MASK_STATE as u64;
        const FORMAT = pw_sys::PW_LINK_CHANGE_MASK_FORMAT as u64;
        const PROPS = pw_sys::PW_LINK_CHANGE_MASK_PROPS as u64;
    }
}

impl fmt::Debug for LinkInfo {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("LinkInfo")
            .field("id", &self.id())
            .field("output_node_id", &self.output_node_id())
            .field("output_port_id", &self.output_port_id())
            .field("input_node_id", &self.input_node_id())
            .field("input_port_id", &self.input_port_id())
            .field("change-mask", &self.change_mask())
            .field("state", &self.state())
            .field("props", &self.props())
            // TODO: .field("format", &self.format())
            .finish()
    }
}

#[derive(Debug)]
pub enum LinkState<'a> {
    Error(&'a str),
    Unlinked,
    Init,
    Negotiating,
    Allocating,
    Paused,
    Active,
}
