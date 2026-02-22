//! Error type which can be returned by some [`OptionOperations`].

#[cfg(feature = "std")]
use std::{error, fmt};

// Required for doc
#[allow(unused)]
use crate::OptionOperations;

/// Error type which can be returned by some [`OptionOperations`].
#[derive(Copy, Clone, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum Error {
    /// Division by zero attempted with an [`OptionOperations`].
    DivisionByZero,
    /// An [`OptionOperations`] overflowed.
    Overflow,
}

impl Error {
    /// Returns `true` if this [`Error`] results from a division by zero.
    #[must_use]
    pub fn is_division_by_zero(&self) -> bool {
        matches!(self, Error::DivisionByZero)
    }

    /// Returns `true` if this [`Error`] results from an overflow.
    #[must_use]
    pub fn is_overflow(&self) -> bool {
        matches!(self, Error::Overflow)
    }
}

#[cfg(feature = "std")]
impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        match self {
            Error::DivisionByZero => f.write_str("An Option Operation overflowed"),
            Error::Overflow => f.write_str("Division by zero attempted with an Option Operation"),
        }
    }
}

#[cfg(feature = "std")]
impl error::Error for Error {}
