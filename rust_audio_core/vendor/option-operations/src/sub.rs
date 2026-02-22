//! Traits for the substraction [`OptionOperations`].

use core::ops::{Sub, SubAssign};

use crate::{Error, OptionOperations};

common_option_op!(Sub, sub, substraction);

impl_for_ints!(OptionOverflowingSub, {
    type Output = Self;
    fn opt_overflowing_sub(self, rhs: Self) -> Option<(Self::Output, bool)> {
        Some(self.overflowing_sub(rhs))
    }
});

impl_for_ints!(OptionWrappingSub, {
    type Output = Self;
    fn opt_wrapping_sub(self, rhs: Self) -> Option<Self::Output> {
        Some(self.wrapping_sub(rhs))
    }
});

option_op_checked!(Sub, sub, substraction);

impl_for_ints_and_duration!(OptionCheckedSub, {
    type Output = Self;
    fn opt_checked_sub(self, rhs: Self) -> Result<Option<Self::Output>, Error> {
        self.checked_sub(rhs).ok_or(Error::Overflow).map(Some)
    }
});

#[cfg(feature = "std")]
impl OptionCheckedSub<std::time::Duration> for std::time::Instant {
    type Output = Self;
    fn opt_checked_sub(self, rhs: std::time::Duration) -> Result<Option<Self::Output>, Error> {
        self.checked_sub(rhs).ok_or(Error::Overflow).map(Some)
    }
}

#[cfg(feature = "std")]
impl OptionCheckedSub<std::time::Duration> for std::time::SystemTime {
    type Output = Self;
    fn opt_checked_sub(self, rhs: std::time::Duration) -> Result<Option<Self::Output>, Error> {
        self.checked_sub(rhs).ok_or(Error::Overflow).map(Some)
    }
}

option_op_saturating!(Sub, sub, substraction);

impl_for_ints_and_duration!(OptionSaturatingSub, {
    type Output = Self;
    fn opt_saturating_sub(self, rhs: Self) -> Option<Self::Output> {
        Some(self.saturating_sub(rhs))
    }
});

#[cfg(test)]
mod test {
    use super::*;
    use crate::OptionOperations;
    use core::ops::{Sub, SubAssign};

    #[derive(Copy, Clone, Debug, PartialEq, PartialOrd)]
    struct MyInt(u64);

    impl OptionOperations for MyInt {}

    impl Sub<MyInt> for MyInt {
        type Output = MyInt;

        fn sub(self, rhs: MyInt) -> MyInt {
            MyInt(self.0.sub(rhs.0))
        }
    }

    impl Sub<u64> for MyInt {
        type Output = MyInt;

        fn sub(self, rhs: u64) -> MyInt {
            MyInt(self.0.sub(rhs))
        }
    }

    impl SubAssign<MyInt> for MyInt {
        fn sub_assign(&mut self, rhs: MyInt) {
            self.0.sub_assign(rhs.0)
        }
    }

    impl SubAssign<u64> for MyInt {
        fn sub_assign(&mut self, rhs: u64) {
            self.0.sub_assign(rhs)
        }
    }

    const MY_0: MyInt = MyInt(0);
    const MY_1: MyInt = MyInt(1);
    const MY_2: MyInt = MyInt(2);
    const MY_3: MyInt = MyInt(3);
    const MY_MAX: MyInt = MyInt(u64::MAX);
    const SOME_0: Option<MyInt> = Some(MY_0);
    const SOME_1: Option<MyInt> = Some(MY_1);
    const SOME_2: Option<MyInt> = Some(MY_2);
    const SOME_3: Option<MyInt> = Some(MY_3);
    const SOME_MAX: Option<MyInt> = Some(MY_MAX);
    const NONE: Option<MyInt> = None;

    #[test]
    fn sub_my() {
        assert_eq!(MY_3.opt_sub(MY_1), SOME_2);
        assert_eq!(SOME_3.opt_sub(MY_1), SOME_2);
        assert_eq!(MY_3.opt_sub(SOME_1), SOME_2);
        assert_eq!(MY_3.opt_sub(&SOME_1), SOME_2);
        assert_eq!(MY_3.opt_sub(NONE), NONE);
        assert_eq!(NONE.opt_sub(MY_3), NONE);
    }

    #[test]
    fn sub_u64() {
        assert_eq!(MY_3.opt_sub(1), SOME_2);
        assert_eq!(MY_3.opt_sub(Some(1)), SOME_2);
        assert_eq!(SOME_3.opt_sub(1), SOME_2);
        assert_eq!(SOME_3.opt_sub(Some(1)), SOME_2);
        assert_eq!(SOME_3.opt_sub(&Some(1)), SOME_2);
        assert_eq!(MY_3.opt_sub(Option::<u64>::None), NONE);
        assert_eq!(Option::<MyInt>::None.opt_sub(MY_0), NONE);
    }

    #[test]
    fn sub_assign_my() {
        let mut my = MY_3;
        my.opt_sub_assign(MY_1);
        assert_eq!(my, MY_2);

        let mut some = SOME_3;
        some.opt_sub_assign(MY_1);
        assert_eq!(some, SOME_2);

        let mut my = MY_3;
        my.opt_sub_assign(SOME_1);
        assert_eq!(my, MY_2);

        let mut my = MY_3;
        my.opt_sub_assign(&SOME_1);
        assert_eq!(my, MY_2);

        let mut my = MY_3;
        my.opt_sub_assign(NONE);
        assert_eq!(my, MY_3);

        let mut some = SOME_3;
        some.opt_sub_assign(SOME_1);
        assert_eq!(some, SOME_2);

        let mut some = SOME_3;
        some.opt_sub_assign(&SOME_1);
        assert_eq!(some, SOME_2);

        let mut some = SOME_3;
        some.opt_sub_assign(NONE);
        assert_eq!(some, SOME_3);

        let mut none = NONE;
        none.opt_sub_assign(SOME_1);
        assert_eq!(none, NONE);

        let mut none = NONE;
        none.opt_sub_assign(NONE);
        assert_eq!(none, NONE);
    }

    #[test]
    fn sub_assign_u64() {
        let mut my = MY_3;
        my.opt_sub_assign(1);
        assert_eq!(my, MY_2);

        let mut some = SOME_3;
        some.opt_sub_assign(1);
        assert_eq!(some, SOME_2);

        let mut my = MY_3;
        my.opt_sub_assign(Some(1));
        assert_eq!(my, MY_2);

        let mut my = MY_3;
        my.opt_sub_assign(&Some(1));
        assert_eq!(my, MY_2);

        let mut some = SOME_3;
        some.opt_sub_assign(Some(1));
        assert_eq!(some, SOME_2);

        let mut some = SOME_3;
        some.opt_sub_assign(&Some(1));
        assert_eq!(some, SOME_2);

        let mut none = NONE;
        none.opt_sub_assign(Some(1));
        assert_eq!(none, NONE);
    }

    #[test]
    fn checked_sub() {
        impl OptionCheckedSub for MyInt {
            type Output = MyInt;
            fn opt_checked_sub(self, rhs: MyInt) -> Result<Option<Self::Output>, Error> {
                self.0.opt_checked_sub(rhs.0).map(|ok| ok.map(MyInt))
            }
        }

        impl OptionCheckedSub<u64> for MyInt {
            type Output = MyInt;
            fn opt_checked_sub(self, rhs: u64) -> Result<Option<Self::Output>, Error> {
                self.0.opt_checked_sub(rhs).map(|ok| ok.map(MyInt))
            }
        }

        assert_eq!(MY_3.opt_checked_sub(MY_1), Ok(SOME_2));
        assert_eq!(MY_3.opt_checked_sub(SOME_1), Ok(SOME_2));
        assert_eq!(MY_3.opt_checked_sub(&SOME_1), Ok(SOME_2));
        assert_eq!(MY_0.opt_checked_sub(MY_1), Err(Error::Overflow));

        assert_eq!(SOME_3.opt_checked_sub(MY_1), Ok(SOME_2));
        assert_eq!(SOME_3.opt_checked_sub(SOME_1), Ok(SOME_2));
        assert_eq!(SOME_3.opt_checked_sub(&SOME_1), Ok(SOME_2));

        assert_eq!(SOME_0.opt_checked_sub(MY_1), Err(Error::Overflow));
        assert_eq!(SOME_0.opt_checked_sub(1), Err(Error::Overflow));
        assert_eq!(SOME_0.opt_checked_sub(Some(1)), Err(Error::Overflow));
        assert_eq!(MY_0.opt_checked_sub(SOME_1), Err(Error::Overflow));
        assert_eq!(MY_0.opt_checked_sub(NONE), Ok(None));
        assert_eq!(NONE.opt_checked_sub(MY_0), Ok(None));
    }

    #[test]
    fn saturating_sub() {
        impl OptionSaturatingSub for MyInt {
            type Output = MyInt;
            fn opt_saturating_sub(self, rhs: MyInt) -> Option<Self::Output> {
                self.0.opt_saturating_sub(rhs.0).map(MyInt)
            }
        }

        impl OptionSaturatingSub<u64> for MyInt {
            type Output = MyInt;
            fn opt_saturating_sub(self, rhs: u64) -> Option<Self::Output> {
                self.0.opt_saturating_sub(rhs).map(MyInt)
            }
        }

        assert_eq!(MY_3.opt_saturating_sub(MY_1), SOME_2);
        assert_eq!(MY_1.opt_saturating_sub(MY_2), SOME_0);
        assert_eq!(SOME_1.opt_saturating_sub(MY_2), SOME_0);
        assert_eq!(SOME_1.opt_saturating_sub(2), SOME_0);
        assert_eq!(SOME_1.opt_saturating_sub(Some(2)), SOME_0);
        assert_eq!(SOME_1.opt_saturating_sub(&Some(2)), SOME_0);
        assert_eq!(MY_1.opt_saturating_sub(SOME_2), SOME_0);
        assert_eq!(MY_1.opt_saturating_sub(&SOME_2), SOME_0);
        assert_eq!(MY_1.opt_saturating_sub(NONE), NONE);
        assert_eq!(NONE.opt_saturating_sub(MY_1), NONE);
    }

    #[test]
    fn overflowing_sub() {
        impl OptionOverflowingSub for MyInt {
            type Output = MyInt;
            fn opt_overflowing_sub(self, rhs: MyInt) -> Option<(Self::Output, bool)> {
                self.0
                    .opt_overflowing_sub(rhs.0)
                    .map(|(val, flag)| (MyInt(val), flag))
            }
        }

        impl OptionOverflowingSub<u64> for MyInt {
            type Output = MyInt;
            fn opt_overflowing_sub(self, rhs: u64) -> Option<(Self::Output, bool)> {
                self.0
                    .opt_overflowing_sub(rhs)
                    .map(|(val, flag)| (MyInt(val), flag))
            }
        }

        assert_eq!(MY_3.opt_overflowing_sub(MY_1), Some((MY_2, false)));
        assert_eq!(MY_1.opt_overflowing_sub(MY_2), Some((MY_MAX, true)));
        assert_eq!(SOME_1.opt_overflowing_sub(MY_2), Some((MY_MAX, true)));
        assert_eq!(SOME_1.opt_overflowing_sub(2), Some((MY_MAX, true)));
        assert_eq!(SOME_1.opt_overflowing_sub(Some(2)), Some((MY_MAX, true)));
        assert_eq!(SOME_1.opt_overflowing_sub(&Some(2)), Some((MY_MAX, true)));
        assert_eq!(MY_1.opt_overflowing_sub(SOME_2), Some((MY_MAX, true)));
        assert_eq!(MY_1.opt_overflowing_sub(&SOME_2), Some((MY_MAX, true)));
        assert_eq!(MY_1.opt_overflowing_sub(NONE), None);
        assert_eq!(NONE.opt_overflowing_sub(MY_1), None);
    }

    #[test]
    fn wrapping_sub() {
        impl OptionWrappingSub for MyInt {
            type Output = MyInt;
            fn opt_wrapping_sub(self, rhs: MyInt) -> Option<Self::Output> {
                self.0.opt_wrapping_sub(rhs.0).map(MyInt)
            }
        }

        impl OptionWrappingSub<u64> for MyInt {
            type Output = MyInt;
            fn opt_wrapping_sub(self, rhs: u64) -> Option<Self::Output> {
                self.0.opt_wrapping_sub(rhs).map(MyInt)
            }
        }

        assert_eq!(MY_3.opt_wrapping_sub(MY_1), SOME_2);
        assert_eq!(MY_1.opt_wrapping_sub(MY_2), SOME_MAX);
        assert_eq!(SOME_1.opt_wrapping_sub(MY_2), SOME_MAX);
        assert_eq!(SOME_1.opt_wrapping_sub(2), SOME_MAX);
        assert_eq!(SOME_1.opt_wrapping_sub(Some(2)), SOME_MAX);
        assert_eq!(SOME_1.opt_wrapping_sub(&Some(2)), SOME_MAX);
        assert_eq!(MY_1.opt_wrapping_sub(SOME_2), SOME_MAX);
        assert_eq!(MY_1.opt_wrapping_sub(&SOME_2), SOME_MAX);
        assert_eq!(MY_1.opt_wrapping_sub(NONE), None);
        assert_eq!(NONE.opt_wrapping_sub(MY_1), None);
    }
}
