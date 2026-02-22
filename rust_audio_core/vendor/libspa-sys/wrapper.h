#include <pipewire/version.h>

#include <spa/buffer/alloc.h>
#include <spa/buffer/buffer.h>
#include <spa/buffer/meta.h>
#include <spa/buffer/type-info.h>

#include <spa/control/control.h>
#include <spa/control/type-info.h>

#include <spa/debug/buffer.h>
#include <spa/debug/dict.h>
#include <spa/debug/format.h>
#include <spa/debug/mem.h>
#include <spa/debug/node.h>
#include <spa/debug/pod.h>
#include <spa/debug/types.h>

#include <spa/graph/graph.h>

#include <spa/monitor/device.h>
#if PW_CHECK_VERSION(0,3,7)
#include <spa/monitor/event.h>
#endif
#if PW_CHECK_VERSION(0,3,20)
#include <spa/monitor/type-info.h>
#endif
#include <spa/monitor/utils.h>

#include <spa/node/command.h>
#include <spa/node/event.h>
#include <spa/node/io.h>
#include <spa/node/keys.h>
#include <spa/node/node.h>
#include <spa/node/type-info.h>
#include <spa/node/utils.h>

#include <spa/param/format-utils.h>
#include <spa/param/format.h>
#if PW_CHECK_VERSION(0,3,29)
#include <spa/param/latency-utils.h>
#endif
#include <spa/param/param.h>
#include <spa/param/profiler.h>
#include <spa/param/props.h>
#include <spa/param/type-info.h>

#if PW_CHECK_VERSION(0,3,37)
#include <spa/param/audio/dsd.h>
#endif
#include <spa/param/audio/format-utils.h>
#include <spa/param/audio/format.h>
#if PW_CHECK_VERSION(0,3,34)
#include <spa/param/audio/iec958.h>
#endif
#include <spa/param/audio/layout.h>
#include <spa/param/audio/raw.h>
#include <spa/param/audio/type-info.h>

#if PW_CHECK_VERSION(0,3,25)
#include <spa/param/bluetooth/audio.h>
#include <spa/param/bluetooth/type-info.h>
#endif

#include <spa/param/video/chroma.h>
#include <spa/param/video/color.h>
#include <spa/param/video/encoded.h>
#include <spa/param/video/format-utils.h>
#include <spa/param/video/format.h>
#include <spa/param/video/multiview.h>
#include <spa/param/video/raw.h>
#include <spa/param/video/type-info.h>

#include <spa/pod/builder.h>
#include <spa/pod/command.h>
#include <spa/pod/compare.h>
#include <spa/pod/event.h>
#include <spa/pod/filter.h>
#include <spa/pod/iter.h>
#include <spa/pod/parser.h>
#include <spa/pod/pod.h>
#include <spa/pod/vararg.h>

#include <spa/support/cpu.h>
#include <spa/support/dbus.h>
#if PW_CHECK_VERSION(0,3,26)
#include <spa/support/i18n.h>
#endif
#include <spa/support/log-impl.h>
#include <spa/support/log.h>
#include <spa/support/loop.h>
#if PW_CHECK_VERSION(0,3,35)
#include <spa/support/plugin-loader.h>
#endif
#include <spa/support/plugin.h>
#include <spa/support/system.h>
#if PW_CHECK_VERSION(0,3,32)
#include <spa/support/thread.h>
#endif

#if PW_CHECK_VERSION(0,3,29)
#include <spa/utils/ansi.h>
#endif
#include <spa/utils/defs.h>
#include <spa/utils/dict.h>
#include <spa/utils/hook.h>
#if PW_CHECK_VERSION(0,3,18)
#include <spa/utils/json.h>
#endif
#include <spa/utils/keys.h>
#include <spa/utils/list.h>
#include <spa/utils/names.h>
#include <spa/utils/result.h>
#include <spa/utils/ringbuffer.h>
#if PW_CHECK_VERSION(0,3,28)
#include <spa/utils/string.h>
#endif
#include <spa/utils/type-info.h>
#include <spa/utils/type.h>
