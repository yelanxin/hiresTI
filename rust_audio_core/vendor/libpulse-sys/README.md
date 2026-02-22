libpulse-sys
============

[<img alt="GitHub Workflow Status" src="https://img.shields.io/github/actions/workflow/status/jnqnfe/pulse-binding-rust/test.yml?branch=master&style=for-the-badge" height="24">](https://github.com/jnqnfe/pulse-binding-rust/actions)
[<img alt="crates.io" src="https://img.shields.io/crates/v/libpulse-sys?style=for-the-badge" height="24">](https://crates.io/crates/libpulse-sys)
[<img alt="docs.rs" src="https://img.shields.io/crates/v/libpulse-sys?color=5479ab&label=docs.rs&style=for-the-badge" height="24">](https://docs.rs/libpulse-sys)
[<img alt="min-rust-version" src="https://img.shields.io/static/v1?label=RUST&message=1.63%2B&color=informational&style=for-the-badge" height="24">](https://rust-lang.github.io/rfcs/2495-min-rust-version.html)

FFI bindings for the PulseAudio libpulse system library. See also the higher-level
[`libpulse-binding`](https://crates.io/crates/libpulse-binding) crate.

## Usage

Add this crate to the dependencies specified in your `Cargo.toml`:

```toml
[dependencies]
libpulse-sys = "1.0"
```

Though you may wish to rename the crate to a shorter name (for example `pulse`) for cleaner
references within your code:

```toml
[dependencies]
pulse = { version = "1.0", package = "libpulse-sys" }
```

An alternative to that which some may prefer is:

```toml
[dependencies.pulse]
version = "1.0"
package = "libpulse-sys"
```

### PulseAudio version compatibility

The default functionality provided is support for PulseAudio version 8.0 or newer. This should be
good enough for most needs, however if you _need_ to use something only available in a newer
version then you can select the corresponding version compatibility feature to raise the minimum
compatibility level. You can also reduce support down to even older versions if you wish. See the
overall project `COMPATIBILITY.md` file for further details.

## License

Licensed under either of the following, at your option:

 * [Apache License, Version 2.0](http://www.apache.org/licenses/LICENSE-2.0)
 * [MIT license](http://opensource.org/licenses/MIT)

### Contribution

Unless you explicitly state otherwise, any contribution intentionally submitted for inclusion in the
work by you, as defined in the Apache-2.0 license, shall be dual licensed as above, without any
additional terms or conditions.
