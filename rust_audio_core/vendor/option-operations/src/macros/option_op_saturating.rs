macro_rules! option_op_saturating {
    ($trait:ident, $op:ident, $op_name:ident $(,)?) => {
        paste::paste! {
            #[doc = "Trait for values and `Option`s saturating " $op_name "."]
            ///
            /// Implementing this trait leads to the following auto-implementations:
            ///
            #[doc = "- `" [<OptionSaturating $trait>] "<Option<InnerRhs>>` for `T`."]
            #[doc = "- `" [<OptionSaturating $trait>] "<Rhs>` for `Option<T>`."]
            #[doc = "- `" [<OptionSaturating $trait>] "<Option<InnerRhs>>` for `Option<T>`."]
            /// - ... and some variants with references.
            ///
            /// Note that since the `std` library doesn't define any
            #[doc = "`" [<Saturating $trait >] "` trait, "]
            /// users must provide the base implementation for the inner type.
            pub trait [<OptionSaturating $trait>]<Rhs = Self, InnerRhs = Rhs> {
                #[doc = "The resulting inner type after applying the " $op_name "."]
                type Output;

                #[doc = "Computes the " $op_name]
                /// saturating at the numeric bounds instead of overflowing.
                ///
                /// Returns `None` if at least one argument is `None`.
                fn [<opt_saturating_ $op>](self, rhs: Rhs) -> Option<Self::Output>;
            }

            impl<T, InnerRhs> [<OptionSaturating $trait>]<Option<InnerRhs>, InnerRhs> for T
            where
                T: OptionOperations + [<OptionSaturating $trait>]<InnerRhs>,
            {
                type Output = <T as [<OptionSaturating $trait>]<InnerRhs>>::Output;

                fn [<opt_saturating_ $op>](self, rhs: Option<InnerRhs>) -> Option<Self::Output> {
                    rhs.and_then(|inner_rhs| self.[<opt_saturating_ $op>](inner_rhs))
                }
            }

            impl<T, InnerRhs> [<OptionSaturating $trait>]<&Option<InnerRhs>, InnerRhs> for T
            where
                T: OptionOperations + [<OptionSaturating $trait>]<InnerRhs>,
                InnerRhs: Copy,
            {
                type Output = <T as [<OptionSaturating $trait>]<InnerRhs>>::Output;

                fn [<opt_saturating_ $op>](self, rhs: &Option<InnerRhs>) -> Option<Self::Output> {
                    rhs.as_ref()
                        .and_then(|inner_rhs| self.[<opt_saturating_ $op>](*inner_rhs))
                }
            }

            impl<T, Rhs> [<OptionSaturating $trait>]<Rhs> for Option<T>
            where
                T: OptionOperations + [<OptionSaturating $trait>]<Rhs>,
            {
                type Output = <T as [<OptionSaturating $trait>]<Rhs>>::Output;

                fn [<opt_saturating_ $op>](self, rhs: Rhs) -> Option<Self::Output> {
                    self.and_then(|inner_self| inner_self.[<opt_saturating_ $op>](rhs))
                }
            }

            impl<T, InnerRhs> [<OptionSaturating $trait>]<Option<InnerRhs>, InnerRhs> for Option<T>
            where
                T: OptionOperations + [<OptionSaturating $trait>]<InnerRhs>,
            {
                type Output = <T as [<OptionSaturating $trait>]<InnerRhs>>::Output;

                fn [<opt_saturating_ $op>](self, rhs: Option<InnerRhs>) -> Option<Self::Output> {
                    self.zip(rhs)
                        .and_then(|(inner_self, inner_rhs)| inner_self.[<opt_saturating_ $op>](inner_rhs))
                }
            }

            impl<T, InnerRhs> [<OptionSaturating $trait>]<&Option<InnerRhs>, InnerRhs> for Option<T>
            where
                T: OptionOperations + [<OptionSaturating $trait>]<InnerRhs>,
                InnerRhs: Copy,
            {
                type Output = <T as [<OptionSaturating $trait>]<InnerRhs>>::Output;

                fn [<opt_saturating_ $op>](self, rhs: &Option<InnerRhs>) -> Option<Self::Output> {
                    self.zip(rhs.as_ref())
                        .and_then(|(inner_self, inner_rhs)| inner_self.[<opt_saturating_ $op>](*inner_rhs))
                }
            }
        }
    };
}
