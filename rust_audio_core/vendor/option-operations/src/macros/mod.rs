#[macro_use]
mod impl_for;

#[macro_use]
mod option_op;

#[macro_use]
mod option_op_assign;

#[macro_use]
mod option_op_checked;

#[macro_use]
mod option_op_overflowing;

#[macro_use]
mod option_op_saturating;

#[macro_use]
mod option_op_wrapping;

macro_rules! common_option_op {
    ($trait:ident, $op:ident, $op_name:ident $(, $extra_doc:expr)? $(,)?) => {
        paste::paste! {
            option_op!(
                $trait,
                $op,
                $op_name,
                $($extra_doc)?
            );

            option_op_assign!(
                $trait,
                $op,
                $op_name,
                $($extra_doc)?
            );

            option_op_overflowing!(
                $trait,
                $op,
                $op_name,
                $($extra_doc)?
            );

            option_op_wrapping!(
                $trait,
                $op,
                $op_name,
                $($extra_doc)?
            );
        }
    };
}
