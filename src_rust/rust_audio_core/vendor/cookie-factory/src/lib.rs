//! serialization library built with a combinator design similar to nom.
//!
//! Serializers are built up from single purpose serializers, like `slice`
//! to write a raw byte slice, or `be_u16` to write a `u16` integer in big
//! endian form.
//!
//! Those small serializers can then be assembled by using combinators.
//! As an example, `all(["abcd", "efgh", "ijkl"].iter().map(string))(output)`
//! will write `"abcdefghijkl"` to `output`.
#![cfg_attr(not(feature = "std"), no_std)]

#[cfg(not(feature = "std"))]
mod io_compat;

/// lib module necessary to reexport what we need from std in `no_std` mode
pub mod lib {
    #[cfg(feature = "std")]
    pub mod std {
        pub mod io {
            pub use std::io::{Cursor, Error, Result, Seek, SeekFrom, Write};
        }
        pub use std::{cmp, fmt, iter, mem, result, slice};
    }

    #[cfg(not(feature = "std"))]
    pub mod std {
        pub use core::{cmp, iter, mem, result, slice};
        #[macro_use]
        pub use core::fmt;

        pub mod io {
            pub use crate::io_compat::*;
        }
    }
}

#[macro_use]
pub mod gen;

mod internal;
pub use internal::*;
#[cfg(feature = "async")]
pub mod async_bufwriter;
pub mod bytes;
pub mod combinator;
pub mod multi;
pub mod sequence;
