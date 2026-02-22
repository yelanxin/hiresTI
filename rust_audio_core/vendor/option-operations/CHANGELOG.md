# Change Log

## [Unreleased]

-

## [0.5.0] -- 2022-08-15

### Fixed

- Fix `prelude` not exporting `OptionEq`.

## [0.4.1] -- 2022-06-29

### Added

- Fix repository link in `Cargo.toml`.
- Specify Minimum Supported Rust Version.

### Fixed

- Error: fix a typo in Display impl.

### Changed

- Add `forbid(unsafe_code)` constraint.

## [0.4.0] -- 2021-10-24

### Fixed

- Fix auto implementations for OptionOp and OptionOpAssign. In previous version
  all the implementations required that Op & OpAssign be implemented, which was
  not consistent with documentation and other Option* traits. Now, the user can
  implement OptionOp and OptionOpAssign on the inner type and automatically
  benefit from the implementations on the other variations.

### Changed

- Factorize code in macros.

## [0.3.0] -- 2021-10-18

### Changed

- **Breaking**: don't export internal macros.

## [0.2.0] -- 2021-10-15

### Added

- #[must_use] attributes where applicable.
- Documentation for the associated types.

## [0.1.0] -- 2021-10-07

- First version with the most common operations.

[Unreleased]: https://github.com/fengalin/option-operations/
[0.5.0]: https://github.com/fengalin/option-operations/tree/0.5.0
[0.4.1]: https://github.com/fengalin/option-operations/tree/0.4.1
[0.4.0]: https://github.com/fengalin/option-operations/tree/0.4.0
[0.3.0]: https://github.com/fengalin/option-operations/tree/0.3.0
[0.2.0]: https://github.com/fengalin/option-operations/tree/0.2.0
[0.1.0]: https://github.com/fengalin/option-operations/tree/0.1.0