use futures::io::{AsyncWrite, AsyncWriteExt};

pub struct AsyncBufWriter<W: AsyncWrite + Unpin> {
    inner: W,
    buf: Vec<u8>,
    pos: usize,
}

const DEFAULT_BUF_SIZE: usize = 8 * 1024;

impl<W: AsyncWrite + Unpin> AsyncBufWriter<W> {
    pub fn new(inner: W) -> AsyncBufWriter<W> {
        AsyncBufWriter::with_capacity(DEFAULT_BUF_SIZE, inner)
    }

    pub fn with_capacity(capacity: usize, inner: W) -> AsyncBufWriter<W> {
        let buf = vec![0; capacity];
        AsyncBufWriter { inner, buf, pos: 0 }
    }

    pub async fn flush(&mut self) -> std::io::Result<usize> {
        let sz = self.inner.write(&self.buf[..self.pos]).await?;

        // if we did not write everything, move data to the beginning of the
        // buffer
        if sz < self.pos {
            for i in 0..(self.pos - sz) {
                self.buf[i] = self.buf[sz + i]
            }
        }

        self.pos -= sz;

        Ok(sz)
    }

    pub fn remaining(&self) -> usize {
        self.pos
    }

    pub fn into_parts(mut self) -> (W, Vec<u8>) {
        self.buf.truncate(self.pos);
        (self.inner, self.buf)
    }
}

impl<W: AsyncWrite + Unpin> std::io::Write for AsyncBufWriter<W> {
    fn write(&mut self, buf: &[u8]) -> std::io::Result<usize> {
        let sz = (&mut self.buf[self.pos..]).write(buf)?;
        self.pos += sz;
        Ok(sz)
    }

    fn flush(&mut self) -> std::io::Result<()> {
        Ok(())
    }
}

pub async fn gen<W: AsyncWrite + Unpin, F: crate::internal::SerializeFn<AsyncBufWriter<W>>>(
    f: F,
    w: AsyncBufWriter<W>,
) -> Result<(AsyncBufWriter<W>, u64), crate::internal::GenError> {
    match f(crate::internal::WriteContext::from(w)).map(|ctx| ctx.into_inner()) {
        Err(e) => Err(e),
        Ok((mut w, _)) => {
            let sz = w.flush().await?;
            Ok((w, sz as u64))
        }
    }
}
