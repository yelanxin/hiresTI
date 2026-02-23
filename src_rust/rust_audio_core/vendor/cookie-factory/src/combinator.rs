//! basic serializers
use crate::internal::*;
use crate::lib::std::io::Write;

macro_rules! try_write(($out:ident, $len:ident, $data:expr) => (
    match $out.write($data) {
        Err(io)           => Err(GenError::IoError(io)),
        Ok(n) if n < $len => Err(GenError::BufferTooSmall($len - n)),
        Ok(_)             => Ok($out)
    }
));

/// Writes a byte slice to the output
///
/// ```rust
/// use cookie_factory::{gen, combinator::slice};
///
/// let mut buf = [0u8; 100];
///
/// {
///   let (buf, pos) = gen(slice(&b"abcd"[..]), &mut buf[..]).unwrap();
///   assert_eq!(pos, 4);
///   assert_eq!(buf.len(), 100 - 4);
/// }
///
/// assert_eq!(&buf[..4], &b"abcd"[..]);
/// ```
pub fn slice<S: AsRef<[u8]>, W: Write>(data: S) -> impl SerializeFn<W> {
    let len = data.as_ref().len();

    move |mut out: WriteContext<W>| try_write!(out, len, data.as_ref())
}

/// Writes a string slice to the output
///
/// ```rust
/// use cookie_factory::{gen, combinator::string};
///
/// let mut buf = [0u8; 100];
///
/// {
///   let (buf, pos) = gen(string("abcd"), &mut buf[..]).unwrap();
///   assert_eq!(pos, 4);
///   assert_eq!(buf.len(), 100 - 4);
/// }
///
/// assert_eq!(&buf[..4], &b"abcd"[..]);
/// ```
pub fn string<S: AsRef<str>, W: Write>(data: S) -> impl SerializeFn<W> {
    let len = data.as_ref().len();

    move |mut out: WriteContext<W>| try_write!(out, len, data.as_ref().as_bytes())
}

/// Writes an hex string to the output
#[cfg(feature = "std")]
/// ```rust
/// use cookie_factory::{gen, combinator::hex};
///
/// let mut buf = [0u8; 100];
///
/// {
///   let (buf, pos) = gen(hex(0x2A), &mut buf[..]).unwrap();
///   assert_eq!(pos, 2);
///   assert_eq!(buf.len(), 100 - 2);
/// }
///
/// assert_eq!(&buf[..2], &b"2A"[..]);
/// ```
pub fn hex<S: crate::lib::std::fmt::UpperHex, W: Write>(data: S) -> impl SerializeFn<W> {
    move |mut out: WriteContext<W>| match write!(out, "{:X}", data) {
        Err(io) => Err(GenError::IoError(io)),
        Ok(()) => Ok(out),
    }
}

/// Skips over some input bytes without writing anything
///
/// ```rust
/// use cookie_factory::{gen, combinator::skip};
///
/// let mut buf = [0u8; 100];
///
/// let (out, pos) = gen(skip(2), &mut buf[..]).unwrap();
///
/// assert_eq!(pos, 2);
/// assert_eq!(out.len(), 98);
/// ```
pub fn skip<W: Write + Skip>(len: usize) -> impl SerializeFn<W> {
    move |out: WriteContext<W>| W::skip(out, len)
}

/// Applies a serializer if the condition is true
///
/// ```rust
/// use cookie_factory::{gen, combinator::{cond, string}};
///
/// let mut buf = [0u8; 100];
///
/// {
///   let (buf, pos) = gen(cond(true, string("abcd")), &mut buf[..]).unwrap();
///   assert_eq!(pos, 4);
///   assert_eq!(buf.len(), 100 - 4);
/// }
///
/// assert_eq!(&buf[..4], &b"abcd"[..]);
/// ```
pub fn cond<F, W: Write>(condition: bool, f: F) -> impl SerializeFn<W>
where
    F: SerializeFn<W>,
{
    move |out: WriteContext<W>| {
        if condition {
            f(out)
        } else {
            Ok(out)
        }
    }
}

/// Reserves space for the `Before` combinator, applies the `Gen` combinator,
/// then applies the `Before` combinator with the output from `Gen` onto the
/// reserved space.
///
/// ```rust
/// use cookie_factory::{gen, gen_simple, sequence::tuple, combinator::{back_to_the_buffer, string}, bytes::be_u8, bytes::be_u32};
///
/// let mut buf = [0; 9];
/// gen_simple(tuple((
///     back_to_the_buffer(
///         4,
///         move |buf| gen(string("test"), buf),
///         move |buf, len| gen_simple(be_u32(len as u32), buf)
///     ),
///     be_u8(42)
/// )), &mut buf[..]).unwrap();
/// assert_eq!(&buf, &[0, 0, 0, 4, 't' as u8, 'e' as u8, 's' as u8, 't' as u8, 42]);
/// ```
pub fn back_to_the_buffer<W: BackToTheBuffer, Tmp, Gen, Before>(
    reserved: usize,
    gen: Gen,
    before: Before,
) -> impl SerializeFn<W>
where
    Gen: Fn(WriteContext<W>) -> Result<(WriteContext<W>, Tmp), GenError>,
    Before: Fn(WriteContext<W>, Tmp) -> GenResult<W>,
{
    move |w: WriteContext<W>| W::reserve_write_use(w, reserved, &gen, &before)
}

//missing combinators:
//or
//empty
//then
//stream
//length_value
//text print
//text upperhex
//text lowerhex

#[cfg(test)]
mod test {
    use super::*;
    use crate::bytes::{be_u32, be_u8};
    use crate::sequence::tuple;

    #[test]
    fn test_gen_with_length() {
        let mut buf = [0; 8];
        {
            let (len_buf, buf) = buf.split_at_mut(4);
            let (_, pos) = gen(string("test"), buf).unwrap();
            gen(be_u32(pos as u32), len_buf).unwrap();
        }
        assert_eq!(&buf, &[0, 0, 0, 4, b't', b'e', b's', b't']);
    }

    #[test]
    fn test_back_to_the_buffer() {
        let mut buf = [0; 9];

        let new_buf = gen_simple(
            tuple((
                back_to_the_buffer(
                    4,
                    move |buf| gen(string("test"), buf),
                    move |buf, len| gen_simple(be_u32(len as u32), buf),
                ),
                be_u8(42),
            )),
            &mut buf[..],
        )
        .unwrap();

        assert!(new_buf.is_empty());
        assert_eq!(&buf, &[0, 0, 0, 4, b't', b'e', b's', b't', 42]);
    }

    #[cfg(feature = "std")]
    #[test]
    fn test_back_to_the_buffer_vec() {
        let buf = Vec::new();

        let buf = gen_simple(
            tuple((
                back_to_the_buffer(
                    4,
                    move |buf| gen(string("test"), buf),
                    move |buf, len| gen_simple(be_u32(len as u32), buf),
                ),
                be_u8(42),
            )),
            buf,
        )
        .unwrap();

        assert_eq!(&buf[..], &[0, 0, 0, 4, b't', b'e', b's', b't', 42]);
    }

    #[test]
    fn test_back_to_the_buffer_cursor() {
        let mut buf = [0; 9];
        {
            let cursor = crate::lib::std::io::Cursor::new(&mut buf[..]);
            let cursor = gen_simple(
                tuple((
                    back_to_the_buffer(
                        4,
                        move |buf| gen(string("test"), buf),
                        move |buf, len| gen_simple(be_u32(len as u32), buf),
                    ),
                    be_u8(42),
                )),
                cursor,
            )
            .unwrap();
            assert_eq!(cursor.position(), 9);
        }
        assert_eq!(&buf, &[0, 0, 0, 4, b't', b'e', b's', b't', 42]);
    }

    #[test]
    fn test_back_to_the_buffer_cursor_counter() {
        let mut buf = [0; 10];
        {
            let cursor = crate::lib::std::io::Cursor::new(&mut buf[..]);
            let (cursor, pos) = gen(
                tuple((
                    be_u8(64),
                    back_to_the_buffer(
                        4,
                        &move |buf| gen(string("test"), buf),
                        &move |buf, len| gen_simple(be_u32(len as u32), buf),
                    ),
                    be_u8(42),
                )),
                cursor,
            )
            .unwrap();
            assert_eq!(pos, 10);
            assert_eq!(cursor.position(), 10);
        }
        assert_eq!(&buf, &[64, 0, 0, 0, 4, b't', b'e', b's', b't', 42]);
    }
}
