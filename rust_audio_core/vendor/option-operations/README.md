# option-operations

[![crates.io][Crate Logo]][Crate]
[![Documentation][Doc Logo]][Doc]
[![Build Status][CI Logo]][CI]
[![MSRV][rustc Logo]][Crate]

`option-operations` provides traits and auto-implementations to
improve arithmetic operations usability when dealing with `Option`s.

## Example

Dealing with two `Option`s, can lead to verbose expressions:

``` rust
let lhs = Some(1u64);
let rhs = Some(u64::MAX);

assert_eq!(
    lhs.zip(rhs).map(|(lhs, rhs)| lhs.saturating_add(rhs)),
    Some(u64::MAX),
);
```

Thanks to the trait `OptionSaturatingAdd` we can write:

``` rust
assert_eq!(
    lhs.opt_saturating_add(rhs),
    Some(u64::MAX),
);
```

The trait can also be used with the inner type:

``` rust
assert_eq!(
    lhs.opt_saturating_add(u64::MAX),
    Some(u64::MAX),
);

assert_eq!(
    1.opt_saturating_add(rhs),
    Some(u64::MAX),
);
```

## Alternative to `PartialOrd` for `Option<T>`

Another purpose is to workaround the `PartiaOrd` implementation
for `Option<T>`, which uses the declaration order of the variants
for `Option`. `None` appearing before `Some(_)`, it results in
the following behavior:

``` rust
let some_0 = Some(0);
let none: Option<u64> = None;

assert_eq!(none.partial_cmp(&some_0), Some(Ordering::Less));
assert_eq!(some_0.partial_cmp(&none), Some(Ordering::Greater));
```

In some cases, we might consider that `None` reflects a value which
is not defined and thus can not be compared with `Some(_)`.

``` rust
assert_eq!(none.opt_cmp(&some_0), None);
assert_eq!(some_0.opt_cmp(&none), None);
```

Of course, this is consistent with other usual comparisons:

``` rust
assert_eq!(none.opt_lt(&some_0), None);
assert_eq!(none.opt_min(&some_0), None);
```

## LICENSE

This crate is licensed under either of

 * Apache License, Version 2.0, ([LICENSE-APACHE](LICENSE-APACHE) or
   http://www.apache.org/licenses/LICENSE-2.0)
 * MIT license ([LICENSE-MIT](LICENSE-MIT) or
   http://opensource.org/licenses/MIT)

at your option.


[Crate]: https://crates.io/crates/option-operations
[Crate Logo]: https://img.shields.io/crates/v/option-operations.svg

[Doc]: https://docs.rs/option-operations
[Doc Logo]: https://docs.rs/option-operations/badge.svg

[CI]: https://github.com/fengalin/option-operations/actions/workflows/CI.yml
[CI Logo]: https://github.com/fengalin/option-operations/workflows/CI/badge.svg

[rustc Logo]: https://img.shields.io/badge/rust-1.53.0%2B-blue.svg?maxAge=3600
