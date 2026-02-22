//! Trait for the equality [`OptionOperations`].

use crate::OptionOperations;

/// Trait for the equality [`OptionOperations`].
pub trait OptionEq<Rhs, InnerRhs = Rhs> {
    /// Tests whether `self` is equal to `other`.
    ///
    /// Returns `None` if they can't be compared, e.g. if
    /// at most one argument is `None`.
    #[must_use]
    fn opt_eq(&self, other: Rhs) -> Option<bool>;

    /// Tests whether `self` is not equal to `other`.
    ///
    /// Returns `None` if they can't be compared, e.g. if
    /// at most one argument is `None`.
    #[must_use]
    fn opt_ne(&self, other: Rhs) -> Option<bool> {
        self.opt_eq(other).map(|res| !res)
    }
}

impl<T, Rhs> OptionEq<&Rhs, Rhs> for T
where
    T: OptionOperations + PartialEq<Rhs>,
{
    fn opt_eq(&self, rhs: &Rhs) -> Option<bool> {
        Some(self.eq(rhs))
    }
}

impl<T, Rhs> OptionEq<Rhs> for T
where
    T: OptionOperations + for<'a> OptionEq<&'a Rhs, Rhs>,
{
    fn opt_eq(&self, rhs: Rhs) -> Option<bool> {
        self.opt_eq(&rhs)
    }
}

impl<T, InnerRhs> OptionEq<&Option<InnerRhs>, InnerRhs> for T
where
    T: OptionOperations + for<'a> OptionEq<&'a InnerRhs, InnerRhs>,
{
    fn opt_eq(&self, rhs: &Option<InnerRhs>) -> Option<bool> {
        rhs.as_ref().and_then(|inner_rhs| self.opt_eq(inner_rhs))
    }
}

impl<T, InnerRhs> OptionEq<Option<InnerRhs>, InnerRhs> for T
where
    T: OptionOperations + for<'a> OptionEq<&'a InnerRhs, InnerRhs>,
{
    fn opt_eq(&self, rhs: Option<InnerRhs>) -> Option<bool> {
        rhs.as_ref().and_then(|inner_rhs| self.opt_eq(inner_rhs))
    }
}

impl<T, Rhs> OptionEq<&Rhs, Rhs> for Option<T>
where
    T: OptionOperations + for<'a> OptionEq<&'a Rhs, Rhs>,
{
    fn opt_eq(&self, rhs: &Rhs) -> Option<bool> {
        self.as_ref().and_then(|inner_self| inner_self.opt_eq(rhs))
    }
}

impl<T, Rhs> OptionEq<Rhs> for Option<T>
where
    T: OptionOperations + for<'a> OptionEq<&'a Rhs, Rhs>,
{
    fn opt_eq(&self, rhs: Rhs) -> Option<bool> {
        self.opt_eq(&rhs)
    }
}

impl<T, InnerRhs> OptionEq<&Option<InnerRhs>, InnerRhs> for Option<T>
where
    T: OptionOperations + for<'a> OptionEq<&'a InnerRhs, InnerRhs>,
{
    fn opt_eq(&self, rhs: &Option<InnerRhs>) -> Option<bool> {
        match (self, rhs) {
            (Some(inner_self), Some(inner_rhs)) => inner_self.opt_eq(inner_rhs),
            (None, None) => Some(true),
            _ => None,
        }
    }
}

impl<T, InnerRhs> OptionEq<Option<InnerRhs>, InnerRhs> for Option<T>
where
    T: OptionOperations + for<'a> OptionEq<&'a InnerRhs, InnerRhs>,
{
    fn opt_eq(&self, rhs: Option<InnerRhs>) -> Option<bool> {
        match (self, rhs.as_ref()) {
            (Some(inner_self), Some(inner_rhs)) => inner_self.opt_eq(inner_rhs),
            (None, None) => Some(true),
            _ => None,
        }
    }
}

#[cfg(test)]
mod test {
    use super::OptionEq;
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
    fn opt_eq() {
        assert_eq!(MY_1.opt_eq(MY_1), Some(true));
        assert_eq!(MY_1.opt_eq(SOME_1), Some(true));
        assert_eq!(SOME_1.opt_eq(MY_1), Some(true));
        assert_eq!(SOME_1.opt_eq(SOME_1), Some(true));

        assert_eq!(MY_1.opt_eq(MY_2), Some(false));
        assert_eq!(MY_1.opt_eq(SOME_2), Some(false));
        assert_eq!(SOME_1.opt_eq(MY_2), Some(false));
        assert_eq!(SOME_1.opt_eq(SOME_2), Some(false));

        assert_eq!(MY_1.opt_eq(NONE), None);
        assert_eq!(NONE.opt_eq(SOME_2), None);
        assert_eq!(SOME_1.opt_eq(NONE), None);
        assert_eq!(NONE.opt_eq(SOME_2), None);
        assert_eq!(NONE.opt_eq(NONE), Some(true));
    }

    #[test]
    fn opt_ne() {
        assert_eq!(MY_1.opt_ne(MY_1), Some(false));
        assert_eq!(MY_1.opt_ne(SOME_1), Some(false));
        assert_eq!(SOME_1.opt_ne(MY_1), Some(false));
        assert_eq!(SOME_1.opt_ne(SOME_1), Some(false));

        assert_eq!(MY_1.opt_ne(MY_2), Some(true));
        assert_eq!(MY_1.opt_ne(SOME_2), Some(true));
        assert_eq!(SOME_1.opt_ne(MY_2), Some(true));
        assert_eq!(SOME_1.opt_ne(SOME_2), Some(true));

        assert_eq!(MY_1.opt_ne(NONE), None);
        assert_eq!(NONE.opt_ne(SOME_2), None);
        assert_eq!(SOME_1.opt_ne(NONE), None);
        assert_eq!(NONE.opt_ne(SOME_2), None);
        assert_eq!(NONE.opt_ne(NONE), Some(false));
    }
}
