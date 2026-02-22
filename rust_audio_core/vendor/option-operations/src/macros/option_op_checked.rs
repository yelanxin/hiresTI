macro_rules! option_op_checked {
    ($trait:ident, $op:ident, $op_name:ident $(, $extra_doc:expr)? $(,)?) => {
        paste::paste! {
            #[doc = "Trait for values and `Option`s checked " $op_name "."]
            ///
            /// Implementing this trait leads to the following auto-implementations:
            ///
            #[doc = "- `" [<OptionChecked $trait>] "<Option<InnerRhs>>` for `T`."]
            #[doc = "- `" [<OptionChecked $trait>] "<Rhs>` for `Option<T>`."]
            #[doc = "- `" [<OptionChecked $trait>] "<Option<InnerRhs>>` for `Option<T>`."]
            /// - ... and some variants with references.
            ///
            /// Note that since the `std` library doesn't define any
            #[doc = "`" [<Checked $trait >] "` trait, "]
            /// users must provide the base implementation for the inner type.
            pub trait [<OptionChecked $trait>]<Rhs = Self, InnerRhs = Rhs> {
                #[doc = "The resulting inner type after applying the " $op_name "."]
                type Output;

                #[doc = "Computes the checked " $op_name "."]
                ///
                /// - Returns `Ok(Some(result))` if `result` could be computed.
                /// - Returns `Ok(None)` if at least one argument is `None`.
                /// - Returns `Err(Error::Overflow)` if an overflow occured.
                $(#[doc = $extra_doc])?
                fn [<opt_checked_ $op>](self, rhs: Rhs) -> Result<Option<Self::Output>, Error>;
            }

            impl<T, InnerRhs> [<OptionChecked $trait>]<Option<InnerRhs>, InnerRhs> for T
            where
                T: OptionOperations + [<OptionChecked $trait>]<InnerRhs>,
            {
                type Output = <T as [<OptionChecked $trait>]<InnerRhs>>::Output;

                fn [<opt_checked_ $op>](self, rhs: Option<InnerRhs>) -> Result<Option<Self::Output>, Error> {
                    if let Some(inner_rhs) = rhs {
                        self.[<opt_checked_ $op>](inner_rhs)
                    } else {
                        Ok(None)
                    }
                }
            }

            impl<T, InnerRhs> [<OptionChecked $trait>]<&Option<InnerRhs>, InnerRhs> for T
            where
                T: OptionOperations + [<OptionChecked $trait>]<InnerRhs>,
                InnerRhs: Copy,
            {
                type Output = <T as [<OptionChecked $trait>]<InnerRhs>>::Output;

                fn [<opt_checked_ $op>](self, rhs: &Option<InnerRhs>) -> Result<Option<Self::Output>, Error> {
                    if let Some(inner_rhs) = rhs.as_ref() {
                        self.[<opt_checked_ $op>](*inner_rhs)
                    } else {
                        Ok(None)
                    }
                }
            }

            impl<T, Rhs> [<OptionChecked $trait>]<Rhs> for Option<T>
            where
                T: OptionOperations + [<OptionChecked $trait>]<Rhs>,
            {
                type Output = <T as [<OptionChecked $trait>]<Rhs>>::Output;

                fn [<opt_checked_ $op>](self, rhs: Rhs) -> Result<Option<Self::Output>, Error> {
                    if let Some(inner_self) = self {
                        inner_self.[<opt_checked_ $op>](rhs)
                    } else {
                        Ok(None)
                    }
                }
            }

            impl<T, InnerRhs> [<OptionChecked $trait>]<Option<InnerRhs>, InnerRhs> for Option<T>
            where
                T: OptionOperations + [<OptionChecked $trait>]<InnerRhs>,
            {
                type Output = <T as [<OptionChecked $trait>]<InnerRhs>>::Output;

                fn [<opt_checked_ $op>](self, rhs: Option<InnerRhs>) -> Result<Option<Self::Output>, Error> {
                    if let (Some(inner_self), Some(inner_rhs)) = (self, rhs) {
                        inner_self.[<opt_checked_ $op>](inner_rhs)
                    } else {
                        Ok(None)
                    }
                }
            }

            impl<T, InnerRhs> [<OptionChecked $trait>]<&Option<InnerRhs>, InnerRhs> for Option<T>
            where
                T: OptionOperations + [<OptionChecked $trait>]<InnerRhs>,
                InnerRhs: Copy,
            {
                type Output = <T as [<OptionChecked $trait>]<InnerRhs>>::Output;

                fn [<opt_checked_ $op>](self, rhs: &Option<InnerRhs>) -> Result<Option<Self::Output>, Error> {
                    if let (Some(inner_self), Some(inner_rhs)) = (self, rhs.as_ref()) {
                        inner_self.[<opt_checked_ $op>](*inner_rhs)
                    } else {
                        Ok(None)
                    }
                }
            }
        }
    };
}
