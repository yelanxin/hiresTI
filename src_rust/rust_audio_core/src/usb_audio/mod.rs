//! USB Audio Class (UAC 1.0 / 2.0) self-hosted output driver.
//!
//! # Architecture
//!
//! ```text
//! GStreamer appsink (pull mode)
//!        │  PCM frames (S32LE / S24LE / S16LE)
//!   FrameQueue  (SPSC lock-free ring, ~200 ms)
//!        │
//!  UsbAudioThread  (dedicated RT thread)
//!   ├── IsoTransferRing   (libusb async iso, N=16 transfers)
//!   ├── FeedbackReader    (UAC 2.0 async sample-rate feedback)
//!   ├── RateAdapter       (dynamic per-frame sample count)
//!   └── HwClockFeed       (frame counter → AlsaHwClock)
//!        │
//!   libusb-1.0  (async, event loop in dedicated thread)
//!        │  USB Isochronous OUT
//!   USB DAC
//! ```
//!
//! Phase 1 (this file): descriptor parsing + device enumeration.
//! Later phases add the transfer ring, feedback reader, and Engine integration.

pub mod control;
pub mod borrowed_queue;
pub mod descriptor;
pub mod device;
pub mod dop;
pub mod feedback;
pub mod owned_buffer_queue;
pub mod queue;
pub mod raw_sink;
pub mod sink;
pub mod source;
pub mod transfer;

pub use borrowed_queue::BorrowedBufferQueue;
pub use descriptor::{FeatureUnitInfo, UacFormat, UacStreamAlt, UacVersion};
pub use device::{enumerate_usb_audio_devices, OpenUsbDevice, UacAltProfile, UsbAudioDevice};
pub use dop::DopEncoder;
pub use owned_buffer_queue::OwnedBufferQueue;
pub use queue::FrameQueue;
pub use raw_sink::{UsbRawSink, UsbRawSinkConfig};
pub use sink::{QueueMode, UsbAudioSink};
pub use source::TransferSource;
pub use transfer::{IsoTransferRing, RingState};
