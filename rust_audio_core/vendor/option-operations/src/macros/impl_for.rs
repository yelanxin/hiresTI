macro_rules! impl_for {
    ($trait:ident, $typ_:ty, $block:tt) => {
        impl $trait for $typ_ $block
    };
}

macro_rules! impl_for_ints {
    ($trait:ident, $block:tt) => {
        impl_for!($trait, i8, $block);
        impl_for!($trait, i16, $block);
        impl_for!($trait, i32, $block);
        impl_for!($trait, i64, $block);
        impl_for!($trait, i128, $block);
        impl_for!($trait, u8, $block);
        impl_for!($trait, u16, $block);
        impl_for!($trait, u32, $block);
        impl_for!($trait, u64, $block);
        impl_for!($trait, u128, $block);
    };
}

macro_rules! impl_for_floats {
    ($trait:ident, $block:tt) => {
        impl_for!($trait, f32, $block);
        impl_for!($trait, f64, $block);
    };
}

macro_rules! impl_for_numerics {
    ($trait:ident, $block:tt) => {
        impl_for_ints!($trait, $block);
        impl_for_floats!($trait, $block);
    };
}

macro_rules! impl_for_time_types {
    ($trait:ident, $block:tt) => {
        impl_for!($trait, core::time::Duration, $block);
        #[cfg(feature = "std")]
        impl_for!($trait, std::time::Instant, $block);
        #[cfg(feature = "std")]
        impl_for!($trait, std::time::SystemTime, $block);
    };
}

macro_rules! impl_for_ints_and_duration {
    ($trait:ident, $block:tt) => {
        impl_for_ints!($trait, $block);
        impl_for!($trait, core::time::Duration, $block);
    };
}

macro_rules! impl_for_all {
    ($trait:ident, $block:tt) => {
        impl_for_numerics!($trait, $block);
        impl_for_time_types!($trait, $block);
    };

    ($trait:ident) => {
        impl_for_all!($trait, {});
    };
}
