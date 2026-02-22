//! Traits for the remainder [`OptionOperations`].

use core::ops::{Rem, RemAssign};

use crate::{Error, OptionOperations};

common_option_op!(
    Rem,
    rem,
    remainder,
    "
# Panics

Most implementations will panic if `rhs` is zero.
",
);

impl_for_ints!(OptionOverflowingRem, {
    type Output = Self;
    fn opt_overflowing_rem(self, rhs: Self) -> Option<(Self::Output, bool)> {
        Some(self.overflowing_rem(rhs))
    }
});

impl_for_ints!(OptionWrappingRem, {
    type Output = Self;
    fn opt_wrapping_rem(self, rhs: Self) -> Option<Self::Output> {
        Some(self.wrapping_rem(rhs))
    }
});

option_op_checked!(
    Rem,
    rem,
    remainder,
    "- Returns `Err(Error::DivisionByZero)` if `rhs` is zero.",
);

impl_for_ints!(OptionCheckedRem, {
    type Output = Self;
    fn opt_checked_rem(self, rhs: Self) -> Result<Option<Self::Output>, Error> {
        if rhs == 0 {
            return Err(Error::DivisionByZero);
        }
        self.checked_rem(rhs).ok_or(Error::Overflow).map(Some)
    }
});

#[cfg(test)]
mod test {
    use super::*;
    use crate::OptionOperations;
    use core::ops::{Rem, RemAssign};

    #[derive(Copy, Clone, Debug, PartialEq, PartialOrd)]
    struct MyInt(i64);

    impl OptionOperations for MyInt {}

    impl Rem<MyInt> for MyInt {
        type Output = MyInt;

        fn rem(self, rhs: MyInt) -> MyInt {
            MyInt(self.0.rem(rhs.0))
        }
    }

    impl Rem<i64> for MyInt {
        type Output = MyInt;

        fn rem(self, rhs: i64) -> MyInt {
            MyInt(self.0.rem(rhs))
        }
    }

    impl RemAssign<MyInt> for MyInt {
        fn rem_assign(&mut self, rhs: MyInt) {
            self.0.rem_assign(rhs.0)
        }
    }

    impl RemAssign<i64> for MyInt {
        fn rem_assign(&mut self, rhs: i64) {
            self.0.rem_assign(rhs)
        }
    }

    const MY_MINUS_1: MyInt = MyInt(-1);
    const MY_0: MyInt = MyInt(0);
    const MY_1: MyInt = MyInt(1);
    const MY_2: MyInt = MyInt(2);
    const MY_5: MyInt = MyInt(5);
    const MY_10: MyInt = MyInt(10);
    const MY_MIN: MyInt = MyInt(i64::MIN);
    const MY_MAX: MyInt = MyInt(i64::MAX);
    const SOME_MINUS_1: Option<MyInt> = Some(MY_MINUS_1);
    const SOME_0: Option<MyInt> = Some(MY_0);
    const SOME_1: Option<MyInt> = Some(MY_1);
    const SOME_2: Option<MyInt> = Some(MY_2);
    const SOME_5: Option<MyInt> = Some(MY_5);
    const SOME_10: Option<MyInt> = Some(MY_10);
    const SOME_MIN: Option<MyInt> = Some(MY_MIN);
    const SOME_MAX: Option<MyInt> = Some(MY_MAX);
    const NONE: Option<MyInt> = None;

    #[test]
    fn rem_my() {
        assert_eq!(MY_5.opt_rem(MY_1), SOME_0);
        assert_eq!(SOME_5.opt_rem(MY_2), SOME_1);
        assert_eq!(MY_0.opt_rem(SOME_1), SOME_0);
        assert_eq!(MY_MAX.opt_rem(&SOME_2), SOME_1);
        assert_eq!(MY_1.opt_rem(NONE), NONE);
        assert_eq!(NONE.opt_rem(MY_1), NONE);
    }

    #[test]
    #[should_panic]
    fn rem_by_zero_my() {
        let _ = SOME_10.opt_rem(SOME_0);
    }

    #[test]
    fn rem_i64() {
        assert_eq!(MY_5.opt_rem(1), SOME_0);
        assert_eq!(SOME_5.opt_rem(MY_2), SOME_1);
        assert_eq!(MY_0.opt_rem(Some(1)), SOME_0);
        assert_eq!(MY_MAX.opt_rem(Some(2)), SOME_1);
        assert_eq!(MY_1.opt_rem(Option::<i64>::None), NONE);
        assert_eq!(Option::<MyInt>::None.opt_rem(MY_1), NONE);
    }

    #[test]
    #[should_panic]
    fn rem_by_zero_i64() {
        let _ = SOME_10.opt_rem(Some(0));
    }

    #[test]
    fn rem_assign_my() {
        let mut my = MY_5;
        my.opt_rem_assign(MY_1);
        assert_eq!(my, MY_0);

        let mut some = SOME_5;
        some.opt_rem_assign(MY_2);
        assert_eq!(some, SOME_1);

        let mut my = MY_0;
        my.opt_rem_assign(SOME_1);
        assert_eq!(my, MY_0);

        let mut my = MY_MAX;
        my.opt_rem_assign(&SOME_2);
        assert_eq!(my, MY_1);

        let mut my = MY_1;
        my.opt_rem_assign(NONE);
        assert_eq!(my, MY_1);

        let mut some = SOME_2;
        some.opt_rem_assign(SOME_1);
        assert_eq!(some, SOME_0);

        let mut some = SOME_5;
        some.opt_rem_assign(&SOME_2);
        assert_eq!(some, SOME_1);

        let mut some = SOME_1;
        some.opt_rem_assign(NONE);
        assert_eq!(some, SOME_1);

        let mut none = NONE;
        none.opt_rem_assign(SOME_1);
        assert_eq!(none, NONE);

        let mut none = NONE;
        none.opt_rem_assign(NONE);
        assert_eq!(none, NONE);
    }

    #[test]
    #[should_panic]
    fn rem_assign_by_zero_my() {
        let mut some = SOME_10;
        some.opt_rem_assign(SOME_0);
    }

    #[test]
    fn rem_assign_i64() {
        let mut my = MY_5;
        my.opt_rem_assign(1);
        assert_eq!(my, MY_0);

        let mut some = SOME_5;
        some.opt_rem_assign(2);
        assert_eq!(some, SOME_1);

        let mut my = MY_0;
        my.opt_rem_assign(1);
        assert_eq!(my, MY_0);

        let mut my = MY_MAX;
        my.opt_rem_assign(2);
        assert_eq!(my, MY_1);

        let mut my = MY_1;
        my.opt_rem_assign(Option::<i64>::None);
        assert_eq!(my, MY_1);

        let mut some = SOME_2;
        some.opt_rem_assign(1);
        assert_eq!(some, SOME_0);

        let mut some = SOME_1;
        some.opt_rem_assign(Option::<i64>::None);
        assert_eq!(some, SOME_1);

        let mut none = NONE;
        none.opt_rem_assign(1);
        assert_eq!(none, NONE);

        let mut none = NONE;
        none.opt_rem_assign(Option::<i64>::None);
        assert_eq!(none, NONE);
    }

    #[test]
    #[should_panic]
    fn rem_assign_by_zero_i64() {
        let mut some = SOME_10;
        some.opt_rem_assign(Some(0));
    }

    #[test]
    fn checked_rem() {
        impl OptionCheckedRem for MyInt {
            type Output = MyInt;
            fn opt_checked_rem(self, rhs: MyInt) -> Result<Option<Self::Output>, Error> {
                self.0.opt_checked_rem(rhs.0).map(|ok| ok.map(MyInt))
            }
        }

        impl OptionCheckedRem<i64> for MyInt {
            type Output = MyInt;
            fn opt_checked_rem(self, rhs: i64) -> Result<Option<Self::Output>, Error> {
                self.0.opt_checked_rem(rhs).map(|ok| ok.map(MyInt))
            }
        }

        assert_eq!(MY_2.opt_checked_rem(MY_1), Ok(SOME_0));
        assert_eq!(MY_5.opt_checked_rem(SOME_2), Ok(SOME_1));
        assert_eq!(MY_0.opt_checked_rem(&SOME_1), Ok(SOME_0));
        assert_eq!(MY_MAX.opt_checked_rem(MY_2), Ok(SOME_1));
        assert_eq!(MY_MAX.opt_checked_rem(MY_0), Err(Error::DivisionByZero));
        assert_eq!(MY_MIN.opt_checked_rem(MY_MINUS_1), Err(Error::Overflow));

        assert_eq!(SOME_2.opt_checked_rem(MY_1), Ok(SOME_0));
        assert_eq!(SOME_5.opt_checked_rem(SOME_2), Ok(SOME_1));
        assert_eq!(SOME_0.opt_checked_rem(&SOME_1), Ok(SOME_0));

        assert_eq!(SOME_MAX.opt_checked_rem(MY_2), Ok(SOME_1));
        assert_eq!(SOME_MAX.opt_checked_rem(MY_0), Err(Error::DivisionByZero));
        assert_eq!(SOME_MIN.opt_checked_rem(MY_MINUS_1), Err(Error::Overflow));
        assert_eq!(SOME_MAX.opt_checked_rem(0), Err(Error::DivisionByZero));
        assert_eq!(SOME_MIN.opt_checked_rem(-1), Err(Error::Overflow));
        assert_eq!(
            SOME_MAX.opt_checked_rem(Some(0)),
            Err(Error::DivisionByZero)
        );
        assert_eq!(SOME_MIN.opt_checked_rem(Some(-1)), Err(Error::Overflow));
        assert_eq!(SOME_MAX.opt_checked_rem(SOME_0), Err(Error::DivisionByZero));
        assert_eq!(SOME_MIN.opt_checked_rem(SOME_MINUS_1), Err(Error::Overflow));
        assert_eq!(MY_MIN.opt_checked_rem(NONE), Ok(None));
        assert_eq!(NONE.opt_checked_rem(SOME_MIN), Ok(None));
    }

    #[test]
    fn overflowing_rem() {
        impl OptionOverflowingRem for MyInt {
            type Output = MyInt;
            fn opt_overflowing_rem(self, rhs: MyInt) -> Option<(Self::Output, bool)> {
                self.0
                    .opt_overflowing_rem(rhs.0)
                    .map(|(val, flag)| (MyInt(val), flag))
            }
        }

        impl OptionOverflowingRem<i64> for MyInt {
            type Output = MyInt;
            fn opt_overflowing_rem(self, rhs: i64) -> Option<(Self::Output, bool)> {
                self.0
                    .opt_overflowing_rem(rhs)
                    .map(|(val, flag)| (MyInt(val), flag))
            }
        }

        assert_eq!(MY_2.opt_overflowing_rem(MY_1), Some((MY_0, false)));
        assert_eq!(MY_0.opt_overflowing_rem(MY_1), Some((MY_0, false)));
        assert_eq!(MY_MAX.opt_overflowing_rem(MY_2), Some((MY_1, false)));
        assert_eq!(MY_MIN.opt_overflowing_rem(MY_MINUS_1), Some((MY_0, true)));
        assert_eq!(SOME_MIN.opt_overflowing_rem(MY_MINUS_1), Some((MY_0, true)));
        assert_eq!(SOME_MIN.opt_overflowing_rem(-1), Some((MY_0, true)));
        assert_eq!(SOME_MIN.opt_overflowing_rem(Some(-1)), Some((MY_0, true)));
        assert_eq!(SOME_MIN.opt_overflowing_rem(&Some(-1)), Some((MY_0, true)));
        assert_eq!(MY_MIN.opt_overflowing_rem(SOME_MINUS_1), Some((MY_0, true)));
        assert_eq!(
            MY_MIN.opt_overflowing_rem(&SOME_MINUS_1),
            Some((MY_0, true))
        );
        assert_eq!(MY_MIN.opt_overflowing_rem(NONE), None);
        assert_eq!(NONE.opt_overflowing_rem(MY_MIN), None);
    }

    #[test]
    fn wrapping_rem() {
        impl OptionWrappingRem for MyInt {
            type Output = MyInt;
            fn opt_wrapping_rem(self, rhs: MyInt) -> Option<Self::Output> {
                self.0.opt_wrapping_rem(rhs.0).map(MyInt)
            }
        }

        impl OptionWrappingRem<i64> for MyInt {
            type Output = MyInt;
            fn opt_wrapping_rem(self, rhs: i64) -> Option<Self::Output> {
                self.0.opt_wrapping_rem(rhs).map(MyInt)
            }
        }

        assert_eq!(MY_2.opt_wrapping_rem(MY_1), SOME_0);
        assert_eq!(MY_0.opt_wrapping_rem(MY_1), SOME_0);
        assert_eq!(MY_MAX.opt_wrapping_rem(MY_2), SOME_1);
        assert_eq!(MY_MIN.opt_wrapping_rem(MY_MINUS_1), SOME_0);
        assert_eq!(SOME_MIN.opt_wrapping_rem(MY_MINUS_1), SOME_0);
        assert_eq!(SOME_MIN.opt_wrapping_rem(-1), SOME_0);
        assert_eq!(SOME_MIN.opt_wrapping_rem(Some(-1)), SOME_0);
        assert_eq!(SOME_MIN.opt_wrapping_rem(&Some(-1)), SOME_0);
        assert_eq!(MY_MIN.opt_wrapping_rem(SOME_MINUS_1), SOME_0);
        assert_eq!(MY_MIN.opt_wrapping_rem(&SOME_MINUS_1), SOME_0,);
        assert_eq!(MY_MIN.opt_wrapping_rem(NONE), None);
        assert_eq!(NONE.opt_wrapping_rem(MY_MIN), None);
    }
}
