//! Traits for the minimun and maximum [`OptionOperations`].

// Required for doc
#[allow(unused)]
use crate::OptionOperations;

use crate::OptionOrd;

/// Trait for values and `Option`s that can be compared
/// to get the minimum or maximum.
///
/// Implementing this type leads to the following auto-implementations:
///
/// - `OptionMinMax<Option<InnerRhs>> for T`.
/// - `OptionMinMax<Rhs> for Option<T>`.
/// - `OptionMinMax<Option<InnerRhs>> for Option<T>`.
/// - ... and some variants with references.
///
/// This trait is auto-implemented for [`OptionOperations`] types
/// implementing `OptionOrd<Rhs>`.
pub trait OptionMinMax<Other, Inner = Other> {
    /// Compares and returns the minimum of two values.
    ///
    /// Returns `None` if they can't be compared, e.g. if
    /// at most one argument is `None`.
    #[must_use]
    fn opt_min(self, other: Other) -> Option<Inner>;

    /// Compares and returns the maximum of two values.
    ///
    /// Returns `None` if they can't be compared, e.g. if
    /// at most one argument is `None`.
    #[must_use]
    fn opt_max(self, other: Other) -> Option<Inner>;
}

impl<T> OptionMinMax<T> for T
where
    T: for<'a> OptionOrd<&'a T, T>,
{
    fn opt_min(self, other: T) -> Option<T> {
        self.opt_lt(&other)
            .map(|is_lt| if is_lt { self } else { other })
    }

    fn opt_max(self, other: T) -> Option<T> {
        self.opt_gt(&other)
            .map(|is_gt| if is_gt { self } else { other })
    }
}

impl<T> OptionMinMax<Option<T>, T> for T
where
    T: for<'a> OptionOrd<&'a T, T>,
{
    fn opt_min(self, other: Option<T>) -> Option<T> {
        other.and_then(|inner_other| {
            self.opt_lt(&inner_other)
                .map(|is_lt| if is_lt { self } else { inner_other })
        })
    }

    fn opt_max(self, other: Option<T>) -> Option<T> {
        other.and_then(|inner_other| {
            self.opt_gt(&inner_other)
                .map(|is_gt| if is_gt { self } else { inner_other })
        })
    }
}

impl<T> OptionMinMax<T> for Option<T>
where
    T: for<'a> OptionOrd<&'a T, T>,
{
    fn opt_min(self, other: T) -> Option<T> {
        self.and_then(|inner_self| {
            inner_self
                .opt_lt(&other)
                .map(|is_lt| if is_lt { inner_self } else { other })
        })
    }

    fn opt_max(self, other: T) -> Option<T> {
        self.and_then(|inner_self| {
            inner_self
                .opt_gt(&other)
                .map(|is_gt| if is_gt { inner_self } else { other })
        })
    }
}

impl<T> OptionMinMax<Option<T>, T> for Option<T>
where
    T: for<'a> OptionOrd<&'a T, T>,
{
    fn opt_min(self, other: Option<T>) -> Option<T> {
        self.zip(other).and_then(|(inner_self, inner_other)| {
            inner_self
                .opt_lt(&inner_other)
                .map(|is_lt| if is_lt { inner_self } else { inner_other })
        })
    }

    fn opt_max(self, other: Option<T>) -> Option<T> {
        self.zip(other).and_then(|(inner_self, inner_other)| {
            inner_self
                .opt_gt(&inner_other)
                .map(|is_gt| if is_gt { inner_self } else { inner_other })
        })
    }
}

#[cfg(test)]
mod test {
    use super::OptionMinMax;
    use crate::OptionOperations;

    #[derive(Copy, Clone, Debug, PartialEq, PartialOrd)]
    struct MyInt(u64);

    impl OptionOperations for MyInt {}

    const MY_1: MyInt = MyInt(1);
    const MY_2: MyInt = MyInt(2);
    const SOME_1: Option<MyInt> = Some(MY_1);
    const SOME_2: Option<MyInt> = Some(MY_2);
    const NONE: Option<MyInt> = None;

    #[test]
    fn min() {
        assert_eq!(SOME_1.opt_min(SOME_2), SOME_1);
        assert_eq!(SOME_2.opt_min(SOME_1), SOME_1);
        assert_eq!(SOME_1.opt_min(NONE), None);

        assert_eq!(SOME_1.opt_min(MY_2), SOME_1);
        assert_eq!(SOME_2.opt_min(MY_1), SOME_1);

        assert_eq!(MY_1.opt_min(MY_2), SOME_1);
        assert_eq!(MY_2.opt_min(MY_1), SOME_1);

        assert_eq!(MY_1.opt_min(SOME_2), SOME_1);
        assert_eq!(MY_2.opt_min(SOME_1), SOME_1);

        assert_eq!(MY_1.opt_min(NONE), None);
        assert_eq!(NONE.opt_min(MY_1), None);

        assert_eq!(SOME_1.opt_min(NONE).or(SOME_1), SOME_1);
    }

    #[test]
    fn max() {
        assert_eq!(SOME_1.opt_max(SOME_2), SOME_2);
        assert_eq!(SOME_2.opt_max(SOME_1), SOME_2);
        assert_eq!(SOME_1.opt_max(NONE), None);

        assert_eq!(SOME_1.opt_max(MY_2), SOME_2);
        assert_eq!(SOME_2.opt_max(MY_1), SOME_2);

        assert_eq!(MY_1.opt_max(MY_2), SOME_2);
        assert_eq!(MY_2.opt_max(MY_1), SOME_2);

        assert_eq!(MY_1.opt_max(SOME_2), SOME_2);
        assert_eq!(MY_2.opt_max(SOME_1), SOME_2);

        assert_eq!(MY_1.opt_max(NONE), None);
        assert_eq!(NONE.opt_max(MY_1), None);

        assert_eq!(SOME_1.opt_max(NONE).or(SOME_1), SOME_1);
    }
}
