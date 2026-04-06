pub trait TransferSource: Send + Sync {
    /// Human-readable source kind used for diagnostics and staged rollouts.
    fn kind_name(&self) -> &'static str;

    /// Number of bytes currently queued and not yet released by completed
    /// transfers.
    fn available_read(&self) -> usize;

    /// Number of bytes currently queued but not yet assigned to an in-flight
    /// USB transfer.
    fn available_assign(&self) -> usize;

    /// Reserve a contiguous region for direct libusb submission.
    fn reserve_direct_contiguous(&self, len: usize) -> Option<*mut u8>;

    /// Copy bytes from the next unassigned region into a scratch buffer.
    fn reserve_copy_into(&self, dst: &mut [u8]) -> usize;

    /// Release bytes after a transfer completes.
    fn release_reserved(&self, len: usize);

    /// Roll back bytes reserved for a transfer that never became in-flight.
    fn cancel_reserved(&self, len: usize);
}
