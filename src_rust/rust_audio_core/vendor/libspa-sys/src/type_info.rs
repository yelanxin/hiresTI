use super::*;

extern "C" {
    #[link_name = "libspa_rs_types"]
    pub static spa_types: *const spa_type_info;
    #[link_name = "libspa_rs_type_direction"]
    pub static spa_type_direction: *const spa_type_info;
    #[link_name = "libspa_rs_type_choice"]
    pub static spa_type_choice: *const spa_type_info;
    #[link_name = "libspa_rs_type_device_event_id"]
    pub static spa_type_device_event_id: *const spa_type_info;
    #[link_name = "libspa_rs_type_device_event"]
    pub static spa_type_device_event: *const spa_type_info;
    #[link_name = "libspa_rs_type_io"]
    pub static spa_type_io: *const spa_type_info;
    #[link_name = "libspa_rs_type_node_event_id"]
    pub static spa_type_node_event_id: *const spa_type_info;
    #[link_name = "libspa_rs_type_node_event"]
    pub static spa_type_node_event: *const spa_type_info;
    #[link_name = "libspa_rs_type_node_command_id"]
    pub static spa_type_node_command_id: *const spa_type_info;
    #[link_name = "libspa_rs_type_node_command"]
    pub static spa_type_node_command: *const spa_type_info;
    #[link_name = "libspa_rs_type_data_type"]
    pub static spa_type_data_type: *const spa_type_info;
    #[link_name = "libspa_rs_type_meta_type"]
    pub static spa_type_meta_type: *const spa_type_info;
    #[link_name = "libspa_rs_type_control"]
    pub static spa_type_control: *const spa_type_info;
    #[link_name = "libspa_rs_type_param"]
    pub static spa_type_param: *const spa_type_info;
    #[link_name = "libspa_rs_type_prop_float_array"]
    pub static spa_type_prop_float_array: *const spa_type_info;
    #[link_name = "libspa_rs_type_prop_channel_map"]
    pub static spa_type_prop_channel_map: *const spa_type_info;
    #[link_name = "libspa_rs_type_prop_iec958_codec"]
    pub static spa_type_prop_iec958_codec: *const spa_type_info;
    #[link_name = "libspa_rs_type_param_bitorder"]
    pub static spa_type_param_bitorder: *const spa_type_info;
    #[link_name = "libspa_rs_type_props"]
    pub static spa_type_props: *const spa_type_info;
    #[link_name = "libspa_rs_type_prop_info"]
    pub static spa_type_prop_info: *const spa_type_info;
    #[link_name = "libspa_rs_type_param_meta"]
    pub static spa_type_param_meta: *const spa_type_info;
    #[link_name = "libspa_rs_type_param_io"]
    pub static spa_type_param_io: *const spa_type_info;
    #[link_name = "libspa_rs_type_media_type"]
    pub static spa_type_media_type: *const spa_type_info;
    #[link_name = "libspa_rs_type_media_subtype"]
    pub static spa_type_media_subtype: *const spa_type_info;
    #[link_name = "libspa_rs_type_format"]
    pub static spa_type_format: *const spa_type_info;
    #[link_name = "libspa_rs_type_param_buffers"]
    pub static spa_type_param_buffers: *const spa_type_info;
    #[link_name = "libspa_rs_type_param_availability"]
    pub static spa_type_param_availability: *const spa_type_info;
    #[link_name = "libspa_rs_type_param_profile"]
    pub static spa_type_param_profile: *const spa_type_info;
    #[link_name = "libspa_rs_type_param_port_config_mode"]
    pub static spa_type_param_port_config_mode: *const spa_type_info;
    #[link_name = "libspa_rs_type_param_port_config"]
    pub static spa_type_param_port_config: *const spa_type_info;
    #[link_name = "libspa_rs_type_param_route"]
    pub static spa_type_param_route: *const spa_type_info;
    #[link_name = "libspa_rs_type_profiler"]
    pub static spa_type_profiler: *const spa_type_info;
    #[link_name = "libspa_rs_type_param_latency"]
    pub static spa_type_param_latency: *const spa_type_info;
    #[link_name = "libspa_rs_type_param_process_latency"]
    pub static spa_type_param_process_latency: *const spa_type_info;
    #[link_name = "libspa_rs_type_audio_format"]
    pub static spa_type_audio_format: *const spa_type_info;
    #[link_name = "libspa_rs_type_audio_flags"]
    pub static spa_type_audio_flags: *const spa_type_info;
    #[link_name = "libspa_rs_type_audio_channel"]
    pub static spa_type_audio_channel: *const spa_type_info;
    #[link_name = "libspa_rs_type_audio_iec958_codec"]
    pub static spa_type_audio_iec958_codec: *const spa_type_info;
    #[link_name = "libspa_rs_type_bluetooth_audio_codec"]
    pub static spa_type_bluetooth_audio_codec: *const spa_type_info;
    #[link_name = "libspa_rs_type_video_format"]
    pub static spa_type_video_format: *const spa_type_info;
    #[cfg(feature = "v0_3_65")]
    #[link_name = "libspa_rs_type_video_flags"]
    pub static spa_type_video_flags: *const spa_type_info;
    #[cfg(feature = "v0_3_65")]
    #[link_name = "libspa_rs_type_video_interlace_mode"]
    pub static spa_type_video_interlace_mode: *const spa_type_info;
}

#[cfg(test)]
mod test {
    use crate::{spa_type_media_type, SPA_MEDIA_TYPE_audio};

    use std::ffi;

    #[test]
    fn test_libspa_rs_debug_type_find() {
        unsafe {
            let type_info = super::spa_debug_type_find(spa_type_media_type, SPA_MEDIA_TYPE_audio);
            assert_eq!(
                ffi::CStr::from_ptr((*type_info).name),
                ffi::CString::new("Spa:Enum:MediaType:audio")
                    .unwrap()
                    .as_ref()
            );
        }
    }

    #[test]
    fn test_libspa_rs_debug_type_find_name() {
        unsafe {
            let name = super::spa_debug_type_find_name(spa_type_media_type, SPA_MEDIA_TYPE_audio);
            assert_eq!(
                ffi::CStr::from_ptr(name),
                ffi::CString::new("Spa:Enum:MediaType:audio")
                    .unwrap()
                    .as_ref()
            );
        }
    }

    #[test]
    fn test_libspa_rs_debug_type_find_short_name() {
        unsafe {
            let name =
                super::spa_debug_type_find_short_name(spa_type_media_type, SPA_MEDIA_TYPE_audio);
            assert_eq!(
                ffi::CStr::from_ptr(name),
                ffi::CString::new("audio").unwrap().as_ref()
            );
        }
    }
}
