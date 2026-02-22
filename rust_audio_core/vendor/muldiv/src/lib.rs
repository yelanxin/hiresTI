// Copyright (C) 2016,2017 Sebastian Dröge <sebastian@centricular.com>
//
// Licensed under the MIT license, see the LICENSE file or <http://opensource.org/licenses/MIT>

#![no_std]

//! Provides a trait for numeric types to perform combined multiplication and division with
//! overflow protection.
//!
//! The [`MulDiv`] trait provides functions for performing combined multiplication and division for
//! numeric types and comes with implementations for all the primitive integer types. Three
//! variants with different rounding characteristics are provided: [`mul_div_floor()`],
//! [`mul_div_round()`] and [`mul_div_ceil()`].
//!
//! ## Example
//!
//! ```rust
//! extern crate muldiv;
//! use muldiv::MulDiv;
//! # fn main() {
//! // Calculates 127 * 23 / 42 rounded down
//! let x = 127u8.mul_div_floor(23, 42);
//! assert_eq!(x, Some(69));
//! # }
//! ```
//! [`MulDiv`]: trait.MulDiv.html
//! [`mul_div_floor()`]: trait.MulDiv.html#tymethod.mul_div_floor
//! [`mul_div_round()`]: trait.MulDiv.html#tymethod.mul_div_round
//! [`mul_div_ceil()`]: trait.MulDiv.html#tymethod.mul_div_ceil

use core::u16;
use core::u32;
use core::u64;
use core::u8;

use core::i16;
use core::i32;
use core::i64;
use core::i8;

/// Trait for calculating `val * num / denom` with different rounding modes and overflow
/// protection.
///
/// Implementations of this trait have to ensure that even if the result of the multiplication does
/// not fit into the type, as long as it would fit after the division the correct result has to be
/// returned instead of `None`. `None` only should be returned if the overall result does not fit
/// into the type.
///
/// This specifically means that e.g. the `u64` implementation must, depending on the arguments, be
/// able to do 128 bit integer multiplication.
pub trait MulDiv<RHS = Self> {
    /// Output type for the methods of this trait.
    type Output;

    /// Calculates `floor(val * num / denom)`, i.e. the largest integer less than or equal to the
    /// result of the division.
    ///
    /// ## Example
    ///
    /// ```rust
    /// extern crate muldiv;
    /// use muldiv::MulDiv;
    ///
    /// # fn main() {
    /// let x = 3i8.mul_div_floor(4, 2);
    /// assert_eq!(x, Some(6));
    ///
    /// let x = 5i8.mul_div_floor(2, 3);
    /// assert_eq!(x, Some(3));
    ///
    /// let x = (-5i8).mul_div_floor(2, 3);
    /// assert_eq!(x, Some(-4));
    ///
    /// let x = 3i8.mul_div_floor(3, 2);
    /// assert_eq!(x, Some(4));
    ///
    /// let x = (-3i8).mul_div_floor(3, 2);
    /// assert_eq!(x, Some(-5));
    ///
    /// let x = 127i8.mul_div_floor(4, 3);
    /// assert_eq!(x, None);
    /// # }
    /// ```
    fn mul_div_floor(self, num: RHS, denom: RHS) -> Option<Self::Output>;

    /// Calculates `round(val * num / denom)`, i.e. the closest integer to the result of the
    /// division. If both surrounding integers are the same distance (`x.5`), the one with the bigger
    /// absolute value is returned (round away from 0.0).
    ///
    /// ## Example
    ///
    /// ```rust
    /// extern crate muldiv;
    /// use muldiv::MulDiv;
    ///
    /// # fn main() {
    /// let x = 3i8.mul_div_round(4, 2);
    /// assert_eq!(x, Some(6));
    ///
    /// let x = 5i8.mul_div_round(2, 3);
    /// assert_eq!(x, Some(3));
    ///
    /// let x = (-5i8).mul_div_round(2, 3);
    /// assert_eq!(x, Some(-3));
    ///
    /// let x = 3i8.mul_div_round(3, 2);
    /// assert_eq!(x, Some(5));
    ///
    /// let x = (-3i8).mul_div_round(3, 2);
    /// assert_eq!(x, Some(-5));
    ///
    /// let x = 127i8.mul_div_round(4, 3);
    /// assert_eq!(x, None);
    /// # }
    /// ```
    fn mul_div_round(self, num: RHS, denom: RHS) -> Option<Self::Output>;

    /// Calculates `ceil(val * num / denom)`, i.e. the the smallest integer greater than or equal to
    /// the result of the division.
    ///
    /// ## Example
    ///
    /// ```rust
    /// extern crate muldiv;
    /// use muldiv::MulDiv;
    ///
    /// # fn main() {
    /// let x = 3i8.mul_div_ceil(4, 2);
    /// assert_eq!(x, Some(6));
    ///
    /// let x = 5i8.mul_div_ceil(2, 3);
    /// assert_eq!(x, Some(4));
    ///
    /// let x = (-5i8).mul_div_ceil(2, 3);
    /// assert_eq!(x, Some(-3));
    ///
    /// let x = 3i8.mul_div_ceil(3, 2);
    /// assert_eq!(x, Some(5));
    ///
    /// let x = (-3i8).mul_div_ceil(3, 2);
    /// assert_eq!(x, Some(-4));
    ///
    /// let x = (127i8).mul_div_ceil(4, 3);
    /// assert_eq!(x, None);
    /// # }
    /// ```
    fn mul_div_ceil(self, num: RHS, denom: RHS) -> Option<Self::Output>;
}

macro_rules! mul_div_impl_unsigned {
    ($t:ident, $u:ident) => {
        impl MulDiv for $t {
            type Output = $t;

            fn mul_div_floor(self, num: $t, denom: $t) -> Option<$t> {
                assert_ne!(denom, 0);
                let r = ((self as $u) * (num as $u)) / (denom as $u);
                if r > $t::MAX as $u {
                    None
                } else {
                    Some(r as $t)
                }
            }

            fn mul_div_round(self, num: $t, denom: $t) -> Option<$t> {
                assert_ne!(denom, 0);
                let r = ((self as $u) * (num as $u) + ((denom >> 1) as $u)) / (denom as $u);
                if r > $t::MAX as $u {
                    None
                } else {
                    Some(r as $t)
                }
            }

            fn mul_div_ceil(self, num: $t, denom: $t) -> Option<$t> {
                assert_ne!(denom, 0);
                let r = ((self as $u) * (num as $u) + ((denom - 1) as $u)) / (denom as $u);
                if r > $t::MAX as $u {
                    None
                } else {
                    Some(r as $t)
                }
            }
        }
    };
}

#[cfg(test)]
macro_rules! mul_div_impl_unsigned_tests {
    ($t:ident, $u:ident) => {
        use super::*;

        use quickcheck::{quickcheck, Arbitrary, Gen};

        #[derive(Debug, Clone, Copy, PartialEq, Eq)]
        struct NonZero($t);

        impl Arbitrary for NonZero {
            fn arbitrary(g: &mut Gen) -> Self {
                loop {
                    let v = $t::arbitrary(g);
                    if v != 0 {
                        return NonZero(v);
                    }
                }
            }
        }

        quickcheck! {
            fn scale_floor(val: $t, num: $t, den: NonZero) -> bool {
                let res = val.mul_div_floor(num, den.0);

                let expected = ((val as $u) * (num as $u)) / (den.0 as $u);

                if expected > $t::MAX as $u {
                    res.is_none()
                } else {
                    res == Some(expected as $t)
                }
            }
        }

        quickcheck! {
            fn scale_round(val: $t, num: $t, den: NonZero) -> bool {
                let res = val.mul_div_round(num, den.0);

                let mut expected = ((val as $u) * (num as $u)) / (den.0 as $u);
                let expected_rem = ((val as $u) * (num as $u)) % (den.0 as $u);

                if expected_rem >= ((den.0 as $u) + 1) >> 1 {
                    expected += 1
                }

                if expected > $t::MAX as $u {
                    res.is_none()
                } else {
                    res == Some(expected as $t)
                }
            }
        }

        quickcheck! {
            fn scale_ceil(val: $t, num: $t, den: NonZero) -> bool {
                let res = val.mul_div_ceil(num, den.0);

                let mut expected = ((val as $u) * (num as $u)) / (den.0 as $u);
                let expected_rem = ((val as $u) * (num as $u)) % (den.0 as $u);

                if expected_rem != 0 {
                    expected += 1
                }

                if expected > $t::MAX as $u {
                    res.is_none()
                } else {
                    res == Some(expected as $t)
                }
            }
        }
    };
}

mul_div_impl_unsigned!(u64, u128);
mul_div_impl_unsigned!(u32, u64);
mul_div_impl_unsigned!(u16, u32);
mul_div_impl_unsigned!(u8, u16);

// FIXME: https://github.com/rust-lang/rust/issues/12249
#[cfg(test)]
mod muldiv_u64_tests {
    mul_div_impl_unsigned_tests!(u64, u128);
}

#[cfg(test)]
mod muldiv_u32_tests {
    mul_div_impl_unsigned_tests!(u32, u64);
}

#[cfg(test)]
mod muldiv_u16_tests {
    mul_div_impl_unsigned_tests!(u16, u32);
}

#[cfg(test)]
mod muldiv_u8_tests {
    mul_div_impl_unsigned_tests!(u8, u16);
}

macro_rules! mul_div_impl_signed {
    ($t:ident, $u:ident, $v:ident, $b:expr) => {
        impl MulDiv for $t {
            type Output = $t;

            fn mul_div_floor(self, num: $t, denom: $t) -> Option<$t> {
                assert_ne!(denom, 0);

                let sgn = self.signum() * num.signum() * denom.signum();

                let min_val: $u = 1 << ($b - 1);
                let abs = |x: $t| if x != $t::MIN { x.abs() as $u } else { min_val };

                let self_u = abs(self);
                let num_u = abs(num);
                let denom_u = abs(denom);

                if sgn < 0 {
                    self_u.mul_div_ceil(num_u, denom_u)
                } else {
                    self_u.mul_div_floor(num_u, denom_u)
                }
                .and_then(|r| {
                    if r <= $t::MAX as $u {
                        Some(sgn * (r as $t))
                    } else if sgn < 0 && r == min_val {
                        Some($t::MIN)
                    } else {
                        None
                    }
                })
            }

            fn mul_div_round(self, num: $t, denom: $t) -> Option<$t> {
                assert_ne!(denom, 0);

                let sgn = self.signum() * num.signum() * denom.signum();

                let min_val: $u = 1 << ($b - 1);
                let abs = |x: $t| if x != $t::MIN { x.abs() as $u } else { min_val };

                let self_u = abs(self);
                let num_u = abs(num);
                let denom_u = abs(denom);

                if sgn < 0 {
                    let r =
                        ((self_u as $v) * (num_u as $v) + ((denom_u >> 1) as $v)) / (denom_u as $v);
                    if r > $u::MAX as $v {
                        None
                    } else {
                        Some(r as $u)
                    }
                } else {
                    self_u.mul_div_round(num_u, denom_u)
                }
                .and_then(|r| {
                    if r <= $t::MAX as $u {
                        Some(sgn * (r as $t))
                    } else if sgn < 0 && r == min_val {
                        Some($t::MIN)
                    } else {
                        None
                    }
                })
            }

            fn mul_div_ceil(self, num: $t, denom: $t) -> Option<$t> {
                assert_ne!(denom, 0);

                let sgn = self.signum() * num.signum() * denom.signum();

                let min_val: $u = 1 << ($b - 1);
                let abs = |x: $t| if x != $t::MIN { x.abs() as $u } else { min_val };

                let self_u = abs(self);
                let num_u = abs(num);
                let denom_u = abs(denom);

                if sgn < 0 {
                    self_u.mul_div_floor(num_u, denom_u)
                } else {
                    self_u.mul_div_ceil(num_u, denom_u)
                }
                .and_then(|r| {
                    if r <= $t::MAX as $u {
                        Some(sgn * (r as $t))
                    } else if sgn < 0 && r == min_val {
                        Some($t::MIN)
                    } else {
                        None
                    }
                })
            }
        }
    };
}

mul_div_impl_signed!(i64, u64, u128, 64);
mul_div_impl_signed!(i32, u32, u64, 32);
mul_div_impl_signed!(i16, u16, u32, 16);
mul_div_impl_signed!(i8, u8, u16, 8);

#[cfg(test)]
macro_rules! mul_div_impl_signed_tests {
    ($t:ident, $u:ident) => {
        use super::*;

        use quickcheck::{quickcheck, Arbitrary, Gen};

        #[derive(Debug, Clone, Copy, PartialEq, Eq)]
        struct NonZero($t);

        impl Arbitrary for NonZero {
            fn arbitrary(g: &mut Gen) -> Self {
                loop {
                    let v = $t::arbitrary(g);
                    if v != 0 {
                        return NonZero(v);
                    }
                }
            }
        }

        quickcheck! {
            fn scale_floor(val: $t, num: $t, den: NonZero) -> bool {
                let res = val.mul_div_floor(num, den.0);

                let sgn = val.signum() * num.signum() * den.0.signum();
                let mut expected = ((val as $u) * (num as $u)) / (den.0 as $u);
                let expected_rem = ((val as $u) * (num as $u)) % (den.0 as $u);

                if sgn < 0 && expected_rem.abs() != 0 {
                    expected -= 1
                }

                if expected > $t::MAX as $u || expected < $t::MIN as $u {
                    res.is_none()
                } else {
                    res == Some(expected as $t)
                }
            }
        }

        quickcheck! {
            fn scale_round(val: $t, num: $t, den: NonZero) -> bool {
                let res = val.mul_div_round(num, den.0);

                let sgn = val.signum() * num.signum() * den.0.signum();
                let mut expected = ((val as $u) * (num as $u)) / (den.0 as $u);
                let expected_rem = ((val as $u) * (num as $u)) % (den.0 as $u);

                if sgn < 0 && expected_rem.abs() >= ((den.0 as $u).abs() + 1) >> 1 {
                    expected -= 1
                } else if sgn > 0 && expected_rem.abs() >= ((den.0 as $u).abs() + 1) >> 1 {
                    expected += 1
                }

                if expected > $t::MAX as $u || expected < $t::MIN as $u {
                    res.is_none()
                } else {
                    res == Some(expected as $t)
                }
            }
        }

        quickcheck! {
            fn scale_ceil(val: $t, num: $t, den: NonZero) -> bool {
                let res = val.mul_div_ceil(num, den.0);

                let sgn = val.signum() * num.signum() * den.0.signum();
                let mut expected = ((val as $u) * (num as $u)) / (den.0 as $u);
                let expected_rem = ((val as $u) * (num as $u)) % (den.0 as $u);

                if sgn > 0 && expected_rem.abs() != 0 {
                    expected += 1
                }

                if expected > $t::MAX as $u || expected < $t::MIN as $u {
                    res.is_none()
                } else {
                    res == Some(expected as $t)
                }
            }
        }
    };
}

// FIXME: https://github.com/rust-lang/rust/issues/12249
#[cfg(test)]
mod muldiv_i64_tests {
    mul_div_impl_signed_tests!(i64, i128);
}

#[cfg(test)]
mod muldiv_i32_tests {
    mul_div_impl_signed_tests!(i32, i64);
}

#[cfg(test)]
mod muldiv_i16_tests {
    mul_div_impl_signed_tests!(i16, i32);
}

#[cfg(test)]
mod muldiv_i8_tests {
    mul_div_impl_signed_tests!(i8, i16);
}
