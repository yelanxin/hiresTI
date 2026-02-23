macro_rules! option_op_wrapping {
    ($trait:ident, $op:ident, $op_name:ident $(, $extra_doc:expr)? $(,)?) => {
        paste::paste! {
            #[doc = "Trait for values and `Option`s wrapping " $op_name "."]
            ///
            /// Implementing this trait leads to the following auto-implementations:
            ///
            #[doc = "- `" [<OptionWrapping $trait>] "<Option<InnerRhs>>` for `T`."]
            #[doc = "- `" [<OptionWrapping $trait>] "<Rhs>` for `Option<T>`."]
            #[doc = "- `" [<OptionWrapping $trait>] "<Option<InnerRhs>>` for `Option<T>`."]
            /// - ... and some variants with references.
            ///
            /// Note that since the `std` library doesn't define any
            #[doc = "`" [<Wrapping $trait >] "` trait, "]
            /// users must provide the base implementation for the inner type.
            pub trait [<OptionWrapping $trait>]<Rhs = Self, InnerRhs = Rhs> {
                #[doc = "The resulting inner type after applying the " $op_name "."]
                type Output;

                #[doc = "Computes the " $op_name]
                /// wrapping at the numeric bounds instead of overflowing.
                ///
                /// Returns `None` if at least one argument is `None`.
                $(#[doc = $extra_doc])?
                fn [<opt_wrapping_ $op>](self, rhs: Rhs) -> Option<Self::Output>;
            }

            impl<T, InnerRhs> [<OptionWrapping $trait>]<Option<InnerRhs>, InnerRhs> for T
            where
                T: OptionOperations + [<OptionWrapping $trait>]<InnerRhs>,
            {
                type Output = <T as [<OptionWrapping $trait>]<InnerRhs>>::Output;

                fn [<opt_wrapping_ $op>](self, rhs: Option<InnerRhs>) -> Option<Self::Output> {
                    rhs.and_then(|inner_rhs| self.[<opt_wrapping_ $op>](inner_rhs))
                }
            }

            impl<T, InnerRhs> [<OptionWrapping $trait>]<&Option<InnerRhs>, InnerRhs> for T
            where
                T: OptionOperations + [<OptionWrapping $trait>]<InnerRhs>,
                InnerRhs: Copy,
            {
                type Output = <T as [<OptionWrapping $trait>]<InnerRhs>>::Output;

                fn [<opt_wrapping_ $op>](self, rhs: &Option<InnerRhs>) -> Option<Self::Output> {
                    rhs.as_ref()
                        .and_then(|inner_rhs| self.[<opt_wrapping_ $op>](*inner_rhs))
                }
            }

            impl<T, Rhs> [<OptionWrapping $trait>]<Rhs> for Option<T>
            where
                T: OptionOperations + [<OptionWrapping $trait>]<Rhs>,
            {
                type Output = <T as [<OptionWrapping $trait>]<Rhs>>::Output;

                fn [<opt_wrapping_ $op>](self, rhs: Rhs) -> Option<Self::Output> {
                    self.and_then(|inner_self| inner_self.[<opt_wrapping_ $op>](rhs))
                }
            }

            impl<T, InnerRhs> [<OptionWrapping $trait>]<Option<InnerRhs>, InnerRhs> for Option<T>
            where
                T: OptionOperations + [<OptionWrapping $trait>]<InnerRhs>,
            {
                type Output = <T as [<OptionWrapping $trait>]<InnerRhs>>::Output;

                fn [<opt_wrapping_ $op>](self, rhs: Option<InnerRhs>) -> Option<Self::Output> {
                    self.zip(rhs)
                        .and_then(|(inner_self, inner_rhs)| inner_self.[<opt_wrapping_ $op>](inner_rhs))
                }
            }

            impl<T, InnerRhs> [<OptionWrapping $trait>]<&Option<InnerRhs>, InnerRhs> for Option<T>
            where
                T: OptionOperations + [<OptionWrapping $trait>]<InnerRhs>,
                InnerRhs: Copy,
            {
                type Output = <T as [<OptionWrapping $trait>]<InnerRhs>>::Output;

                fn [<opt_wrapping_ $op>](self, rhs: &Option<InnerRhs>) -> Option<Self::Output> {
                    self.zip(rhs.as_ref())
                        .and_then(|(inner_self, inner_rhs)| inner_self.[<opt_wrapping_ $op>](*inner_rhs))
                }
            }
        }
    };
}
