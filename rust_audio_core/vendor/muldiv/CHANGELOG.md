# Changelog
All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](http://keepachangelog.com/en/1.0.0/)
and this project adheres to [Semantic Versioning](http://semver.org/spec/v2.0.0.html),
specifically the [variant used by Rust](http://doc.crates.io/manifest.html#the-version-field).

## [1.0.1] - 2022-10-28
### Changed
- Switch tests from quickcheck 0.9 to quickcheck 1.0.

## [1.0.0] - 2020-10-13
### Changed
- Release as 1.0.0 without further changes.

## [0.2.1] - 2019-12-29
### Fixed
- `mul_div_round()` rounds down now for `-x.5` instead of rounding up, as
  documented and as the `round()` function in `std` does

### Changed
- All tests were ported to `quickcheck`
- The crate is `no_std` by default now as we don't need any `std` API outside
  the tests
- Documentation was improved and examples converted to proper doctests

## [0.2.0] - 2018-05-11
### Changed
- Switch to `i128`/`u128` and require Rust 1.26 instead of having our own 96/128
  bit integer implementation

## [0.1.1] - 2017-08-18
### Added
- README.md

### Changed
- Relicensed from LGPLv2 to MIT
- Use docs.rs for the documentation

### Fixed
- Various clippy warnings

## [0.1.0] - 2016-02-26

- Initial release of muldiv.

[Unreleased]: https://github.com/sdroege/rust-muldiv/compare/1.0.1...HEAD
[1.0.1]: https://github.com/sdroege/rust-muldiv/compare/1.0.0...1.0.1
[1.0.0]: https://github.com/sdroege/rust-muldiv/compare/0.2.1...1.0.0
[0.2.1]: https://github.com/sdroege/rust-muldiv/compare/0.2.0...0.2.1
[0.2.0]: https://github.com/sdroege/rust-muldiv/compare/0.1.1...0.2.0
[0.1.1]: https://github.com/sdroege/rust-muldiv/compare/0.1.0...0.1.1
