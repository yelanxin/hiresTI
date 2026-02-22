//! serializers working on a list of elements (vectors, iterators, etc)
use crate::internal::{SerializeFn, WriteContext};
use crate::lib::std::io::Write;

/// Applies an iterator of serializers of the same type
///
/// ```rust
/// use cookie_factory::{gen, multi::all, combinator::string};
///
/// let mut buf = [0u8; 100];
///
/// let data = vec!["abcd", "efgh", "ijkl"];
/// {
///   let (buf, pos) = gen(all(data.iter().map(string)), &mut buf[..]).unwrap();
///   assert_eq!(pos, 12);
///   assert_eq!(buf.len(), 100 - 12);
/// }
///
/// assert_eq!(&buf[..12], &b"abcdefghijkl"[..]);
/// ```
pub fn all<G, W: Write, It>(values: It) -> impl SerializeFn<W>
where
    G: SerializeFn<W>,
    It: Clone + Iterator<Item = G>,
{
    move |mut out: WriteContext<W>| {
        let it = values.clone();

        for v in it {
            out = v(out)?;
        }

        Ok(out)
    }
}

/// Applies an iterator of serializers of the same type with a separator between each serializer
///
/// ```rust
/// use cookie_factory::{gen, multi::separated_list, combinator::string};
///
/// let mut buf = [0u8; 100];
///
/// let data = vec!["abcd", "efgh", "ijkl"];
/// {
///   let (buf, pos) = gen(separated_list(string(","), data.iter().map(string)), &mut buf[..]).unwrap();
///   assert_eq!(pos, 14);
///   assert_eq!(buf.len(), 100 - 14);
/// }
///
/// assert_eq!(&buf[..14], &b"abcd,efgh,ijkl"[..]);
/// ```
pub fn separated_list<F, G, W: Write, It>(sep: F, values: It) -> impl SerializeFn<W>
where
    F: SerializeFn<W>,
    G: SerializeFn<W>,
    It: Clone + Iterator<Item = G>,
{
    move |mut out: WriteContext<W>| {
        let mut it = values.clone();

        match it.next() {
            None => return Ok(out),
            Some(first) => {
                out = first(out)?;
            }
        }

        for v in it {
            out = sep(out).and_then(v)?;
        }

        Ok(out)
    }
}

/// Applies a generator over an iterator of values, and applies the serializers generated
///
/// ```rust
/// use cookie_factory::{gen, multi::many_ref, combinator::string};
///
/// let mut buf = [0u8; 100];
///
/// let data = vec!["abcd", "efgh", "ijkl"];
/// {
///   let (buf, pos) = gen(many_ref(&data, string), &mut buf[..]).unwrap();
///   assert_eq!(pos, 12);
///   assert_eq!(buf.len(), 100 - 12);
/// }
///
/// assert_eq!(&buf[..12], &b"abcdefghijkl"[..]);
/// ```
pub fn many_ref<E, It, I, F, G, O: Write>(items: I, generator: F) -> impl SerializeFn<O>
where
    It: Iterator<Item = E> + Clone,
    I: IntoIterator<Item = E, IntoIter = It>,
    F: Fn(E) -> G,
    G: SerializeFn<O>,
{
    let items = items.into_iter();
    move |mut out: WriteContext<O>| {
        for item in items.clone() {
            out = generator(item)(out)?;
        }
        Ok(out)
    }
}
