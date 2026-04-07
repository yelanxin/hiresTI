use std::collections::VecDeque;
use std::sync::{Arc, Mutex};

use super::source::TransferSource;

struct QueueEntry {
    data: Box<[u8]>,
    reserved: usize,
    released: usize,
}

impl QueueEntry {
    #[inline]
    fn size(&self) -> usize {
        self.data.len()
    }

    #[inline]
    fn remaining_unassigned(&self) -> usize {
        self.size().saturating_sub(self.reserved)
    }

    #[inline]
    fn remaining_unreleased(&self) -> usize {
        self.size().saturating_sub(self.released)
    }
}

#[derive(Default)]
struct Inner {
    entries: VecDeque<QueueEntry>,
    queued_bytes: usize,
    unassigned_bytes: usize,
    enqueue_count: u64,
}

pub struct OwnedBufferQueue {
    cap_bytes: usize,
    inner: Mutex<Inner>,
}

impl OwnedBufferQueue {
    pub fn new(cap_bytes: usize) -> Arc<Self> {
        Arc::new(Self {
            cap_bytes: cap_bytes.max(1),
            inner: Mutex::new(Inner::default()),
        })
    }

    pub fn available_write(&self) -> usize {
        self.cap_bytes.saturating_sub(self.available_read())
    }

    pub fn push_bytes(&self, data: Vec<u8>) -> Result<(), Vec<u8>> {
        if data.is_empty() {
            return Ok(());
        }

        let mut inner = self.inner.lock().unwrap_or_else(|e| e.into_inner());
        if inner.queued_bytes.saturating_add(data.len()) > self.cap_bytes {
            return Err(data);
        }

        inner.enqueue_count = inner.enqueue_count.saturating_add(1);
        let enqueue_count = inner.enqueue_count;
        inner.queued_bytes = inner.queued_bytes.saturating_add(data.len());
        inner.unassigned_bytes = inner.unassigned_bytes.saturating_add(data.len());
        inner.entries.push_back(QueueEntry {
            data: data.into_boxed_slice(),
            reserved: 0,
            released: 0,
        });

        if enqueue_count <= 4 || enqueue_count % 2048 == 0 {
            eprintln!(
                "usb-audio: owned queue enqueue #{} size={} queued={} unassigned={}",
                enqueue_count,
                inner.entries.back().map(|entry| entry.size()).unwrap_or(0),
                inner.queued_bytes,
                inner.unassigned_bytes,
            );
        }

        Ok(())
    }
}

impl TransferSource for OwnedBufferQueue {
    fn kind_name(&self) -> &'static str {
        "owned-buffer-queue"
    }

    fn available_read(&self) -> usize {
        let inner = self.inner.lock().unwrap_or_else(|e| e.into_inner());
        inner.queued_bytes
    }

    fn available_assign(&self) -> usize {
        let inner = self.inner.lock().unwrap_or_else(|e| e.into_inner());
        inner.unassigned_bytes
    }

    fn reserve_direct_contiguous(&self, len: usize) -> Option<*mut u8> {
        if len == 0 {
            return None;
        }

        let mut inner = self.inner.lock().unwrap_or_else(|e| e.into_inner());
        if inner.unassigned_bytes < len {
            return None;
        }

        let entry = inner
            .entries
            .iter_mut()
            .find(|entry| entry.remaining_unassigned() > 0)?;
        if entry.remaining_unassigned() < len {
            return None;
        }

        let ptr = unsafe { entry.data.as_mut_ptr().add(entry.reserved) };
        entry.reserved = entry.reserved.saturating_add(len);
        inner.unassigned_bytes = inner.unassigned_bytes.saturating_sub(len);
        Some(ptr)
    }

    fn reserve_copy_into(&self, dst: &mut [u8]) -> usize {
        if dst.is_empty() {
            return 0;
        }

        let mut inner = self.inner.lock().unwrap_or_else(|e| e.into_inner());
        let mut remaining = dst.len().min(inner.unassigned_bytes);
        if remaining == 0 {
            return 0;
        }

        let mut written = 0usize;
        for entry in inner.entries.iter_mut() {
            let avail = entry.remaining_unassigned();
            if avail == 0 {
                continue;
            }
            let take = avail.min(remaining);
            let start = entry.reserved;
            let end = start + take;
            dst[written..written + take].copy_from_slice(&entry.data[start..end]);
            entry.reserved = end;
            written += take;
            remaining -= take;
            if remaining == 0 {
                break;
            }
        }

        inner.unassigned_bytes = inner.unassigned_bytes.saturating_sub(written);
        written
    }

    fn release_reserved(&self, len: usize) {
        if len == 0 {
            return;
        }

        let mut inner = self.inner.lock().unwrap_or_else(|e| e.into_inner());
        let mut remaining = len.min(inner.queued_bytes);
        while remaining > 0 {
            let Some(front) = inner.entries.front_mut() else {
                break;
            };
            let (take, should_pop) = {
                let releasable = front.reserved.saturating_sub(front.released);
                let take = releasable.min(remaining);
                front.released = front.released.saturating_add(take);
                (take, front.remaining_unreleased() == 0)
            };
            inner.queued_bytes = inner.queued_bytes.saturating_sub(take);
            remaining -= take;
            if should_pop {
                inner.entries.pop_front();
            }
        }
    }

    fn cancel_reserved(&self, len: usize) {
        if len == 0 {
            return;
        }

        let mut inner = self.inner.lock().unwrap_or_else(|e| e.into_inner());
        let mut remaining = len.min(self.cap_bytes.saturating_sub(inner.unassigned_bytes));
        for idx in (0..inner.entries.len()).rev() {
            let take = {
                let entry = &mut inner.entries[idx];
                let cancellable = entry.reserved.saturating_sub(entry.released);
                let take = cancellable.min(remaining);
                entry.reserved = entry.reserved.saturating_sub(take);
                take
            };
            inner.unassigned_bytes = inner.unassigned_bytes.saturating_add(take);
            remaining -= take;
            if remaining == 0 {
                break;
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::usb_audio::FrameQueue;

    #[test]
    fn owned_queue_direct_and_release() {
        let q = OwnedBufferQueue::new(FrameQueue::capacity_bytes());
        q.push_bytes(vec![1u8, 2, 3, 4]).unwrap();
        assert_eq!(q.available_read(), 4);
        let ptr = q.reserve_direct_contiguous(4).unwrap();
        let view = unsafe { std::slice::from_raw_parts(ptr as *const u8, 4) };
        assert_eq!(view, &[1, 2, 3, 4]);
        q.release_reserved(4);
        assert_eq!(q.available_read(), 0);
    }
}
