#include <spa/utils/type-info.h>
#include <spa/debug/types.h>

// spa/utils
const struct spa_type_info* libspa_rs_types = spa_types;
const struct spa_type_info* libspa_rs_type_direction = spa_type_direction;
const struct spa_type_info* libspa_rs_type_choice = spa_type_choice;

// spa/monitor
const struct spa_type_info* libspa_rs_type_device_event_id = spa_type_device_event_id;
const struct spa_type_info* libspa_rs_type_device_event = spa_type_device_event;

// spa/node
const struct spa_type_info* libspa_rs_type_io = spa_type_io;
const struct spa_type_info* libspa_rs_type_node_event_id = spa_type_node_event_id;
const struct spa_type_info* libspa_rs_type_node_event = spa_type_node_event;
const struct spa_type_info* libspa_rs_type_node_command_id = spa_type_node_command_id;
const struct spa_type_info* libspa_rs_type_node_command = spa_type_node_command;

// spa/buffer
const struct spa_type_info* libspa_rs_type_data_type = spa_type_data_type;
const struct spa_type_info* libspa_rs_type_meta_type = spa_type_meta_type;

// spa/control
const struct spa_type_info* libspa_rs_type_control = spa_type_control;

// spa/param
const struct spa_type_info* libspa_rs_type_param = spa_type_param;
const struct spa_type_info* libspa_rs_type_prop_float_array = spa_type_prop_float_array;
const struct spa_type_info* libspa_rs_type_prop_channel_map = spa_type_prop_channel_map;
const struct spa_type_info* libspa_rs_type_prop_iec958_codec = spa_type_prop_iec958_codec;
const struct spa_type_info* libspa_rs_type_param_bitorder = spa_type_param_bitorder;
const struct spa_type_info* libspa_rs_type_props = spa_type_props;
const struct spa_type_info* libspa_rs_type_prop_info = spa_type_prop_info;
const struct spa_type_info* libspa_rs_type_param_meta = spa_type_param_meta;
const struct spa_type_info* libspa_rs_type_param_io = spa_type_param_io;
const struct spa_type_info* libspa_rs_type_media_type = spa_type_media_type;
const struct spa_type_info* libspa_rs_type_media_subtype = spa_type_media_subtype;
const struct spa_type_info* libspa_rs_type_format = spa_type_format;
const struct spa_type_info* libspa_rs_type_param_buffers = spa_type_param_buffers;
const struct spa_type_info* libspa_rs_type_param_availability = spa_type_param_availability;
const struct spa_type_info* libspa_rs_type_param_profile = spa_type_param_profile;
const struct spa_type_info* libspa_rs_type_param_port_config_mode = spa_type_param_port_config_mode;
const struct spa_type_info* libspa_rs_type_param_port_config = spa_type_param_port_config;
const struct spa_type_info* libspa_rs_type_param_route = spa_type_param_route;
const struct spa_type_info* libspa_rs_type_profiler = spa_type_profiler;
const struct spa_type_info* libspa_rs_type_param_latency = spa_type_param_latency;
const struct spa_type_info* libspa_rs_type_param_process_latency = spa_type_param_process_latency;

// spa/param/audio
const struct spa_type_info* libspa_rs_type_audio_format = spa_type_audio_format;
const struct spa_type_info* libspa_rs_type_audio_flags = spa_type_audio_flags;
const struct spa_type_info* libspa_rs_type_audio_channel = spa_type_audio_channel;
const struct spa_type_info* libspa_rs_type_audio_iec958_codec = spa_type_audio_iec958_codec;

// spa/param/bluetooth
const struct spa_type_info* libspa_rs_type_bluetooth_audio_codec = spa_type_bluetooth_audio_codec;

// spa/param/video
const struct spa_type_info* libspa_rs_type_video_format = spa_type_video_format;
#ifdef FEATURE_0_3_65
const struct spa_type_info* libspa_rs_type_video_flags = spa_type_video_flags;
const struct spa_type_info* libspa_rs_type_video_interlace_mode = spa_type_video_interlace_mode;
#endif
