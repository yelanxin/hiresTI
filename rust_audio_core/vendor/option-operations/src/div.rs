//! Traits for the division [`OptionOperations`].

use core::ops::{Div, DivAssign};

use crate::{Error, OptionOperations};

common_option_op!(
    Div,
    div,
    division,
    "
# Panics

Most implementations will panic if `rhs` is zero.
",
);

impl_for_ints!(OptionOverflowingDiv, {
    type Output = Self;
    fn opt_overflowing_div(self, rhs: Self) -> Option<(Self::Output, bool)> {
        Some(self.overflowing_div(rhs))
    }
});

impl_for_ints!(OptionWrappingDiv, {
    type Output = Self;
    fn opt_wrapping_div(self, rhs: Self) -> Option<Self::Output> {
        Some(self.wrapping_div(rhs))
    }
});

option_op_checked!(
    Div,
    div,
    division,
    "- Returns `Err(Error::DivisionByZero)` if `rhs` is zero.",
);

impl_for_ints!(OptionCheckedDiv, {
    type Output = Self;
    fn opt_checked_div(self, rhs: Self) -> Result<Option<Self::Output>, Error> {
        if rhs == 0 {
            return Err(Error::DivisionByZero);
        }
        self.checked_div(rhs).ok_or(Error::Overflow).map(Some)
    }
});

impl OptionCheckedDiv<u32> for core::time::Duration {
    type Output = Self;
    fn opt_checked_div(self, rhs: u32) -> Result<Option<Self::Output>, Error> {
        if rhs == 0 {
            return Err(Error::DivisionByZero);
        }
        self.checked_div(rhs).ok_or(Error::Overflow).map(Some)
    }
}

#[cfg(test)]
mod test {
    use super::*;
    use crate::OptionOperations;
    use core::ops::{Div, DivAssign};

    #[derive(Copy, Clone, Debug, PartialEq, PartialOrd)]
    struct MyInt(i64);

    impl OptionOperations for MyInt {}

    impl Div<MyInt> for MyInt {
        type Output = MyInt;

        fn div(self, rhs: MyInt) -> MyInt {
            MyInt(self.0.div(rhs.0))
        }
    }

    impl Div<i64> for MyInt {
        type Output = MyInt;

        fn div(self, rhs: i64) -> MyInt {
            MyInt(self.0.div(rhs))
        }
    }

    impl DivAssign<MyInt> for MyInt {
        fn div_assign(&mut self, rhs: MyInt) {
            self.0.div_assign(rhs.0)
        }
    }

    impl DivAssign<i64> for MyInt {
        fn div_assign(&mut self, rhs: i64) {
            self.0.div_assign(rhs)
        }
    }

    const MY_MINUS_1: MyInt = MyInt(-1);
    const MY_0: MyInt = MyInt(0);
    const MY_1: MyInt = MyInt(1);
    const MY_2: MyInt = MyInt(2);
    const MY_5: MyInt = MyInt(5);
    const MY_10: MyInt = MyInt(10);
    const MY_MIN: MyInt = MyInt(i64::MIN);
    const MY_HALF_MAX: MyInt = MyInt(i64::MAX / 2);
    const MY_MAX: MyInt = MyInt(i64::MAX);
    const SOME_MINUS_1: Option<MyInt> = Some(MY_MINUS_1);
    const SOME_0: Option<MyInt> = Some(MY_0);
    const SOME_1: Option<MyInt> = Some(MY_1);
    const SOME_2: Option<MyInt> = Some(MY_2);
    const SOME_5: Option<MyInt> = Some(MY_5);
    const SOME_10: Option<MyInt> = Some(MY_10);
    const SOME_MIN: Option<MyInt> = Some(MY_MIN);
    const SOME_HALF_MAX: Option<MyInt> = Some(MY_HALF_MAX);
    const SOME_MAX: Option<MyInt> = Some(MY_MAX);
    const NONE: Option<MyInt> = None;

    #[test]
    fn div_my() {
        assert_eq!(MY_5.opt_div(MY_1), SOME_5);
        assert_eq!(SOME_10.opt_div(MY_2), SOME_5);
        assert_eq!(MY_0.opt_div(SOME_1), SOME_0);
        assert_eq!(MY_MAX.opt_div(&SOME_2), SOME_HALF_MAX);
        assert_eq!(MY_1.opt_div(NONE), NONE);
        assert_eq!(NONE.opt_div(MY_1), NONE);
    }

    #[test]
    #[should_panic]
    fn div_by_zero_my() {
        let _ = SOME_10.opt_div(SOME_0);
    }

    #[test]
    fn div_i64() {
        assert_eq!(MY_5.opt_div(5), SOME_1);
        assert_eq!(SOME_10.opt_div(MY_2), SOME_5);
        assert_eq!(MY_0.opt_div(Some(1)), SOME_0);
        assert_eq!(MY_MAX.opt_div(Some(2)), SOME_HALF_MAX);
        assert_eq!(MY_1.opt_div(Option::<i64>::None), NONE);
        assert_eq!(Option::<MyInt>::None.opt_div(MY_1), NONE);
    }

    #[test]
    #[should_panic]
    fn div_by_zero_i64() {
        let _ = SOME_10.opt_div(Some(0));
    }

    #[test]
    fn div_assign_my() {
        let mut my = MY_5;
        my.opt_div_assign(MY_1);
        assert_eq!(my, MY_5);

        let mut some = SOME_10;
        some.opt_div_assign(MY_5);
        assert_eq!(some, SOME_2);

        let mut my = MY_0;
        my.opt_div_assign(SOME_1);
        assert_eq!(my, MY_0);

        let mut my = MY_MAX;
        my.opt_div_assign(&SOME_2);
        assert_eq!(my, MY_HALF_MAX);

        let mut my = MY_1;
        my.opt_div_assign(NONE);
        assert_eq!(my, MY_1);

        let mut some = SOME_2;
        some.opt_div_assign(SOME_1);
        assert_eq!(some, SOME_2);

        let mut some = SOME_10;
        some.opt_div_assign(&SOME_2);
        assert_eq!(some, SOME_5);

        let mut some = SOME_1;
        some.opt_div_assign(NONE);
        assert_eq!(some, SOME_1);

        let mut none = NONE;
        none.opt_div_assign(SOME_1);
        assert_eq!(none, NONE);

        let mut none = NONE;
        none.opt_div_assign(NONE);
        assert_eq!(none, NONE);
    }

    #[test]
    #[should_panic]
    fn div_assign_by_zero_my() {
        let mut some = SOME_10;
        some.opt_div_assign(SOME_0);
    }

    #[test]
    fn div_assign_i64() {
        let mut my = MY_5;
        my.opt_div_assign(1);
        assert_eq!(my, MY_5);

        let mut some = SOME_10;
        some.opt_div_assign(5);
        assert_eq!(some, SOME_2);

        let mut my = MY_0;
        my.opt_div_assign(1);
        assert_eq!(my, MY_0);

        let mut my = MY_MAX;
        my.opt_div_assign(2);
        assert_eq!(my, MY_HALF_MAX);

        let mut my = MY_1;
        my.opt_div_assign(Option::<i64>::None);
        assert_eq!(my, MY_1);

        let mut some = SOME_2;
        some.opt_div_assign(1);
        assert_eq!(some, SOME_2);

        let mut some = SOME_1;
        some.opt_div_assign(Option::<i64>::None);
        assert_eq!(some, SOME_1);

        let mut none = NONE;
        none.opt_div_assign(1);
        assert_eq!(none, NONE);

        let mut none = NONE;
        none.opt_div_assign(Option::<i64>::None);
        assert_eq!(none, NONE);
    }

    #[test]
    #[should_panic]
    fn div_assign_by_zero_i64() {
        let mut some = SOME_10;
        some.opt_div_assign(Some(0));
    }

    #[test]
    fn checked_div() {
        impl OptionCheckedDiv for MyInt {
            type Output = MyInt;
            fn opt_checked_div(self, rhs: MyInt) -> Result<Option<Self::Output>, Error> {
                self.0.opt_checked_div(rhs.0).map(|ok| ok.map(MyInt))
            }
        }

        impl OptionCheckedDiv<i64> for MyInt {
            type Output = MyInt;
            fn opt_checked_div(self, rhs: i64) -> Result<Option<Self::Output>, Error> {
                self.0.opt_checked_div(rhs).map(|ok| ok.map(MyInt))
            }
        }

        assert_eq!(MY_2.opt_checked_div(MY_1), Ok(SOME_2));
        assert_eq!(MY_10.opt_checked_div(SOME_5), Ok(SOME_2));
        assert_eq!(MY_0.opt_checked_div(&SOME_1), Ok(SOME_0));
        assert_eq!(MY_MAX.opt_checked_div(MY_2), Ok(SOME_HALF_MAX));
        assert_eq!(MY_MAX.opt_checked_div(MY_0), Err(Error::DivisionByZero));
        assert_eq!(MY_MIN.opt_checked_div(MY_MINUS_1), Err(Error::Overflow));

        assert_eq!(SOME_2.opt_checked_div(MY_1), Ok(SOME_2));
        assert_eq!(SOME_10.opt_checked_div(SOME_2), Ok(SOME_5));
        assert_eq!(SOME_0.opt_checked_div(&SOME_1), Ok(SOME_0));

        assert_eq!(SOME_MAX.opt_checked_div(MY_2), Ok(SOME_HALF_MAX));
        assert_eq!(SOME_MAX.opt_checked_div(MY_0), Err(Error::DivisionByZero));
        assert_eq!(SOME_MIN.opt_checked_div(MY_MINUS_1), Err(Error::Overflow));
        assert_eq!(SOME_MAX.opt_checked_div(0), Err(Error::DivisionByZero));
        assert_eq!(SOME_MIN.opt_checked_div(-1), Err(Error::Overflow));
        assert_eq!(
            SOME_MAX.opt_checked_div(Some(0)),
            Err(Error::DivisionByZero)
        );
        assert_eq!(SOME_MIN.opt_checked_div(Some(-1)), Err(Error::Overflow));
        assert_eq!(SOME_MAX.opt_checked_div(SOME_0), Err(Error::DivisionByZero));
        assert_eq!(SOME_MIN.opt_checked_div(SOME_MINUS_1), Err(Error::Overflow));
        assert_eq!(MY_MIN.opt_checked_div(NONE), Ok(None));
        assert_eq!(NONE.opt_checked_div(SOME_MIN), Ok(None));
    }

    #[test]
    fn overflowing_div() {
        impl OptionOverflowingDiv for MyInt {
            type Output = MyInt;
            fn opt_overflowing_div(self, rhs: MyInt) -> Option<(Self::Output, bool)> {
                self.0
                    .opt_overflowing_div(rhs.0)
                    .map(|(val, flag)| (MyInt(val), flag))
            }
        }

        impl OptionOverflowingDiv<i64> for MyInt {
            type Output = MyInt;
            fn opt_overflowing_div(self, rhs: i64) -> Option<(Self::Output, bool)> {
                self.0
                    .opt_overflowing_div(rhs)
                    .map(|(val, flag)| (MyInt(val), flag))
            }
        }

        assert_eq!(MY_2.opt_overflowing_div(MY_1), Some((MY_2, false)));
        assert_eq!(MY_0.opt_overflowing_div(MY_1), Some((MY_0, false)));
        assert_eq!(MY_MAX.opt_overflowing_div(MY_2), Some((MY_HALF_MAX, false)));
        assert_eq!(MY_MIN.opt_overflowing_div(MY_MINUS_1), Some((MY_MIN, true)));
        assert_eq!(
            SOME_MIN.opt_overflowing_div(MY_MINUS_1),
            Some((MY_MIN, true))
        );
        assert_eq!(SOME_MIN.opt_overflowing_div(-1), Some((MY_MIN, true)));
        assert_eq!(SOME_MIN.opt_overflowing_div(Some(-1)), Some((MY_MIN, true)));
        assert_eq!(
            SOME_MIN.opt_overflowing_div(&Some(-1)),
            Some((MY_MIN, true))
        );
        assert_eq!(
            MY_MIN.opt_overflowing_div(SOME_MINUS_1),
            Some((MY_MIN, true))
        );
        assert_eq!(
            MY_MIN.opt_overflowing_div(&SOME_MINUS_1),
            Some((MY_MIN, true))
        );
        assert_eq!(MY_MIN.opt_overflowing_div(NONE), None);
        assert_eq!(NONE.opt_overflowing_div(MY_MIN), None);
    }

    #[test]
    fn wrapping_div() {
        impl OptionWrappingDiv for MyInt {
            type Output = MyInt;
            fn opt_wrapping_div(self, rhs: MyInt) -> Option<Self::Output> {
                self.0.opt_wrapping_div(rhs.0).map(MyInt)
            }
        }

        impl OptionWrappingDiv<i64> for MyInt {
            type Output = MyInt;
            fn opt_wrapping_div(self, rhs: i64) -> Option<Self::Output> {
                self.0.opt_wrapping_div(rhs).map(MyInt)
            }
        }

        assert_eq!(MY_2.opt_wrapping_div(MY_1), SOME_2);
        assert_eq!(MY_0.opt_wrapping_div(MY_1), SOME_0);
        assert_eq!(MY_MIN.opt_wrapping_div(MY_MINUS_1), SOME_MIN);
        assert_eq!(SOME_MIN.opt_wrapping_div(MY_MINUS_1), SOME_MIN);
        assert_eq!(SOME_MIN.opt_wrapping_div(-1), SOME_MIN);
        assert_eq!(SOME_MIN.opt_wrapping_div(Some(-1)), SOME_MIN);
        assert_eq!(SOME_MIN.opt_wrapping_div(&Some(-1)), SOME_MIN);
        assert_eq!(MY_MIN.opt_wrapping_div(SOME_MINUS_1), SOME_MIN);
        assert_eq!(MY_MIN.opt_wrapping_div(&SOME_MINUS_1), SOME_MIN);
        assert_eq!(MY_MIN.opt_wrapping_div(NONE), None);
        assert_eq!(NONE.opt_wrapping_div(MY_MIN), None);
    }
}
