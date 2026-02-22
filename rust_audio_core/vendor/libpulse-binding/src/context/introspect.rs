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

//! Routines for daemon introspection.
//!
//! # Overview
//!
//! Sometimes it is necessary to query and modify global settings in the server. For this,
//! PulseAudio has the introspection API. It can list sinks, sources, samples and other aspects of
//! the server. It can also modify the attributes of the server that will affect operations on a
//! global level, and not just the application’s context.
//!
//! # Usage
//!
//! The introspection routines are exposed as methods on an [`Introspector`] object held by the
//! [`Context`] object, and can be accessed via the [`Context::introspect()`] method.
//!
//! # Querying
//!
//! All querying is done through callbacks. This approach is necessary to maintain an asynchronous
//! design. The client will request the information and some time later, the server will respond
//! with the desired data.
//!
//! Some objects can have multiple instances on the server. When requesting all of these at once,
//! the callback will be called multiple times, each time with a [`ListResult`] variant. It will be
//! called once for each item in turn, using the `Item` variant, and then one more time with the
//! `End` variant to signal that the end of the list has been reached. If an error occurs, then
//! the `Error` variant will be given.
//!
//! Note that even if a single object is requested, and not the entire list, the terminating call
//! will still be made.
//!
//! Data members in the information structures are only valid during the duration of the callback.
//! If they are required after the callback is finished, a deep copy of the information structure
//! must be performed.
//!
//! # Server Information
//!
//! The server can be queried about its name, the environment it’s running on and the currently
//! active global defaults. Calling [`Introspector::get_server_info()`] provides access to a
//! [`ServerInfo`] structure containing all of these.
//!
//! # Memory Usage
//!
//! Statistics about memory usage can be fetched using [`Introspector::stat()`], giving a
//! [`StatInfo`] structure.
//!
//! # Sinks and Sources
//!
//! The server can have an arbitrary number of sinks and sources. Each sink and source have both an
//! index and a name associated with it. As such, there are three ways to get access to them:
//!
//! * By index: [`Introspector::get_sink_info_by_index()`],
//!   [`Introspector::get_source_info_by_index()`]
//! * By name: [`Introspector::get_sink_info_by_name()`],
//!   [`Introspector::get_source_info_by_name()`]
//! * All: [`Introspector::get_sink_info_list()`], [`Introspector::get_source_info_list()`]
//!
//! All three methods use the same callback and will provide a [`SinkInfo`] or [`SourceInfo`]
//! structure.
//!
//! # Sink Inputs and Source Outputs
//!
//! Sink inputs and source outputs are the representations of the client ends of streams inside the
//! server. I.e. they connect a client stream to one of the global sinks or sources.
//!
//! Sink inputs and source outputs only have an index to identify them. As such, there are only two
//! ways to get information about them:
//!
//! * By index: [`Introspector::get_sink_input_info()`], [`Introspector::get_source_output_info()`]
//! * All: [`Introspector::get_sink_input_info_list()`],
//!   [`Introspector::get_source_output_info_list()`]
//!
//! The structure returned is the [`SinkInputInfo`] or [`SourceOutputInfo`] structure.
//!
//! # Samples
//!
//! The list of cached samples can be retrieved from the server. Three methods exist for querying
//! the sample cache list:
//!
//! * By index: [`Introspector::get_sample_info_by_index()`]
//! * By name: [`Introspector::get_sample_info_by_name()`]
//! * All: [`Introspector::get_sample_info_list()`]
//!
//! Note that this only retrieves information about the sample, not the sample data itself.
//!
//! # Driver Modules
//!
//! PulseAudio driver modules are identified by index and are retrieved using either
//! [`Introspector::get_module_info()`] or [`Introspector::get_module_info_list()`]. The information
//! structure is called [`ModuleInfo`].
//!
//! # Clients
//!
//! PulseAudio clients are also identified by index and are retrieved using either
//! [`Introspector::get_client_info()`] or [`Introspector::get_client_info_list()`]. The information
//! structure is called [`ClientInfo`].
//!
//! # Control
//!
//! Some parts of the server are only possible to read, but most can also be modified in different
//! ways. Note that these changes will affect all connected clients and not just the one issuing the
//! request.
//!
//! # Sinks and Sources
//!
//! The most common change one would want to apply to sinks and sources is to modify the volume of
//! the audio. Identically to how sinks and sources can be queried, there are two ways of
//! identifying them:
//!
//! * By index: [`Introspector::set_sink_volume_by_index()`],
//!   [`Introspector::set_source_volume_by_index()`]
//! * By name: [`Introspector::set_sink_volume_by_name()`],
//!   [`Introspector::set_source_volume_by_name()`]
//!
//! It is also possible to mute a sink or source:
//!
//! * By index: [`Introspector::set_sink_mute_by_index()`],
//!   [`Introspector::set_source_mute_by_index()`]
//! * By name: [`Introspector::set_sink_mute_by_name()`],
//!   [`Introspector::set_source_mute_by_name()`]
//!
//! # Sink Inputs and Source Outputs
//!
//! If an application desires to modify the volume of just a single stream (commonly one of its own
//! streams), this can be done by setting the volume of its associated sink input or source output,
//! using [`Introspector::set_sink_input_volume()`] or [`Introspector::set_source_output_volume()`].
//!
//! It is also possible to remove sink inputs and source outputs, terminating the streams associated
//! with them:
//!
//! * Sink input: [`Introspector::kill_sink_input()`]
//! * Source output: [`Introspector::kill_source_output()`]
//!
//! It is strongly recommended that all volume changes are done as a direct result of user input.
//! With automated requests, such as those resulting from misguided attempts of crossfading,
//! PulseAudio can store the stream volume at an inappropriate moment and restore it later. Besides,
//! such attempts lead to OSD popups in some desktop environments.
//!
//! As a special case of the general rule above, it is recommended that your application leaves the
//! task of saving and restoring the volume of its streams to PulseAudio and does not attempt to do
//! it by itself. PulseAudio really knows better about events such as stream moving or headphone
//! plugging that would make the volume stored by the application inapplicable to the new
//! configuration.
//!
//! Another important case where setting a sink input volume may be a bad idea is related to
//! interpreters that interpret potentially untrusted scripts. PulseAudio relies on your application
//! not making malicious requests (such as repeatedly setting the volume to 100%). Thus, script
//! interpreters that represent a security boundary must sandbox volume-changing requests coming
//! from their scripts. In the worst case, it may be necessary to apply the script-requested volume
//! to the script-produced sounds by altering the samples in the script interpreter and not touching
//! the sink or sink input volume as seen by PulseAudio.
//!
//! If an application changes any volume, it should also listen to changes of the same volume
//! originating from outside the application (e.g., from the system mixer application) and update
//! its user interface accordingly. Use [`Context::subscribe()`] to get such notifications.
//!
//! # Modules
//!
//! Server modules can be remotely loaded and unloaded using [`Introspector::load_module()`] and
//! [`Introspector::unload_module()`].
//!
//! # Messages
//!
//! Server objects like sinks, sink inputs or modules can register a message handler to communicate
//! with clients. A message can be sent to a named message handler using
//! [`Introspector::send_message_to_object()`].
//!
//! # Clients
//!
//! The only operation supported on clients is the possibility of kicking them off the server using
//! [`Introspector::kill_client()`].

use std::os::raw::c_void;
#[cfg(any(doc, feature = "pa_v15"))]
use std::os::raw::c_char;
use std::ffi::{CStr, CString};
use std::borrow::Cow;
use std::ptr::null_mut;
use num_traits::FromPrimitive;
use capi::pa_sink_port_info as SinkPortInfoInternal;
use capi::pa_sink_info as SinkInfoInternal;
use capi::pa_source_port_info as SourcePortInfoInternal;
use capi::pa_source_info as SourceInfoInternal;
use capi::pa_server_info as ServerInfoInternal;
use capi::pa_module_info as ModuleInfoInternal;
use capi::pa_client_info as ClientInfoInternal;
use capi::pa_card_profile_info2 as CardProfileInfoInternal;
use capi::pa_card_port_info as CardPortInfoInternal;
use capi::pa_card_info as CardInfoInternal;
use capi::pa_sink_input_info as SinkInputInfoInternal;
use capi::pa_source_output_info as SourceOutputInfoInternal;
use capi::pa_sample_info as SampleInfoInternal;
use super::{Context, ContextInternal};
use crate::{def, sample, channelmap, format, direction};
use crate::time::MicroSeconds;
use crate::callbacks::{
    ListResult, box_closure_get_capi_ptr, callback_for_list_instance, get_su_capi_params,
    get_su_callback
};
use crate::volume::{ChannelVolumes, Volume};
use crate::{operation::Operation, proplist::Proplist};
#[cfg(any(doc, feature = "pa_v14"))]
use crate::def::DevicePortType;

pub use capi::pa_stat_info as StatInfo;

/// A wrapper object providing introspection routines to a context.
pub struct Introspector {
    context: *mut super::ContextInternal,
}

unsafe impl Send for Introspector {}
unsafe impl Sync for Introspector {}

impl Context {
    /// Gets an introspection object linked to the current context, giving access to introspection
    /// routines.
    ///
    /// See [`context::introspect`](mod@crate::context::introspect).
    #[inline]
    pub fn introspect(&self) -> Introspector {
        unsafe { capi::pa_context_ref(self.ptr) };
        Introspector::from_raw(self.ptr)
    }
}

impl Introspector {
    /// Creates a new `Introspector` from an existing [`ContextInternal`] pointer.
    #[inline(always)]
    fn from_raw(context: *mut ContextInternal) -> Self {
        Self { context: context }
    }
}

impl Drop for Introspector {
    fn drop(&mut self) {
        unsafe { capi::pa_context_unref(self.context) };
        self.context = null_mut::<super::ContextInternal>();
    }
}

////////////////////////////////////////////////////////////////////////////////////////////////////
// Sink info
////////////////////////////////////////////////////////////////////////////////////////////////////

/// Stores information about a specific port of a sink.
///
/// Please note that this structure can be extended as part of evolutionary API updates at any time
/// in any new release.
#[derive(Debug)]
pub struct SinkPortInfo<'a> {
    /// Name of this port.
    pub name: Option<Cow<'a, str>>,
    /// Description of this port.
    pub description: Option<Cow<'a, str>>,
    /// The higher this value is, the more useful this port is as a default.
    pub priority: u32,
    /// A flag indicating availability status of this port.
    pub available: def::PortAvailable,
    /// An indentifier for the group of ports that share their availability status with each other.
    ///
    /// This is meant especially for handling cases where one 3.5 mm connector is used for
    /// headphones, headsets and microphones, and the hardware can only tell that something was
    /// plugged in but not what exactly. In this situation the ports for all those devices share
    /// their availability status, and PulseAudio can’t tell which one is actually plugged in, and
    /// some application may ask the user what was plugged in. Such applications should get a list
    /// of all card ports and compare their `availability_group` fields. Ports that have the same
    /// group are those that need input from the user to determine which device was plugged in. The
    /// application should then activate the user-chosen port.
    ///
    /// May be `None`, in which case the port is not part of any availability group (which is the
    /// same as having a group with only one member).
    ///
    /// The group identifier must be treated as an opaque identifier. The string may look like an
    /// ALSA control name, but applications must not assume any such relationship. The group naming
    /// scheme can change without a warning.
    ///
    /// Since one group can include both input and output ports, the grouping should be done using
    /// `CardPortInfo` instead of `SinkPortInfo`, but this field is duplicated also in
    /// `SinkPortInfo` (and `SourcePortInfo`) in case someone finds that convenient.
    #[cfg(any(doc, feature = "pa_v14"))]
    #[cfg_attr(docsrs, doc(cfg(feature = "pa_v14")))]
    pub availability_group: Option<Cow<'a, str>>,
    /// Port device type.
    #[cfg(any(doc, feature = "pa_v14"))]
    #[cfg_attr(docsrs, doc(cfg(feature = "pa_v14")))]
    pub r#type: DevicePortType,
}

impl SinkPortInfo<'_> {
    fn new_from_raw(p: *const SinkPortInfoInternal) -> Self {
        assert!(!p.is_null());
        let src = unsafe { &*p };
        unsafe {
            SinkPortInfo {
                name: match src.name.is_null() {
                    false => Some(CStr::from_ptr(src.name).to_string_lossy()),
                    true => None,
                },
                description: match src.description.is_null() {
                    false => Some(CStr::from_ptr(src.description).to_string_lossy()),
                    true => None,
                },
                priority: src.priority,
                available: def::PortAvailable::from_i32(src.available).unwrap(),
                #[cfg(any(doc, feature = "pa_v14"))]
                availability_group: match src.availability_group.is_null() {
                    false => Some(CStr::from_ptr(src.availability_group).to_string_lossy()),
                    true => None,
                },
                #[cfg(any(doc, feature = "pa_v14"))]
                r#type: DevicePortType::from_u32(src.r#type).unwrap(),
            }
        }
    }

    /// Creates a copy with owned data.
    pub fn to_owned(&self) -> SinkPortInfo<'static> {
        SinkPortInfo {
            name: self.name.clone().map(|o| Cow::Owned(o.into_owned())),
            description: self.description.clone().map(|o| Cow::Owned(o.into_owned())),
            #[cfg(any(doc, feature = "pa_v14"))]
            availability_group: self.availability_group.clone().map(|o| Cow::Owned(o.into_owned())),
            ..*self
        }
    }
}

/// Stores information about sinks.
///
/// Please note that this structure can be extended as part of evolutionary API updates at any time
/// in any new release.
#[derive(Debug)]
pub struct SinkInfo<'a> {
    /// Name of the sink.
    pub name: Option<Cow<'a, str>>,
    /// Index of the sink.
    pub index: u32,
    /// Description of this sink.
    pub description: Option<Cow<'a, str>>,
    /// Sample spec of this sink.
    pub sample_spec: sample::Spec,
    /// Channel map.
    pub channel_map: channelmap::Map,
    /// Index of the owning module of this sink, or `None` if is invalid.
    pub owner_module: Option<u32>,
    /// Volume of the sink.
    pub volume: ChannelVolumes,
    /// Mute switch of the sink.
    pub mute: bool,
    /// Index of the monitor source connected to this sink.
    pub monitor_source: u32,
    /// The name of the monitor source.
    pub monitor_source_name: Option<Cow<'a, str>>,
    /// Length of queued audio in the output buffer.
    pub latency: MicroSeconds,
    /// Driver name.
    pub driver: Option<Cow<'a, str>>,
    /// Flags.
    pub flags: def::SinkFlagSet,
    /// Property list.
    pub proplist: Proplist,
    /// The latency this device has been configured to.
    pub configured_latency: MicroSeconds,
    /// Some kind of “base” volume that refers to unamplified/unattenuated volume in the context of
    /// the output device.
    pub base_volume: Volume,
    /// State.
    pub state: def::SinkState,
    /// Number of volume steps for sinks which do not support arbitrary volumes.
    pub n_volume_steps: u32,
    /// Card index, or `None` if invalid.
    pub card: Option<u32>,
    /// Set of available ports.
    pub ports: Vec<SinkPortInfo<'a>>,
    /// Pointer to active port in the set, or `None`.
    pub active_port: Option<Box<SinkPortInfo<'a>>>,
    /// Set of formats supported by the sink.
    pub formats: Vec<format::Info>,
}

impl SinkInfo<'_> {
    fn new_from_raw(p: *const SinkInfoInternal) -> Self {
        assert!(!p.is_null());
        let src = unsafe { &*p };

        let mut port_vec = Vec::with_capacity(src.n_ports as usize);
        assert!(src.n_ports == 0 || !src.ports.is_null());
        for i in 0..src.n_ports as isize {
            let indexed_ptr = unsafe { (*src.ports.offset(i)) as *mut SinkPortInfoInternal };
            if !indexed_ptr.is_null() {
                port_vec.push(SinkPortInfo::new_from_raw(indexed_ptr));
            }
        }
        let mut formats_vec = Vec::with_capacity(src.n_formats as usize);
        assert!(src.n_formats == 0 || !src.formats.is_null());
        for i in 0..src.n_formats as isize {
            let indexed_ptr = unsafe { (*src.formats.offset(i)) as *mut format::InfoInternal };
            if !indexed_ptr.is_null() {
                formats_vec.push(format::Info::from_raw_weak(indexed_ptr));
            }
        }

        unsafe {
            SinkInfo {
                name: match src.name.is_null() {
                    false => Some(CStr::from_ptr(src.name).to_string_lossy()),
                    true => None,
                },
                index: src.index,
                description: match src.description.is_null() {
                    false => Some(CStr::from_ptr(src.description).to_string_lossy()),
                    true => None,
                },
                sample_spec: src.sample_spec.into(),
                channel_map: src.channel_map.into(),
                owner_module: match src.owner_module {
                    def::INVALID_INDEX => None,
                    i => Some(i),
                },
                volume: src.volume.into(),
                mute: match src.mute {
                    0 => false,
                    _ => true,
                },
                monitor_source: src.monitor_source,
                monitor_source_name: match src.monitor_source_name.is_null() {
                    false => Some(CStr::from_ptr(src.monitor_source_name).to_string_lossy()),
                    true => None,
                },
                latency: MicroSeconds(src.latency),
                driver: match src.driver.is_null() {
                    false => Some(CStr::from_ptr(src.driver).to_string_lossy()),
                    true => None,
                },
                flags: def::SinkFlagSet::from_bits_truncate(src.flags),
                proplist: Proplist::from_raw_weak(src.proplist),
                configured_latency: MicroSeconds(src.configured_latency),
                base_volume: Volume(src.base_volume),
                state: src.state.into(),
                n_volume_steps: src.n_volume_steps,
                card: match src.card {
                    def::INVALID_INDEX => None,
                    i => Some(i),
                },
                ports: port_vec,
                active_port: match src.active_port.is_null() {
                    true => None,
                    false => Some(Box::new(SinkPortInfo::new_from_raw(src.active_port))),
                },
                formats: formats_vec,
            }
        }
    }

    /// Creates a copy with owned data.
    pub fn to_owned(&self) -> SinkInfo<'static> {
        SinkInfo {
            name: self.name.clone().map(|o| Cow::Owned(o.into_owned())),
            description: self.description.clone().map(|o| Cow::Owned(o.into_owned())),
            monitor_source_name: self.monitor_source_name.clone().map(|o| Cow::Owned(o.into_owned())),
            driver: self.driver.clone().map(|o| Cow::Owned(o.into_owned())),
            proplist: self.proplist.to_owned(),
            ports: self.ports.iter().map(SinkPortInfo::to_owned).collect(),
            active_port: self.active_port.as_ref().map(|ap| Box::new(ap.as_ref().to_owned())),
            formats: self.formats.iter().map(format::Info::to_owned).collect(),
            ..*self
        }
    }
}

impl Introspector {
    /// Gets information about a sink by its name.
    ///
    /// Panics on error, i.e. invalid arguments or state.
    pub fn get_sink_info_by_name<F>(&self, name: &str, callback: F)
        -> Operation<dyn FnMut(ListResult<&SinkInfo>)>
        where F: FnMut(ListResult<&SinkInfo>) + 'static
    {
        // Warning: New CStrings will be immediately freed if not bound to a variable, leading to
        // as_ptr() giving dangling pointers!
        let c_name = CString::new(name).unwrap();

        let cb_data = box_closure_get_capi_ptr::<dyn FnMut(ListResult<&SinkInfo>)>(Box::new(callback));
        let ptr = unsafe { capi::pa_context_get_sink_info_by_name(self.context, c_name.as_ptr(),
            Some(get_sink_info_list_cb_proxy), cb_data) };
        Operation::from_raw(ptr, cb_data as *mut Box<dyn FnMut(ListResult<&SinkInfo>)>)
    }

    /// Gets information about a sink by its index.
    ///
    /// Panics on error, i.e. invalid arguments or state.
    pub fn get_sink_info_by_index<F>(&self, index: u32, callback: F)
        -> Operation<dyn FnMut(ListResult<&SinkInfo>)>
        where F: FnMut(ListResult<&SinkInfo>) + 'static
    {
        let cb_data = box_closure_get_capi_ptr::<dyn FnMut(ListResult<&SinkInfo>)>(Box::new(callback));
        let ptr = unsafe { capi::pa_context_get_sink_info_by_index(self.context, index,
            Some(get_sink_info_list_cb_proxy), cb_data) };
        Operation::from_raw(ptr, cb_data as *mut Box<dyn FnMut(ListResult<&SinkInfo>)>)
    }

    /// Gets the complete sink list.
    ///
    /// Panics on error, i.e. invalid arguments or state.
    pub fn get_sink_info_list<F>(&self, callback: F) -> Operation<dyn FnMut(ListResult<&SinkInfo>)>
        where F: FnMut(ListResult<&SinkInfo>) + 'static
    {
        let cb_data = box_closure_get_capi_ptr::<dyn FnMut(ListResult<&SinkInfo>)>(Box::new(callback));
        let ptr = unsafe { capi::pa_context_get_sink_info_list(self.context,
            Some(get_sink_info_list_cb_proxy), cb_data) };
        Operation::from_raw(ptr, cb_data as *mut Box<dyn FnMut(ListResult<&SinkInfo>)>)
    }

    /// Sets the volume of a sink device specified by its index.
    ///
    /// Panics on error, i.e. invalid arguments or state.
    ///
    /// The optional callback must accept a `bool`, which indicates success.
    pub fn set_sink_volume_by_index(&mut self, index: u32, volume: &ChannelVolumes,
        callback: Option<Box<dyn FnMut(bool) + 'static>>) -> Operation<dyn FnMut(bool)>
    {
        let (cb_fn, cb_data): (Option<extern "C" fn(_, _, _)>, _) =
            get_su_capi_params::<_, _>(callback, super::success_cb_proxy);
        let ptr = unsafe { capi::pa_context_set_sink_volume_by_index(self.context, index,
            volume.as_ref(), cb_fn, cb_data) };
        Operation::from_raw(ptr, cb_data as *mut Box<dyn FnMut(bool)>)
    }

    /// Sets the volume of a sink device specified by its name.
    ///
    /// Panics on error, i.e. invalid arguments or state.
    ///
    /// The optional callback must accept a `bool`, which indicates success.
    pub fn set_sink_volume_by_name(&mut self, name: &str, volume: &ChannelVolumes,
        callback: Option<Box<dyn FnMut(bool) + 'static>>) -> Operation<dyn FnMut(bool)>
    {
        // Warning: New CStrings will be immediately freed if not bound to a variable, leading to
        // as_ptr() giving dangling pointers!
        let c_name = CString::new(name).unwrap();

        let (cb_fn, cb_data): (Option<extern "C" fn(_, _, _)>, _) =
            get_su_capi_params::<_, _>(callback, super::success_cb_proxy);
        let ptr = unsafe { capi::pa_context_set_sink_volume_by_name(self.context, c_name.as_ptr(),
            volume.as_ref(), cb_fn, cb_data) };
        Operation::from_raw(ptr, cb_data as *mut Box<dyn FnMut(bool)>)
    }

    /// Sets the mute switch of a sink device specified by its index.
    ///
    /// Panics on error, i.e. invalid arguments or state.
    ///
    /// The optional callback must accept a `bool`, which indicates success.
    pub fn set_sink_mute_by_index(&mut self, index: u32, mute: bool,
        callback: Option<Box<dyn FnMut(bool) + 'static>>) -> Operation<dyn FnMut(bool)>
    {
        let (cb_fn, cb_data): (Option<extern "C" fn(_, _, _)>, _) =
            get_su_capi_params::<_, _>(callback, super::success_cb_proxy);
        let ptr = unsafe { capi::pa_context_set_sink_mute_by_index(self.context, index, mute as i32,
            cb_fn, cb_data) };
        Operation::from_raw(ptr, cb_data as *mut Box<dyn FnMut(bool)>)
    }

    /// Sets the mute switch of a sink device specified by its name.
    ///
    /// Panics on error, i.e. invalid arguments or state.
    ///
    /// The optional callback must accept a `bool`, which indicates success.
    pub fn set_sink_mute_by_name(&mut self, name: &str, mute: bool,
        callback: Option<Box<dyn FnMut(bool) + 'static>>) -> Operation<dyn FnMut(bool)>
    {
        // Warning: New CStrings will be immediately freed if not bound to a variable, leading to
        // as_ptr() giving dangling pointers!
        let c_name = CString::new(name).unwrap();

        let (cb_fn, cb_data): (Option<extern "C" fn(_, _, _)>, _) =
            get_su_capi_params::<_, _>(callback, super::success_cb_proxy);
        let ptr = unsafe { capi::pa_context_set_sink_mute_by_name(self.context, c_name.as_ptr(),
            mute as i32, cb_fn, cb_data) };
        Operation::from_raw(ptr, cb_data as *mut Box<dyn FnMut(bool)>)
    }

    /// Suspends/Resumes a sink.
    ///
    /// Panics on error, i.e. invalid arguments or state.
    ///
    /// The optional callback must accept a `bool`, which indicates success.
    pub fn suspend_sink_by_name(&mut self, sink_name: &str, suspend: bool,
        callback: Option<Box<dyn FnMut(bool) + 'static>>) -> Operation<dyn FnMut(bool)>
    {
        // Warning: New CStrings will be immediately freed if not bound to a variable, leading to
        // as_ptr() giving dangling pointers!
        let c_name = CString::new(sink_name).unwrap();

        let (cb_fn, cb_data): (Option<extern "C" fn(_, _, _)>, _) =
            get_su_capi_params::<_, _>(callback, super::success_cb_proxy);
        let ptr = unsafe { capi::pa_context_suspend_sink_by_name(self.context, c_name.as_ptr(),
            suspend as i32, cb_fn, cb_data) };
        Operation::from_raw(ptr, cb_data as *mut Box<dyn FnMut(bool)>)
    }

    /// Suspends/Resumes a sink.
    ///
    /// If `index` is [`def::INVALID_INDEX`] all sinks will be suspended.
    /// Panics on error, i.e. invalid arguments or state.
    ///
    /// The optional callback must accept a `bool`, which indicates success.
    pub fn suspend_sink_by_index(&mut self, index: u32, suspend: bool,
        callback: Option<Box<dyn FnMut(bool) + 'static>>) -> Operation<dyn FnMut(bool)>
    {
        let (cb_fn, cb_data): (Option<extern "C" fn(_, _, _)>, _) =
            get_su_capi_params::<_, _>(callback, super::success_cb_proxy);
        let ptr = unsafe { capi::pa_context_suspend_sink_by_index(self.context, index,
            suspend as i32, cb_fn, cb_data) };
        Operation::from_raw(ptr, cb_data as *mut Box<dyn FnMut(bool)>)
    }

    /// Changes the profile of a sink.
    ///
    /// Panics on error, i.e. invalid arguments or state.
    ///
    /// The optional callback must accept a `bool`, which indicates success.
    pub fn set_sink_port_by_index(&mut self, index: u32, port: &str,
        callback: Option<Box<dyn FnMut(bool) + 'static>>) -> Operation<dyn FnMut(bool)>
    {
        // Warning: New CStrings will be immediately freed if not bound to a variable, leading to
        // as_ptr() giving dangling pointers!
        let c_port = CString::new(port).unwrap();

        let (cb_fn, cb_data): (Option<extern "C" fn(_, _, _)>, _) =
            get_su_capi_params::<_, _>(callback, super::success_cb_proxy);
        let ptr = unsafe { capi::pa_context_set_sink_port_by_index(self.context, index,
            c_port.as_ptr(), cb_fn, cb_data) };
        Operation::from_raw(ptr, cb_data as *mut Box<dyn FnMut(bool)>)
    }

    /// Changes the profile of a sink.
    ///
    /// Panics on error, i.e. invalid arguments or state.
    ///
    /// The optional callback must accept a `bool`, which indicates success.
    pub fn set_sink_port_by_name(&mut self, name: &str, port: &str,
        callback: Option<Box<dyn FnMut(bool) + 'static>>) -> Operation<dyn FnMut(bool)>
    {
        // Warning: New CStrings will be immediately freed if not bound to a variable, leading to
        // as_ptr() giving dangling pointers!
        let c_name = CString::new(name).unwrap();
        let c_port = CString::new(port).unwrap();

        let (cb_fn, cb_data): (Option<extern "C" fn(_, _, _)>, _) =
            get_su_capi_params::<_, _>(callback, super::success_cb_proxy);
        let ptr = unsafe { capi::pa_context_set_sink_port_by_name(self.context, c_name.as_ptr(),
            c_port.as_ptr(), cb_fn, cb_data) };
        Operation::from_raw(ptr, cb_data as *mut Box<dyn FnMut(bool)>)
    }
}

/// Proxy for get sink info list callbacks.
/// Warning: This is for list cases only! On EOL it destroys the actual closure callback.
extern "C"
fn get_sink_info_list_cb_proxy(_: *mut ContextInternal, i: *const SinkInfoInternal, eol: i32,
    userdata: *mut c_void)
{
    let _ = std::panic::catch_unwind(|| {
        callback_for_list_instance(i, eol, userdata, SinkInfo::new_from_raw);
    });
}

////////////////////////////////////////////////////////////////////////////////////////////////////
// Source info
////////////////////////////////////////////////////////////////////////////////////////////////////

/// Stores information about a specific port of a source.
///
/// Please note that this structure can be extended as part of evolutionary API updates at any time
/// in any new release.
#[derive(Debug)]
pub struct SourcePortInfo<'a> {
    /// Name of this port.
    pub name: Option<Cow<'a, str>>,
    /// Description of this port.
    pub description: Option<Cow<'a, str>>,
    /// The higher this value is, the more useful this port is as a default.
    pub priority: u32,
    /// A flag indicating availability status of this port.
    pub available: def::PortAvailable,
    /// An indentifier for the group of ports that share their availability status with each other.
    ///
    /// This is meant especially for handling cases where one 3.5 mm connector is used for
    /// headphones, headsets and microphones, and the hardware can only tell that something was
    /// plugged in but not what exactly. In this situation the ports for all those devices share
    /// their availability status, and PulseAudio can’t tell which one is actually plugged in, and
    /// some application may ask the user what was plugged in. Such applications should get a list
    /// of all card ports and compare their `availability_group` fields. Ports that have the same
    /// group are those that need input from the user to determine which device was plugged in. The
    /// application should then activate the user-chosen port.
    ///
    /// May be `None`, in which case the port is not part of any availability group (which is the
    /// same as having a group with only one member).
    ///
    /// The group identifier must be treated as an opaque identifier. The string may look like an
    /// ALSA control name, but applications must not assume any such relationship. The group naming
    /// scheme can change without a warning.
    ///
    /// Since one group can include both input and output ports, the grouping should be done using
    /// `CardPortInfo` instead of `SourcePortInfo`, but this field is duplicated also in
    /// `SourcePortInfo` (and `SinkPortInfo`) in case someone finds that convenient.
    #[cfg(any(doc, feature = "pa_v14"))]
    #[cfg_attr(docsrs, doc(cfg(feature = "pa_v14")))]
    pub availability_group: Option<Cow<'a, str>>,
    /// Port device type.
    #[cfg(any(doc, feature = "pa_v14"))]
    #[cfg_attr(docsrs, doc(cfg(feature = "pa_v14")))]
    pub r#type: DevicePortType,
}

impl SourcePortInfo<'_> {
    fn new_from_raw(p: *const SourcePortInfoInternal) -> Self {
        assert!(!p.is_null());
        let src = unsafe { &*p };
        unsafe {
            SourcePortInfo {
                name: match src.name.is_null() {
                    false => Some(CStr::from_ptr(src.name).to_string_lossy()),
                    true => None,
                },
                description: match src.description.is_null() {
                    false => Some(CStr::from_ptr(src.description).to_string_lossy()),
                    true => None,
                },
                priority: src.priority,
                available: def::PortAvailable::from_i32(src.available).unwrap(),
                #[cfg(any(doc, feature = "pa_v14"))]
                availability_group: match src.availability_group.is_null() {
                    false => Some(CStr::from_ptr(src.availability_group).to_string_lossy()),
                    true => None,
                },
                #[cfg(any(doc, feature = "pa_v14"))]
                r#type: DevicePortType::from_u32(src.r#type).unwrap(),
            }
        }
    }

    /// Creates a copy with owned data.
    pub fn to_owned(&self) -> SourcePortInfo<'static> {
        SourcePortInfo {
            name: self.name.clone().map(|o| Cow::Owned(o.into_owned())),
            description: self.description.clone().map(|o| Cow::Owned(o.into_owned())),
            #[cfg(any(doc, feature = "pa_v14"))]
            availability_group: self.availability_group.clone().map(|o| Cow::Owned(o.into_owned())),
            ..*self
        }
    }
}

/// Stores information about sources.
///
/// Please note that this structure can be extended as part of evolutionary API updates at any time
/// in any new release.
#[derive(Debug)]
pub struct SourceInfo<'a> {
    /// Name of the source.
    pub name: Option<Cow<'a, str>>,
    /// Index of the source.
    pub index: u32,
    /// Description of this source.
    pub description: Option<Cow<'a, str>>,
    /// Sample spec of this source.
    pub sample_spec: sample::Spec,
    /// Channel map.
    pub channel_map: channelmap::Map,
    /// Owning module index, or `None`.
    pub owner_module: Option<u32>,
    /// Volume of the source.
    pub volume: ChannelVolumes,
    /// Mute switch of the sink.
    pub mute: bool,
    /// If this is a monitor source, the index of the owning sink, otherwise `None`.
    pub monitor_of_sink: Option<u32>,
    /// Name of the owning sink, or `None`.
    pub monitor_of_sink_name: Option<Cow<'a, str>>,
    /// Length of filled record buffer of this source.
    pub latency: MicroSeconds,
    /// Driver name.
    pub driver: Option<Cow<'a, str>>,
    /// Flags.
    pub flags: def::SourceFlagSet,
    /// Property list.
    pub proplist: Proplist,
    /// The latency this device has been configured to.
    pub configured_latency: MicroSeconds,
    /// Some kind of “base” volume that refers to unamplified/unattenuated volume in the context of
    /// the input device.
    pub base_volume: Volume,
    /// State.
    pub state: def::SourceState,
    /// Number of volume steps for sources which do not support arbitrary volumes.
    pub n_volume_steps: u32,
    /// Card index, or `None`.
    pub card: Option<u32>,
    /// Set of available ports.
    pub ports: Vec<SourcePortInfo<'a>>,
    /// Pointer to active port in the set, or `None`.
    pub active_port: Option<Box<SourcePortInfo<'a>>>,
    /// Set of formats supported by the sink.
    pub formats: Vec<format::Info>,
}

impl SourceInfo<'_> {
    fn new_from_raw(p: *const SourceInfoInternal) -> Self {
        assert!(!p.is_null());
        let src = unsafe { &*p };

        let mut port_vec = Vec::with_capacity(src.n_ports as usize);
        assert!(src.n_ports == 0 || !src.ports.is_null());
        for i in 0..src.n_ports as isize {
            let indexed_ptr = unsafe { (*src.ports.offset(i)) as *mut SourcePortInfoInternal };
            if !indexed_ptr.is_null() {
                port_vec.push(SourcePortInfo::new_from_raw(indexed_ptr));
            }
        }
        let mut formats_vec = Vec::with_capacity(src.n_formats as usize);
        assert!(src.n_formats == 0 || !src.formats.is_null());
        for i in 0..src.n_formats as isize {
            let indexed_ptr = unsafe { (*src.formats.offset(i)) as *mut format::InfoInternal };
            if !indexed_ptr.is_null() {
                formats_vec.push(format::Info::from_raw_weak(indexed_ptr));
            }
        }

        unsafe {
            SourceInfo {
                name: match src.name.is_null() {
                    false => Some(CStr::from_ptr(src.name).to_string_lossy()),
                    true => None,
                },
                index: src.index,
                description: match src.description.is_null() {
                    false => Some(CStr::from_ptr(src.description).to_string_lossy()),
                    true => None,
                },
                sample_spec: src.sample_spec.into(),
                channel_map: src.channel_map.into(),
                owner_module: match src.owner_module {
                    def::INVALID_INDEX => None,
                    i => Some(i),
                },
                volume: src.volume.into(),
                mute: match src.mute {
                    0 => false,
                    _ => true,
                },
                monitor_of_sink: match src.monitor_of_sink {
                    def::INVALID_INDEX => None,
                    i => Some(i),
                },
                monitor_of_sink_name: match src.monitor_of_sink_name.is_null() {
                    false => Some(CStr::from_ptr(src.monitor_of_sink_name).to_string_lossy()),
                    true => None,
                },
                latency: MicroSeconds(src.latency),
                driver: match src.driver.is_null() {
                    false => Some(CStr::from_ptr(src.driver).to_string_lossy()),
                    true => None,
                },
                flags: def::SourceFlagSet::from_bits_truncate(src.flags),
                proplist: Proplist::from_raw_weak(src.proplist),
                configured_latency: MicroSeconds(src.configured_latency),
                base_volume: Volume(src.base_volume),
                state: src.state.into(),
                n_volume_steps: src.n_volume_steps,
                card: match src.card {
                    def::INVALID_INDEX => None,
                    i => Some(i),
                },
                ports: port_vec,
                active_port: match src.active_port.is_null() {
                    true => None,
                    false => Some(Box::new(SourcePortInfo::new_from_raw(src.active_port))),
                },
                formats: formats_vec,
            }
        }
    }

    /// Creates a copy with owned data.
    pub fn to_owned(&self) -> SourceInfo<'static> {
        SourceInfo {
            name: self.name.clone().map(|o| Cow::Owned(o.into_owned())),
            description: self.description.clone().map(|o| Cow::Owned(o.into_owned())),
            monitor_of_sink_name: self.monitor_of_sink_name.clone().map(|o| Cow::Owned(o.into_owned())),
            driver: self.driver.clone().map(|o| Cow::Owned(o.into_owned())),
            proplist: self.proplist.to_owned(),
            ports: self.ports.iter().map(SourcePortInfo::to_owned).collect(),
            active_port: self.active_port.as_ref().map(|ap| Box::new(ap.as_ref().to_owned())),
            formats: self.formats.iter().map(format::Info::to_owned).collect(),
            ..*self
        }
    }
}

impl Introspector {
    /// Gets information about a source by its name.
    ///
    /// Panics on error, i.e. invalid arguments or state.
    pub fn get_source_info_by_name<F>(&self, name: &str, callback: F)
        -> Operation<dyn FnMut(ListResult<&SourceInfo>)>
        where F: FnMut(ListResult<&SourceInfo>) + 'static
    {
        // Warning: New CStrings will be immediately freed if not bound to a variable, leading to
        // as_ptr() giving dangling pointers!
        let c_name = CString::new(name).unwrap();

        let cb_data = box_closure_get_capi_ptr::<dyn FnMut(ListResult<&SourceInfo>)>(Box::new(callback));
        let ptr = unsafe { capi::pa_context_get_source_info_by_name(self.context, c_name.as_ptr(),
            Some(get_source_info_list_cb_proxy), cb_data) };
        Operation::from_raw(ptr, cb_data as *mut Box<dyn FnMut(ListResult<&SourceInfo>)>)
    }

    /// Gets information about a source by its index.
    ///
    /// Panics on error, i.e. invalid arguments or state.
    pub fn get_source_info_by_index<F>(&self, index: u32, callback: F)
        -> Operation<dyn FnMut(ListResult<&SourceInfo>)>
        where F: FnMut(ListResult<&SourceInfo>) + 'static
    {
        let cb_data = box_closure_get_capi_ptr::<dyn FnMut(ListResult<&SourceInfo>)>(Box::new(callback));
        let ptr = unsafe { capi::pa_context_get_source_info_by_index(self.context, index,
            Some(get_source_info_list_cb_proxy), cb_data) };
        Operation::from_raw(ptr, cb_data as *mut Box<dyn FnMut(ListResult<&SourceInfo>)>)
    }

    /// Gets the complete source list.
    ///
    /// Panics on error, i.e. invalid arguments or state.
    pub fn get_source_info_list<F>(&self, callback: F)
        -> Operation<dyn FnMut(ListResult<&SourceInfo>)>
        where F: FnMut(ListResult<&SourceInfo>) + 'static
    {
        let cb_data = box_closure_get_capi_ptr::<dyn FnMut(ListResult<&SourceInfo>)>(Box::new(callback));
        let ptr = unsafe { capi::pa_context_get_source_info_list(self.context,
            Some(get_source_info_list_cb_proxy), cb_data) };
        Operation::from_raw(ptr, cb_data as *mut Box<dyn FnMut(ListResult<&SourceInfo>)>)
    }

    /// Sets the volume of a source device specified by its index.
    ///
    /// Panics on error, i.e. invalid arguments or state.
    ///
    /// The optional callback must accept a `bool`, which indicates success.
    pub fn set_source_volume_by_index(&mut self, index: u32, volume: &ChannelVolumes,
        callback: Option<Box<dyn FnMut(bool) + 'static>>) -> Operation<dyn FnMut(bool)>
    {
        let (cb_fn, cb_data): (Option<extern "C" fn(_, _, _)>, _) =
            get_su_capi_params::<_, _>(callback, super::success_cb_proxy);
        let ptr = unsafe { capi::pa_context_set_source_volume_by_index(self.context, index,
            volume.as_ref(), cb_fn, cb_data) };
        Operation::from_raw(ptr, cb_data as *mut Box<dyn FnMut(bool)>)
    }

    /// Sets the volume of a source device specified by its name.
    ///
    /// Panics on error, i.e. invalid arguments or state.
    ///
    /// The optional callback must accept a `bool`, which indicates success.
    pub fn set_source_volume_by_name(&mut self, name: &str, volume: &ChannelVolumes,
        callback: Option<Box<dyn FnMut(bool) + 'static>>) -> Operation<dyn FnMut(bool)>
    {
        // Warning: New CStrings will be immediately freed if not bound to a variable, leading to
        // as_ptr() giving dangling pointers!
        let c_name = CString::new(name).unwrap();

        let (cb_fn, cb_data): (Option<extern "C" fn(_, _, _)>, _) =
            get_su_capi_params::<_, _>(callback, super::success_cb_proxy);
        let ptr = unsafe { capi::pa_context_set_source_volume_by_name(self.context,
            c_name.as_ptr(), volume.as_ref(), cb_fn, cb_data) };
        Operation::from_raw(ptr, cb_data as *mut Box<dyn FnMut(bool)>)
    }

    /// Sets the mute switch of a source device specified by its index.
    ///
    /// Panics on error, i.e. invalid arguments or state.
    ///
    /// The optional callback must accept a `bool`, which indicates success.
    pub fn set_source_mute_by_index(&mut self, index: u32, mute: bool,
        callback: Option<Box<dyn FnMut(bool) + 'static>>) -> Operation<dyn FnMut(bool)>
    {
        let (cb_fn, cb_data): (Option<extern "C" fn(_, _, _)>, _) =
            get_su_capi_params::<_, _>(callback, super::success_cb_proxy);
        let ptr = unsafe { capi::pa_context_set_source_mute_by_index(self.context, index,
            mute as i32, cb_fn, cb_data) };
        Operation::from_raw(ptr, cb_data as *mut Box<dyn FnMut(bool)>)
    }

    /// Sets the mute switch of a source device specified by its name.
    ///
    /// Panics on error, i.e. invalid arguments or state.
    ///
    /// The optional callback must accept a `bool`, which indicates success.
    pub fn set_source_mute_by_name(&mut self, name: &str, mute: bool,
        callback: Option<Box<dyn FnMut(bool) + 'static>>) -> Operation<dyn FnMut(bool)>
    {
        // Warning: New CStrings will be immediately freed if not bound to a variable, leading to
        // as_ptr() giving dangling pointers!
        let c_name = CString::new(name).unwrap();

        let (cb_fn, cb_data): (Option<extern "C" fn(_, _, _)>, _) =
            get_su_capi_params::<_, _>(callback, super::success_cb_proxy);
        let ptr = unsafe { capi::pa_context_set_source_mute_by_name(self.context, c_name.as_ptr(),
            mute as i32, cb_fn, cb_data) };
        Operation::from_raw(ptr, cb_data as *mut Box<dyn FnMut(bool)>)
    }

    /// Suspends/Resumes a source.
    ///
    /// Panics on error, i.e. invalid arguments or state.
    ///
    /// The optional callback must accept a `bool`, which indicates success.
    pub fn suspend_source_by_name(&mut self, name: &str, suspend: bool,
        callback: Option<Box<dyn FnMut(bool) + 'static>>) -> Operation<dyn FnMut(bool)>
    {
        // Warning: New CStrings will be immediately freed if not bound to a variable, leading to
        // as_ptr() giving dangling pointers!
        let c_name = CString::new(name).unwrap();

        let (cb_fn, cb_data): (Option<extern "C" fn(_, _, _)>, _) =
            get_su_capi_params::<_, _>(callback, super::success_cb_proxy);
        let ptr = unsafe { capi::pa_context_suspend_source_by_name(self.context, c_name.as_ptr(),
            suspend as i32, cb_fn, cb_data) };
        Operation::from_raw(ptr, cb_data as *mut Box<dyn FnMut(bool)>)
    }

    /// Suspends/Resumes a source.
    ///
    /// If `index` is [`def::INVALID_INDEX`], all sources will be suspended.
    /// Panics on error, i.e. invalid arguments or state.
    ///
    /// The optional callback must accept a `bool`, which indicates success.
    pub fn suspend_source_by_index(&mut self, index: u32, suspend: bool,
        callback: Option<Box<dyn FnMut(bool) + 'static>>) -> Operation<dyn FnMut(bool)>
    {
        let (cb_fn, cb_data): (Option<extern "C" fn(_, _, _)>, _) =
            get_su_capi_params::<_, _>(callback, super::success_cb_proxy);
        let ptr = unsafe { capi::pa_context_suspend_source_by_index(self.context, index,
            suspend as i32, cb_fn, cb_data) };
        Operation::from_raw(ptr, cb_data as *mut Box<dyn FnMut(bool)>)
    }

    /// Changes the profile of a source.
    ///
    /// Panics on error, i.e. invalid arguments or state.
    ///
    /// The optional callback must accept a `bool`, which indicates success.
    pub fn set_source_port_by_index(&mut self, index: u32, port: &str,
        callback: Option<Box<dyn FnMut(bool) + 'static>>) -> Operation<dyn FnMut(bool)>
    {
        // Warning: New CStrings will be immediately freed if not bound to a variable, leading to
        // as_ptr() giving dangling pointers!
        let c_port = CString::new(port).unwrap();

        let (cb_fn, cb_data): (Option<extern "C" fn(_, _, _)>, _) =
            get_su_capi_params::<_, _>(callback, super::success_cb_proxy);
        let ptr = unsafe { capi::pa_context_set_source_port_by_index(self.context, index,
            c_port.as_ptr(), cb_fn, cb_data) };
        Operation::from_raw(ptr, cb_data as *mut Box<dyn FnMut(bool)>)
    }

    /// Changes the profile of a source.
    ///
    /// Panics on error, i.e. invalid arguments or state.
    ///
    /// The optional callback must accept a `bool`, which indicates success.
    pub fn set_source_port_by_name(&mut self, name: &str, port: &str,
        callback: Option<Box<dyn FnMut(bool) + 'static>>) -> Operation<dyn FnMut(bool)>
    {
        // Warning: New CStrings will be immediately freed if not bound to a variable, leading to
        // as_ptr() giving dangling pointers!
        let c_name = CString::new(name).unwrap();
        let c_port = CString::new(port).unwrap();

        let (cb_fn, cb_data): (Option<extern "C" fn(_, _, _)>, _) =
            get_su_capi_params::<_, _>(callback, super::success_cb_proxy);
        let ptr = unsafe { capi::pa_context_set_source_port_by_name(self.context, c_name.as_ptr(),
            c_port.as_ptr(), cb_fn, cb_data) };
        Operation::from_raw(ptr, cb_data as *mut Box<dyn FnMut(bool)>)
    }
}

/// Proxy for get source info list callbacks.
///
/// Warning: This is for list cases only! On EOL it destroys the actual closure callback.
extern "C"
fn get_source_info_list_cb_proxy(_: *mut ContextInternal, i: *const SourceInfoInternal, eol: i32,
    userdata: *mut c_void)
{
    let _ = std::panic::catch_unwind(|| {
        callback_for_list_instance(i, eol, userdata, SourceInfo::new_from_raw);
    });
}

////////////////////////////////////////////////////////////////////////////////////////////////////
// Server info
////////////////////////////////////////////////////////////////////////////////////////////////////

/// Server information.
///
/// Please note that this structure can be extended as part of evolutionary API updates at any time
/// in any new release.
#[derive(Debug)]
pub struct ServerInfo<'a> {
    /// User name of the daemon process.
    pub user_name: Option<Cow<'a, str>>,
    /// Host name the daemon is running on.
    pub host_name: Option<Cow<'a, str>>,
    /// Version string of the daemon.
    pub server_version: Option<Cow<'a, str>>,
    /// Server package name (usually “pulseaudio”).
    pub server_name: Option<Cow<'a, str>>,
    /// Default sample specification.
    pub sample_spec: sample::Spec,
    /// Name of default sink.
    pub default_sink_name: Option<Cow<'a, str>>,
    /// Name of default source.
    pub default_source_name: Option<Cow<'a, str>>,
    /// A random cookie for identifying this instance of PulseAudio.
    pub cookie: u32,
    /// Default channel map.
    pub channel_map: channelmap::Map,
}

impl ServerInfo<'_> {
    fn new_from_raw(p: *const ServerInfoInternal) -> Self {
        assert!(!p.is_null());
        let src = unsafe { &*p };
        unsafe {
            ServerInfo {
                user_name: match src.user_name.is_null() {
                    false => Some(CStr::from_ptr(src.user_name).to_string_lossy()),
                    true => None,
                },
                host_name: match src.host_name.is_null() {
                    false => Some(CStr::from_ptr(src.host_name).to_string_lossy()),
                    true => None,
                },
                server_version: match src.server_version.is_null() {
                    false => Some(CStr::from_ptr(src.server_version).to_string_lossy()),
                    true => None,
                },
                server_name: match src.server_name.is_null() {
                    false => Some(CStr::from_ptr(src.server_name).to_string_lossy()),
                    true => None,
                },
                sample_spec: src.sample_spec.into(),
                default_sink_name: match src.default_sink_name.is_null() {
                    false => Some(CStr::from_ptr(src.default_sink_name).to_string_lossy()),
                    true => None,
                },
                default_source_name: match src.default_source_name.is_null() {
                    false => Some(CStr::from_ptr(src.default_source_name).to_string_lossy()),
                    true => None,
                },
                cookie: src.cookie,
                channel_map: src.channel_map.into(),
            }
        }
    }

    /// Creates a copy with owned data.
    pub fn to_owned(&self) -> ServerInfo<'static> {
        ServerInfo {
            user_name: self.user_name.clone().map(|o| Cow::Owned(o.into_owned())),
            host_name: self.host_name.clone().map(|o| Cow::Owned(o.into_owned())),
            server_version: self.server_version.clone().map(|o| Cow::Owned(o.into_owned())),
            server_name: self.server_name.clone().map(|o| Cow::Owned(o.into_owned())),
            default_sink_name: self.default_sink_name.clone().map(|o| Cow::Owned(o.into_owned())),
            default_source_name: self.default_source_name.clone().map(|o| Cow::Owned(o.into_owned())),
            ..*self
        }
    }
}

impl Introspector {
    /// Gets some information about the server.
    ///
    /// Panics on error, i.e. invalid arguments or state.
    pub fn get_server_info<F>(&self, callback: F) -> Operation<dyn FnMut(&ServerInfo)>
        where F: FnMut(&ServerInfo) + 'static
    {
        let cb_data = box_closure_get_capi_ptr::<dyn FnMut(&ServerInfo)>(Box::new(callback));
        let ptr = unsafe { capi::pa_context_get_server_info(self.context,
            Some(get_server_info_cb_proxy), cb_data) };
        Operation::from_raw(ptr, cb_data as *mut Box<dyn FnMut(&ServerInfo)>)
    }
}

/// Proxy for get server info callbacks.
/// Warning: This is for single-use cases only! It destroys the actual closure callback.
extern "C"
fn get_server_info_cb_proxy(_: *mut ContextInternal, i: *const ServerInfoInternal,
    userdata: *mut c_void)
{
    let _ = std::panic::catch_unwind(|| {
        assert!(!i.is_null());
        let obj = ServerInfo::new_from_raw(i);

        // Note, destroys closure callback after use - restoring outer box means it gets dropped
        let mut callback = get_su_callback::<dyn FnMut(&ServerInfo)>(userdata);
        (callback)(&obj);
    });
}

////////////////////////////////////////////////////////////////////////////////////////////////////
// Module info
////////////////////////////////////////////////////////////////////////////////////////////////////

/// Stores information about modules.
///
/// Please note that this structure can be extended as part of evolutionary API updates at any time
/// in any new release.
#[derive(Debug)]
pub struct ModuleInfo<'a> {
    /// Index of the module.
    pub index: u32,
    /// Name of the module.
    pub name: Option<Cow<'a, str>>,
    /// Argument string of the module.
    pub argument: Option<Cow<'a, str>>,
    /// Usage counter or `None` if invalid.
    pub n_used: Option<u32>,
    /// Property list.
    pub proplist: Proplist,
}

impl ModuleInfo<'_> {
    fn new_from_raw(p: *const ModuleInfoInternal) -> Self {
        assert!(!p.is_null());
        let src = unsafe { &*p };
        unsafe {
            ModuleInfo {
                index: src.index,
                name: match src.name.is_null() {
                    false => Some(CStr::from_ptr(src.name).to_string_lossy()),
                    true => None,
                },
                argument: match src.argument.is_null() {
                    false => Some(CStr::from_ptr(src.argument).to_string_lossy()),
                    true => None,
                },
                n_used: match src.n_used {
                    def::INVALID_INDEX => None,
                    i => Some(i),
                },
                proplist: Proplist::from_raw_weak(src.proplist),
            }
        }
    }

    /// Creates a copy with owned data.
    pub fn to_owned(&self) -> ModuleInfo<'static> {
        ModuleInfo {
            name: self.name.clone().map(|o| Cow::Owned(o.into_owned())),
            argument: self.argument.clone().map(|o| Cow::Owned(o.into_owned())),
            proplist: self.proplist.to_owned(),
            ..*self
        }
    }
}

impl Introspector {
    /// Gets some information about a module by its index.
    ///
    /// Panics on error, i.e. invalid arguments or state.
    pub fn get_module_info<F>(&self, index: u32, callback: F)
        -> Operation<dyn FnMut(ListResult<&ModuleInfo>)>
        where F: FnMut(ListResult<&ModuleInfo>) + 'static
    {
        let cb_data = box_closure_get_capi_ptr::<dyn FnMut(ListResult<&ModuleInfo>)>(Box::new(callback));
        let ptr = unsafe { capi::pa_context_get_module_info(self.context, index,
            Some(mod_info_list_cb_proxy), cb_data) };
        Operation::from_raw(ptr, cb_data as *mut Box<dyn FnMut(ListResult<&ModuleInfo>)>)
    }

    /// Gets the complete list of currently loaded modules.
    ///
    /// Panics on error, i.e. invalid arguments or state.
    pub fn get_module_info_list<F>(&self, callback: F)
        -> Operation<dyn FnMut(ListResult<&ModuleInfo>)>
        where F: FnMut(ListResult<&ModuleInfo>) + 'static
    {
        let cb_data = box_closure_get_capi_ptr::<dyn FnMut(ListResult<&ModuleInfo>)>(Box::new(callback));
        let ptr = unsafe { capi::pa_context_get_module_info_list(self.context,
            Some(mod_info_list_cb_proxy), cb_data) };
        Operation::from_raw(ptr, cb_data as *mut Box<dyn FnMut(ListResult<&ModuleInfo>)>)
    }

    /// Loads a module.
    ///
    /// Panics on error, i.e. invalid arguments or state. The callback is provided with the
    /// index.
    pub fn load_module<F>(&mut self, name: &str, argument: &str, callback: F)
        -> Operation<dyn FnMut(u32)>
        where F: FnMut(u32) + 'static
    {
        // Warning: New CStrings will be immediately freed if not bound to a variable, leading to
        // as_ptr() giving dangling pointers!
        let c_name = CString::new(name).unwrap();
        let c_arg = CString::new(argument).unwrap();

        let cb_data = box_closure_get_capi_ptr::<dyn FnMut(u32)>(Box::new(callback));
        let ptr = unsafe { capi::pa_context_load_module(self.context, c_name.as_ptr(),
            c_arg.as_ptr(), Some(context_index_cb_proxy), cb_data) };
        Operation::from_raw(ptr, cb_data as *mut Box<dyn FnMut(u32)>)
    }

    /// Unloads a module.
    ///
    /// Panics on error, i.e. invalid arguments or state.
    ///
    /// The callback must accept a `bool`, which indicates success.
    pub fn unload_module<F>(&mut self, index: u32, callback: F) -> Operation<dyn FnMut(bool)>
        where F: FnMut(bool) + 'static
    {
        let cb_data = box_closure_get_capi_ptr::<dyn FnMut(bool)>(Box::new(callback));
        let ptr = unsafe { capi::pa_context_unload_module(self.context, index,
            Some(super::success_cb_proxy), cb_data) };
        Operation::from_raw(ptr, cb_data as *mut Box<dyn FnMut(bool)>)
    }
}

/// Proxy for get module info list callbacks.
///
/// Warning: This is for list cases only! On EOL it destroys the actual closure callback.
extern "C"
fn mod_info_list_cb_proxy(_: *mut ContextInternal, i: *const ModuleInfoInternal, eol: i32,
    userdata: *mut c_void)
{
    let _ = std::panic::catch_unwind(|| {
        callback_for_list_instance(i, eol, userdata, ModuleInfo::new_from_raw);
    });
}

/// Proxy for context index callbacks.
///
/// Warning: This is for single-use cases only! It destroys the actual closure callback.
extern "C"
fn context_index_cb_proxy(_: *mut ContextInternal, index: u32, userdata: *mut c_void) {
    let _ = std::panic::catch_unwind(|| {
        // Note, destroys closure callback after use - restoring outer box means it gets dropped
        let mut callback = get_su_callback::<dyn FnMut(u32)>(userdata);
        (callback)(index);
    });
}

////////////////////////////////////////////////////////////////////////////////////////////////////
// Messages
////////////////////////////////////////////////////////////////////////////////////////////////////

impl Introspector {
    /// Send a message to an object that registered a message handler.
    ///
    /// The callback must accept two params, firstly a boolean indicating success if `true`, and
    /// secondly, the response string. The response string may possibly not be given if
    /// unsuccessful.
    ///
    /// For more information see the [messaging_api.txt] documentation in the PulseAudio repository.
    ///
    /// [messaging_api.txt]: https://gitlab.freedesktop.org/pulseaudio/pulseaudio/-/blob/master/doc/messaging_api.txt
    #[cfg(any(doc, feature = "pa_v15"))]
    #[cfg_attr(docsrs, doc(cfg(feature = "pa_v15")))]
    pub fn send_message_to_object<F>(&mut self, recipient_name: &str, message: &str,
        message_parameters: &str, callback: F) -> Operation<dyn FnMut(bool, Option<String>)>
        where F: FnMut(bool, Option<String>) + 'static
    {
        // Warning: New CStrings will be immediately freed if not bound to a variable, leading to
        // as_ptr() giving dangling pointers!
        let c_recipient_name = CString::new(recipient_name.clone()).unwrap();
        let c_message = CString::new(message.clone()).unwrap();
        let c_message_parameters = CString::new(message_parameters.clone()).unwrap();

        let cb_data = box_closure_get_capi_ptr::<dyn FnMut(bool, Option<String>)>(Box::new(callback));
        let ptr = unsafe { capi::pa_context_send_message_to_object(self.context,
            c_recipient_name.as_ptr(), c_message.as_ptr(), c_message_parameters.as_ptr(),
            Some(send_message_to_object_cb_proxy), cb_data) };
        Operation::from_raw(ptr, cb_data as *mut Box<dyn FnMut(bool, Option<String>)>)
    }
}

/// Proxy for send message to object callbacks.
///
/// Warning: This is for single-use cases only! It destroys the actual closure callback.
#[cfg(any(doc, feature = "pa_v15"))]
extern "C"
fn send_message_to_object_cb_proxy(_: *mut ContextInternal, success: i32, response: *const c_char,
    userdata: *mut c_void)
{
    let success_actual = match success {
        0 => false,
        _ => true,
    };
    let _ = std::panic::catch_unwind(|| {
        let r = response.is_null().then(|| {
            unsafe { CStr::from_ptr(response) }.to_string_lossy().into_owned()
        });
        // Note, destroys closure callback after use - restoring outer box means it gets dropped
        let mut callback = get_su_callback::<dyn FnMut(bool, Option<String>)>(userdata);
        (callback)(success_actual, r);
    });
}

////////////////////////////////////////////////////////////////////////////////////////////////////
// Client info
////////////////////////////////////////////////////////////////////////////////////////////////////

/// Stores information about clients.
///
/// Please note that this structure can be extended as part of evolutionary API updates at any time
/// in any new release.
#[derive(Debug)]
pub struct ClientInfo<'a> {
    /// Index of this client.
    pub index: u32,
    /// Name of this client.
    pub name: Option<Cow<'a, str>>,
    /// Index of the owning module, or `None`.
    pub owner_module: Option<u32>,
    /// Driver name.
    pub driver: Option<Cow<'a, str>>,
    /// Property list.
    pub proplist: Proplist,
}

impl ClientInfo<'_> {
    fn new_from_raw(p: *const ClientInfoInternal) -> Self {
        assert!(!p.is_null());
        let src = unsafe { &*p };
        unsafe {
            ClientInfo {
                index: src.index,
                name: match src.name.is_null() {
                    false => Some(CStr::from_ptr(src.name).to_string_lossy()),
                    true => None,
                },
                owner_module: match src.owner_module {
                    def::INVALID_INDEX => None,
                    i => Some(i),
                },
                driver: match src.driver.is_null() {
                    false => Some(CStr::from_ptr(src.driver).to_string_lossy()),
                    true => None,
                },
                proplist: Proplist::from_raw_weak(src.proplist),
            }
        }
    }

    /// Creates a copy with owned data.
    pub fn to_owned(&self) -> ClientInfo<'static> {
        ClientInfo {
            name: self.name.clone().map(|o| Cow::Owned(o.into_owned())),
            driver: self.driver.clone().map(|o| Cow::Owned(o.into_owned())),
            proplist: self.proplist.to_owned(),
            ..*self
        }
    }
}

impl Introspector {
    /// Gets information about a client by its index.
    ///
    /// Panics on error, i.e. invalid arguments or state.
    pub fn get_client_info<F>(&self, index: u32, callback: F)
        -> Operation<dyn FnMut(ListResult<&ClientInfo>)>
        where F: FnMut(ListResult<&ClientInfo>) + 'static
    {
        let cb_data = box_closure_get_capi_ptr::<dyn FnMut(ListResult<&ClientInfo>)>(Box::new(callback));
        let ptr = unsafe { capi::pa_context_get_client_info(self.context, index,
            Some(get_client_info_list_cb_proxy), cb_data) };
        Operation::from_raw(ptr, cb_data as *mut Box<dyn FnMut(ListResult<&ClientInfo>)>)
    }

    /// Gets the complete client list.
    ///
    /// Panics on error, i.e. invalid arguments or state.
    pub fn get_client_info_list<F>(&self, callback: F)
        -> Operation<dyn FnMut(ListResult<&ClientInfo>)>
        where F: FnMut(ListResult<&ClientInfo>) + 'static
    {
        let cb_data = box_closure_get_capi_ptr::<dyn FnMut(ListResult<&ClientInfo>)>(Box::new(callback));
        let ptr = unsafe { capi::pa_context_get_client_info_list(self.context,
            Some(get_client_info_list_cb_proxy), cb_data) };
        Operation::from_raw(ptr, cb_data as *mut Box<dyn FnMut(ListResult<&ClientInfo>)>)
    }

    /// Kills a client.
    ///
    /// Panics on error, i.e. invalid arguments or state.
    ///
    /// The callback must accept a `bool`, which indicates success.
    pub fn kill_client<F>(&mut self, index: u32, callback: F) -> Operation<dyn FnMut(bool)>
        where F: FnMut(bool) + 'static
    {
        let cb_data = box_closure_get_capi_ptr::<dyn FnMut(bool)>(Box::new(callback));
        let ptr = unsafe { capi::pa_context_kill_client(self.context, index,
            Some(super::success_cb_proxy), cb_data) };
        Operation::from_raw(ptr, cb_data as *mut Box<dyn FnMut(bool)>)
    }
}

/// Proxy for get sink info list callbacks.
///
/// Warning: This is for list cases only! On EOL it destroys the actual closure callback.
extern "C"
fn get_client_info_list_cb_proxy(_: *mut ContextInternal, i: *const ClientInfoInternal, eol: i32,
    userdata: *mut c_void)
{
    let _ = std::panic::catch_unwind(|| {
        callback_for_list_instance(i, eol, userdata, ClientInfo::new_from_raw);
    });
}

////////////////////////////////////////////////////////////////////////////////////////////////////
// Card info
////////////////////////////////////////////////////////////////////////////////////////////////////

/// Stores information about a specific profile of a card.
///
/// Please note that this structure can be extended as part of evolutionary API updates at any time
/// in any new release.
#[derive(Debug)]
pub struct CardProfileInfo<'a> {
    /// Name of this profile.
    pub name: Option<Cow<'a, str>>,
    /// Description of this profile.
    pub description: Option<Cow<'a, str>>,
    /// Number of sinks this profile would create.
    pub n_sinks: u32,
    /// Number of sources this profile would create.
    pub n_sources: u32,
    /// The higher this value is, the more useful this profile is as a default.
    pub priority: u32,
    /// Is this profile available? If this is `false`, meaning “unavailable”, then it makes no sense
    /// to try to activate this profile. If this is `true`, it’s still not a guarantee that
    /// activating the profile will result in anything useful, it just means that the server isn’t
    /// aware of any reason why the profile would definitely be useless.
    pub available: bool,
}

impl CardProfileInfo<'_> {
    fn new_from_raw(p: *const CardProfileInfoInternal) -> Self {
        assert!(!p.is_null());
        let src = unsafe { &*p };
        unsafe {
            CardProfileInfo {
                name: match src.name.is_null() {
                    false => Some(CStr::from_ptr(src.name).to_string_lossy()),
                    true => None,
                },
                description: match src.description.is_null() {
                    false => Some(CStr::from_ptr(src.description).to_string_lossy()),
                    true => None,
                },
                n_sinks: src.n_sinks,
                n_sources: src.n_sources,
                priority: src.priority,
                available: match src.available {
                    0 => false,
                    _ => true,
                },
            }
        }
    }

    /// Creates a copy with owned data.
    pub fn to_owned(&self) -> CardProfileInfo<'static> {
        CardProfileInfo {
            name: self.name.clone().map(|o| Cow::Owned(o.into_owned())),
            description: self.description.clone().map(|o| Cow::Owned(o.into_owned())),
            ..*self
        }
    }
}

/// Stores information about a specific port of a card.
///
/// Please note that this structure can be extended as part of evolutionary API updates at any time
/// in any new release.
#[derive(Debug)]
pub struct CardPortInfo<'a> {
    /// Name of this port.
    pub name: Option<Cow<'a, str>>,
    /// Description of this port.
    pub description: Option<Cow<'a, str>>,
    /// The higher this value is, the more useful this port is as a default.
    pub priority: u32,
    /// Availability status of this port.
    pub available: def::PortAvailable,
    /// The direction of this port.
    pub direction: direction::FlagSet,
    /// Property list.
    pub proplist: Proplist,
    /// Latency offset of the port that gets added to the sink/source latency when the port is
    /// active.
    pub latency_offset: i64,
    /// Set of available profiles.
    pub profiles: Vec<CardProfileInfo<'a>>,
    /// An indentifier for the group of ports that share their availability status with each other.
    ///
    /// This is meant especially for handling cases where one 3.5 mm connector is used for
    /// headphones, headsets and microphones, and the hardware can only tell that something was
    /// plugged in but not what exactly. In this situation the ports for all those devices share
    /// their availability status, and PulseAudio can’t tell which one is actually plugged in, and
    /// some application may ask the user what was plugged in. Such applications should get a list
    /// of all card ports and compare their `availability_group` fields. Ports that have the same
    /// group are those that need input from the user to determine which device was plugged in. The
    /// application should then activate the user-chosen port.
    ///
    /// May be `None`, in which case the port is not part of any availability group (which is the
    /// same as having a group with only one member).
    ///
    /// The group identifier must be treated as an opaque identifier. The string may look like an
    /// ALSA control name, but applications must not assume any such relationship. The group naming
    /// scheme can change without a warning.
    #[cfg(any(doc, feature = "pa_v14"))]
    #[cfg_attr(docsrs, doc(cfg(feature = "pa_v14")))]
    pub availability_group: Option<Cow<'a, str>>,
    /// Port device type.
    #[cfg(any(doc, feature = "pa_v14"))]
    #[cfg_attr(docsrs, doc(cfg(feature = "pa_v14")))]
    pub r#type: DevicePortType,
}

impl CardPortInfo<'_> {
    fn new_from_raw(p: *const CardPortInfoInternal) -> Self {
        assert!(!p.is_null());
        let src = unsafe { &*p };

        let mut profiles_vec = Vec::with_capacity(src.n_profiles as usize);

        assert!(src.n_profiles == 0 || !src.profiles2.is_null());
        for i in 0..src.n_profiles as isize {
            let indexed_ptr =
                unsafe { (*src.profiles2.offset(i)) as *mut CardProfileInfoInternal };
            if !indexed_ptr.is_null() {
                profiles_vec.push(CardProfileInfo::new_from_raw(indexed_ptr));
            }
        }

        unsafe {
            CardPortInfo {
                name: match src.name.is_null() {
                    false => Some(CStr::from_ptr(src.name).to_string_lossy()),
                    true => None,
                },
                description: match src.description.is_null() {
                    false => Some(CStr::from_ptr(src.description).to_string_lossy()),
                    true => None,
                },
                priority: src.priority,
                available: def::PortAvailable::from_i32(src.available).unwrap(),
                direction: direction::FlagSet::from_bits_truncate(src.direction),
                proplist: Proplist::from_raw_weak(src.proplist),
                latency_offset: src.latency_offset,
                profiles: profiles_vec,
                #[cfg(any(doc, feature = "pa_v14"))]
                availability_group: match src.availability_group.is_null() {
                    false => Some(CStr::from_ptr(src.availability_group).to_string_lossy()),
                    true => None,
                },
                #[cfg(any(doc, feature = "pa_v14"))]
                r#type: DevicePortType::from_u32(src.r#type).unwrap(),
            }
        }
    }

    /// Creates a copy with owned data.
    pub fn to_owned(&self) -> CardPortInfo<'static> {
        CardPortInfo {
            name: self.name.clone().map(|o| Cow::Owned(o.into_owned())),
            description: self.description.clone().map(|o| Cow::Owned(o.into_owned())),
            proplist: self.proplist.to_owned(),
            profiles: self.profiles.iter().map(CardProfileInfo::to_owned).collect(),
            #[cfg(any(doc, feature = "pa_v14"))]
            availability_group: self.availability_group.clone().map(|o| Cow::Owned(o.into_owned())),
            ..*self
        }
    }
}

/// Stores information about cards.
///
/// Please note that this structure can be extended as part of evolutionary API updates at any time
/// in any new release.
#[derive(Debug)]
pub struct CardInfo<'a> {
    /// Index of this card.
    pub index: u32,
    /// Name of this card.
    pub name: Option<Cow<'a, str>>,
    /// Index of the owning module, or `None`.
    pub owner_module: Option<u32>,
    /// Driver name.
    pub driver: Option<Cow<'a, str>>,
    /// Property list.
    pub proplist: Proplist,
    /// Set of ports.
    pub ports: Vec<CardPortInfo<'a>>,
    /// Set of available profiles.
    pub profiles: Vec<CardProfileInfo<'a>>,
    /// Pointer to active profile in the set, or `None`.
    pub active_profile: Option<Box<CardProfileInfo<'a>>>,
}

impl CardInfo<'_> {
    fn new_from_raw(p: *const CardInfoInternal) -> Self {
        assert!(!p.is_null());
        let src = unsafe { &*p };

        let mut ports_vec = Vec::with_capacity(src.n_ports as usize);
        assert!(src.n_ports == 0 || !src.ports.is_null());
        for i in 0..src.n_ports as isize {
            let indexed_ptr = unsafe { (*src.ports.offset(i)) as *mut CardPortInfoInternal };
            if !indexed_ptr.is_null() {
                ports_vec.push(CardPortInfo::new_from_raw(indexed_ptr));
            }
        }
        let mut profiles_vec = Vec::with_capacity(src.n_profiles as usize);

        assert!(src.n_profiles == 0 || !src.profiles2.is_null());
        for i in 0..src.n_profiles as isize {
            let indexed_ptr =
                unsafe { (*src.profiles2.offset(i)) as *mut CardProfileInfoInternal };
            if !indexed_ptr.is_null() {
                profiles_vec.push(CardProfileInfo::new_from_raw(indexed_ptr));
            }
        }

        unsafe {
            CardInfo {
                index: src.index,
                name: match src.name.is_null() {
                    false => Some(CStr::from_ptr(src.name).to_string_lossy()),
                    true => None,
                },
                owner_module: match src.owner_module {
                    def::INVALID_INDEX => None,
                    i => Some(i),
                },
                driver: match src.driver.is_null() {
                    false => Some(CStr::from_ptr(src.driver).to_string_lossy()),
                    true => None,
                },
                proplist: Proplist::from_raw_weak(src.proplist),
                ports: ports_vec,
                profiles: profiles_vec,
                active_profile: match src.active_profile2.is_null() {
                    true => None,
                    false => Some(Box::new(CardProfileInfo::new_from_raw(src.active_profile2))),
                },
            }
        }
    }

    /// Creates a copy with owned data.
    pub fn to_owned(&self) -> CardInfo<'static> {
        CardInfo {
            name: self.name.clone().map(|o| Cow::Owned(o.into_owned())),
            driver: self.driver.clone().map(|o| Cow::Owned(o.into_owned())),
            proplist: self.proplist.to_owned(),
            ports: self.ports.iter().map(CardPortInfo::to_owned).collect(),
            profiles: self.profiles.iter().map(CardProfileInfo::to_owned).collect(),
            active_profile: self.active_profile.as_ref().map(|ap| Box::new(ap.as_ref().to_owned())),
            ..*self
        }
    }
}

impl Introspector {
    /// Gets information about a card by its index.
    ///
    /// Panics on error, i.e. invalid arguments or state.
    pub fn get_card_info_by_index<F>(&self, index: u32, callback: F)
        -> Operation<dyn FnMut(ListResult<&CardInfo>)>
        where F: FnMut(ListResult<&CardInfo>) + 'static
    {
        let cb_data = box_closure_get_capi_ptr::<dyn FnMut(ListResult<&CardInfo>)>(Box::new(callback));
        let ptr = unsafe { capi::pa_context_get_card_info_by_index(self.context, index,
            Some(get_card_info_list_cb_proxy), cb_data) };
        Operation::from_raw(ptr, cb_data as *mut Box<dyn FnMut(ListResult<&CardInfo>)>)
    }

    /// Gets information about a card by its name.
    ///
    /// Panics on error, i.e. invalid arguments or state.
    pub fn get_card_info_by_name<F>(&self, name: &str, callback: F)
        -> Operation<dyn FnMut(ListResult<&CardInfo>)>
        where F: FnMut(ListResult<&CardInfo>) + 'static
    {
        // Warning: New CStrings will be immediately freed if not bound to a variable, leading to
        // as_ptr() giving dangling pointers!
        let c_name = CString::new(name).unwrap();

        let cb_data = box_closure_get_capi_ptr::<dyn FnMut(ListResult<&CardInfo>)>(Box::new(callback));
        let ptr = unsafe { capi::pa_context_get_card_info_by_name(self.context, c_name.as_ptr(),
            Some(get_card_info_list_cb_proxy), cb_data) };
        Operation::from_raw(ptr, cb_data as *mut Box<dyn FnMut(ListResult<&CardInfo>)>)
    }

    /// Gets the complete card list.
    ///
    /// Panics on error, i.e. invalid arguments or state.
    pub fn get_card_info_list<F>(&self, callback: F) -> Operation<dyn FnMut(ListResult<&CardInfo>)>
        where F: FnMut(ListResult<&CardInfo>) + 'static
    {
        let cb_data = box_closure_get_capi_ptr::<dyn FnMut(ListResult<&CardInfo>)>(Box::new(callback));
        let ptr = unsafe { capi::pa_context_get_card_info_list(self.context,
            Some(get_card_info_list_cb_proxy), cb_data) };
        Operation::from_raw(ptr, cb_data as *mut Box<dyn FnMut(ListResult<&CardInfo>)>)
    }

    /// Changes the profile of a card.
    ///
    /// Panics on error, i.e. invalid arguments or state.
    ///
    /// The optional callback must accept a `bool`, which indicates success.
    pub fn set_card_profile_by_index(&mut self, index: u32, profile: &str,
        callback: Option<Box<dyn FnMut(bool) + 'static>>) -> Operation<dyn FnMut(bool)>
    {
        // Warning: New CStrings will be immediately freed if not bound to a variable, leading to
        // as_ptr() giving dangling pointers!
        let c_profile = CString::new(profile).unwrap();

        let (cb_fn, cb_data): (Option<extern "C" fn(_, _, _)>, _) =
            get_su_capi_params::<_, _>(callback, super::success_cb_proxy);
        let ptr = unsafe { capi::pa_context_set_card_profile_by_index(self.context, index,
            c_profile.as_ptr(), cb_fn, cb_data) };
        Operation::from_raw(ptr, cb_data as *mut Box<dyn FnMut(bool)>)
    }

    /// Changes the profile of a card.
    ///
    /// Panics on error, i.e. invalid arguments or state.
    ///
    /// The optional callback must accept a `bool`, which indicates success.
    pub fn set_card_profile_by_name(&mut self, name: &str, profile: &str,
        callback: Option<Box<dyn FnMut(bool) + 'static>>) -> Operation<dyn FnMut(bool)>
    {
        // Warning: New CStrings will be immediately freed if not bound to a variable, leading to
        // as_ptr() giving dangling pointers!
        let c_name = CString::new(name).unwrap();
        let c_profile = CString::new(profile).unwrap();

        let (cb_fn, cb_data): (Option<extern "C" fn(_, _, _)>, _) =
            get_su_capi_params::<_, _>(callback, super::success_cb_proxy);
        let ptr = unsafe { capi::pa_context_set_card_profile_by_name(self.context, c_name.as_ptr(),
            c_profile.as_ptr(), cb_fn, cb_data) };
        Operation::from_raw(ptr, cb_data as *mut Box<dyn FnMut(bool)>)
    }

    /// Sets the latency offset of a port.
    ///
    /// Panics on error, i.e. invalid arguments or state.
    ///
    /// The optional callback must accept a `bool`, which indicates success.
    pub fn set_port_latency_offset(&mut self, card_name: &str, port_name: &str, offset: i64,
        callback: Option<Box<dyn FnMut(bool) + 'static>>) -> Operation<dyn FnMut(bool)>
    {
        // Warning: New CStrings will be immediately freed if not bound to a variable, leading to
        // as_ptr() giving dangling pointers!
        let c_name = CString::new(card_name).unwrap();
        let c_port = CString::new(port_name).unwrap();

        let (cb_fn, cb_data): (Option<extern "C" fn(_, _, _)>, _) =
            get_su_capi_params::<_, _>(callback, super::success_cb_proxy);
        let ptr = unsafe { capi::pa_context_set_port_latency_offset(self.context, c_name.as_ptr(),
            c_port.as_ptr(), offset, cb_fn, cb_data) };
        Operation::from_raw(ptr, cb_data as *mut Box<dyn FnMut(bool)>)
    }
}

/// Proxy for get card info list callbacks.
///
/// Warning: This is for list cases only! On EOL it destroys the actual closure callback.
extern "C"
fn get_card_info_list_cb_proxy(_: *mut ContextInternal, i: *const CardInfoInternal, eol: i32,
    userdata: *mut c_void)
{
    let _ = std::panic::catch_unwind(|| {
        callback_for_list_instance(i, eol, userdata, CardInfo::new_from_raw);
    });
}

////////////////////////////////////////////////////////////////////////////////////////////////////
// Sink input info
////////////////////////////////////////////////////////////////////////////////////////////////////

/// Stores information about sink inputs.
///
/// Please note that this structure can be extended as part of evolutionary API updates at any time
/// in any new release.
#[derive(Debug)]
pub struct SinkInputInfo<'a> {
    /// Index of the sink input.
    pub index: u32,
    /// Name of the sink input.
    pub name: Option<Cow<'a, str>>,
    /// Index of the module this sink input belongs to, or `None` when it does not belong to any
    /// module.
    pub owner_module: Option<u32>,
    /// Index of the client this sink input belongs to, or invalid when it does not belong to any
    /// client.
    pub client: Option<u32>,
    /// Index of the connected sink.
    pub sink: u32,
    /// The sample specification of the sink input.
    pub sample_spec: sample::Spec,
    /// Channel map.
    pub channel_map: channelmap::Map,
    /// The volume of this sink input.
    pub volume: ChannelVolumes,
    /// Latency due to buffering in sink input, see [`TimingInfo`](crate::def::TimingInfo) for
    /// details.
    pub buffer_usec: MicroSeconds,
    /// Latency of the sink device, see [`TimingInfo`](crate::def::TimingInfo) for details.
    pub sink_usec: MicroSeconds,
    /// The resampling method used by this sink input.
    pub resample_method: Option<Cow<'a, str>>,
    /// Driver name.
    pub driver: Option<Cow<'a, str>>,
    /// Stream muted.
    pub mute: bool,
    /// Property list.
    pub proplist: Proplist,
    /// Stream corked.
    pub corked: bool,
    /// Stream has volume. If not set, then the meaning of this struct’s volume member is
    /// unspecified.
    pub has_volume: bool,
    /// The volume can be set. If not set, the volume can still change even though clients can’t
    /// control the volume.
    pub volume_writable: bool,
    /// Stream format information.
    pub format: format::Info,
}

impl SinkInputInfo<'_> {
    fn new_from_raw(p: *const SinkInputInfoInternal) -> Self {
        assert!(!p.is_null());
        let src = unsafe { &*p };
        unsafe {
            SinkInputInfo {
                index: src.index,
                name: match src.name.is_null() {
                    false => Some(CStr::from_ptr(src.name).to_string_lossy()),
                    true => None,
                },
                owner_module: match src.owner_module {
                    def::INVALID_INDEX => None,
                    i => Some(i),
                },
                client: match src.client {
                    def::INVALID_INDEX => None,
                    i => Some(i),
                },
                sink: src.sink,
                sample_spec: src.sample_spec.into(),
                channel_map: src.channel_map.into(),
                volume: src.volume.into(),
                buffer_usec: MicroSeconds(src.buffer_usec),
                sink_usec: MicroSeconds(src.sink_usec),
                resample_method: match src.resample_method.is_null() {
                    false => Some(CStr::from_ptr(src.resample_method).to_string_lossy()),
                    true => None,
                },
                driver: match src.driver.is_null() {
                    false => Some(CStr::from_ptr(src.driver).to_string_lossy()),
                    true => None,
                },
                mute: match src.mute {
                    0 => false,
                    _ => true,
                },
                proplist: Proplist::from_raw_weak(src.proplist),
                corked: match src.corked {
                    0 => false,
                    _ => true,
                },
                has_volume: match src.has_volume {
                    0 => false,
                    _ => true,
                },
                volume_writable: match src.volume_writable {
                    0 => false,
                    _ => true,
                },
                format: format::Info::from_raw_weak(src.format as *mut format::InfoInternal),
            }
        }
    }

    /// Creates a copy with owned data.
    pub fn to_owned(&self) -> SinkInputInfo<'static> {
        SinkInputInfo {
            name: self.name.clone().map(|o| Cow::Owned(o.into_owned())),
            resample_method: self.resample_method.clone().map(|o| Cow::Owned(o.into_owned())),
            driver: self.driver.clone().map(|o| Cow::Owned(o.into_owned())),
            proplist: self.proplist.to_owned(),
            format: self.format.to_owned(),
            ..*self
        }
    }
}

impl Introspector {
    /// Gets some information about a sink input by its index.
    ///
    /// Panics on error, i.e. invalid arguments or state.
    pub fn get_sink_input_info<F>(&self, index: u32, callback: F)
        -> Operation<dyn FnMut(ListResult<&SinkInputInfo>)>
        where F: FnMut(ListResult<&SinkInputInfo>) + 'static
    {
        let cb_data =
            box_closure_get_capi_ptr::<dyn FnMut(ListResult<&SinkInputInfo>)>(Box::new(callback));
        let ptr = unsafe { capi::pa_context_get_sink_input_info(self.context, index,
            Some(get_sink_input_info_list_cb_proxy), cb_data) };
        Operation::from_raw(ptr, cb_data as *mut Box<dyn FnMut(ListResult<&SinkInputInfo>)>)
    }

    /// Gets the complete sink input list.
    ///
    /// Panics on error, i.e. invalid arguments or state.
    pub fn get_sink_input_info_list<F>(&self, callback: F)
        -> Operation<dyn FnMut(ListResult<&SinkInputInfo>)>
        where F: FnMut(ListResult<&SinkInputInfo>) + 'static
    {
        let cb_data =
            box_closure_get_capi_ptr::<dyn FnMut(ListResult<&SinkInputInfo>)>(Box::new(callback));
        let ptr = unsafe { capi::pa_context_get_sink_input_info_list(self.context,
            Some(get_sink_input_info_list_cb_proxy), cb_data) };
        Operation::from_raw(ptr, cb_data as *mut Box<dyn FnMut(ListResult<&SinkInputInfo>)>)
    }

    /// Moves the specified sink input to a different sink.
    ///
    /// Panics on error, i.e. invalid arguments or state.
    ///
    /// The optional callback must accept a `bool`, which indicates success.
    pub fn move_sink_input_by_name(&mut self, index: u32, sink_name: &str,
        callback: Option<Box<dyn FnMut(bool) + 'static>>) -> Operation<dyn FnMut(bool)>
    {
        // Warning: New CStrings will be immediately freed if not bound to a variable, leading to
        // as_ptr() giving dangling pointers!
        let c_name = CString::new(sink_name).unwrap();

        let (cb_fn, cb_data): (Option<extern "C" fn(_, _, _)>, _) =
            get_su_capi_params::<_, _>(callback, super::success_cb_proxy);
        let ptr = unsafe { capi::pa_context_move_sink_input_by_name(self.context, index,
            c_name.as_ptr(), cb_fn, cb_data) };
        Operation::from_raw(ptr, cb_data as *mut Box<dyn FnMut(bool)>)
    }

    /// Moves the specified sink input to a different sink.
    ///
    /// Panics on error, i.e. invalid arguments or state.
    ///
    /// The optional callback must accept a `bool`, which indicates success.
    pub fn move_sink_input_by_index(&mut self, index: u32, sink_index: u32,
        callback: Option<Box<dyn FnMut(bool) + 'static>>) -> Operation<dyn FnMut(bool)>
    {
        let (cb_fn, cb_data): (Option<extern "C" fn(_, _, _)>, _) =
            get_su_capi_params::<_, _>(callback, super::success_cb_proxy);
        let ptr = unsafe { capi::pa_context_move_sink_input_by_index(self.context, index,
            sink_index, cb_fn, cb_data) };
        Operation::from_raw(ptr, cb_data as *mut Box<dyn FnMut(bool)>)
    }

    /// Sets the volume of a sink input stream.
    ///
    /// Panics on error, i.e. invalid arguments or state.
    ///
    /// The optional callback must accept a `bool`, which indicates success.
    pub fn set_sink_input_volume(&mut self, index: u32, volume: &ChannelVolumes,
        callback: Option<Box<dyn FnMut(bool) + 'static>>) -> Operation<dyn FnMut(bool)>
    {
        let (cb_fn, cb_data): (Option<extern "C" fn(_, _, _)>, _) =
            get_su_capi_params::<_, _>(callback, super::success_cb_proxy);
        let ptr = unsafe { capi::pa_context_set_sink_input_volume(self.context, index,
            volume.as_ref(), cb_fn, cb_data) };
        Operation::from_raw(ptr, cb_data as *mut Box<dyn FnMut(bool)>)
    }

    /// Sets the mute switch of a sink input stream.
    ///
    /// Panics on error, i.e. invalid arguments or state.
    ///
    /// The optional callback must accept a `bool`, which indicates success.
    pub fn set_sink_input_mute(&mut self, index: u32, mute: bool,
        callback: Option<Box<dyn FnMut(bool) + 'static>>) -> Operation<dyn FnMut(bool)>
    {
        let (cb_fn, cb_data): (Option<extern "C" fn(_, _, _)>, _) =
            get_su_capi_params::<_, _>(callback, super::success_cb_proxy);
        let ptr = unsafe { capi::pa_context_set_sink_input_mute(self.context, index, mute as i32,
            cb_fn, cb_data) };
        Operation::from_raw(ptr, cb_data as *mut Box<dyn FnMut(bool)>)
    }

    /// Kills a sink input.
    ///
    /// Panics on error, i.e. invalid arguments or state.
    ///
    /// The callback must accept a `bool`, which indicates success.
    pub fn kill_sink_input<F>(&mut self, index: u32, callback: F) -> Operation<dyn FnMut(bool)>
        where F: FnMut(bool) + 'static
    {
        let cb_data = box_closure_get_capi_ptr::<dyn FnMut(bool)>(Box::new(callback));
        let ptr = unsafe { capi::pa_context_kill_sink_input(self.context, index,
            Some(super::success_cb_proxy), cb_data) };
        Operation::from_raw(ptr, cb_data as *mut Box<dyn FnMut(bool)>)
    }
}

/// Proxy for get sink input info list callbacks.
///
/// Warning: This is for list cases only! On EOL it destroys the actual closure callback.
extern "C"
fn get_sink_input_info_list_cb_proxy(_: *mut ContextInternal, i: *const SinkInputInfoInternal,
    eol: i32, userdata: *mut c_void)
{
    let _ = std::panic::catch_unwind(|| {
        callback_for_list_instance(i, eol, userdata, SinkInputInfo::new_from_raw);
    });
}

////////////////////////////////////////////////////////////////////////////////////////////////////
// Source output info
////////////////////////////////////////////////////////////////////////////////////////////////////

/// Stores information about source outputs.
///
/// Please note that this structure can be extended as part of evolutionary API updates at any time
/// in any new release.
#[derive(Debug)]
pub struct SourceOutputInfo<'a> {
    /// Index of the source output.
    pub index: u32,
    /// Name of the source output.
    pub name: Option<Cow<'a, str>>,
    /// Index of the module this source output belongs to, or `None` when it does not belong to any
    /// module.
    pub owner_module: Option<u32>,
    /// Index of the client this source output belongs to, or `None` when it does not belong to any
    /// client.
    pub client: Option<u32>,
    /// Index of the connected source.
    pub source: u32,
    /// The sample specification of the source output.
    pub sample_spec: sample::Spec,
    /// Channel map.
    pub channel_map: channelmap::Map,
    /// Latency due to buffering in the source output, see [`TimingInfo`](crate::def::TimingInfo)
    /// for details.
    pub buffer_usec: MicroSeconds,
    /// Latency of the source device, see [`TimingInfo`](crate::def::TimingInfo) for details.
    pub source_usec: MicroSeconds,
    /// The resampling method used by this source output.
    pub resample_method: Option<Cow<'a, str>>,
    /// Driver name.
    pub driver: Option<Cow<'a, str>>,
    /// Property list.
    pub proplist: Proplist,
    /// Stream corked.
    pub corked: bool,
    /// The volume of this source output.
    pub volume: ChannelVolumes,
    /// Stream muted.
    pub mute: bool,
    /// Stream has volume. If not set, then the meaning of this struct’s volume member is
    /// unspecified.
    pub has_volume: bool,
    /// The volume can be set. If not set, the volume can still change even though clients can’t
    /// control the volume.
    pub volume_writable: bool,
    /// Stream format information.
    pub format: format::Info,
}

impl SourceOutputInfo<'_> {
    fn new_from_raw(p: *const SourceOutputInfoInternal) -> Self {
        assert!(!p.is_null());
        let src = unsafe { &*p };
        unsafe {
            SourceOutputInfo {
                index: src.index,
                name: match src.name.is_null() {
                    false => Some(CStr::from_ptr(src.name).to_string_lossy()),
                    true => None,
                },
                owner_module: match src.owner_module {
                    def::INVALID_INDEX => None,
                    i => Some(i),
                },
                client: match src.client {
                    def::INVALID_INDEX => None,
                    i => Some(i),
                },
                source: src.source,
                sample_spec: src.sample_spec.into(),
                channel_map: src.channel_map.into(),
                buffer_usec: MicroSeconds(src.buffer_usec),
                source_usec: MicroSeconds(src.source_usec),
                resample_method: match src.resample_method.is_null() {
                    false => Some(CStr::from_ptr(src.resample_method).to_string_lossy()),
                    true => None,
                },
                driver: match src.driver.is_null() {
                    false => Some(CStr::from_ptr(src.driver).to_string_lossy()),
                    true => None,
                },
                proplist: Proplist::from_raw_weak(src.proplist),
                corked: match src.corked {
                    0 => false,
                    _ => true,
                },
                volume: src.volume.into(),
                mute: match src.mute {
                    0 => false,
                    _ => true,
                },
                has_volume: match src.has_volume {
                    0 => false,
                    _ => true,
                },
                volume_writable: match src.volume_writable {
                    0 => false,
                    _ => true,
                },
                format: format::Info::from_raw_weak(src.format as *mut format::InfoInternal),
            }
        }
    }

    /// Creates a copy with owned data.
    pub fn to_owned(&self) -> SourceOutputInfo<'static> {
        SourceOutputInfo {
            name: self.name.clone().map(|o| Cow::Owned(o.into_owned())),
            resample_method: self.resample_method.clone().map(|o| Cow::Owned(o.into_owned())),
            driver: self.driver.clone().map(|o| Cow::Owned(o.into_owned())),
            proplist: self.proplist.to_owned(),
            format: self.format.to_owned(),
            ..*self
        }
    }
}

impl Introspector {
    /// Gets information about a source output by its index.
    ///
    /// Panics on error, i.e. invalid arguments or state.
    pub fn get_source_output_info<F>(&self, index: u32, callback: F)
        -> Operation<dyn FnMut(ListResult<&SourceOutputInfo>)>
        where F: FnMut(ListResult<&SourceOutputInfo>) + 'static
    {
        let cb_data =
            box_closure_get_capi_ptr::<dyn FnMut(ListResult<&SourceOutputInfo>)>(Box::new(callback));
        let ptr = unsafe { capi::pa_context_get_source_output_info(self.context, index,
            Some(get_source_output_info_list_cb_proxy), cb_data) };
        Operation::from_raw(ptr, cb_data as *mut Box<dyn FnMut(ListResult<&SourceOutputInfo>)>)
    }

    /// Gets the complete list of source outputs.
    ///
    /// Panics on error, i.e. invalid arguments or state.
    pub fn get_source_output_info_list<F>(&self, callback: F)
        -> Operation<dyn FnMut(ListResult<&SourceOutputInfo>)>
        where F: FnMut(ListResult<&SourceOutputInfo>) + 'static
    {
        let cb_data =
            box_closure_get_capi_ptr::<dyn FnMut(ListResult<&SourceOutputInfo>)>(Box::new(callback));
        let ptr = unsafe { capi::pa_context_get_source_output_info_list(self.context,
            Some(get_source_output_info_list_cb_proxy), cb_data) };
        Operation::from_raw(ptr, cb_data as *mut Box<dyn FnMut(ListResult<&SourceOutputInfo>)>)
    }

    /// Moves the specified source output to a different source.
    ///
    /// Panics on error, i.e. invalid arguments or state.
    ///
    /// The optional callback must accept a `bool`, which indicates success.
    pub fn move_source_output_by_name(&mut self, index: u32, source_name: &str,
        callback: Option<Box<dyn FnMut(bool) + 'static>>) -> Operation<dyn FnMut(bool)>
    {
        // Warning: New CStrings will be immediately freed if not bound to a variable, leading to
        // as_ptr() giving dangling pointers!
        let c_name = CString::new(source_name).unwrap();

        let (cb_fn, cb_data): (Option<extern "C" fn(_, _, _)>, _) =
            get_su_capi_params::<_, _>(callback, super::success_cb_proxy);
        let ptr = unsafe { capi::pa_context_move_source_output_by_name(self.context, index,
            c_name.as_ptr(), cb_fn, cb_data) };
        Operation::from_raw(ptr, cb_data as *mut Box<dyn FnMut(bool)>)
    }

    /// Moves the specified source output to a different source.
    ///
    /// Panics on error, i.e. invalid arguments or state.
    ///
    /// The optional callback must accept a `bool`, which indicates success.
    pub fn move_source_output_by_index(&mut self, index: u32, source_index: u32,
        callback: Option<Box<dyn FnMut(bool) + 'static>>) -> Operation<dyn FnMut(bool)>
    {
        let (cb_fn, cb_data): (Option<extern "C" fn(_, _, _)>, _) =
            get_su_capi_params::<_, _>(callback, super::success_cb_proxy);
        let ptr = unsafe { capi::pa_context_move_source_output_by_index(self.context, index,
            source_index, cb_fn, cb_data) };
        Operation::from_raw(ptr, cb_data as *mut Box<dyn FnMut(bool)>)
    }

    /// Sets the volume of a source output stream.
    ///
    /// Panics on error, i.e. invalid arguments or state.
    ///
    /// The optional callback must accept a `bool`, which indicates success.
    pub fn set_source_output_volume(&mut self, index: u32, volume: &ChannelVolumes,
        callback: Option<Box<dyn FnMut(bool) + 'static>>) -> Operation<dyn FnMut(bool)>
    {
        let (cb_fn, cb_data): (Option<extern "C" fn(_, _, _)>, _) =
            get_su_capi_params::<_, _>(callback, super::success_cb_proxy);
        let ptr = unsafe { capi::pa_context_set_source_output_volume(self.context, index,
            volume.as_ref(), cb_fn, cb_data) };
        Operation::from_raw(ptr, cb_data as *mut Box<dyn FnMut(bool)>)
    }

    /// Sets the mute switch of a source output stream.
    ///
    /// Panics on error, i.e. invalid arguments or state.
    ///
    /// The optional callback must accept a `bool`, which indicates success.
    pub fn set_source_output_mute(&mut self, index: u32, mute: bool,
        callback: Option<Box<dyn FnMut(bool) + 'static>>) -> Operation<dyn FnMut(bool)>
    {
        let (cb_fn, cb_data): (Option<extern "C" fn(_, _, _)>, _) =
            get_su_capi_params::<_, _>(callback, super::success_cb_proxy);
        let ptr = unsafe { capi::pa_context_set_source_output_mute(self.context, index, mute as i32,
            cb_fn, cb_data) };
        Operation::from_raw(ptr, cb_data as *mut Box<dyn FnMut(bool)>)
    }

    /// Kills a source output.
    ///
    /// Panics on error, i.e. invalid arguments or state.
    ///
    /// The callback must accept a `bool`, which indicates success.
    pub fn kill_source_output<F>(&mut self, index: u32, callback: F) -> Operation<dyn FnMut(bool)>
        where F: FnMut(bool) + 'static
    {
        let cb_data = box_closure_get_capi_ptr::<dyn FnMut(bool)>(Box::new(callback));
        let ptr = unsafe { capi::pa_context_kill_source_output(self.context, index,
            Some(super::success_cb_proxy), cb_data) };
        Operation::from_raw(ptr, cb_data as *mut Box<dyn FnMut(bool)>)
    }
}

/// Proxy for get source output info list callbacks.
///
/// Warning: This is for list cases only! On EOL it destroys the actual closure callback.
extern "C"
fn get_source_output_info_list_cb_proxy(_: *mut ContextInternal, i: *const SourceOutputInfoInternal,
    eol: i32, userdata: *mut c_void)
{
    let _ = std::panic::catch_unwind(|| {
        callback_for_list_instance(i, eol, userdata, SourceOutputInfo::new_from_raw);
    });
}

////////////////////////////////////////////////////////////////////////////////////////////////////
// Stat info
////////////////////////////////////////////////////////////////////////////////////////////////////

impl Introspector {
    /// Gets daemon memory block statistics.
    ///
    /// Panics on error, i.e. invalid arguments or state.
    pub fn stat<F>(&self, callback: F) -> Operation<dyn FnMut(&StatInfo)>
        where F: FnMut(&StatInfo) + 'static
    {
        let cb_data = box_closure_get_capi_ptr::<dyn FnMut(&StatInfo)>(Box::new(callback));
        let ptr =
            unsafe { capi::pa_context_stat(self.context, Some(get_stat_info_cb_proxy), cb_data) };
        Operation::from_raw(ptr, cb_data as *mut Box<dyn FnMut(&StatInfo)>)
    }
}

/// Proxy for get stat info callbacks.
///
/// Warning: This is for single-use cases only! It destroys the actual closure callback.
extern "C"
fn get_stat_info_cb_proxy(_: *mut ContextInternal, i: *const StatInfo, userdata: *mut c_void) {
    let _ = std::panic::catch_unwind(|| {
        assert!(!i.is_null());
        // Note, destroys closure callback after use - restoring outer box means it gets dropped
        let mut callback = get_su_callback::<dyn FnMut(&StatInfo)>(userdata);
        (callback)(unsafe { &*i });
    });
}

////////////////////////////////////////////////////////////////////////////////////////////////////
// Sample info
////////////////////////////////////////////////////////////////////////////////////////////////////

/// Stores information about sample cache entries.
///
/// Please note that this structure can be extended as part of evolutionary API updates at any time
/// in any new release.
#[derive(Debug)]
pub struct SampleInfo<'a> {
    /// Index of this entry.
    pub index: u32,
    /// Name of this entry.
    pub name: Option<Cow<'a, str>>,
    /// Default volume of this entry.
    pub volume: ChannelVolumes,
    /// Sample specification of the sample.
    pub sample_spec: sample::Spec,
    /// The channel map.
    pub channel_map: channelmap::Map,
    /// Duration of this entry.
    pub duration: MicroSeconds,
    /// Length of this sample in bytes.
    pub bytes: u32,
    /// Non-zero when this is a lazy cache entry.
    pub lazy: bool,
    /// In case this is a lazy cache entry, the filename for the sound file to be loaded on demand.
    pub filename: Option<Cow<'a, str>>,
    /// Property list for this sample.
    pub proplist: Proplist,
}

impl SampleInfo<'_> {
    fn new_from_raw(p: *const SampleInfoInternal) -> Self {
        assert!(!p.is_null());
        let src = unsafe { &*p };
        unsafe {
            SampleInfo {
                index: src.index,
                name: match src.name.is_null() {
                    false => Some(CStr::from_ptr(src.name).to_string_lossy()),
                    true => None,
                },
                volume: src.volume.into(),
                sample_spec: src.sample_spec.into(),
                channel_map: src.channel_map.into(),
                duration: MicroSeconds(src.duration),
                bytes: src.bytes,
                lazy: match src.lazy {
                    0 => false,
                    _ => true,
                },
                filename: match src.filename.is_null() {
                    false => Some(CStr::from_ptr(src.filename).to_string_lossy()),
                    true => None,
                },
                proplist: Proplist::from_raw_weak(src.proplist),
            }
        }
    }

    /// Creates a copy with owned data.
    pub fn to_owned(&self) -> SampleInfo<'static> {
        SampleInfo {
            name: self.name.clone().map(|o| Cow::Owned(o.into_owned())),
            filename: self.filename.clone().map(|o| Cow::Owned(o.into_owned())),
            proplist: self.proplist.to_owned(),
            ..*self
        }
    }
}

impl Introspector {
    /// Gets information about a sample by its name.
    ///
    /// Panics on error, i.e. invalid arguments or state.
    pub fn get_sample_info_by_name<F>(&self, name: &str, callback: F)
        -> Operation<dyn FnMut(ListResult<&SampleInfo>)>
        where F: FnMut(ListResult<&SampleInfo>) + 'static
    {
        // Warning: New CStrings will be immediately freed if not bound to a variable, leading to
        // as_ptr() giving dangling pointers!
        let c_name = CString::new(name).unwrap();

        let cb_data = box_closure_get_capi_ptr::<dyn FnMut(ListResult<&SampleInfo>)>(Box::new(callback));
        let ptr = unsafe { capi::pa_context_get_sample_info_by_name(self.context, c_name.as_ptr(),
            Some(get_sample_info_list_cb_proxy), cb_data) };
        Operation::from_raw(ptr, cb_data as *mut Box<dyn FnMut(ListResult<&SampleInfo>)>)
    }

    /// Gets information about a sample by its index.
    ///
    /// Panics on error, i.e. invalid arguments or state.
    pub fn get_sample_info_by_index<F>(&self, index: u32, callback: F)
        -> Operation<dyn FnMut(ListResult<&SampleInfo>)>
        where F: FnMut(ListResult<&SampleInfo>) + 'static
    {
        let cb_data = box_closure_get_capi_ptr::<dyn FnMut(ListResult<&SampleInfo>)>(Box::new(callback));
        let ptr = unsafe { capi::pa_context_get_sample_info_by_index(self.context, index,
            Some(get_sample_info_list_cb_proxy), cb_data) };
        Operation::from_raw(ptr, cb_data as *mut Box<dyn FnMut(ListResult<&SampleInfo>)>)
    }

    /// Gets the complete list of samples stored in the daemon.
    ///
    /// Panics on error, i.e. invalid arguments or state.
    pub fn get_sample_info_list<F>(&self, callback: F)
        -> Operation<dyn FnMut(ListResult<&SampleInfo>)>
        where F: FnMut(ListResult<&SampleInfo>) + 'static
    {
        let cb_data = box_closure_get_capi_ptr::<dyn FnMut(ListResult<&SampleInfo>)>(Box::new(callback));
        let ptr = unsafe { capi::pa_context_get_sample_info_list(self.context,
            Some(get_sample_info_list_cb_proxy), cb_data) };
        Operation::from_raw(ptr, cb_data as *mut Box<dyn FnMut(ListResult<&SampleInfo>)>)
    }
}

/// Proxy for get sample info list callbacks.
///
/// Warning: This is for list cases only! On EOL it destroys the actual closure callback.
extern "C"
fn get_sample_info_list_cb_proxy(_: *mut ContextInternal, i: *const SampleInfoInternal, eol: i32,
    userdata: *mut c_void)
{
    let _ = std::panic::catch_unwind(|| {
        callback_for_list_instance(i, eol, userdata, SampleInfo::new_from_raw);
    });
}
