//! SPSC lock-free ring buffer for PCM byte streaming.
//!
//! [`FrameQueue`] bridges the GStreamer appsink pull thread (producer) and
//! the USB ISO transfer callback (consumer).  Both ends operate concurrently
//! with no mutex — only two `AtomicUsize` indices.
//!
//! # Capacity
//!
//! Fixed at [`QUEUE_CAP`] bytes (512 KiB), a power of two.  At 192 kHz /
//! 32-bit stereo this covers ~333 ms, well beyond the 200 ms headroom target.
//!
//! # Index convention
//!
//! `write` and `read` advance monotonically (never masked).  The actual buffer
//! position is `index & QUEUE_MASK`.  This makes empty/full detection trivial:
//! - empty : `write == read`
//! - full  : `write - read == QUEUE_CAP`

use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;

/// Backing store size in bytes.  Must be a power of two.
const QUEUE_CAP: usize = 1 << 19; // 512 KiB
const QUEUE_MASK: usize = QUEUE_CAP - 1;

pub struct FrameQueue {
    buf: Box<[u8; QUEUE_CAP]>,
    /// Next byte to write (producer-owned, relaxed by consumer).
    write: AtomicUsize,
    /// Next byte to read  (consumer-owned, relaxed by producer).
    read: AtomicUsize,
    /// Bytes per interleaved audio frame (channels × bytes_per_sample).
    /// Used for frame-alignment validation in debug builds.
    /// Zero means validation is disabled (not configured yet).
    frame_bytes: AtomicUsize,
}

// SAFETY: The SPSC protocol ensures only one thread writes and one reads.
unsafe impl Send for FrameQueue {}
unsafe impl Sync for FrameQueue {}

impl FrameQueue {
    pub fn new() -> Arc<Self> {
        Arc::new(Self {
            buf: Box::new([0u8; QUEUE_CAP]),
            write: AtomicUsize::new(0),
            read: AtomicUsize::new(0),
            frame_bytes: AtomicUsize::new(0),
        })
    }

    /// Set the frame size for alignment validation.
    /// Call once after the audio format is known.
    pub fn set_frame_bytes(&self, frame_bytes: usize) {
        self.frame_bytes.store(frame_bytes, Ordering::Relaxed);
    }

    /// Number of bytes available to read.
    #[inline]
    pub fn available_read(&self) -> usize {
        let w = self.write.load(Ordering::Acquire);
        let r = self.read.load(Ordering::Relaxed);
        w.wrapping_sub(r)
    }

    /// Number of bytes available to write.
    #[inline]
    pub fn available_write(&self) -> usize {
        QUEUE_CAP - self.available_read()
    }

    /// Push up to `data.len()` bytes.  Returns how many were written.
    ///
    /// The producer calls this.  Writes as many bytes as there is space for;
    /// does not block.
    pub fn push(&self, data: &[u8]) -> usize {
        let fb = self.frame_bytes.load(Ordering::Relaxed);
        debug_assert!(
            fb == 0 || data.len() % fb == 0,
            "FrameQueue::push: data.len()={} not frame-aligned (frame_bytes={})",
            data.len(),
            fb,
        );
        let r = self.read.load(Ordering::Acquire);
        let w = self.write.load(Ordering::Relaxed);
        let space = QUEUE_CAP - w.wrapping_sub(r);
        let n = data.len().min(space);
        if n == 0 {
            return 0;
        }

        // SAFETY: SPSC — only producer writes; indices guarantee no aliasing.
        let buf =
            unsafe { std::slice::from_raw_parts_mut(self.buf.as_ptr() as *mut u8, QUEUE_CAP) };
        let wi = w & QUEUE_MASK;
        let end = (wi + n).min(QUEUE_CAP);
        let first = end - wi; // bytes before wrap
        buf[wi..end].copy_from_slice(&data[..first]);
        if first < n {
            // Wrap-around: copy remaining bytes at the start of the buffer
            let second = n - first;
            buf[..second].copy_from_slice(&data[first..n]);
        }

        self.write.store(w.wrapping_add(n), Ordering::Release);
        n
    }

    /// Pop up to `dst.len()` bytes.  Returns how many were read.
    ///
    /// The consumer (USB callback) calls this.  Reads as many bytes as are
    /// available; does not block.  Unread bytes in `dst` are left unchanged.
    pub fn pop(&self, dst: &mut [u8]) -> usize {
        let w = self.write.load(Ordering::Acquire);
        let r = self.read.load(Ordering::Relaxed);
        let avail = w.wrapping_sub(r);
        let n = dst.len().min(avail);
        if n == 0 {
            return 0;
        }

        // SAFETY: SPSC — only consumer reads; indices guarantee no aliasing.
        let buf = unsafe { std::slice::from_raw_parts(self.buf.as_ptr() as *const u8, QUEUE_CAP) };
        let ri = r & QUEUE_MASK;
        let end = (ri + n).min(QUEUE_CAP);
        let first = end - ri;
        dst[..first].copy_from_slice(&buf[ri..end]);
        if first < n {
            let second = n - first;
            dst[first..n].copy_from_slice(&buf[..second]);
        }

        self.read.store(r.wrapping_add(n), Ordering::Release);
        n
    }

    /// Reset both indices to zero (call only when no threads are active).
    pub fn reset(&self) {
        self.write.store(0, Ordering::SeqCst);
        self.read.store(0, Ordering::SeqCst);
    }
}
