// Copyright The pipewire-rs Contributors.
// SPDX-License-Identifier: MIT

//! Pipewire Stream

use crate::buffer::Buffer;
use crate::{
    core::Core,
    error::Error,
    properties::{Properties, PropertiesRef},
};
use bitflags::bitflags;
use spa::utils::result::SpaResult;
use std::{
    ffi::{self, CStr, CString},
    fmt::Debug,
    mem, os,
    pin::Pin,
    ptr,
};

#[derive(Debug, PartialEq)]
pub enum StreamState {
    Error(String),
    Unconnected,
    Connecting,
    Paused,
    Streaming,
}

impl StreamState {
    pub(crate) fn from_raw(state: pw_sys::pw_stream_state, error: *const os::raw::c_char) -> Self {
        match state {
            pw_sys::pw_stream_state_PW_STREAM_STATE_UNCONNECTED => StreamState::Unconnected,
            pw_sys::pw_stream_state_PW_STREAM_STATE_CONNECTING => StreamState::Connecting,
            pw_sys::pw_stream_state_PW_STREAM_STATE_PAUSED => StreamState::Paused,
            pw_sys::pw_stream_state_PW_STREAM_STATE_STREAMING => StreamState::Streaming,
            _ => {
                let error = if error.is_null() {
                    "".to_string()
                } else {
                    unsafe { ffi::CStr::from_ptr(error).to_string_lossy().to_string() }
                };

                StreamState::Error(error)
            }
        }
    }
}

/// A wrapper around the pipewire stream interface. Streams are a higher
/// level abstraction around nodes in the graph. A stream can be used to send or
/// receive frames of audio or video data by connecting it to another node.
/// `D` is the user data, to allow passing extra context to the callbacks.
pub struct Stream {
    ptr: ptr::NonNull<pw_sys::pw_stream>,
    // objects that need to stay alive while the Stream is
    _core: Core,
}

impl Stream {
    /// Create a [`Stream`]
    ///
    /// Initialises a new stream with the given `name` and `properties`.
    pub fn new(core: &Core, name: &str, properties: Properties) -> Result<Self, Error> {
        let name = CString::new(name).expect("Invalid byte in stream name");
        let stream = unsafe {
            pw_sys::pw_stream_new(core.as_raw_ptr(), name.as_ptr(), properties.into_raw())
        };
        let stream = ptr::NonNull::new(stream).ok_or(Error::CreationFailed)?;

        Ok(Stream {
            ptr: stream,
            _core: core.clone(),
        })
    }

    pub fn into_raw(self) -> *mut pw_sys::pw_stream {
        let mut this = std::mem::ManuallyDrop::new(self);

        // FIXME: self needs to be wrapped in ManuallyDrop so the raw stream
        //        isn't destroyed. However, the core should still be dropped.
        //        Is there a cleaner and safer way to drop the core than like this?
        unsafe {
            ptr::drop_in_place(ptr::addr_of_mut!(this._core));
        }

        this.ptr.as_ptr()
    }
}

impl std::ops::Deref for Stream {
    type Target = StreamRef;

    fn deref(&self) -> &Self::Target {
        unsafe { self.ptr.cast().as_ref() }
    }
}

impl std::fmt::Debug for Stream {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("Stream")
            .field("name", &self.name())
            .field("state", &self.state())
            .field("node-id", &self.node_id())
            .field("properties", &self.properties())
            .finish()
    }
}

impl std::ops::Drop for Stream {
    fn drop(&mut self) {
        unsafe { pw_sys::pw_stream_destroy(self.as_raw_ptr()) }
    }
}

#[repr(transparent)]
pub struct StreamRef(pw_sys::pw_stream);

impl StreamRef {
    pub fn as_raw(&self) -> &pw_sys::pw_stream {
        &self.0
    }

    pub fn as_raw_ptr(&self) -> *mut pw_sys::pw_stream {
        ptr::addr_of!(self.0).cast_mut()
    }

    /// Add a local listener builder
    #[must_use = "Fluent builder API"]
    pub fn add_local_listener_with_user_data<D>(
        &self,
        user_data: D,
    ) -> ListenerLocalBuilder<'_, D> {
        let mut callbacks = ListenerLocalCallbacks::with_user_data(user_data);
        callbacks.stream =
            Some(ptr::NonNull::new(self.as_raw_ptr()).expect("Pointer should be nonnull"));
        ListenerLocalBuilder {
            stream: self,
            callbacks,
        }
    }

    /// Add a local listener builder. User data is initialized with its default value
    #[must_use = "Fluent builder API"]
    pub fn add_local_listener<D: Default>(&self) -> ListenerLocalBuilder<'_, D> {
        self.add_local_listener_with_user_data(Default::default())
    }

    /// Connect the stream
    ///
    /// Tries to connect to the node `id` in the given `direction`. If no node
    /// is provided then any suitable node will be used.
    // FIXME: high-level API for params
    pub fn connect(
        &self,
        direction: spa::utils::Direction,
        id: Option<u32>,
        flags: StreamFlags,
        params: &mut [&spa::pod::Pod],
    ) -> Result<(), Error> {
        let r = unsafe {
            pw_sys::pw_stream_connect(
                self.as_raw_ptr(),
                direction.as_raw(),
                id.unwrap_or(crate::constants::ID_ANY),
                flags.bits(),
                // We cast from *mut [&spa::pod::Pod] to *mut [*const spa_sys::spa_pod] here,
                // which is valid because spa::pod::Pod is a transparent wrapper around spa_sys::spa_pod
                params.as_mut_ptr().cast(),
                params.len() as u32,
            )
        };

        SpaResult::from_c(r).into_sync_result()?;
        Ok(())
    }

    /// Update Parameters
    ///
    /// Call from the `param_changed` callback to negotiate a new set of
    /// parameters for the stream.
    // FIXME: high-level API for params
    pub fn update_params(&self, params: &mut [&spa::pod::Pod]) -> Result<(), Error> {
        let r = unsafe {
            pw_sys::pw_stream_update_params(
                self.as_raw_ptr(),
                params.as_mut_ptr().cast(),
                params.len() as u32,
            )
        };

        SpaResult::from_c(r).into_sync_result()?;
        Ok(())
    }

    /// Activate or deactivate the stream
    pub fn set_active(&self, active: bool) -> Result<(), Error> {
        let r = unsafe { pw_sys::pw_stream_set_active(self.as_raw_ptr(), active) };

        SpaResult::from_c(r).into_sync_result()?;
        Ok(())
    }

    /// Take a Buffer from the Stream
    ///
    /// Removes a buffer from the stream. If this is an input stream the buffer
    /// will contain data ready to process. If this is an output stream it can
    /// be filled.
    ///
    /// # Safety
    ///
    /// The pointer returned could be NULL if no buffer is available. The buffer
    /// should be returned to the stream once processing is complete.
    pub unsafe fn dequeue_raw_buffer(&self) -> *mut pw_sys::pw_buffer {
        pw_sys::pw_stream_dequeue_buffer(self.as_raw_ptr())
    }

    pub fn dequeue_buffer(&self) -> Option<Buffer> {
        unsafe { Buffer::from_raw(self.dequeue_raw_buffer(), self) }
    }

    /// Return a Buffer to the Stream
    ///
    /// Give back a buffer once processing is complete. Use this to queue up a
    /// frame for an output stream, or return the buffer to the pool ready to
    /// receive new data for an input stream.
    ///
    /// # Safety
    ///
    /// The buffer pointer should be one obtained from this stream instance by
    /// a call to [StreamRef::dequeue_raw_buffer()].
    pub unsafe fn queue_raw_buffer(&self, buffer: *mut pw_sys::pw_buffer) {
        pw_sys::pw_stream_queue_buffer(self.as_raw_ptr(), buffer);
    }

    /// Disconnect the stream
    pub fn disconnect(&self) -> Result<(), Error> {
        let r = unsafe { pw_sys::pw_stream_disconnect(self.as_raw_ptr()) };

        SpaResult::from_c(r).into_sync_result()?;
        Ok(())
    }

    /// Set the stream in error state
    ///
    /// # Panics
    /// Will panic if `error` contains a 0 byte.
    ///
    pub fn set_error(&mut self, res: i32, error: &str) {
        let error = CString::new(error).expect("failed to convert error to CString");
        unsafe {
            pw_sys::pw_stream_set_error(self.as_raw_ptr(), res, error.as_c_str().as_ptr());
        }
    }

    /// Flush the stream. When  `drain` is `true`, the `drained` callback will
    /// be called when all data is played or recorded.
    pub fn flush(&self, drain: bool) -> Result<(), Error> {
        let r = unsafe { pw_sys::pw_stream_flush(self.as_raw_ptr(), drain) };

        SpaResult::from_c(r).into_sync_result()?;
        Ok(())
    }

    pub fn set_control(&self, id: u32, values: &[f32]) -> Result<(), Error> {
        let r = unsafe {
            pw_sys::pw_stream_set_control(
                self.as_raw_ptr(),
                id,
                values.len() as u32,
                values.as_ptr() as *mut f32,
            )
        };
        SpaResult::from_c(r).into_sync_result()?;
        Ok(())
    }

    // getters

    /// Get the name of the stream.
    pub fn name(&self) -> String {
        let name = unsafe {
            let name = pw_sys::pw_stream_get_name(self.as_raw_ptr());
            CStr::from_ptr(name)
        };

        name.to_string_lossy().to_string()
    }

    /// Get the current state of the stream.
    pub fn state(&self) -> StreamState {
        let mut error: *const std::os::raw::c_char = ptr::null();
        let state = unsafe {
            pw_sys::pw_stream_get_state(self.as_raw_ptr(), (&mut error) as *mut *const _)
        };
        StreamState::from_raw(state, error)
    }

    /// Get the properties of the stream.
    pub fn properties(&self) -> &PropertiesRef {
        unsafe {
            let props = pw_sys::pw_stream_get_properties(self.as_raw_ptr());
            let props = ptr::NonNull::new(props.cast_mut()).expect("stream properties is NULL");
            props.cast().as_ref()
        }
    }

    /// Get the node ID of the stream.
    pub fn node_id(&self) -> u32 {
        unsafe { pw_sys::pw_stream_get_node_id(self.as_raw_ptr()) }
    }

    #[cfg(feature = "v0_3_34")]
    pub fn is_driving(&self) -> bool {
        unsafe { pw_sys::pw_stream_is_driving(self.as_raw_ptr()) }
    }

    #[cfg(feature = "v0_3_34")]
    pub fn trigger_process(&self) -> Result<(), Error> {
        let r = unsafe { pw_sys::pw_stream_trigger_process(self.as_raw_ptr()) };

        SpaResult::from_c(r).into_result()?;
        Ok(())
    }

    // TODO: pw_stream_get_core()
    // TODO: pw_stream_get_time()
}

type ParamChangedCB<D> = dyn FnMut(&StreamRef, &mut D, u32, Option<&spa::pod::Pod>);
type ProcessCB<D> = dyn FnMut(&StreamRef, &mut D);

#[allow(clippy::type_complexity)]
pub struct ListenerLocalCallbacks<D> {
    pub state_changed: Option<Box<dyn FnMut(&StreamRef, &mut D, StreamState, StreamState)>>,
    pub control_info:
        Option<Box<dyn FnMut(&StreamRef, &mut D, u32, *const pw_sys::pw_stream_control)>>,
    pub io_changed: Option<Box<dyn FnMut(&StreamRef, &mut D, u32, *mut os::raw::c_void, u32)>>,
    pub param_changed: Option<Box<ParamChangedCB<D>>>,
    pub add_buffer: Option<Box<dyn FnMut(&StreamRef, &mut D, *mut pw_sys::pw_buffer)>>,
    pub remove_buffer: Option<Box<dyn FnMut(&StreamRef, &mut D, *mut pw_sys::pw_buffer)>>,
    pub process: Option<Box<ProcessCB<D>>>,
    pub drained: Option<Box<dyn FnMut(&StreamRef, &mut D)>>,
    #[cfg(feature = "v0_3_39")]
    pub command: Option<Box<dyn FnMut(&StreamRef, &mut D, *const spa_sys::spa_command)>>,
    #[cfg(feature = "v0_3_40")]
    pub trigger_done: Option<Box<dyn FnMut(&StreamRef, &mut D)>>,
    pub user_data: D,
    stream: Option<ptr::NonNull<pw_sys::pw_stream>>,
}

unsafe fn unwrap_stream_ptr<'a>(stream: Option<ptr::NonNull<pw_sys::pw_stream>>) -> &'a StreamRef {
    stream
        .map(|ptr| ptr.cast::<StreamRef>().as_ref())
        .expect("stream cannot be null")
}

impl<D> ListenerLocalCallbacks<D> {
    fn with_user_data(user_data: D) -> Self {
        ListenerLocalCallbacks {
            process: Default::default(),
            stream: Default::default(),
            drained: Default::default(),
            add_buffer: Default::default(),
            control_info: Default::default(),
            io_changed: Default::default(),
            param_changed: Default::default(),
            remove_buffer: Default::default(),
            state_changed: Default::default(),
            #[cfg(feature = "v0_3_39")]
            command: Default::default(),
            #[cfg(feature = "v0_3_40")]
            trigger_done: Default::default(),
            user_data,
        }
    }

    pub(crate) fn into_raw(
        self,
    ) -> (
        Pin<Box<pw_sys::pw_stream_events>>,
        Box<ListenerLocalCallbacks<D>>,
    ) {
        let callbacks = Box::new(self);

        unsafe extern "C" fn on_state_changed<D>(
            data: *mut os::raw::c_void,
            old: pw_sys::pw_stream_state,
            new: pw_sys::pw_stream_state,
            error: *const os::raw::c_char,
        ) {
            if let Some(state) = (data as *mut ListenerLocalCallbacks<D>).as_mut() {
                if let Some(cb) = &mut state.state_changed {
                    let stream = unwrap_stream_ptr(state.stream);
                    let old = StreamState::from_raw(old, error);
                    let new = StreamState::from_raw(new, error);
                    cb(stream, &mut state.user_data, old, new)
                };
            }
        }

        unsafe extern "C" fn on_control_info<D>(
            data: *mut os::raw::c_void,
            id: u32,
            control: *const pw_sys::pw_stream_control,
        ) {
            if let Some(state) = (data as *mut ListenerLocalCallbacks<D>).as_mut() {
                if let Some(cb) = &mut state.control_info {
                    let stream = unwrap_stream_ptr(state.stream);
                    cb(stream, &mut state.user_data, id, control);
                }
            }
        }

        unsafe extern "C" fn on_io_changed<D>(
            data: *mut os::raw::c_void,
            id: u32,
            area: *mut os::raw::c_void,
            size: u32,
        ) {
            if let Some(state) = (data as *mut ListenerLocalCallbacks<D>).as_mut() {
                if let Some(cb) = &mut state.io_changed {
                    let stream = unwrap_stream_ptr(state.stream);
                    cb(stream, &mut state.user_data, id, area, size);
                }
            }
        }

        unsafe extern "C" fn on_param_changed<D>(
            data: *mut os::raw::c_void,
            id: u32,
            param: *const spa_sys::spa_pod,
        ) {
            if let Some(state) = (data as *mut ListenerLocalCallbacks<D>).as_mut() {
                if let Some(cb) = &mut state.param_changed {
                    let stream = unwrap_stream_ptr(state.stream);
                    let param = if !param.is_null() {
                        Some(spa::pod::Pod::from_raw(param))
                    } else {
                        None
                    };

                    cb(stream, &mut state.user_data, id, param);
                }
            }
        }

        unsafe extern "C" fn on_add_buffer<D>(
            data: *mut ::std::os::raw::c_void,
            buffer: *mut pw_sys::pw_buffer,
        ) {
            if let Some(state) = (data as *mut ListenerLocalCallbacks<D>).as_mut() {
                if let Some(cb) = &mut state.add_buffer {
                    let stream = unwrap_stream_ptr(state.stream);
                    cb(stream, &mut state.user_data, buffer);
                }
            }
        }

        unsafe extern "C" fn on_remove_buffer<D>(
            data: *mut ::std::os::raw::c_void,
            buffer: *mut pw_sys::pw_buffer,
        ) {
            if let Some(state) = (data as *mut ListenerLocalCallbacks<D>).as_mut() {
                if let Some(cb) = &mut state.remove_buffer {
                    let stream = unwrap_stream_ptr(state.stream);
                    cb(stream, &mut state.user_data, buffer);
                }
            }
        }

        unsafe extern "C" fn on_process<D>(data: *mut ::std::os::raw::c_void) {
            if let Some(state) = (data as *mut ListenerLocalCallbacks<D>).as_mut() {
                if let Some(cb) = &mut state.process {
                    let stream = unwrap_stream_ptr(state.stream);
                    cb(stream, &mut state.user_data);
                }
            }
        }

        unsafe extern "C" fn on_drained<D>(data: *mut ::std::os::raw::c_void) {
            if let Some(state) = (data as *mut ListenerLocalCallbacks<D>).as_mut() {
                if let Some(cb) = &mut state.drained {
                    let stream = unwrap_stream_ptr(state.stream);
                    cb(stream, &mut state.user_data);
                }
            }
        }

        #[cfg(feature = "v0_3_39")]
        unsafe extern "C" fn on_command<D>(
            data: *mut ::std::os::raw::c_void,
            command: *const spa_sys::spa_command,
        ) {
            if let Some(state) = (data as *mut ListenerLocalCallbacks<D>).as_mut() {
                if let Some(cb) = &mut state.command {
                    let stream = unwrap_stream_ptr(state.stream);
                    cb(stream, &mut state.user_data, command);
                }
            }
        }

        #[cfg(feature = "v0_3_40")]
        unsafe extern "C" fn on_trigger_done<D>(data: *mut ::std::os::raw::c_void) {
            if let Some(state) = (data as *mut ListenerLocalCallbacks<D>).as_mut() {
                if let Some(cb) = &mut state.trigger_done {
                    let stream = unwrap_stream_ptr(state.stream);
                    cb(stream, &mut state.user_data);
                }
            }
        }

        let events = unsafe {
            let mut events: Pin<Box<pw_sys::pw_stream_events>> = Box::pin(mem::zeroed());
            events.version = pw_sys::PW_VERSION_STREAM_EVENTS;

            if callbacks.state_changed.is_some() {
                events.state_changed = Some(on_state_changed::<D>);
            }
            if callbacks.control_info.is_some() {
                events.control_info = Some(on_control_info::<D>);
            }
            if callbacks.io_changed.is_some() {
                events.io_changed = Some(on_io_changed::<D>);
            }
            if callbacks.param_changed.is_some() {
                events.param_changed = Some(on_param_changed::<D>);
            }
            if callbacks.add_buffer.is_some() {
                events.add_buffer = Some(on_add_buffer::<D>);
            }
            if callbacks.remove_buffer.is_some() {
                events.remove_buffer = Some(on_remove_buffer::<D>);
            }
            if callbacks.process.is_some() {
                events.process = Some(on_process::<D>);
            }
            if callbacks.drained.is_some() {
                events.drained = Some(on_drained::<D>);
            }
            #[cfg(feature = "v0_3_39")]
            if callbacks.command.is_some() {
                events.command = Some(on_command::<D>);
            }
            #[cfg(feature = "v0_3_40")]
            if callbacks.trigger_done.is_some() {
                events.trigger_done = Some(on_trigger_done::<D>);
            }

            events
        };

        (events, callbacks)
    }
}

#[must_use]
pub struct ListenerLocalBuilder<'a, D> {
    stream: &'a StreamRef,
    callbacks: ListenerLocalCallbacks<D>,
}

impl<'a, D> ListenerLocalBuilder<'a, D> {
    /// Set the callback for the `state_changed` event.
    pub fn state_changed<F>(mut self, callback: F) -> Self
    where
        F: FnMut(&StreamRef, &mut D, StreamState, StreamState) + 'static,
    {
        self.callbacks.state_changed = Some(Box::new(callback));
        self
    }

    /// Set the callback for the `control_info` event.
    pub fn control_info<F>(mut self, callback: F) -> Self
    where
        F: FnMut(&StreamRef, &mut D, u32, *const pw_sys::pw_stream_control) + 'static,
    {
        self.callbacks.control_info = Some(Box::new(callback));
        self
    }

    /// Set the callback for the `io_changed` event.
    pub fn io_changed<F>(mut self, callback: F) -> Self
    where
        F: FnMut(&StreamRef, &mut D, u32, *mut os::raw::c_void, u32) + 'static,
    {
        self.callbacks.io_changed = Some(Box::new(callback));
        self
    }

    /// Set the callback for the `param_changed` event.
    pub fn param_changed<F>(mut self, callback: F) -> Self
    where
        F: FnMut(&StreamRef, &mut D, u32, Option<&spa::pod::Pod>) + 'static,
    {
        self.callbacks.param_changed = Some(Box::new(callback));
        self
    }

    /// Set the callback for the `add_buffer` event.
    pub fn add_buffer<F>(mut self, callback: F) -> Self
    where
        F: FnMut(&StreamRef, &mut D, *mut pw_sys::pw_buffer) + 'static,
    {
        self.callbacks.add_buffer = Some(Box::new(callback));
        self
    }

    /// Set the callback for the `remove_buffer` event.
    pub fn remove_buffer<F>(mut self, callback: F) -> Self
    where
        F: FnMut(&StreamRef, &mut D, *mut pw_sys::pw_buffer) + 'static,
    {
        self.callbacks.remove_buffer = Some(Box::new(callback));
        self
    }

    /// Set the callback for the `process` event.
    pub fn process<F>(mut self, callback: F) -> Self
    where
        F: FnMut(&StreamRef, &mut D) + 'static,
    {
        self.callbacks.process = Some(Box::new(callback));
        self
    }

    /// Set the callback for the `drained` event.
    pub fn drained<F>(mut self, callback: F) -> Self
    where
        F: FnMut(&StreamRef, &mut D) + 'static,
    {
        self.callbacks.drained = Some(Box::new(callback));
        self
    }

    //// Register the Callbacks
    ///
    /// Stop building the listener and register it on the stream. Returns a
    /// `StreamListener` handlle that will un-register the listener on drop.
    pub fn register(self) -> Result<StreamListener<D>, Error> {
        let (events, data) = self.callbacks.into_raw();
        let (listener, data) = unsafe {
            let listener: Box<spa_sys::spa_hook> = Box::new(mem::zeroed());
            let raw_listener = Box::into_raw(listener);
            let raw_data = Box::into_raw(data);
            pw_sys::pw_stream_add_listener(
                self.stream.as_raw_ptr(),
                raw_listener,
                events.as_ref().get_ref(),
                raw_data as *mut _,
            );
            (Box::from_raw(raw_listener), Box::from_raw(raw_data))
        };
        Ok(StreamListener {
            listener,
            _events: events,
            _data: data,
        })
    }
}

pub struct StreamListener<D> {
    listener: Box<spa_sys::spa_hook>,
    // Need to stay allocated while the listener is registered
    _events: Pin<Box<pw_sys::pw_stream_events>>,
    _data: Box<ListenerLocalCallbacks<D>>,
}

impl<D> StreamListener<D> {
    /// Stop the listener from receiving any events
    ///
    /// Removes the listener registration and cleans up allocated resources.
    pub fn unregister(self) {
        // do nothing, drop will clean up.
    }
}

impl<D> std::ops::Drop for StreamListener<D> {
    fn drop(&mut self) {
        spa::utils::hook::remove(*self.listener);
    }
}

bitflags! {
    /// Extra flags that can be used in [`Stream::connect()`]
    #[derive(Debug, PartialEq, Eq, Clone, Copy)]
    pub struct StreamFlags: pw_sys::pw_stream_flags {
        const AUTOCONNECT = pw_sys::pw_stream_flags_PW_STREAM_FLAG_AUTOCONNECT;
        const INACTIVE = pw_sys::pw_stream_flags_PW_STREAM_FLAG_INACTIVE;
        const MAP_BUFFERS = pw_sys::pw_stream_flags_PW_STREAM_FLAG_MAP_BUFFERS;
        const DRIVER = pw_sys::pw_stream_flags_PW_STREAM_FLAG_DRIVER;
        const RT_PROCESS = pw_sys::pw_stream_flags_PW_STREAM_FLAG_RT_PROCESS;
        const NO_CONVERT = pw_sys::pw_stream_flags_PW_STREAM_FLAG_NO_CONVERT;
        const EXCLUSIVE = pw_sys::pw_stream_flags_PW_STREAM_FLAG_EXCLUSIVE;
        const DONT_RECONNECT = pw_sys::pw_stream_flags_PW_STREAM_FLAG_DONT_RECONNECT;
        const ALLOC_BUFFERS = pw_sys::pw_stream_flags_PW_STREAM_FLAG_ALLOC_BUFFERS;
        #[cfg(feature = "v0_3_41")]
        const TRIGGER = pw_sys::pw_stream_flags_PW_STREAM_FLAG_TRIGGER;
    }
}
