//! main structures and traits used to build serializers
use crate::lib::std::{
    fmt,
    io::{self, Seek as _, SeekFrom, Write},
};

/// Holds the result of serializing functions
///
/// The `Ok` case returns the `Write` used for writing, in the `Err` case an instance of
/// `cookie_factory::GenError` is returned.
pub type GenResult<W> = Result<WriteContext<W>, GenError>;

/// Base type for generator errors
#[derive(Debug)]
pub enum GenError {
    /// Input buffer is too small. Argument is the maximum index that is required
    BufferTooSmall(usize),
    /// We expected to fill the whole buffer but there is some space left
    BufferTooBig(usize),
    /// Operation asked for accessing an invalid index
    InvalidOffset,
    /// IoError returned by Write
    IoError(io::Error),

    /// Allocated for custom errors
    CustomError(u32),
    /// Generator or function not yet implemented
    NotYetImplemented,
}

impl fmt::Display for GenError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{:?}", self)
    }
}

#[cfg(feature = "std")]
impl std::error::Error for GenError {}

impl From<io::Error> for GenError {
    fn from(err: io::Error) -> Self {
        GenError::IoError(err)
    }
}

/// Trait for serializing functions
///
/// Serializing functions take one input `W` that is the target of writing and return an instance
/// of `cookie_factory::GenResult`.
///
/// This trait is implemented for all `Fn(W) -> GenResult<W>`.
pub trait SerializeFn<W>: Fn(WriteContext<W>) -> GenResult<W> {}

impl<W, F: Fn(WriteContext<W>) -> GenResult<W>> SerializeFn<W> for F {}

/// Context around a `Write` impl that is passed through serializing functions
///
/// Currently this only keeps track of the current write position since the start of serialization.
pub struct WriteContext<W> {
    pub write: W,
    pub position: u64,
}

impl<W: Write> From<W> for WriteContext<W> {
    fn from(write: W) -> Self {
        Self { write, position: 0 }
    }
}

impl<W: Write> WriteContext<W> {
    /// Returns the contained `Write` and the current position
    pub fn into_inner(self) -> (W, u64) {
        (self.write, self.position)
    }
}

impl<W: Write> Write for WriteContext<W> {
    fn write(&mut self, data: &[u8]) -> crate::lib::std::io::Result<usize> {
        let amt = self.write.write(data)?;
        self.position += amt as u64;
        Ok(amt)
    }

    #[cfg(feature = "std")]
    fn flush(&mut self) -> io::Result<()> {
        self.write.flush()
    }
}

impl<W: Seek> io::Seek for WriteContext<W> {
    fn seek(&mut self, pos: SeekFrom) -> io::Result<u64> {
        let old_pos = self.write.stream_position()?;
        let new_pos = self.write.seek(pos)?;
        if new_pos >= old_pos {
            self.position += new_pos - old_pos;
        } else {
            self.position -= old_pos - new_pos;
        }
        Ok(new_pos)
    }
}

/// Runs the given serializer `f` with the `Write` impl `w` and returns the result
///
/// This internally wraps `w` in a `WriteContext`, starting at position 0.
///
/// ```rust
/// use cookie_factory::{gen, combinator::slice};
///
/// let mut buf = [0u8; 100];
///
/// {
///   let (buf, pos) = gen(slice(&b"abcd"[..]), &mut buf[..]).unwrap();
///   assert_eq!(buf.len(), 100 - 4);
///   assert_eq!(pos, 4);
/// }
///
/// assert_eq!(&buf[..4], &b"abcd"[..]);
/// ```
pub fn gen<W: Write, F: SerializeFn<W>>(f: F, w: W) -> Result<(W, u64), GenError> {
    f(WriteContext::from(w)).map(|ctx| ctx.into_inner())
}

/// Runs the given serializer `f` with the `Write` impl `w` and returns the updated `w`
///
/// This internally wraps `w` in a `WriteContext`, starting at position 0.
///
/// ```rust
/// use cookie_factory::{gen_simple, combinator::slice};
///
/// let mut buf = [0u8; 100];
///
/// {
///   let buf = gen_simple(slice(&b"abcd"[..]), &mut buf[..]).unwrap();
///   assert_eq!(buf.len(), 100 - 4);
/// }
///
/// assert_eq!(&buf[..4], &b"abcd"[..]);
/// ```
pub fn gen_simple<W: Write, F: SerializeFn<W>>(f: F, w: W) -> Result<W, GenError> {
    f(WriteContext::from(w)).map(|ctx| ctx.into_inner().0)
}

/// Trait for `Write` types that allow skipping over the data
pub trait Skip: Write {
    fn skip(s: WriteContext<Self>, sz: usize) -> GenResult<Self>
    where
        Self: Sized;
}

/// Trait for `Write` types that allow skipping and reserving a slice, then writing some data,
/// then write something in the slice we reserved using the return for our data write.
pub trait BackToTheBuffer: Write {
    fn reserve_write_use<
        Tmp,
        Gen: Fn(WriteContext<Self>) -> Result<(WriteContext<Self>, Tmp), GenError>,
        Before: Fn(WriteContext<Self>, Tmp) -> GenResult<Self>,
    >(
        s: WriteContext<Self>,
        reserved: usize,
        gen: &Gen,
        before: &Before,
    ) -> Result<WriteContext<Self>, GenError>
    where
        Self: Sized;
}

/// Trait for `Seek` types that want to automatically implement `BackToTheBuffer`
pub trait Seek: Write + io::Seek {}
impl Seek for io::Cursor<&mut [u8]> {}

impl<W: Seek> BackToTheBuffer for W {
    fn reserve_write_use<
        Tmp,
        Gen: Fn(WriteContext<Self>) -> Result<(WriteContext<Self>, Tmp), GenError>,
        Before: Fn(WriteContext<Self>, Tmp) -> GenResult<Self>,
    >(
        mut s: WriteContext<Self>,
        reserved: usize,
        gen: &Gen,
        before: &Before,
    ) -> Result<WriteContext<Self>, GenError> {
        let start = s.stream_position()?;
        let begin = s.seek(SeekFrom::Current(reserved as i64))?;
        let (mut buf, tmp) = gen(s)?;
        let end = buf.stream_position()?;
        buf.seek(SeekFrom::Start(start))?;
        let mut buf = before(buf, tmp)?;
        let pos = buf.stream_position()?;
        if pos != begin {
            return Err(GenError::BufferTooBig((begin - pos) as usize));
        }
        buf.seek(SeekFrom::Start(end))?;
        Ok(buf)
    }
}

impl Skip for &mut [u8] {
    fn skip(s: WriteContext<Self>, len: usize) -> Result<WriteContext<Self>, GenError> {
        if s.write.len() < len {
            Err(GenError::BufferTooSmall(len - s.write.len()))
        } else {
            Ok(WriteContext {
                write: &mut s.write[len..],
                position: s.position + len as u64,
            })
        }
    }
}

impl Skip for io::Cursor<&mut [u8]> {
    fn skip(mut s: WriteContext<Self>, len: usize) -> GenResult<Self> {
        let remaining = s
            .write
            .get_ref()
            .len()
            .saturating_sub(s.write.position() as usize);
        if remaining < len {
            Err(GenError::BufferTooSmall(len - remaining))
        } else {
            let cursor_position = s.write.position();
            s.write.set_position(cursor_position + len as u64);
            s.position += len as u64;
            Ok(s)
        }
    }
}

impl BackToTheBuffer for &mut [u8] {
    fn reserve_write_use<
        Tmp,
        Gen: Fn(WriteContext<Self>) -> Result<(WriteContext<Self>, Tmp), GenError>,
        Before: Fn(WriteContext<Self>, Tmp) -> GenResult<Self>,
    >(
        s: WriteContext<Self>,
        reserved: usize,
        gen: &Gen,
        before: &Before,
    ) -> Result<WriteContext<Self>, GenError> {
        let WriteContext {
            write: slice,
            position: original_position,
        } = s;

        let (res, buf) = slice.split_at_mut(reserved);
        let (new_context, tmp) = gen(WriteContext {
            write: buf,
            position: original_position + reserved as u64,
        })?;

        let res = before(
            WriteContext {
                write: res,
                position: original_position,
            },
            tmp,
        )?;

        if !res.write.is_empty() {
            return Err(GenError::BufferTooBig(res.write.len()));
        }

        Ok(new_context)
    }
}

#[cfg(feature = "std")]
impl BackToTheBuffer for Vec<u8> {
    fn reserve_write_use<
        Tmp,
        Gen: Fn(WriteContext<Self>) -> Result<(WriteContext<Self>, Tmp), GenError>,
        Before: Fn(WriteContext<Self>, Tmp) -> GenResult<Self>,
    >(
        s: WriteContext<Self>,
        reserved: usize,
        gen: &Gen,
        before: &Before,
    ) -> Result<WriteContext<Self>, GenError> {
        let WriteContext {
            write: mut vec,
            position: original_position,
        } = s;

        let start_len = vec.len();
        vec.extend(std::iter::repeat(0).take(reserved));

        let (mut new_context, tmp) = gen(WriteContext {
            write: vec,
            position: original_position + reserved as u64,
        })?;

        let tmp_context = before(
            WriteContext {
                write: Vec::new(),
                position: original_position,
            },
            tmp,
        )?;

        let tmp_written = tmp_context.write.len();
        if tmp_written != reserved {
            return Err(GenError::BufferTooBig(reserved - tmp_written));
        }

        // FIXME?: find a way to do that without copying
        // Vec::from_raw_parts + core::mem::forget makes it work, but
        // if `before` writes more than `reserved`, realloc will cause troubles
        new_context.write[start_len..(start_len + reserved)]
            .copy_from_slice(&tmp_context.write[..]);

        Ok(new_context)
    }
}
