# cookie-factory

[![Crates.io Version][crates.io badge]][crate]
[![docs.rs][docs.rs badge]][docs]
[![Actions Status][actions badge]][actions]
[![CodeCov][codecov badge]][codecov]
[![LICENSE][license badge]][license]

serialization library built with a combinator design similar to the [nom parser combinators library](https://github.com/geal/nom).

Serializers are built up from single purpose serializers, like `slice`
to write a raw byte slice, or `be_u16` to write a `u16` integer in big
endian form.

Those small serializers can then be assembled by using combinators.
As an example, `all(["abcd", "efgh", "ijkl"].iter().map(string))(output)`
will write `"abcdefghijkl"` to `output`.


<!-- Links -->
[crate]: https://crates.io/crates/cookie-factory
[docs]: https://docs.rs/cookie-factory/
[actions]: https://github.com/rust-bakery/cookie-factory/actions
[codecov]: https://codecov.io/gh/rust-bakery/cookie-factory
[license]: LICENSES/MIT.txt


<!-- Badges -->
[crates.io badge]: https://img.shields.io/crates/v/cookie-factory.svg
[docs.rs badge]: https://img.shields.io/docsrs/cookie-factory
[actions badge]: https://github.com/rust-bakery/cookie-factory/workflows/cookie-factory/badge.svg
[codecov badge]: https://codecov.io/gh/rust-bakery/cookie-factory/branch/master/graph/badge.svg
[license badge]: https://img.shields.io/badge/license-MIT-blue.svg
