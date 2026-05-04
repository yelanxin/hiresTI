//! USB Audio Class (UAC 1.0 / 2.0) self-hosted output driver.
//!
//! # Architecture
//!
//! ```text
//! Symphonia decoder (PCM slabs)
//!        │  S16LE / S24_3LE / S32LE / F32LE / F64LE
//!   FrameQueue  (SPSC lock-free ring, ~200 ms)
//!        │
//!  UsbAudioThread  (dedicated RT thread)
//!   ├── IsoTransferRing   (libusb async iso, N=16 transfers)
//!   ├── FeedbackReader    (UAC 2.0 async sample-rate feedback)
//!   ├── RateAdapter       (dynamic per-frame sample count)
//!   └── HwClockFeed       (frame counter → master clock)
//!        │
//!   libusb-1.0  (async, event loop in dedicated thread)
//!        │  USB Isochronous OUT
//!   USB DAC
//! ```

pub mod control;
pub mod borrowed_queue;
pub mod descriptor;
pub mod device;
pub mod dop;
pub mod feedback;
pub mod owned_buffer_queue;
pub mod queue;
pub mod raw_config;
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
pub use raw_config::UsbRawSinkConfig;
pub use raw_sink::UsbRawSink;
pub use sink::{QueueMode, UsbAudioSink};
pub use source::TransferSource;
pub use transfer::{IsoTransferRing, RingState};
