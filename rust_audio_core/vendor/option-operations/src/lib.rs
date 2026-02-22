//! `option-operations` provides traits and auto-implementations to
//! improve arithmetic operations usability when dealing with `Option`s.
//!
//! # Example
//!
//! Dealing with two `Option`s, can lead to verbose expressions:
//!
//! ```
//! let lhs = Some(1u64);
//! let rhs = Some(u64::MAX);
//!
//! assert_eq!(
//!     lhs.zip(rhs).map(|(lhs, rhs)| lhs.saturating_add(rhs)),
//!     Some(u64::MAX),
//! );
//! ```
//!
//! Thanks to the trait [`OptionSaturatingAdd`] we can write:
//!
//! ```
//! # use option_operations::{Error, OptionSaturatingAdd};
//! # let lhs = Some(1u64);
//! # let rhs = Some(u64::MAX);
//! assert_eq!(
//!     lhs.opt_saturating_add(rhs),
//!     Some(u64::MAX),
//! );
//! ```
//!
//! The trait can also be used with the inner type:
//!
//! ```
//! # use option_operations::{Error, OptionSaturatingAdd};
//! # let lhs = Some(1u64);
//! # let rhs = Some(u64::MAX);
//! assert_eq!(
//!     lhs.opt_saturating_add(u64::MAX),
//!     Some(u64::MAX),
//! );
//!
//! assert_eq!(
//!     1.opt_saturating_add(rhs),
//!     Some(u64::MAX),
//! );
//! ```
//!
//! # Alternative to `PartialOrd` for `Option<T>`
//!
//! Another purpose is to workaround the `PartiaOrd` implementation
//! for `Option<T>`, which uses the declaration order of the variants
//! for `Option`. `None` appearing before `Some(_)`, it results in
//! the following behavior:
//!
//! ```
//! # use core::cmp::Ordering;
//! let some_0 = Some(0);
//! let none: Option<u64> = None;
//!
//! assert_eq!(none.partial_cmp(&some_0), Some(Ordering::Less));
//! assert_eq!(some_0.partial_cmp(&none), Some(Ordering::Greater));
//! ```
//!
//! In some cases, we might consider that `None` reflects a value which
//! is not defined and thus can not be compared with `Some(_)`.
//!
//! ```
//! # use option_operations::{OptionOperations, OptionOrd};
//! # let some_0 = Some(0);
//! # let none: Option<u64> = None;
//! assert_eq!(none.opt_cmp(&some_0), None);
//! assert_eq!(some_0.opt_cmp(&none), None);
//! ```
//!
//! Of course, this is consistent with other usual comparisons:
//!
//! ``` rust
//! # use option_operations::{OptionOperations, OptionOrd, OptionMinMax};
//! # let some_0 = Some(0);
//! # let none: Option<u64> = None;
//! assert_eq!(none.opt_lt(&some_0), None);
//! assert_eq!(none.opt_min(some_0), None);
//! ```

#![forbid(unsafe_code)]
#![cfg_attr(not(feature = "std"), no_std)]

/// Trait for inner types participating in `option-operations`.
///
/// The purpose of this trait is twofold:
///
/// - Auto-implement various `Option*` traits such as `OptionOrd`.
/// - Prevent some conflicting auto-implementation of traits on
///   `Option<T>`.
pub trait OptionOperations {}

impl<T: OptionOperations> OptionOperations for &T {}
impl<T: OptionOperations> OptionOperations for &mut T {}

#[macro_use]
mod macros;

impl_for_all!(OptionOperations);

pub mod add;
pub use add::{
    OptionAdd, OptionAddAssign, OptionCheckedAdd, OptionOverflowingAdd, OptionSaturatingAdd,
    OptionWrappingAdd,
};

pub mod error;
pub use error::Error;

pub mod div;
pub use div::{
    OptionCheckedDiv, OptionDiv, OptionDivAssign, OptionOverflowingDiv, OptionWrappingDiv,
};

pub mod eq;
pub use eq::OptionEq;

pub mod min_max;
pub use min_max::OptionMinMax;

pub mod mul;
pub use mul::{
    OptionCheckedMul, OptionMul, OptionMulAssign, OptionOverflowingMul, OptionSaturatingMul,
    OptionWrappingMul,
};

pub mod ord;
pub use ord::OptionOrd;

pub mod rem;
pub use rem::{
    OptionCheckedRem, OptionOverflowingRem, OptionRem, OptionRemAssign, OptionWrappingRem,
};

pub mod sub;
pub use sub::{
    OptionCheckedSub, OptionOverflowingSub, OptionSaturatingSub, OptionSub, OptionSubAssign,
    OptionWrappingSub,
};

pub mod prelude {
    pub use crate::add::{
        OptionAdd, OptionAddAssign, OptionCheckedAdd, OptionOverflowingAdd, OptionSaturatingAdd,
        OptionWrappingAdd,
    };
    pub use crate::div::{
        OptionCheckedDiv, OptionDiv, OptionDivAssign, OptionOverflowingDiv, OptionWrappingDiv,
    };
    pub use crate::eq::OptionEq;
    pub use crate::min_max::OptionMinMax;
    pub use crate::mul::{
        OptionCheckedMul, OptionMul, OptionMulAssign, OptionOverflowingMul, OptionSaturatingMul,
        OptionWrappingMul,
    };
    pub use crate::ord::OptionOrd;
    pub use crate::rem::{
        OptionCheckedRem, OptionOverflowingRem, OptionRem, OptionRemAssign, OptionWrappingRem,
    };
    pub use crate::sub::{
        OptionCheckedSub, OptionOverflowingSub, OptionSaturatingSub, OptionSub, OptionSubAssign,
        OptionWrappingSub,
    };
    pub use crate::OptionOperations;
}
