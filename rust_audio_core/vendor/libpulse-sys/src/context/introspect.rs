// Copyright 2017 Lyndon Brown
//
// This file is part of the PulseAudio Rust language linking library.
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

use std::os::raw::{c_char, c_void};
use super::{pa_context, pa_context_success_cb_t};
use crate::volume::{pa_cvolume, pa_volume_t};
use crate::sample::{pa_sample_spec, pa_usec_t};
use crate::def::{pa_sink_flags_t, pa_sink_state_t, pa_source_flags_t, pa_source_state_t};
use crate::{operation::pa_operation, channelmap::pa_channel_map};
use crate::{proplist::pa_proplist, format::pa_format_info};

#[repr(C)]
pub struct pa_sink_port_info {
    pub name: *const c_char,
    pub description: *const c_char,
    pub priority: u32,
    pub available: i32,
    #[cfg(any(doc, feature = "pa_v14"))]
    #[cfg_attr(docsrs, doc(cfg(feature = "pa_v14")))]
    pub availability_group: *const c_char,
    #[cfg(any(doc, feature = "pa_v14"))]
    #[cfg_attr(docsrs, doc(cfg(feature = "pa_v14")))]
    pub r#type: u32,
}

#[repr(C)]
pub struct pa_sink_info {
    pub name: *const c_char,
    pub index: u32,
    pub description: *const c_char,
    pub sample_spec: pa_sample_spec,
    pub channel_map: pa_channel_map,
    pub owner_module: u32,
    pub volume: pa_cvolume,
    pub mute: i32,
    pub monitor_source: u32,
    pub monitor_source_name: *const c_char,
    pub latency: pa_usec_t,
    pub driver: *const c_char,
    pub flags: pa_sink_flags_t,
    pub proplist: *mut pa_proplist,
    pub configured_latency: pa_usec_t,
    pub base_volume: pa_volume_t,
    pub state: pa_sink_state_t,
    pub n_volume_steps: u32,
    pub card: u32,
    pub n_ports: u32,
    pub ports: *mut *mut pa_sink_port_info,
    pub active_port: *mut pa_sink_port_info,
    pub n_formats: u8,
    pub formats: *mut *mut pa_format_info,
}

#[rustfmt::skip]
pub type pa_sink_info_cb_t = Option<extern "C" fn(c: *mut pa_context, i: *const pa_sink_info, eol: i32, userdata: *mut c_void)>;

#[repr(C)]
pub struct pa_source_port_info {
    pub name: *const c_char,
    pub description: *const c_char,
    pub priority: u32,
    pub available: i32,
    #[cfg(any(doc, feature = "pa_v14"))]
    #[cfg_attr(docsrs, doc(cfg(feature = "pa_v14")))]
    pub availability_group: *const c_char,
    #[cfg(any(doc, feature = "pa_v14"))]
    #[cfg_attr(docsrs, doc(cfg(feature = "pa_v14")))]
    pub r#type: u32,
}

#[repr(C)]
pub struct pa_source_info {
    pub name: *const c_char,
    pub index: u32,
    pub description: *const c_char,
    pub sample_spec: pa_sample_spec,
    pub channel_map: pa_channel_map,
    pub owner_module: u32,
    pub volume: pa_cvolume,
    pub mute: i32,
    pub monitor_of_sink: u32,
    pub monitor_of_sink_name: *const c_char,
    pub latency: pa_usec_t,
    pub driver: *const c_char,
    pub flags: pa_source_flags_t,
    pub proplist: *mut pa_proplist,
    pub configured_latency: pa_usec_t,
    pub base_volume: pa_volume_t,
    pub state: pa_source_state_t,
    pub n_volume_steps: u32,
    pub card: u32,
    pub n_ports: u32,
    pub ports: *mut *mut pa_source_port_info,
    pub active_port: *mut pa_source_port_info,
    pub n_formats: u8,
    pub formats: *mut *mut pa_format_info,
}

#[rustfmt::skip]
pub type pa_source_info_cb_t = Option<extern "C" fn(c: *mut pa_context, i: *const pa_source_info, eol: i32, userdata: *mut c_void)>;

#[repr(C)]
pub struct pa_server_info {
    pub user_name: *const c_char,
    pub host_name: *const c_char,
    pub server_version: *const c_char,
    pub server_name: *const c_char,
    pub sample_spec: pa_sample_spec,
    pub default_sink_name: *const c_char,
    pub default_source_name: *const c_char,
    pub cookie: u32,
    pub channel_map: pa_channel_map,
}

#[rustfmt::skip]
pub type pa_server_info_cb_t = Option<extern "C" fn(c: *mut pa_context, i: *const pa_server_info, userdata: *mut c_void)>;

#[repr(C)]
pub struct pa_module_info {
    pub index: u32,
    pub name: *const c_char,
    pub argument: *const c_char,
    pub n_used: u32,
    #[deprecated]
    pub auto_unload: i32,
    pub proplist: *mut pa_proplist,
}

#[rustfmt::skip]
pub type pa_module_info_cb_t = Option<extern "C" fn(c: *mut pa_context, i: *const pa_module_info, eol: i32, userdata: *mut c_void)>;

#[rustfmt::skip]
pub type pa_context_index_cb_t = Option<extern "C" fn(c: *mut pa_context, idx: u32, userdata: *mut c_void)>;

/// Stores information about clients.
///
/// Please note that this structure can be extended as part of evolutionary API updates at any time
/// in any new release.
#[repr(C)]
pub struct pa_client_info {
    /// Index of this client.
    pub index: u32,
    /// Name of this client.
    pub name: *const c_char,
    /// Index of the owning module, or [`PA_INVALID_INDEX`](crate::def::PA_INVALID_INDEX).
    pub owner_module: u32,
    /// Driver name.
    pub driver: *const c_char,
    /// Property list.
    pub proplist: *mut pa_proplist,
}

#[rustfmt::skip]
pub type pa_client_info_cb_t = Option<extern "C" fn(c: *mut pa_context, i: *const pa_client_info, eol: i32, userdata: *mut c_void)>;

/// Stores information about a specific profile of a card.
///
/// Please note that this structure is obsolete, replaced by [`pa_card_profile_info2`] in PA v5.
#[repr(C)]
pub struct pa_card_profile_info {
    /// Name of this profile.
    pub name: *const c_char,
    /// Description of this profile.
    pub description: *const c_char,
    /// Number of sinks this profile would create.
    pub n_sinks: u32,
    /// Number of sources this profile would create.
    pub n_sources: u32,
    /// The higher this value is, the more useful this profile is as a default.
    pub priority: u32,
}

/// Stores information about a specific profile of a card.
///
/// Please note that this structure can be extended as part of evolutionary API updates at any time
/// in any new release.
#[repr(C)]
pub struct pa_card_profile_info2 {
    /// Name of this profile.
    pub name: *const c_char,
    /// Description of this profile.
    pub description: *const c_char,
    /// Number of sinks this profile would create.
    pub n_sinks: u32,
    /// Number of sources this profile would create.
    pub n_sources: u32,
    /// The higher this value is, the more useful this profile is as a default.
    pub priority: u32,

    /// Is this profile available? If this is zero, meaning “unavailable”, then it makes no sense to
    /// try to activate this profile. If this is non-zero, it’s still not a guarantee that
    /// activating the profile will result in anything useful, it just means that the server isn’t
    /// aware of any reason why the profile would definitely be useless.
    pub available: i32,
}

#[repr(C)]
pub struct pa_card_port_info {
    pub name: *const c_char,
    pub description: *const c_char,
    pub priority: u32,
    pub available: i32,
    pub direction: i32,
    pub n_profiles: u32,
    #[deprecated]
    pub profiles: *mut *mut pa_card_profile_info,
    pub proplist: *mut pa_proplist,
    pub latency_offset: i64,
    pub profiles2: *mut *mut pa_card_profile_info2,
    #[cfg(any(doc, feature = "pa_v14"))]
    #[cfg_attr(docsrs, doc(cfg(feature = "pa_v14")))]
    pub availability_group: *const c_char,
    #[cfg(any(doc, feature = "pa_v14"))]
    #[cfg_attr(docsrs, doc(cfg(feature = "pa_v14")))]
    pub r#type: u32,
}

#[repr(C)]
pub struct pa_card_info {
    pub index: u32,
    pub name: *const c_char,
    pub owner_module: u32,
    pub driver: *const c_char,
    pub n_profiles: u32,
    #[deprecated]
    pub profiles: *mut pa_card_profile_info,
    #[deprecated]
    pub active_profile: *mut pa_card_profile_info,
    pub proplist: *mut pa_proplist,
    pub n_ports: u32,
    pub ports: *mut *mut pa_card_port_info,
    pub profiles2: *mut *mut pa_card_profile_info2,
    pub active_profile2: *mut pa_card_profile_info2,
}

#[rustfmt::skip]
pub type pa_card_info_cb_t = Option<extern "C" fn(c: *mut pa_context, i: *const pa_card_info, eol: i32, userdata: *mut c_void)>;

#[repr(C)]
pub struct pa_sink_input_info {
    pub index: u32,
    pub name: *const c_char,
    pub owner_module: u32,
    pub client: u32,
    pub sink: u32,
    pub sample_spec: pa_sample_spec,
    pub channel_map: pa_channel_map,
    pub volume: pa_cvolume,
    pub buffer_usec: pa_usec_t,
    pub sink_usec: pa_usec_t,
    pub resample_method: *const c_char,
    pub driver: *const c_char,
    pub mute: i32,
    pub proplist: *mut pa_proplist,
    pub corked: i32,
    pub has_volume: i32,
    pub volume_writable: i32,
    pub format: *mut pa_format_info,
}

#[rustfmt::skip]
pub type pa_sink_input_info_cb_t = Option<extern "C" fn(c: *mut pa_context, i: *const pa_sink_input_info, eol: i32, userdata: *mut c_void)>;

#[repr(C)]
pub struct pa_source_output_info {
    pub index: u32,
    pub name: *const c_char,
    pub owner_module: u32,
    pub client: u32,
    pub source: u32,
    pub sample_spec: pa_sample_spec,
    pub channel_map: pa_channel_map,
    pub buffer_usec: pa_usec_t,
    pub source_usec: pa_usec_t,
    pub resample_method: *const c_char,
    pub driver: *const c_char,
    pub proplist: *mut pa_proplist,
    pub corked: i32,
    pub volume: pa_cvolume,
    pub mute: i32,
    pub has_volume: i32,
    pub volume_writable: i32,
    pub format: *mut pa_format_info,
}

#[rustfmt::skip]
pub type pa_source_output_info_cb_t = Option<extern "C" fn(c: *mut pa_context, i: *const pa_source_output_info, eol: i32, userdata: *mut c_void)>;

/// Memory block statistics.
///
/// Please note that this structure can be extended as part of evolutionary API updates at any time
/// in any new release.
#[repr(C)]
#[derive(Debug)]
pub struct pa_stat_info {
    /// Currently allocated memory blocks.
    pub memblock_total: u32,
    /// Current total size of allocated memory blocks.
    pub memblock_total_size: u32,
    /// Allocated memory blocks during the whole lifetime of the daemon.
    pub memblock_allocated: u32,
    /// Total size of all memory blocks allocated during the whole lifetime of the daemon.
    pub memblock_allocated_size: u32,
    /// Total size of all sample cache entries.
    pub scache_size: u32,
}

#[rustfmt::skip]
pub type pa_stat_info_cb_t = Option<extern "C" fn(c: *mut pa_context, i: *const pa_stat_info, userdata: *mut c_void)>;

#[repr(C)]
pub struct pa_sample_info {
    pub index: u32,
    pub name: *const c_char,
    pub volume: pa_cvolume,
    pub sample_spec: pa_sample_spec,
    pub channel_map: pa_channel_map,
    pub duration: pa_usec_t,
    pub bytes: u32,
    pub lazy: i32,
    pub filename: *const c_char,
    pub proplist: *mut pa_proplist,
}

#[rustfmt::skip]
pub type pa_sample_info_cb_t = Option<extern "C" fn(c: *mut pa_context, i: *const pa_sample_info, eol: i32, userdata: *mut c_void)>;

#[rustfmt::skip]
#[cfg(any(doc, feature = "pa_v15"))]
#[cfg_attr(docsrs, doc(cfg(feature = "pa_v15")))]
pub type pa_context_string_cb_t = Option<extern "C" fn(c: *mut pa_context, success: i32, response: *const c_char, userdata: *mut c_void)>;

#[rustfmt::skip]
#[link(name = "pulse")]
extern "C" {
    pub fn pa_context_get_sink_info_by_name(c: *mut pa_context, name: *const c_char, cb: pa_sink_info_cb_t, userdata: *mut c_void) -> *mut pa_operation;
    pub fn pa_context_get_sink_info_by_index(c: *mut pa_context, idx: u32, cb: pa_sink_info_cb_t, userdata: *mut c_void) -> *mut pa_operation;
    pub fn pa_context_get_sink_info_list(c: *mut pa_context, cb: pa_sink_info_cb_t, userdata: *mut c_void) -> *mut pa_operation;
    pub fn pa_context_set_sink_volume_by_index(c: *mut pa_context, idx: u32, volume: *const pa_cvolume, cb: pa_context_success_cb_t, userdata: *mut c_void) -> *mut pa_operation;
    pub fn pa_context_set_sink_volume_by_name(c: *mut pa_context, name: *const c_char, volume: *const pa_cvolume, cb: pa_context_success_cb_t, userdata: *mut c_void) -> *mut pa_operation;
    pub fn pa_context_set_sink_mute_by_index(c: *mut pa_context, idx: u32, mute: i32, cb: pa_context_success_cb_t, userdata: *mut c_void) -> *mut pa_operation;
    pub fn pa_context_set_sink_mute_by_name(c: *mut pa_context, name: *const c_char, mute: i32, cb: pa_context_success_cb_t, userdata: *mut c_void) -> *mut pa_operation;
    pub fn pa_context_suspend_sink_by_name(c: *mut pa_context, sink_name: *const c_char, suspend: i32, cb: pa_context_success_cb_t, userdata: *mut c_void) -> *mut pa_operation;
    pub fn pa_context_suspend_sink_by_index(c: *mut pa_context, idx: u32, suspend: i32, cb: pa_context_success_cb_t, userdata: *mut c_void) -> *mut pa_operation;
    pub fn pa_context_set_sink_port_by_index(c: *mut pa_context, idx: u32, port: *const c_char, cb: pa_context_success_cb_t, userdata: *mut c_void) -> *mut pa_operation;
    pub fn pa_context_set_sink_port_by_name(c: *mut pa_context, name: *const c_char, port: *const c_char, cb: pa_context_success_cb_t, userdata: *mut c_void) -> *mut pa_operation;

    pub fn pa_context_get_source_info_by_name(c: *mut pa_context, name: *const c_char, cb: pa_source_info_cb_t, userdata: *mut c_void) -> *mut pa_operation;
    pub fn pa_context_get_source_info_by_index(c: *mut pa_context, idx: u32, cb: pa_source_info_cb_t, userdata: *mut c_void) -> *mut pa_operation;
    pub fn pa_context_get_source_info_list(c: *mut pa_context, cb: pa_source_info_cb_t, userdata: *mut c_void) -> *mut pa_operation;
    pub fn pa_context_set_source_volume_by_index(c: *mut pa_context, idx: u32, volume: *const pa_cvolume, cb: pa_context_success_cb_t, userdata: *mut c_void) -> *mut pa_operation;
    pub fn pa_context_set_source_volume_by_name(c: *mut pa_context, name: *const c_char, volume: *const pa_cvolume, cb: pa_context_success_cb_t, userdata: *mut c_void) -> *mut pa_operation;
    pub fn pa_context_set_source_mute_by_index(c: *mut pa_context, idx: u32, mute: i32, cb: pa_context_success_cb_t, userdata: *mut c_void) -> *mut pa_operation;
    pub fn pa_context_set_source_mute_by_name(c: *mut pa_context, name: *const c_char, mute: i32, cb: pa_context_success_cb_t, userdata: *mut c_void) -> *mut pa_operation;
    pub fn pa_context_suspend_source_by_name(c: *mut pa_context, source_name: *const c_char, suspend: i32, cb: pa_context_success_cb_t, userdata: *mut c_void) -> *mut pa_operation;
    pub fn pa_context_suspend_source_by_index(c: *mut pa_context, idx: u32, suspend: i32, cb: pa_context_success_cb_t, userdata: *mut c_void) -> *mut pa_operation;
    pub fn pa_context_set_source_port_by_index(c: *mut pa_context, idx: u32, port: *const c_char, cb: pa_context_success_cb_t, userdata: *mut c_void) -> *mut pa_operation;
    pub fn pa_context_set_source_port_by_name(c: *mut pa_context, name: *const c_char, port: *const c_char, cb: pa_context_success_cb_t, userdata: *mut c_void) -> *mut pa_operation;

    pub fn pa_context_get_server_info(c: *mut pa_context, cb: pa_server_info_cb_t, userdata: *mut c_void) -> *mut pa_operation;

    pub fn pa_context_get_module_info(c: *mut pa_context, idx: u32, cb: pa_module_info_cb_t, userdata: *mut c_void) -> *mut pa_operation;
    pub fn pa_context_get_module_info_list(c: *mut pa_context, cb: pa_module_info_cb_t, userdata: *mut c_void) -> *mut pa_operation;
    pub fn pa_context_load_module(c: *mut pa_context, name: *const c_char, argument: *const c_char, cb: pa_context_index_cb_t, userdata: *mut c_void) -> *mut pa_operation;
    pub fn pa_context_unload_module(c: *mut pa_context, idx: u32, cb: pa_context_success_cb_t, userdata: *mut c_void) -> *mut pa_operation;

    #[cfg(any(doc, feature = "pa_v15"))]
    #[cfg_attr(docsrs, doc(cfg(feature = "pa_v15")))]
    pub fn pa_context_send_message_to_object(c: *mut pa_context, recipient_name: *const c_char, message: *const c_char, message_parameters: *const c_char, cb: pa_context_string_cb_t, userdata: *mut c_void) -> *mut pa_operation;

    pub fn pa_context_get_client_info(c: *mut pa_context, idx: u32, cb: pa_client_info_cb_t, userdata: *mut c_void) -> *mut pa_operation;
    pub fn pa_context_get_client_info_list(c: *mut pa_context, cb: pa_client_info_cb_t, userdata: *mut c_void) -> *mut pa_operation;
    pub fn pa_context_kill_client(c: *mut pa_context, idx: u32, cb: pa_context_success_cb_t, userdata: *mut c_void) -> *mut pa_operation;

    pub fn pa_context_get_card_info_by_index(c: *mut pa_context, idx: u32, cb: pa_card_info_cb_t, userdata: *mut c_void) -> *mut pa_operation;
    pub fn pa_context_get_card_info_by_name(c: *mut pa_context, name: *const c_char, cb: pa_card_info_cb_t, userdata: *mut c_void) -> *mut pa_operation;
    pub fn pa_context_get_card_info_list(c: *mut pa_context, cb: pa_card_info_cb_t, userdata: *mut c_void) -> *mut pa_operation;
    pub fn pa_context_set_card_profile_by_index(c: *mut pa_context, idx: u32, profile: *const c_char, cb: pa_context_success_cb_t, userdata: *mut c_void) -> *mut pa_operation;
    pub fn pa_context_set_card_profile_by_name(c: *mut pa_context, name: *const c_char, profile: *const c_char, cb: pa_context_success_cb_t, userdata: *mut c_void) -> *mut pa_operation;
    pub fn pa_context_set_port_latency_offset(c: *mut pa_context, card_name: *const c_char, port_name: *const c_char, offset: i64, cb: pa_context_success_cb_t, userdata: *mut c_void) -> *mut pa_operation;

    pub fn pa_context_get_sink_input_info(c: *mut pa_context, idx: u32, cb: pa_sink_input_info_cb_t, userdata: *mut c_void) -> *mut pa_operation;
    pub fn pa_context_get_sink_input_info_list(c: *mut pa_context, cb: pa_sink_input_info_cb_t, userdata: *mut c_void) -> *mut pa_operation;
    pub fn pa_context_move_sink_input_by_name(c: *mut pa_context, idx: u32, sink_name: *const c_char, cb: pa_context_success_cb_t, userdata: *mut c_void) -> *mut pa_operation;
    pub fn pa_context_move_sink_input_by_index(c: *mut pa_context, idx: u32, sink_idx: u32, cb: pa_context_success_cb_t, userdata: *mut c_void) -> *mut pa_operation;
    pub fn pa_context_set_sink_input_volume(c: *mut pa_context, idx: u32, volume: *const pa_cvolume, cb: pa_context_success_cb_t, userdata: *mut c_void) -> *mut pa_operation;
    pub fn pa_context_set_sink_input_mute(c: *mut pa_context, idx: u32, mute: i32, cb: pa_context_success_cb_t, userdata: *mut c_void) -> *mut pa_operation;
    pub fn pa_context_kill_sink_input(c: *mut pa_context, idx: u32, cb: pa_context_success_cb_t, userdata: *mut c_void) -> *mut pa_operation;

    pub fn pa_context_get_source_output_info(c: *mut pa_context, idx: u32, cb: pa_source_output_info_cb_t, userdata: *mut c_void) -> *mut pa_operation;
    pub fn pa_context_get_source_output_info_list(c: *mut pa_context, cb: pa_source_output_info_cb_t, userdata: *mut c_void) -> *mut pa_operation;
    pub fn pa_context_move_source_output_by_name(c: *mut pa_context, idx: u32, source_name: *const c_char, cb: pa_context_success_cb_t, userdata: *mut c_void) -> *mut pa_operation;
    pub fn pa_context_move_source_output_by_index(c: *mut pa_context, idx: u32, source_idx: u32, cb: pa_context_success_cb_t, userdata: *mut c_void) -> *mut pa_operation;
    pub fn pa_context_set_source_output_volume(c: *mut pa_context, idx: u32, volume: *const pa_cvolume, cb: pa_context_success_cb_t, userdata: *mut c_void) -> *mut pa_operation;
    pub fn pa_context_set_source_output_mute(c: *mut pa_context, idx: u32, mute: i32, cb: pa_context_success_cb_t, userdata: *mut c_void) -> *mut pa_operation;
    pub fn pa_context_kill_source_output(c: *mut pa_context, idx: u32, cb: pa_context_success_cb_t, userdata: *mut c_void) -> *mut pa_operation;

    pub fn pa_context_stat(c: *mut pa_context, cb: pa_stat_info_cb_t, userdata: *mut c_void) -> *mut pa_operation;

    pub fn pa_context_get_sample_info_by_name(c: *mut pa_context, name: *const c_char, cb: pa_sample_info_cb_t, userdata: *mut c_void) -> *mut pa_operation;
    pub fn pa_context_get_sample_info_by_index(c: *mut pa_context, idx: u32, cb: pa_sample_info_cb_t, userdata: *mut c_void) -> *mut pa_operation;
    pub fn pa_context_get_sample_info_list(c: *mut pa_context, cb: pa_sample_info_cb_t, userdata: *mut c_void) -> *mut pa_operation;
}
