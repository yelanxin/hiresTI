macro_rules! option_op_assign {
    ($trait:ident, $op:ident, $op_name:ident $(, $extra_doc:expr)? $(,)?) => {
        paste::paste! {
            #[doc = "Trait for values and `Option`s " $op_name " assignment."]
            ///
            /// Implementing this trait leads to the following auto-implementations:
            ///
            #[doc = "- `" [<Option $trait Assign>] "<Option<InnerRhs>>` for `T`."]
            #[doc = "- `" [<Option $trait Assign>] "<Rhs>` for `Option<T>`."]
            #[doc = "- `" [<Option $trait Assign>] "<Option<InnerRhs>>` for `Option<T>`."]
            /// - ... and some variants with references.
            ///
            /// This trait is auto-implemented for [`OptionOperations`] types implementing
            #[doc = "`" $trait "<Rhs>`."]
            pub trait [<Option $trait Assign>]<Rhs = Self, InnerRhs = Rhs> {
                #[doc = "Performs the " $op_name " assignment."]
                ///
                /// `self` is unchanged if `rhs` is `None`.
                $(#[doc = $extra_doc])?
                fn [<opt_ $op _assign>](&mut self, rhs: Rhs);
            }

            impl<T, Rhs> [<Option $trait Assign>]<Rhs> for T
            where
                T: OptionOperations + [<$trait Assign>]<Rhs>,
            {
                fn [<opt_ $op _assign>](&mut self, rhs: Rhs) {
                    self.[<$op _assign>](rhs)
                }
            }

            impl<T, InnerRhs> [<Option $trait Assign>]<Option<InnerRhs>, InnerRhs> for T
            where
                T: OptionOperations + [<Option $trait Assign>]<InnerRhs>,
            {
                fn [<opt_ $op _assign>](&mut self, rhs: Option<InnerRhs>) {
                    if let Some(inner_rhs) = rhs {
                        self.[<opt_ $op _assign>](inner_rhs)
                    }
                }
            }

            impl<T, InnerRhs> [<Option $trait Assign>]<&Option<InnerRhs>, InnerRhs> for T
            where
                T: OptionOperations + [<Option $trait Assign>]<InnerRhs>,
                InnerRhs: Copy,
            {
                fn [<opt_ $op _assign>](&mut self, rhs: &Option<InnerRhs>) {
                    if let Some(inner_rhs) = rhs.as_ref() {
                        self.[<opt_ $op _assign>](*inner_rhs)
                    }
                }
            }

            impl<T, Rhs> [<Option $trait Assign>]<Rhs> for Option<T>
            where
                T: OptionOperations + [<Option $trait Assign>]<Rhs>,
            {
                fn [<opt_ $op _assign>](&mut self, rhs: Rhs) {
                    if let Some(inner_self) = self {
                        inner_self.[<opt_ $op _assign>](rhs)
                    }
                }
            }

            impl<T, InnerRhs> [<Option $trait Assign>]<Option<InnerRhs>, InnerRhs> for Option<T>
            where
                T: OptionOperations + [<Option $trait Assign>]<InnerRhs>,
            {
                fn [<opt_ $op _assign>](&mut self, rhs: Option<InnerRhs>) {
                    if let Some((inner_self, inner_rhs)) = self.as_mut().zip(rhs) {
                        inner_self.[<opt_ $op _assign>](inner_rhs)
                    }
                }
            }

            impl<T, InnerRhs> [<Option $trait Assign>]<&Option<InnerRhs>, InnerRhs> for Option<T>
            where
                T: OptionOperations + [<Option $trait Assign>]<InnerRhs>,
                InnerRhs: Copy,
            {
                fn [<opt_ $op _assign>](&mut self, rhs: &Option<InnerRhs>) {
                    if let Some((inner_self, inner_rhs)) = self.as_mut().zip(rhs.as_ref()) {
                        inner_self.[<opt_ $op _assign>](*inner_rhs)
                    }
                }
            }
        }
    };
}
