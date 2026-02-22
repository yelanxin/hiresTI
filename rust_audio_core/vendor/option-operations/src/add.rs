//! Traits for the addition [`OptionOperations`].

use core::ops::{Add, AddAssign};

use crate::{Error, OptionOperations};

common_option_op!(Add, add, addition);

impl_for_ints!(OptionOverflowingAdd, {
    type Output = Self;
    fn opt_overflowing_add(self, rhs: Self) -> Option<(Self::Output, bool)> {
        Some(self.overflowing_add(rhs))
    }
});

impl_for_ints!(OptionWrappingAdd, {
    type Output = Self;
    fn opt_wrapping_add(self, rhs: Self) -> Option<Self::Output> {
        Some(self.wrapping_add(rhs))
    }
});

option_op_checked!(Add, add, addition);

impl_for_ints_and_duration!(OptionCheckedAdd, {
    type Output = Self;
    fn opt_checked_add(self, rhs: Self) -> Result<Option<Self::Output>, Error> {
        self.checked_add(rhs).ok_or(Error::Overflow).map(Some)
    }
});

#[cfg(feature = "std")]
impl OptionCheckedAdd<std::time::Duration> for std::time::Instant {
    type Output = Self;
    fn opt_checked_add(self, rhs: std::time::Duration) -> Result<Option<Self::Output>, Error> {
        self.checked_add(rhs).ok_or(Error::Overflow).map(Some)
    }
}

#[cfg(feature = "std")]
impl OptionCheckedAdd<std::time::Duration> for std::time::SystemTime {
    type Output = Self;
    fn opt_checked_add(self, rhs: std::time::Duration) -> Result<Option<Self::Output>, Error> {
        self.checked_add(rhs).ok_or(Error::Overflow).map(Some)
    }
}

option_op_saturating!(Add, add, addition);

impl_for_ints_and_duration!(OptionSaturatingAdd, {
    type Output = Self;
    fn opt_saturating_add(self, rhs: Self) -> Option<Self::Output> {
        Some(self.saturating_add(rhs))
    }
});

#[cfg(test)]
mod test {
    use super::*;
    use crate::OptionOperations;
    use core::ops::{Add, AddAssign};

    #[derive(Copy, Clone, Debug, PartialEq, PartialOrd)]
    struct MyInt(u64);

    impl OptionOperations for MyInt {}

    impl Add<MyInt> for MyInt {
        type Output = MyInt;

        fn add(self, rhs: MyInt) -> MyInt {
            MyInt(self.0.add(rhs.0))
        }
    }

    impl Add<u64> for MyInt {
        type Output = MyInt;

        fn add(self, rhs: u64) -> MyInt {
            MyInt(self.0.add(rhs))
        }
    }

    impl AddAssign<MyInt> for MyInt {
        fn add_assign(&mut self, rhs: MyInt) {
            self.0.add_assign(rhs.0)
        }
    }

    impl AddAssign<u64> for MyInt {
        fn add_assign(&mut self, rhs: u64) {
            self.0.add_assign(rhs)
        }
    }

    const MY_0: MyInt = MyInt(0);
    const MY_1: MyInt = MyInt(1);
    const MY_2: MyInt = MyInt(2);
    const MY_MAX: MyInt = MyInt(u64::MAX);
    const SOME_0: Option<MyInt> = Some(MY_0);
    const SOME_1: Option<MyInt> = Some(MY_1);
    const SOME_2: Option<MyInt> = Some(MY_2);
    const SOME_MAX: Option<MyInt> = Some(MY_MAX);
    const NONE: Option<MyInt> = None;

    #[test]
    fn add_my() {
        assert_eq!(MY_1.opt_add(MY_1), SOME_2);
        assert_eq!(SOME_1.opt_add(MY_1), SOME_2);
        assert_eq!(MY_1.opt_add(SOME_1), SOME_2);
        assert_eq!(MY_1.opt_add(&SOME_1), SOME_2);
        assert_eq!(MY_1.opt_add(NONE), NONE);
        assert_eq!(NONE.opt_add(MY_1), NONE);
    }

    #[test]
    fn add_u64() {
        assert_eq!(MY_1.opt_add(1), SOME_2);
        assert_eq!(MY_1.opt_add(Some(1)), SOME_2);
        assert_eq!(SOME_1.opt_add(1), SOME_2);
        assert_eq!(SOME_1.opt_add(Some(1)), SOME_2);
        assert_eq!(SOME_1.opt_add(&Some(1)), SOME_2);
        assert_eq!(MY_1.opt_add(Option::<u64>::None), NONE);
        assert_eq!(Option::<MyInt>::None.opt_add(MY_0), NONE);
    }

    #[test]
    fn add_assign_my() {
        let mut my = MY_1;
        my.opt_add_assign(MY_1);
        assert_eq!(my, MY_2);

        let mut some = SOME_1;
        some.opt_add_assign(MY_1);
        assert_eq!(some, SOME_2);

        let mut my = MY_1;
        my.opt_add_assign(SOME_1);
        assert_eq!(my, MY_2);

        let mut my = MY_1;
        my.opt_add_assign(&SOME_1);
        assert_eq!(my, MY_2);

        let mut my = MY_1;
        my.opt_add_assign(NONE);
        assert_eq!(my, MY_1);

        let mut some = SOME_1;
        some.opt_add_assign(SOME_1);
        assert_eq!(some, SOME_2);

        let mut some = SOME_1;
        some.opt_add_assign(&SOME_1);
        assert_eq!(some, SOME_2);

        let mut some = SOME_1;
        some.opt_add_assign(NONE);
        assert_eq!(some, SOME_1);

        let mut none = NONE;
        none.opt_add_assign(SOME_1);
        assert_eq!(none, NONE);

        let mut none = NONE;
        none.opt_add_assign(NONE);
        assert_eq!(none, NONE);
    }

    #[test]
    fn add_assign_u64() {
        let mut my = MY_1;
        my.opt_add_assign(1);
        assert_eq!(my, MY_2);

        let mut some = SOME_1;
        some.opt_add_assign(1);
        assert_eq!(some, SOME_2);

        let mut my = MY_1;
        my.opt_add_assign(Some(1));
        assert_eq!(my, MY_2);

        let mut my = MY_1;
        my.opt_add_assign(&Some(1));
        assert_eq!(my, MY_2);

        let mut some = SOME_1;
        some.opt_add_assign(Some(1));
        assert_eq!(some, SOME_2);

        let mut some = SOME_1;
        some.opt_add_assign(&Some(1));
        assert_eq!(some, SOME_2);

        let mut none = NONE;
        none.opt_add_assign(Some(1));
        assert_eq!(none, NONE);
    }

    #[test]
    fn checked_add() {
        impl OptionCheckedAdd for MyInt {
            type Output = MyInt;
            fn opt_checked_add(self, rhs: MyInt) -> Result<Option<Self::Output>, Error> {
                self.0.opt_checked_add(rhs.0).map(|ok| ok.map(MyInt))
            }
        }

        impl OptionCheckedAdd<u64> for MyInt {
            type Output = MyInt;
            fn opt_checked_add(self, rhs: u64) -> Result<Option<Self::Output>, Error> {
                self.0.opt_checked_add(rhs).map(|ok| ok.map(MyInt))
            }
        }

        assert_eq!(MY_1.opt_checked_add(MY_1), Ok(SOME_2));
        assert_eq!(MY_1.opt_checked_add(SOME_1), Ok(SOME_2));
        assert_eq!(MY_1.opt_checked_add(&SOME_1), Ok(SOME_2));
        assert_eq!(MY_MAX.opt_checked_add(MY_1), Err(Error::Overflow));

        assert_eq!(SOME_1.opt_checked_add(MY_1), Ok(SOME_2));
        assert_eq!(SOME_1.opt_checked_add(SOME_1), Ok(SOME_2));
        assert_eq!(SOME_1.opt_checked_add(&SOME_1), Ok(SOME_2));

        assert_eq!(SOME_MAX.opt_checked_add(MY_1), Err(Error::Overflow));
        assert_eq!(SOME_MAX.opt_checked_add(1), Err(Error::Overflow));
        assert_eq!(SOME_MAX.opt_checked_add(Some(1)), Err(Error::Overflow));
        assert_eq!(MY_1.opt_checked_add(SOME_MAX), Err(Error::Overflow));
        assert_eq!(MY_MAX.opt_checked_add(NONE), Ok(None));
        assert_eq!(NONE.opt_checked_add(SOME_MAX), Ok(None));
    }

    #[test]
    fn saturating_add() {
        impl OptionSaturatingAdd for MyInt {
            type Output = MyInt;
            fn opt_saturating_add(self, rhs: MyInt) -> Option<Self::Output> {
                self.0.opt_saturating_add(rhs.0).map(MyInt)
            }
        }

        impl OptionSaturatingAdd<u64> for MyInt {
            type Output = MyInt;
            fn opt_saturating_add(self, rhs: u64) -> Option<Self::Output> {
                self.0.opt_saturating_add(rhs).map(MyInt)
            }
        }

        assert_eq!(MY_1.opt_saturating_add(MY_1), SOME_2);
        assert_eq!(MY_MAX.opt_saturating_add(MY_1), SOME_MAX);
        assert_eq!(SOME_MAX.opt_saturating_add(MY_1), SOME_MAX);
        assert_eq!(SOME_MAX.opt_saturating_add(1), SOME_MAX);
        assert_eq!(SOME_MAX.opt_saturating_add(Some(1)), SOME_MAX);
        assert_eq!(SOME_MAX.opt_saturating_add(&Some(1)), SOME_MAX);
        assert_eq!(MY_1.opt_saturating_add(SOME_MAX), SOME_MAX);
        assert_eq!(MY_1.opt_saturating_add(&SOME_MAX), SOME_MAX);
        assert_eq!(MY_MAX.opt_saturating_add(NONE), NONE);
        assert_eq!(NONE.opt_saturating_add(SOME_MAX), NONE);
    }

    #[test]
    fn overflowing_add() {
        impl OptionOverflowingAdd for MyInt {
            type Output = MyInt;
            fn opt_overflowing_add(self, rhs: MyInt) -> Option<(Self::Output, bool)> {
                self.0
                    .opt_overflowing_add(rhs.0)
                    .map(|(val, flag)| (MyInt(val), flag))
            }
        }

        impl OptionOverflowingAdd<u64> for MyInt {
            type Output = MyInt;
            fn opt_overflowing_add(self, rhs: u64) -> Option<(Self::Output, bool)> {
                self.0
                    .opt_overflowing_add(rhs)
                    .map(|(val, flag)| (MyInt(val), flag))
            }
        }

        assert_eq!(MY_1.opt_overflowing_add(MY_1), Some((MY_2, false)));
        assert_eq!(MY_MAX.opt_overflowing_add(MY_1), Some((MY_0, true)));
        assert_eq!(SOME_MAX.opt_overflowing_add(MY_1), Some((MY_0, true)));
        assert_eq!(SOME_MAX.opt_overflowing_add(1), Some((MY_0, true)));
        assert_eq!(SOME_MAX.opt_overflowing_add(Some(1)), Some((MY_0, true)));
        assert_eq!(SOME_MAX.opt_overflowing_add(&Some(1)), Some((MY_0, true)));
        assert_eq!(MY_1.opt_overflowing_add(SOME_MAX), Some((MY_0, true)));
        assert_eq!(MY_1.opt_overflowing_add(&SOME_MAX), Some((MY_0, true)));
        assert_eq!(MY_MAX.opt_overflowing_add(NONE), None);
        assert_eq!(NONE.opt_overflowing_add(SOME_MAX), None);
    }

    #[test]
    fn wrapping_add() {
        impl OptionWrappingAdd for MyInt {
            type Output = MyInt;
            fn opt_wrapping_add(self, rhs: MyInt) -> Option<Self::Output> {
                self.0.opt_wrapping_add(rhs.0).map(MyInt)
            }
        }

        impl OptionWrappingAdd<u64> for MyInt {
            type Output = MyInt;
            fn opt_wrapping_add(self, rhs: u64) -> Option<Self::Output> {
                self.0.opt_wrapping_add(rhs).map(MyInt)
            }
        }

        assert_eq!(MY_1.opt_wrapping_add(MY_1), SOME_2);
        assert_eq!(MY_MAX.opt_wrapping_add(MY_1), SOME_0);
        assert_eq!(SOME_MAX.opt_wrapping_add(MY_1), SOME_0);
        assert_eq!(SOME_MAX.opt_wrapping_add(1), SOME_0);
        assert_eq!(SOME_MAX.opt_wrapping_add(Some(1)), SOME_0);
        assert_eq!(SOME_MAX.opt_wrapping_add(&Some(1)), SOME_0);
        assert_eq!(MY_1.opt_wrapping_add(SOME_MAX), SOME_0);
        assert_eq!(MY_1.opt_wrapping_add(&SOME_MAX), SOME_0);
        assert_eq!(MY_MAX.opt_wrapping_add(NONE), NONE);
        assert_eq!(NONE.opt_wrapping_add(SOME_MAX), NONE);
    }
}
