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

use super::source::TransferSource;

/// Backing store size in bytes.  Must be a power of two.
const QUEUE_CAP: usize = 1 << 19; // 512 KiB
const QUEUE_MASK: usize = QUEUE_CAP - 1;

#[cfg(target_os = "linux")]
struct MirroredQueueStorage {
    base: *mut u8,
}

#[cfg(target_os = "linux")]
impl MirroredQueueStorage {
    fn new() -> std::io::Result<Self> {
        use std::ffi::CString;
        use std::io;
        use std::os::raw::c_void;
        use std::ptr;

        let name = CString::new("hiresti-framequeue").unwrap();
        let fd = unsafe { libc::memfd_create(name.as_ptr(), libc::MFD_CLOEXEC) };
        if fd < 0 {
            return Err(io::Error::last_os_error());
        }

        let mut setup_failed = false;
        let result = unsafe {
            if libc::ftruncate(fd, QUEUE_CAP as libc::off_t) != 0 {
                setup_failed = true;
                ptr::null_mut()
            } else {
                libc::mmap(
                    ptr::null_mut(),
                    QUEUE_CAP * 2,
                    libc::PROT_NONE,
                    libc::MAP_PRIVATE | libc::MAP_ANONYMOUS,
                    -1,
                    0,
                )
            }
        };
        if setup_failed || result == libc::MAP_FAILED {
            let err = std::io::Error::last_os_error();
            unsafe { libc::close(fd) };
            return Err(err);
        }

        let reserve = result as *mut c_void;
        let first = unsafe {
            libc::mmap(
                reserve,
                QUEUE_CAP,
                libc::PROT_READ | libc::PROT_WRITE,
                libc::MAP_SHARED | libc::MAP_FIXED,
                fd,
                0,
            )
        };
        if first == libc::MAP_FAILED {
            let err = std::io::Error::last_os_error();
            unsafe {
                libc::munmap(reserve, QUEUE_CAP * 2);
                libc::close(fd);
            }
            return Err(err);
        }

        let second_addr = unsafe { (reserve as *mut u8).add(QUEUE_CAP) } as *mut c_void;
        let second = unsafe {
            libc::mmap(
                second_addr,
                QUEUE_CAP,
                libc::PROT_READ | libc::PROT_WRITE,
                libc::MAP_SHARED | libc::MAP_FIXED,
                fd,
                0,
            )
        };
        let close_rc = unsafe { libc::close(fd) };
        if second == libc::MAP_FAILED || close_rc != 0 {
            let err = std::io::Error::last_os_error();
            unsafe {
                libc::munmap(reserve, QUEUE_CAP * 2);
            }
            return Err(err);
        }

        Ok(Self {
            base: reserve as *mut u8,
        })
    }

    #[inline]
    fn as_ptr(&self) -> *const u8 {
        self.base as *const u8
    }

    #[inline]
    fn as_mut_ptr(&self) -> *mut u8 {
        self.base
    }
}

#[cfg(target_os = "linux")]
impl Drop for MirroredQueueStorage {
    fn drop(&mut self) {
        unsafe {
            libc::munmap(self.base as *mut _, QUEUE_CAP * 2);
        }
    }
}

enum QueueStorage {
    #[cfg(target_os = "linux")]
    Mirrored(MirroredQueueStorage),
    Plain(Box<[u8; QUEUE_CAP]>),
}

impl QueueStorage {
    fn new() -> Self {
        #[cfg(target_os = "linux")]
        {
            match MirroredQueueStorage::new() {
                Ok(storage) => {
                    eprintln!("usb-audio: FrameQueue storage=mirrored-mmap cap={} B", QUEUE_CAP);
                    return Self::Mirrored(storage);
                }
                Err(err) => {
                    eprintln!(
                        "usb-audio: FrameQueue mirrored-mmap unavailable: {} ; falling back to plain ring",
                        err
                    );
                }
            }
        }
        Self::Plain(Box::new([0u8; QUEUE_CAP]))
    }

    #[inline]
    fn as_ptr(&self) -> *const u8 {
        match self {
            #[cfg(target_os = "linux")]
            Self::Mirrored(storage) => storage.as_ptr(),
            Self::Plain(buf) => buf.as_ptr(),
        }
    }

    #[inline]
    fn as_mut_ptr(&self) -> *mut u8 {
        match self {
            #[cfg(target_os = "linux")]
            Self::Mirrored(storage) => storage.as_mut_ptr(),
            Self::Plain(buf) => buf.as_ptr() as *mut u8,
        }
    }

    #[inline]
    fn is_mirrored(&self) -> bool {
        match self {
            #[cfg(target_os = "linux")]
            Self::Mirrored(_) => true,
            Self::Plain(_) => false,
        }
    }
}

pub struct FrameQueue {
    storage: QueueStorage,
    /// Next byte to write (producer-owned, relaxed by consumer).
    write: AtomicUsize,
    /// Oldest byte not yet safe to overwrite.
    ///
    /// A byte is released only after the USB transfer that references it has
    /// completed.  This keeps queue-backed transfer buffers valid for the whole
    /// libusb in-flight window.
    read: AtomicUsize,
    /// Next byte to assign to a future USB transfer.
    ///
    /// The consumer advances this when it either leases queue memory directly
    /// to libusb or copies queued data into a scratch transfer buffer.  Bytes
    /// remain unavailable to the producer until `read` catches up after the
    /// transfer completes.
    reserve: AtomicUsize,
    /// Bytes per interleaved audio frame (channels × bytes_per_sample).
    /// Used for frame-alignment validation in debug builds.
    /// Zero means validation is disabled (not configured yet).
    frame_bytes: AtomicUsize,
}

// SAFETY: The SPSC protocol ensures only one thread writes and one reads.
unsafe impl Send for FrameQueue {}
unsafe impl Sync for FrameQueue {}

impl FrameQueue {
    pub const fn capacity_bytes() -> usize {
        QUEUE_CAP
    }

    pub fn new() -> Arc<Self> {
        Arc::new(Self {
            storage: QueueStorage::new(),
            write: AtomicUsize::new(0),
            read: AtomicUsize::new(0),
            reserve: AtomicUsize::new(0),
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

    /// Number of bytes not yet assigned to a USB transfer.
    #[inline]
    pub fn available_assign(&self) -> usize {
        let w = self.write.load(Ordering::Acquire);
        let reserve = self.reserve.load(Ordering::Relaxed);
        w.wrapping_sub(reserve)
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

        let wi = w & QUEUE_MASK;
        if self.storage.is_mirrored() {
            unsafe {
                std::ptr::copy_nonoverlapping(data.as_ptr(), self.storage.as_mut_ptr().add(wi), n);
            }
        } else {
            // SAFETY: SPSC — only producer writes; indices guarantee no aliasing.
            let buf =
                unsafe { std::slice::from_raw_parts_mut(self.storage.as_mut_ptr(), QUEUE_CAP) };
            let end = (wi + n).min(QUEUE_CAP);
            let first = end - wi; // bytes before wrap
            buf[wi..end].copy_from_slice(&data[..first]);
            if first < n {
                // Wrap-around: copy remaining bytes at the start of the buffer
                let second = n - first;
                buf[..second].copy_from_slice(&data[first..n]);
            }
        }

        self.write.store(w.wrapping_add(n), Ordering::Release);
        n
    }

    /// Copy up to `dst.len()` bytes from the next unassigned region.
    ///
    /// This advances the reservation pointer, not the release pointer, so the
    /// bytes remain protected from producer overwrite until the corresponding
    /// USB transfer completes.
    ///
    /// The consumer (USB callback) calls this.  Copies as many bytes as are
    /// available; does not block.  Unwritten bytes in `dst` are left unchanged.
    pub fn reserve_copy_into(&self, dst: &mut [u8]) -> usize {
        let w = self.write.load(Ordering::Acquire);
        let reserve = self.reserve.load(Ordering::Relaxed);
        let avail = w.wrapping_sub(reserve);
        let n = dst.len().min(avail);
        if n == 0 {
            return 0;
        }

        let ri = reserve & QUEUE_MASK;
        if self.storage.is_mirrored() {
            unsafe {
                std::ptr::copy_nonoverlapping(self.storage.as_ptr().add(ri), dst.as_mut_ptr(), n);
            }
        } else {
            // SAFETY: SPSC — only consumer reads; indices guarantee no aliasing.
            let buf = unsafe { std::slice::from_raw_parts(self.storage.as_ptr(), QUEUE_CAP) };
            let end = (ri + n).min(QUEUE_CAP);
            let first = end - ri;
            dst[..first].copy_from_slice(&buf[ri..end]);
            if first < n {
                let second = n - first;
                dst[first..n].copy_from_slice(&buf[..second]);
            }
        }

        self.reserve.store(reserve.wrapping_add(n), Ordering::Release);
        n
    }

    /// Lease a contiguous slice of queue-backed memory directly to libusb.
    ///
    /// Returns a stable mutable pointer valid until the leased bytes are later
    /// released via [`release_reserved`].  Fails when the unassigned data wraps
    /// at the end of the ring or when there are fewer than `len` bytes ready.
    pub fn reserve_direct_contiguous(&self, len: usize) -> Option<*mut u8> {
        if len == 0 {
            return None;
        }
        let w = self.write.load(Ordering::Acquire);
        let reserve = self.reserve.load(Ordering::Relaxed);
        let avail = w.wrapping_sub(reserve);
        if avail < len {
            return None;
        }
        let ri = reserve & QUEUE_MASK;
        if !self.storage.is_mirrored() && (QUEUE_CAP - ri) < len {
            return None;
        }

        let ptr = unsafe { self.storage.as_mut_ptr().add(ri) };
        self.reserve.store(reserve.wrapping_add(len), Ordering::Release);
        Some(ptr)
    }

    /// Release `len` bytes previously assigned to completed USB transfers.
    pub fn release_reserved(&self, len: usize) {
        if len == 0 {
            return;
        }
        let r = self.read.load(Ordering::Relaxed);
        self.read.store(r.wrapping_add(len), Ordering::Release);
    }

    /// Roll back the newest reservation when a prepared transfer was not
    /// submitted and therefore never became in-flight.
    pub fn cancel_reserved(&self, len: usize) {
        if len == 0 {
            return;
        }
        let reserve = self.reserve.load(Ordering::Relaxed);
        self.reserve
            .store(reserve.wrapping_sub(len), Ordering::Release);
    }

    /// Reset both indices to zero (call only when no threads are active).
    pub fn reset(&self) {
        self.write.store(0, Ordering::SeqCst);
        self.reserve.store(0, Ordering::SeqCst);
        self.read.store(0, Ordering::SeqCst);
    }
}

impl TransferSource for FrameQueue {
    fn kind_name(&self) -> &'static str {
        "frame-queue"
    }

    fn available_read(&self) -> usize {
        FrameQueue::available_read(self)
    }

    fn available_assign(&self) -> usize {
        FrameQueue::available_assign(self)
    }

    fn reserve_direct_contiguous(&self, len: usize) -> Option<*mut u8> {
        FrameQueue::reserve_direct_contiguous(self, len)
    }

    fn reserve_copy_into(&self, dst: &mut [u8]) -> usize {
        FrameQueue::reserve_copy_into(self, dst)
    }

    fn release_reserved(&self, len: usize) {
        FrameQueue::release_reserved(self, len)
    }

    fn cancel_reserved(&self, len: usize) {
        FrameQueue::cancel_reserved(self, len)
    }
}
