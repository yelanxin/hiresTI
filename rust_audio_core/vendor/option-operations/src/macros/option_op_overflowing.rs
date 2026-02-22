macro_rules! option_op_overflowing {
    ($trait:ident, $op:ident, $op_name:ident $(, $extra_doc:expr)? $(,)?) => {
        paste::paste! {
            #[doc = "Trait for values and `Option`s overflowing " $op_name "."]
            ///
            /// Implementing this trait leads to the following auto-implementations:
            ///
            #[doc = "- `" [<OptionOverflowing $trait>] "<Option<InnerRhs>>` for `T`."]
            #[doc = "- `" [<OptionOverflowing $trait>] "<Rhs>` for `Option<T>`."]
            #[doc = "- `" [<OptionOverflowing $trait>] "<Option<InnerRhs>>` for `Option<T>`."]
            /// - ... and some variants with references.
            ///
            /// Note that since the `std` library doesn't define any
            #[doc = "`" [<Overflowing $trait >] "` trait, "]
            /// users must provide the base implementation for the inner type.
            pub trait [<OptionOverflowing $trait>]<Rhs = Self, InnerRhs = Rhs> {
                #[doc = "The resulting inner type after applying the " $op_name "."]
                type Output;

                #[doc = "Returns a tuple of the " $op_name]
                /// along with a boolean indicating whether an arithmetic overflow
                /// would occur. If an overflow would have occurred then `self` is returned.
                ///
                /// Returns `None` if at least one argument is `None`.
                $(#[doc = $extra_doc])?
                fn [<opt_overflowing_ $op>](self, rhs: Rhs) -> Option<(Self::Output, bool)>;
            }

            impl<T, InnerRhs> [<OptionOverflowing $trait>]<Option<InnerRhs>, InnerRhs> for T
            where
                T: OptionOperations + [<OptionOverflowing $trait>]<InnerRhs>,
            {
                type Output = <T as [<OptionOverflowing $trait>]<InnerRhs>>::Output;

                fn [<opt_overflowing_ $op>](self, rhs: Option<InnerRhs>) -> Option<(Self::Output, bool)> {
                    rhs.and_then(|inner_rhs| self.[<opt_overflowing_ $op>](inner_rhs))
                }
            }

            impl<T, InnerRhs> [<OptionOverflowing $trait>]<&Option<InnerRhs>, InnerRhs> for T
            where
                T: OptionOperations + [<OptionOverflowing $trait>]<InnerRhs>,
                InnerRhs: Copy,
            {
                type Output = <T as [<OptionOverflowing $trait>]<InnerRhs>>::Output;

                fn [<opt_overflowing_ $op>](self, rhs: &Option<InnerRhs>) -> Option<(Self::Output, bool)> {
                    rhs.as_ref()
                        .and_then(|inner_rhs| self.[<opt_overflowing_ $op>](*inner_rhs))
                }
            }

            impl<T, Rhs> [<OptionOverflowing $trait>]<Rhs> for Option<T>
            where
                T: OptionOperations + [<OptionOverflowing $trait>]<Rhs>,
            {
                type Output = <T as [<OptionOverflowing $trait>]<Rhs>>::Output;

                fn [<opt_overflowing_ $op>](self, rhs: Rhs) -> Option<(Self::Output, bool)> {
                    self.and_then(|inner_self| inner_self.[<opt_overflowing_ $op>](rhs))
                }
            }

            impl<T, InnerRhs> [<OptionOverflowing $trait>]<Option<InnerRhs>, InnerRhs> for Option<T>
            where
                T: OptionOperations + [<OptionOverflowing $trait>]<InnerRhs>,
            {
                type Output = <T as [<OptionOverflowing $trait>]<InnerRhs>>::Output;

                fn [<opt_overflowing_ $op>](self, rhs: Option<InnerRhs>) -> Option<(Self::Output, bool)> {
                    self.zip(rhs)
                        .and_then(|(inner_self, inner_rhs)| inner_self.[<opt_overflowing_ $op>](inner_rhs))
                }
            }

            impl<T, InnerRhs> [<OptionOverflowing $trait>]<&Option<InnerRhs>, InnerRhs> for Option<T>
            where
                T: OptionOperations + [<OptionOverflowing $trait>]<InnerRhs>,
                InnerRhs: Copy,
            {
                type Output = <T as [<OptionOverflowing $trait>]<InnerRhs>>::Output;

                fn [<opt_overflowing_ $op>](self, rhs: &Option<InnerRhs>) -> Option<(Self::Output, bool)> {
                    self.zip(rhs.as_ref())
                        .and_then(|(inner_self, inner_rhs)| inner_self.[<opt_overflowing_ $op>](*inner_rhs))
                }
            }
        }
    };
}
