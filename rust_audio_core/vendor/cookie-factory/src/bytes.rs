//! bytes and numbers related serialization functions
use crate::internal::{GenError, SerializeFn, WriteContext};
use crate::lib::std::io::Write;

macro_rules! try_write(($out:ident, $len:ident, $data:expr) => (
    match $out.write($data) {
        Err(io)           => Err(GenError::IoError(io)),
        Ok(n) if n < $len => Err(GenError::BufferTooSmall($len - n)),
        Ok(_)             => Ok($out)
    }
));

/// Writes an `u8` to the output
///
/// ```rust
/// use cookie_factory::{gen, bytes::be_u8};
///
/// let mut buf = [0u8; 100];
///
/// {
///   let (buf, pos) = gen(be_u8(1u8), &mut buf[..]).unwrap();
///   assert_eq!(pos, 1);
///   assert_eq!(buf.len(), 100 - 1);
/// }
///
/// assert_eq!(&buf[..1], &[1u8][..]);
/// ```
pub fn be_u8<W: Write>(i: u8) -> impl SerializeFn<W> {
    let len = 1;

    move |mut out: WriteContext<W>| try_write!(out, len, &i.to_be_bytes()[..])
}

/// Writes an `u16` in big endian byte order to the output
///
/// ```rust
/// use cookie_factory::{gen, bytes::be_u16};
///
/// let mut buf = [0u8; 100];
///
/// {
///   let (buf, pos) = gen(be_u16(1u16), &mut buf[..]).unwrap();
///   assert_eq!(pos, 2);
///   assert_eq!(buf.len(), 100 - 2);
/// }
///
/// assert_eq!(&buf[..2], &[0u8, 1u8][..]);
/// ```
pub fn be_u16<W: Write>(i: u16) -> impl SerializeFn<W> {
    let len = 2;

    move |mut out: WriteContext<W>| try_write!(out, len, &i.to_be_bytes()[..])
}

/// Writes the lower 24 bit of an `u32` in big endian byte order to the output
///
/// ```rust
/// use cookie_factory::{gen, bytes::be_u24};
///
/// let mut buf = [0u8; 100];
///
/// {
///   let (buf, pos) = gen(be_u24(1u32), &mut buf[..]).unwrap();
///   assert_eq!(pos, 3);
///   assert_eq!(buf.len(), 100 - 3);
/// }
///
/// assert_eq!(&buf[..3], &[0u8, 0u8, 1u8][..]);
/// ```
pub fn be_u24<W: Write>(i: u32) -> impl SerializeFn<W> {
    let len = 3;

    move |mut out: WriteContext<W>| try_write!(out, len, &i.to_be_bytes()[1..])
}

/// Writes an `u32` in big endian byte order to the output
///
/// ```rust
/// use cookie_factory::{gen, bytes::be_u32};
///
/// let mut buf = [0u8; 100];
///
/// {
///   let (buf, pos) = gen(be_u32(1u32), &mut buf[..]).unwrap();
///   assert_eq!(pos, 4);
///   assert_eq!(buf.len(), 100 - 4);
/// }
///
/// assert_eq!(&buf[..4], &[0u8, 0u8, 0u8, 1u8][..]);
/// ```
pub fn be_u32<W: Write>(i: u32) -> impl SerializeFn<W> {
    let len = 4;

    move |mut out: WriteContext<W>| try_write!(out, len, &i.to_be_bytes()[..])
}

/// Writes an `u64` in big endian byte order to the output
///
/// ```rust
/// use cookie_factory::{gen, bytes::be_u64};
///
/// let mut buf = [0u8; 100];
///
/// {
///   let (buf, pos) = gen(be_u64(1u64), &mut buf[..]).unwrap();
///   assert_eq!(pos, 8);
///   assert_eq!(buf.len(), 100 - 8);
/// }
///
/// assert_eq!(&buf[..8], &[0u8, 0u8, 0u8, 0u8, 0u8, 0u8, 0u8, 1u8][..]);
/// ```
pub fn be_u64<W: Write>(i: u64) -> impl SerializeFn<W> {
    let len = 8;

    move |mut out: WriteContext<W>| try_write!(out, len, &i.to_be_bytes()[..])
}

/// Writes an `i8` to the output
///
/// ```rust
/// use cookie_factory::{gen, bytes::be_i8};
///
/// let mut buf = [0u8; 100];
///
/// {
///   let (buf, pos) = gen(be_i8(1i8), &mut buf[..]).unwrap();
///   assert_eq!(pos, 1);
///   assert_eq!(buf.len(), 100 - 1);
/// }
///
/// assert_eq!(&buf[..1], &[1u8][..]);
/// ```
pub fn be_i8<W: Write>(i: i8) -> impl SerializeFn<W> {
    be_u8(i as u8)
}

/// Writes an `i16` in big endian byte order to the output
///
/// ```rust
/// use cookie_factory::{gen, bytes::be_i16};
///
/// let mut buf = [0u8; 100];
///
/// {
///   let (buf, pos) = gen(be_i16(1i16), &mut buf[..]).unwrap();
///   assert_eq!(pos, 2);
///   assert_eq!(buf.len(), 100 - 2);
/// }
///
/// assert_eq!(&buf[..2], &[0u8, 1u8][..]);
/// ```
pub fn be_i16<W: Write>(i: i16) -> impl SerializeFn<W> {
    be_u16(i as u16)
}

/// Writes the lower 24 bit of an `i32` in big endian byte order to the output
///
/// ```rust
/// use cookie_factory::{gen, bytes::be_i24};
///
/// let mut buf = [0u8; 100];
///
/// {
///   let (buf, pos) = gen(be_i24(1i32), &mut buf[..]).unwrap();
///   assert_eq!(pos, 3);
///   assert_eq!(buf.len(), 100 - 3);
/// }
///
/// assert_eq!(&buf[..3], &[0u8, 0u8, 1u8][..]);
/// ```
pub fn be_i24<W: Write>(i: i32) -> impl SerializeFn<W> {
    be_u24(i as u32)
}

/// Writes an `i32` in big endian byte order to the output
///
/// ```rust
/// use cookie_factory::{gen, bytes::be_i32};
///
/// let mut buf = [0u8; 100];
///
/// {
///   let (buf, pos) = gen(be_i32(1i32), &mut buf[..]).unwrap();
///   assert_eq!(pos, 4);
///   assert_eq!(buf.len(), 100 - 4);
/// }
///
/// assert_eq!(&buf[..4], &[0u8, 0u8, 0u8, 1u8][..]);
/// ```
pub fn be_i32<W: Write>(i: i32) -> impl SerializeFn<W> {
    be_u32(i as u32)
}

/// Writes an `i64` in big endian byte order to the output
///
/// ```rust
/// use cookie_factory::{gen, bytes::be_i64};
///
/// let mut buf = [0u8; 100];
///
/// {
///   let (buf, pos) = gen(be_i64(1i64), &mut buf[..]).unwrap();
///   assert_eq!(pos, 8);
///   assert_eq!(buf.len(), 100 - 8);
/// }
///
/// assert_eq!(&buf[..8], &[0u8, 0u8, 0u8, 0u8, 0u8, 0u8, 0u8, 1u8][..]);
/// ```
pub fn be_i64<W: Write>(i: i64) -> impl SerializeFn<W> {
    be_u64(i as u64)
}

/// Writes an `f32` in big endian byte order to the output
///
/// ```rust
/// use cookie_factory::{gen, bytes::be_f32};
///
/// let mut buf = [0u8; 100];
///
/// {
///   let (buf, pos) = gen(be_f32(1.0f32), &mut buf[..]).unwrap();
///   assert_eq!(pos, 4);
///   assert_eq!(buf.len(), 100 - 4);
/// }
///
/// assert_eq!(&buf[..4], &[63u8, 128u8, 0u8, 0u8][..]);
/// ```
pub fn be_f32<W: Write>(i: f32) -> impl SerializeFn<W> {
    be_u32(i.to_bits())
}

/// Writes an `f64` in big endian byte order to the output
///
/// ```rust
/// use cookie_factory::{gen, bytes::be_f64};
///
/// let mut buf = [0u8; 100];
///
/// {
///   let (buf, pos) = gen(be_f64(1.0f64), &mut buf[..]).unwrap();
///   assert_eq!(pos, 8);
///   assert_eq!(buf.len(), 100 - 8);
/// }
///
/// assert_eq!(&buf[..8], &[63u8, 240u8, 0u8, 0u8, 0u8, 0u8, 0u8, 0u8][..]);
/// ```
pub fn be_f64<W: Write>(i: f64) -> impl SerializeFn<W> {
    be_u64(i.to_bits())
}

/// Writes an `u8` to the output
///
/// ```rust
/// use cookie_factory::{gen, bytes::le_u8};
///
/// let mut buf = [0u8; 100];
///
/// {
///   let (buf, pos) = gen(le_u8(1u8), &mut buf[..]).unwrap();
///   assert_eq!(pos, 1);
///   assert_eq!(buf.len(), 100 - 1);
/// }
///
/// assert_eq!(&buf[..1], &[1u8][..]);
/// ```
pub fn le_u8<W: Write>(i: u8) -> impl SerializeFn<W> {
    let len = 1;

    move |mut out: WriteContext<W>| try_write!(out, len, &i.to_le_bytes()[..])
}

/// Writes an `u16` in little endian byte order to the output
///
/// ```rust
/// use cookie_factory::{gen, bytes::le_u16};
///
/// let mut buf = [0u8; 100];
///
/// {
///   let (buf, pos) = gen(le_u16(1u16), &mut buf[..]).unwrap();
///   assert_eq!(pos, 2);
///   assert_eq!(buf.len(), 100 - 2);
/// }
///
/// assert_eq!(&buf[..2], &[1u8, 0u8][..]);
/// ```
pub fn le_u16<W: Write>(i: u16) -> impl SerializeFn<W> {
    let len = 2;

    move |mut out: WriteContext<W>| try_write!(out, len, &i.to_le_bytes()[..])
}

/// Writes the lower 24 bit of an `u32` in little endian byte order to the output
///
/// ```rust
/// use cookie_factory::{gen, bytes::le_u24};
///
/// let mut buf = [0u8; 100];
///
/// {
///   let (buf, pos) = gen(le_u24(1u32), &mut buf[..]).unwrap();
///   assert_eq!(pos, 3);
///   assert_eq!(buf.len(), 100 - 3);
/// }
///
/// assert_eq!(&buf[..3], &[1u8, 0u8, 0u8][..]);
/// ```
pub fn le_u24<W: Write>(i: u32) -> impl SerializeFn<W> {
    let len = 3;

    move |mut out: WriteContext<W>| try_write!(out, len, &i.to_le_bytes()[0..3])
}

/// Writes an `u32` in little endian byte order to the output
///
/// ```rust
/// use cookie_factory::{gen, bytes::le_u32};
///
/// let mut buf = [0u8; 100];
///
/// {
///   let (buf, pos) = gen(le_u32(1u32), &mut buf[..]).unwrap();
///   assert_eq!(pos, 4);
///   assert_eq!(buf.len(), 100 - 4);
/// }
///
/// assert_eq!(&buf[..4], &[1u8, 0u8, 0u8, 0u8][..]);
/// ```
pub fn le_u32<W: Write>(i: u32) -> impl SerializeFn<W> {
    let len = 4;

    move |mut out: WriteContext<W>| try_write!(out, len, &i.to_le_bytes()[..])
}

/// Writes an `u64` in little endian byte order to the output
///
/// ```rust
/// use cookie_factory::{gen, bytes::le_u64};
///
/// let mut buf = [0u8; 100];
///
/// {
///   let (buf, pos) = gen(le_u64(1u64), &mut buf[..]).unwrap();
///   assert_eq!(pos, 8);
///   assert_eq!(buf.len(), 100 - 8);
/// }
///
/// assert_eq!(&buf[..8], &[1u8, 0u8, 0u8, 0u8, 0u8, 0u8, 0u8, 0u8][..]);
/// ```
pub fn le_u64<W: Write>(i: u64) -> impl SerializeFn<W> {
    let len = 8;

    move |mut out: WriteContext<W>| try_write!(out, len, &i.to_le_bytes()[..])
}

/// Writes an `i8` to the output
///
/// ```rust
/// use cookie_factory::{gen, bytes::le_i8};
///
/// let mut buf = [0u8; 100];
///
/// {
///   let (buf, pos) = gen(le_i8(1i8), &mut buf[..]).unwrap();
///   assert_eq!(pos, 1);
///   assert_eq!(buf.len(), 100 - 1);
/// }
///
/// assert_eq!(&buf[..1], &[1u8][..]);
/// ```
pub fn le_i8<W: Write>(i: i8) -> impl SerializeFn<W> {
    le_u8(i as u8)
}

/// Writes an `o16` in little endian byte order to the output
///
/// ```rust
/// use cookie_factory::{gen, bytes::le_i16};
///
/// let mut buf = [0u8; 100];
///
/// {
///   let (buf, pos) = gen(le_i16(1i16), &mut buf[..]).unwrap();
///   assert_eq!(pos, 2);
///   assert_eq!(buf.len(), 100 - 2);
/// }
///
/// assert_eq!(&buf[..2], &[1u8, 0u8][..]);
/// ```
pub fn le_i16<W: Write>(i: i16) -> impl SerializeFn<W> {
    le_u16(i as u16)
}

/// Writes the lower 24 bit of an `i32` in little endian byte order to the output
///
/// ```rust
/// use cookie_factory::{gen, bytes::le_i24};
///
/// let mut buf = [0u8; 100];
///
/// {
///   let (buf, pos) = gen(le_i24(1i32), &mut buf[..]).unwrap();
///   assert_eq!(pos, 3);
///   assert_eq!(buf.len(), 100 - 3);
/// }
///
/// assert_eq!(&buf[..3], &[1u8, 0u8, 0u8][..]);
/// ```
pub fn le_i24<W: Write>(i: i32) -> impl SerializeFn<W> {
    le_u24(i as u32)
}

/// Writes an `i32` in little endian byte order to the output
///
/// ```rust
/// use cookie_factory::{gen, bytes::le_i32};
///
/// let mut buf = [0u8; 100];
///
/// {
///   let (buf, pos) = gen(le_i32(1i32), &mut buf[..]).unwrap();
///   assert_eq!(pos, 4);
///   assert_eq!(buf.len(), 100 - 4);
/// }
///
/// assert_eq!(&buf[..4], &[1u8, 0u8, 0u8, 0u8][..]);
/// ```
pub fn le_i32<W: Write>(i: i32) -> impl SerializeFn<W> {
    le_u32(i as u32)
}

/// Writes an `i64` in little endian byte order to the output
///
/// ```rust
/// use cookie_factory::{gen, bytes::le_i64};
///
/// let mut buf = [0u8; 100];
///
/// {
///   let (buf, pos) = gen(le_i64(1i64), &mut buf[..]).unwrap();
///   assert_eq!(pos, 8);
///   assert_eq!(buf.len(), 100 - 8);
/// }
///
/// assert_eq!(&buf[..8], &[1u8, 0u8, 0u8, 0u8, 0u8, 0u8, 0u8, 0u8][..]);
/// ```
pub fn le_i64<W: Write>(i: i64) -> impl SerializeFn<W> {
    le_u64(i as u64)
}

/// Writes an `f32` in little endian byte order to the output
///
/// ```rust
/// use cookie_factory::{gen, bytes::le_f32};
///
/// let mut buf = [0u8; 100];
///
/// {
///   let (buf, pos) = gen(le_f32(1.0f32), &mut buf[..]).unwrap();
///   assert_eq!(pos, 4);
///   assert_eq!(buf.len(), 100 - 4);
/// }
///
/// assert_eq!(&buf[..4], &[0u8, 0u8, 128u8, 63u8][..]);
/// ```
pub fn le_f32<W: Write>(i: f32) -> impl SerializeFn<W> {
    le_u32(i.to_bits())
}

/// Writes an `f64` in little endian byte order to the output
///
/// ```rust
/// use cookie_factory::{gen, bytes::le_f64};
///
/// let mut buf = [0u8; 100];
///
/// {
///   let (buf, pos) = gen(le_f64(1.0f64), &mut buf[..]).unwrap();
///   assert_eq!(pos, 8);
///   assert_eq!(buf.len(), 100 - 8);
/// }
///
/// assert_eq!(&buf[..8], &[0u8, 0u8, 0u8, 0u8, 0u8, 0u8, 240u8, 63u8][..]);
/// ```
pub fn le_f64<W: Write>(i: f64) -> impl SerializeFn<W> {
    le_u64(i.to_bits())
}

/// Writes an `u8` to the output
///
/// ```rust
/// use cookie_factory::{gen, bytes::ne_u8};
///
/// let mut buf = [0u8; 100];
///
/// {
///   let (buf, pos) = gen(ne_u8(1u8), &mut buf[..]).unwrap();
///   assert_eq!(pos, 1);
///   assert_eq!(buf.len(), 100 - 1);
/// }
///
/// assert_eq!(&buf[..1], &[1u8][..]);
/// ```
pub fn ne_u8<W: Write>(i: u8) -> impl SerializeFn<W> {
    let len = 1;

    move |mut out: WriteContext<W>| try_write!(out, len, &i.to_ne_bytes()[..])
}

/// Writes an `u16` in native byte order to the output
///
/// ```rust
/// use cookie_factory::{gen, bytes::ne_u16};
///
/// let mut buf = [0u8; 100];
///
/// {
///   let (buf, pos) = gen(ne_u16(1u16), &mut buf[..]).unwrap();
///   assert_eq!(pos, 2);
///   assert_eq!(buf.len(), 100 - 2);
/// }
///
/// #[cfg(target_endian = "big")]
/// assert_eq!(&buf[..2], &[0u8, 1u8][..]);
/// #[cfg(target_endian = "litte")]
/// assert_eq!(&buf[..2], &[1u8, 0u8][..]);
/// ```
pub fn ne_u16<W: Write>(i: u16) -> impl SerializeFn<W> {
    let len = 2;

    move |mut out: WriteContext<W>| try_write!(out, len, &i.to_ne_bytes()[..])
}

/// Writes the lower 24 bit of an `u32` in native byte order to the output
///
/// ```rust
/// use cookie_factory::{gen, bytes::ne_u24};
///
/// let mut buf = [0u8; 100];
///
/// {
///   let (buf, pos) = gen(ne_u24(1u32), &mut buf[..]).unwrap();
///   assert_eq!(pos, 3);
///   assert_eq!(buf.len(), 100 - 3);
/// }
///
/// #[cfg(target_endian = "big")]
/// assert_eq!(&buf[..3], &[0u8, 0u8, 1u8][..]);
/// #[cfg(target_endian = "litte")]
/// assert_eq!(&buf[..3], &[1u8, 0u8, 0u8][..]);
/// ```
pub fn ne_u24<W: Write>(i: u32) -> impl SerializeFn<W> {
    let len = 3;

    move |mut out: WriteContext<W>| try_write!(out, len, &i.to_ne_bytes()[1..])
}

/// Writes an `u32` in native byte order to the output
///
/// ```rust
/// use cookie_factory::{gen, bytes::ne_u32};
///
/// let mut buf = [0u8; 100];
///
/// {
///   let (buf, pos) = gen(ne_u32(1u32), &mut buf[..]).unwrap();
///   assert_eq!(pos, 4);
///   assert_eq!(buf.len(), 100 - 4);
/// }
///
/// #[cfg(target_endian = "big")]
/// assert_eq!(&buf[..4], &[0u8, 0u8, 0u8, 1u8][..]);
/// #[cfg(target_endian = "litte")]
/// assert_eq!(&buf[..4], &[1u8, 0u8, 0u8, 0u8][..]);
/// ```
pub fn ne_u32<W: Write>(i: u32) -> impl SerializeFn<W> {
    let len = 4;

    move |mut out: WriteContext<W>| try_write!(out, len, &i.to_ne_bytes()[..])
}

/// Writes an `u64` in native byte order to the output
///
/// ```rust
/// use cookie_factory::{gen, bytes::ne_u64};
///
/// let mut buf = [0u8; 100];
///
/// {
///   let (buf, pos) = gen(ne_u64(1u64), &mut buf[..]).unwrap();
///   assert_eq!(pos, 8);
///   assert_eq!(buf.len(), 100 - 8);
/// }
///
/// #[cfg(target_endian = "big")]
/// assert_eq!(&buf[..8], &[0u8, 0u8, 0u8, 0u8, 0u8, 0u8, 0u8, 1u8][..]);
/// #[cfg(target_endian = "litte")]
/// assert_eq!(&buf[..8], &[1u8, 0u8, 0u8, 0u8, 0u8, 0u8, 0u8, 0u8][..]);
/// ```
pub fn ne_u64<W: Write>(i: u64) -> impl SerializeFn<W> {
    let len = 8;

    move |mut out: WriteContext<W>| try_write!(out, len, &i.to_ne_bytes()[..])
}

/// Writes an `i8` to the output
///
/// ```rust
/// use cookie_factory::{gen, bytes::ne_i8};
///
/// let mut buf = [0u8; 100];
///
/// {
///   let (buf, pos) = gen(ne_i8(1i8), &mut buf[..]).unwrap();
///   assert_eq!(pos, 1);
///   assert_eq!(buf.len(), 100 - 1);
/// }
///
/// assert_eq!(&buf[..1], &[1u8][..]);
/// ```
pub fn ne_i8<W: Write>(i: i8) -> impl SerializeFn<W> {
    ne_u8(i as u8)
}

/// Writes an `i16` in native byte order to the output
///
/// ```rust
/// use cookie_factory::{gen, bytes::ne_i16};
///
/// let mut buf = [0u8; 100];
///
/// {
///   let (buf, pos) = gen(ne_i16(1i16), &mut buf[..]).unwrap();
///   assert_eq!(pos, 2);
///   assert_eq!(buf.len(), 100 - 2);
/// }
///
/// #[cfg(target_endian = "big")]
/// assert_eq!(&buf[..2], &[0u8, 1u8][..]);
/// #[cfg(target_endian = "litte")]
/// assert_eq!(&buf[..2], &[1u8, 0u8][..]);
/// ```
pub fn ne_i16<W: Write>(i: i16) -> impl SerializeFn<W> {
    ne_u16(i as u16)
}

/// Writes the lower 24 bit of an `i32` in native byte order to the output
///
/// ```rust
/// use cookie_factory::{gen, bytes::ne_i24};
///
/// let mut buf = [0u8; 100];
///
/// {
///   let (buf, pos) = gen(ne_i24(1i32), &mut buf[..]).unwrap();
///   assert_eq!(pos, 3);
///   assert_eq!(buf.len(), 100 - 3);
/// }
///
/// #[cfg(target_endian = "big")]
/// assert_eq!(&buf[..3], &[0u8, 0u8, 1u8][..]);
/// #[cfg(target_endian = "litte")]
/// assert_eq!(&buf[..3], &[1u8, 0u8, 0u8][..]);
/// ```
pub fn ne_i24<W: Write>(i: i32) -> impl SerializeFn<W> {
    ne_u24(i as u32)
}

/// Writes an `i32` in native byte order to the output
///
/// ```rust
/// use cookie_factory::{gen, bytes::ne_i32};
///
/// let mut buf = [0u8; 100];
///
/// {
///   let (buf, pos) = gen(ne_i32(1i32), &mut buf[..]).unwrap();
///   assert_eq!(pos, 4);
///   assert_eq!(buf.len(), 100 - 4);
/// }
///
/// #[cfg(target_endian = "big")]
/// assert_eq!(&buf[..4], &[0u8, 0u8, 0u8, 1u8][..]);
/// #[cfg(target_endian = "litte")]
/// assert_eq!(&buf[..4], &[1u8, 0u8, 0u8, 0u8][..]);
/// ```
pub fn ne_i32<W: Write>(i: i32) -> impl SerializeFn<W> {
    ne_u32(i as u32)
}

/// Writes an `i64` in native byte order to the output
///
/// ```rust
/// use cookie_factory::{gen, bytes::ne_i64};
///
/// let mut buf = [0u8; 100];
///
/// {
///   let (buf, pos) = gen(ne_i64(1i64), &mut buf[..]).unwrap();
///   assert_eq!(pos, 8);
///   assert_eq!(buf.len(), 100 - 8);
/// }
///
/// #[cfg(target_endian = "big")]
/// assert_eq!(&buf[..8], &[0u8, 0u8, 0u8, 0u8, 0u8, 0u8, 0u8, 1u8][..]);
/// #[cfg(target_endian = "litte")]
/// assert_eq!(&buf[..8], &[1u8, 0u8, 0u8, 0u8, 0u8, 0u8, 0u8, 0u8][..]);
/// ```
pub fn ne_i64<W: Write>(i: i64) -> impl SerializeFn<W> {
    ne_u64(i as u64)
}

/// Writes an `f32` in native byte order to the output
///
/// ```rust
/// use cookie_factory::{gen, bytes::ne_f32};
///
/// let mut buf = [0u8; 100];
///
/// {
///   let (buf, pos) = gen(ne_f32(1.0f32), &mut buf[..]).unwrap();
///   assert_eq!(pos, 4);
///   assert_eq!(buf.len(), 100 - 4);
/// }
///
/// #[cfg(target_endian = "big")]
/// assert_eq!(&buf[..4], &[63u8, 128u8, 0u8, 0u8][..]);
/// #[cfg(target_endian = "little")]
/// assert_eq!(&buf[..4], &[0u8, 0u8, 128u8, 63u8][..]);
/// ```
pub fn ne_f32<W: Write>(i: f32) -> impl SerializeFn<W> {
    ne_u32(i.to_bits())
}

/// Writes an `f64` in native byte order to the output
///
/// ```rust
/// use cookie_factory::{gen, bytes::ne_f64};
///
/// let mut buf = [0u8; 100];
///
/// {
///   let (buf, pos) = gen(ne_f64(1.0f64), &mut buf[..]).unwrap();
///   assert_eq!(pos, 8);
///   assert_eq!(buf.len(), 100 - 8);
/// }
///
/// #[cfg(target_endian = "big")]
/// assert_eq!(&buf[..8], &[63u8, 240u8, 0u8, 0u8, 0u8, 0u8, 0u8, 0u8][..]);
/// #[cfg(target_endian = "little")]
/// assert_eq!(&buf[..8], &[0u8, 0u8, 0u8, 0u8, 0u8, 0u8, 240u8, 63u8][..]);
/// ```
pub fn ne_f64<W: Write>(i: f64) -> impl SerializeFn<W> {
    ne_u64(i.to_bits())
}
