//! serializers working a sequence of objects (pairs, tuples, etc)
use crate::internal::{GenResult, SerializeFn, WriteContext};
use crate::lib::std::io::Write;

/// Applies 2 serializers in sequence
///
/// ```rust
/// use cookie_factory::{gen, sequence::pair, combinator::string};
///
/// let mut buf = [0u8; 100];
///
/// {
///   let (buf, pos) = gen(pair(string("abcd"), string("efgh")), &mut buf[..]).unwrap();
///   assert_eq!(pos, 8);
///   assert_eq!(buf.len(), 100 - 8);
/// }
///
/// assert_eq!(&buf[..8], &b"abcdefgh"[..]);
/// ```
pub fn pair<F, G, W: Write>(first: F, second: G) -> impl SerializeFn<W>
where
    F: SerializeFn<W>,
    G: SerializeFn<W>,
{
    move |out: WriteContext<W>| first(out).and_then(&second)
}

/// Helper trait for the `tuple` combinator
pub trait Tuple<W> {
    fn serialize(&self, w: WriteContext<W>) -> GenResult<W>;
}

impl<W: Write, A: SerializeFn<W>> Tuple<W> for (A,) {
    fn serialize(&self, w: WriteContext<W>) -> GenResult<W> {
        self.0(w)
    }
}

// Generates all the Tuple impls for tuples of arbitrary sizes based on a list of type
// parameters like FnA FnB FnC. It would generate the impl then for (FnA, FnB)
// and (FnA, FnB, FnC).
macro_rules! tuple_trait(
  ($name1:ident, $name2: ident, $($name:ident),*) => (
    tuple_trait!(__impl $name1, $name2; $($name),*);
  );
  (__impl $($name:ident),+; $name1:ident, $($name2:ident),*) => (
    tuple_trait_impl!($($name),+);
    tuple_trait!(__impl $($name),+ , $name1; $($name2),*);
  );
  (__impl $($name:ident),+; $name1:ident) => (
    tuple_trait_impl!($($name),+);
    tuple_trait_impl!($($name),+, $name1);
  );
);

// Generates the impl block for Tuple on tuples or arbitrary sizes based on its
// arguments. Takes a list of type parameters as parameters, e.g. FnA FnB FnC
// and then implements the trait on (FnA, FnB, FnC).
macro_rules! tuple_trait_impl(
  ($($name:ident),+) => (
    impl<W: Write, $($name: SerializeFn<W>),+> Tuple<W> for ( $($name),+ ) {
      fn serialize(&self, w: WriteContext<W>) -> GenResult<W> {
        tuple_trait_inner!(0, self, w, $($name)+)
      }
    }
  );
);

// Generates the inner part of the Tuple::serialize() implementation, which will
// basically look as follows:
//
// let w = self.0(w)?;
// let w = self.1(w)?;
// [...]
// let w = self.N(w)?;
//
// Ok(w)
macro_rules! tuple_trait_inner(
  ($it:tt, $self:expr, $w:ident, $head:ident $($id:ident)+) => ({
    let w = $self.$it($w)?;

    succ!($it, tuple_trait_inner!($self, w, $($id)+))
  });
  ($it:tt, $self:expr, $w:ident, $head:ident) => ({
    let w = $self.$it($w)?;

    Ok(w)
  });
);

// Takes an integer and a macro invocation, and changes the macro invocation
// to take the incremented integer as the first argument
//
// Works for integers between 0 and 19.
#[doc(hidden)]
macro_rules! succ (
  (0, $submac:ident ! ($($rest:tt)*)) => ($submac!(1, $($rest)*));
  (1, $submac:ident ! ($($rest:tt)*)) => ($submac!(2, $($rest)*));
  (2, $submac:ident ! ($($rest:tt)*)) => ($submac!(3, $($rest)*));
  (3, $submac:ident ! ($($rest:tt)*)) => ($submac!(4, $($rest)*));
  (4, $submac:ident ! ($($rest:tt)*)) => ($submac!(5, $($rest)*));
  (5, $submac:ident ! ($($rest:tt)*)) => ($submac!(6, $($rest)*));
  (6, $submac:ident ! ($($rest:tt)*)) => ($submac!(7, $($rest)*));
  (7, $submac:ident ! ($($rest:tt)*)) => ($submac!(8, $($rest)*));
  (8, $submac:ident ! ($($rest:tt)*)) => ($submac!(9, $($rest)*));
  (9, $submac:ident ! ($($rest:tt)*)) => ($submac!(10, $($rest)*));
  (10, $submac:ident ! ($($rest:tt)*)) => ($submac!(11, $($rest)*));
  (11, $submac:ident ! ($($rest:tt)*)) => ($submac!(12, $($rest)*));
  (12, $submac:ident ! ($($rest:tt)*)) => ($submac!(13, $($rest)*));
  (13, $submac:ident ! ($($rest:tt)*)) => ($submac!(14, $($rest)*));
  (14, $submac:ident ! ($($rest:tt)*)) => ($submac!(15, $($rest)*));
  (15, $submac:ident ! ($($rest:tt)*)) => ($submac!(16, $($rest)*));
  (16, $submac:ident ! ($($rest:tt)*)) => ($submac!(17, $($rest)*));
  (17, $submac:ident ! ($($rest:tt)*)) => ($submac!(18, $($rest)*));
  (18, $submac:ident ! ($($rest:tt)*)) => ($submac!(19, $($rest)*));
  (19, $submac:ident ! ($($rest:tt)*)) => ($submac!(20, $($rest)*));
);

tuple_trait!(
    FnA, FnB, FnC, FnD, FnE, FnF, FnG, FnH, FnI, FnJ, FnK, FnL, FnM, FnN, FnO, FnP, FnQ, FnR, FnS,
    FnT, FnU
);

/// Applies multiple serializers in sequence
///
/// Currently tuples up to 20 elements are supported.
///
/// ```rust
/// use cookie_factory::{gen, sequence::tuple, combinator::string, bytes::be_u16};
///
/// let mut buf = [0u8; 100];
///
/// {
///   let (buf, pos) = gen(
///     tuple((
///       string("abcd"),
///       be_u16(0x20),
///       string("efgh"),
///     )),
///     &mut buf[..]
///   ).unwrap();
///   assert_eq!(pos, 10);
///   assert_eq!(buf.len(), 100 - 10);
/// }
///
/// assert_eq!(&buf[..10], &b"abcd\x00\x20efgh"[..]);
/// ```
pub fn tuple<W: Write, List: Tuple<W>>(l: List) -> impl SerializeFn<W> {
    move |w: WriteContext<W>| l.serialize(w)
}

#[cfg(test)]
mod test {
    use super::*;
    use crate::combinator::string;
    use crate::internal::gen_simple;

    #[test]
    fn test_pair_with_cursor() {
        let mut buf = [0u8; 8];

        {
            use crate::lib::std::io::Cursor;

            let cursor = Cursor::new(&mut buf[..]);
            let serializer = pair(string("1234"), string("5678"));

            let cursor = gen_simple(serializer, cursor).unwrap();
            assert_eq!(cursor.position(), 8);
        }

        assert_eq!(&buf[..], b"12345678");
    }

    #[test]
    fn test_tuple() {
        let mut buf = [0u8; 12];

        {
            use crate::lib::std::io::Cursor;

            let cursor = Cursor::new(&mut buf[..]);
            let serializer = tuple((string("1234"), string("5678"), tuple((string("0123"),))));

            let cursor = gen_simple(serializer, cursor).unwrap();
            assert_eq!(cursor.position(), 12);
        }

        assert_eq!(&buf[..], b"123456780123");
    }
}
