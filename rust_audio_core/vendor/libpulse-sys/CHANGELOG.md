# 1.23.0 (April 19th, 2025)

 * Dropped long-deprecated `pa_check_version()` function.

# 1.22.0 (March 3rd, 2025)

 * Bumped MSRV from 1.56 to 1.63 per libc dependency.
 * Fixed warnings by bumping `num-derive` dependency.
 * Updated with PA version 17 changes (just an increase to max. sample rate).
 * Updated required dependencies:
    - `num-derive` from 0.3 to 0.4.

# 1.21.0 (July 18th, 2023)

 * Fixed warning from clashing namespace exports.
 * Fixed docs.rs build failure.
 * Dropped PA v4 support.

# 1.20.1 (January 9th, 2023)

 * Fixed broken build status badge in readme.

# 1.20.0 (January 9th, 2023)

 * Bumped Rust edition to 2021.
 * Bumped MSRV from 1.46 to 1.56.
 * Added `rust-version` (MSRV) attribute to `cargo.toml` file.

# 1.19.3 (December 7th, 2021)

 * Fixed handling of pkg-config failure handling due to change in `pkg-config` crate. Thanks to
   @fredszaq on github for the initial patch.

# 1.19.2 (August 29th, 2021)

 * Minor formatting tweaks.
 * Bumped MSRV from 1.41 to 1.46.
 * Marked `pa_check_version` and `pa_clamp_volume` as `const fn`.

# 1.19.1 (July 29th, 2021)

 * Fixed feature guard mistake in `version` mod causing docs.rs build to fail.

# 1.19.0 (July 28th, 2021)

 * Added PA v15 support (API additions).

# 1.18.0 (January 30th, 2021)

 * Now using intra-doc-linking introduced in Rust 1.48. The MSRV remains unchanged at 1.41; this is
   too great a simplification to maintaining documentation to not implement immediately; the only
   negative is that links will be broken in locally generated documentation when built with an older
   Rust compiler than version 1.48.

# 1.17.0 (December 22nd, 2020)

 * Tweaked version constants.
 * Deprecated `pa_check_version()`.

# 1.16.2 (December 15th, 2020)

 * Nothing notable.

# 1.16.1 (December 15th, 2020)

 * Fixed mistake made trying to conditionally enable `#[cfg(doc)]` for docs.rs.

# 1.16.0 (December 14th, 2020)

 * Made some changes to cargo features:
    - Removed the now obsolete `dox` cargo feature.
    - Removed the `pa_latest` and `pa_latest_common` cargo features.
    - Changed the default version feature level to `pa_v8`.
 * MSRV bumped from 1.40 to 1.41.
 * Changed `PA_CHANNELS_MAX` from `usize` to `u8`.
 * Made use of `#[cfg(doc)]` to always include stuff behind PA version feature guards in generated
   documentation. (Required bump of minimum supported Rust version from 1.40 to 1.41).
 * Added support for feature tagging in documentation (requires nightly Rust version, so only
   enabled if a certain config flag is used, as for the docs.rs copy).
 * Marked `version::Compatibility` as `#[non_exhaustive]`.

# 1.15.3 (December 11th, 2020)

 * Fixed incorrect `PA_SOURCE_DYNAMIC_LATENCY` flag value. Was mistakenly `0x42` instead of `0x40`
   (thus combined with `PA_SOURCE_LATENCY`).

# 1.15.2 (December 8th, 2020)

 * Added missing `Default` implementation for `channelmap::pa_channel_map_def_t`.
 * Added documentation for `pa_check_version()`. If you use it, please double check that it actually
   does what you think it does. It does **not** involve talking to the client library.

# 1.15.1 (November 25th, 2020)

 * Fixed deprecated license attribute syntax.

# 1.15.0 (November 25th, 2020)

 * Marked `pa_encoding_t` as `#[non_exhaustive]`.
 * Added derive of `FromPrimitive` and `ToPrimitive` from the `num-derive` crate on enums.
 * Updated required dependencies:
    - `num-traits` 0.2 now required.
    - `num-derive` 0.3 now required.

# 1.14.1 (November 25th, 2020)

 * Fixed missing rename of `pa_error_code_t::Io` to `pa_error_code_t::IO` to match change in
   binding.

# 1.14.0 (November 24th, 2020)

 * Added PA v14 support (API additions).

# 1.13.3 (November 21st, 2020)

 * Trivial documentation fixes.

# 1.13.2 (September 9th, 2020)

 * Bumped `pa_latest_common` feature to target PA v13.

# 1.13.1 (June 2nd, 2020)

 * Fixed output of build script warning when pkg-config is missing (thanks to @cole-h on github!).

# 1.13.0 (April 18th, 2020)

 * Removed deprecated Cargo features.

# 1.12.1 (December 29th, 2019)

 * Improved the non-pkg-config fallback for lib linking.

# 1.12.0 (December 29th, 2019)

 * Now using pkg-config in build script for more than just Linux.

# 1.11.1 (December 27th, 2019)

 * Fixed an issue compiling on Windows (needed to reference a different `pollfd` definition).
   Thanks to @allquixotic on github for reporting.

# 1.11.0 (September 17th, 2019)

 * Changed the license model from LGPL to dual MIT and Apache-2.0. See [here][issue26] for details.

# 1.10.0 (September 15th, 2019)

 * Implemented PA v13 enhancements.
 * Added PA v13 compatibility control feature.

# 1.9.1 (August 19th, 2019)

 * Fixed broken doc.rs documentation generation.

# 1.9.0 (August 19th, 2019)

 * Extended support to even older versions of PA, specifically up to and including v4.
 * Improved the build script.
 * Revised `version::Compatibility` variants to make more sense.
 * Simplified feature flags, old ones left as temorary aliases, to be removed later.
 * Added a `dox` feature flag, for use with `cargo doc`.
   It enables the very latest PA version compatibility, while bypassing the pkg-config check, thus
   is useful for generating documentation that includes information on features from versions of PA
   that may be newer than the version you have installed.
 * Improved version documentation further.

# 1.8.1 (August 17th, 2019)

 * Version: Improved mod documentation.

# 1.8.0 (August 15th, 2019)

 * Updated `use` conventions to that of Rust 1.30/1.31.
 * Specified edition in toml file.
 * Made the following functions `const`:
    - `version::get_compatibility()`.
    - `channelmap::pa_channel_position_mask()`.
    - `volume::pa_volume_is_valid()`.
    - `context::subscribe::pa_subscription_match_flags()`.
 * Version: purged deprecated items.

Note: version 1.7 skipped, used only for `libpulse-mainloop-glib-sys` crate changes.

# 1.6.0 (August 12th, 2019)

 * Replaced use of empty enums for opaque types with a struct based alternative. According to the
   Rust nomicon ([here][nomicon-ros]) the use of the empty enum trick is apparently undefined
   behaviour.
 * Added a new `latest_pa_common_compatibility` feature flag, used by default now instead of
   `latest_pa_compatibility`.

# 1.5.0 (December 22nd, 2018)

 * Added the new `latest_pa_compatibility` and `pa_v12_compatibility` feature flags, and deprecated
   `pa_encoding_from_string` in favour of `pa_v12_compatibility`.

# 1.4.0 (November 4th, 2018)

 * Switched to using package-config for linking (though retaining the direct linking as a fallback
   for those without the necessary *.pc files installed). Thanks to @JohnAZoidberg on github for
   the original patch.
 * Improved the `version` mod:
    - Constants now vary depending upon backwards compatibility flags, correctly indicating the
      newest supported PA version.
    - Added the `Compatibility` enum and `get_compatibility()` function.
    - Renamed `LINK_TARGET_VERSION` to `TARGET_VERSION_STRING`.
    - Introduced `TARGET_VERSION` and deprecated `PA_MAJOR`, `PA_MINOR` and `PA_MICRO`.
    - Deprecated `get_headers_version()`.
 * Clarified PA version compatibility in `version` mod.
 * Clarified `pa_encoding_from_string` feature purpose.

# 1.3.4 (October 8th, 2018)

 * Fixed broken attempt to include license file in bundled package.

# 1.3.3 (October 8th, 2018)

 * Added dedicated changelog, split off from the old single project overview one.
 * Included copy of license file in bundled package and excluded the `.gitignore` file.

Note, version number 1.3.2 skipped, bumping number into line with the other crates.

# 1.3.1 (September 3rd, 2018)

 * Added homepage and repo links, thanks to @berkus on github for the patch.

# 1.3 (July 17th, 2018)

 * Mainloop API objects now correctly treated as immutable, per related change in version 2.1 of
   `libpulse-binding`.
 * Default-enabled inclusion of the `pa_encoding_from_string` function symbol, which was missing
   from PA’s symbol file and thus not available in the client library before v12.

# 1.2.1 (June 26th, 2018)

 * Updated declared PA version compatibility (11.0 → 12.0).

# 1.2 (June 16th, 2018)

 * Context: Handful of functions changed to take `const` pointers.
   In version 1.1 many functions throughout the API were changed to take `const` pointers, with
   respective patches sent in to PA itself (which have since been accepted). Some context related
   functions were skipped over then however due to a complication with an artefact relating to
   validation checks. Additional patches solving this have now been created and sent in to the PA
   project. Discussion with PA devs indicates that this change will be accepted, so pre-emtively
   pushing the change here in our representation of the API; logically they should be immutable, and
   we do not need to propagate this unfortunate artefact).
 * Introspect & subscribe: Purged autoload API (deprecated in PA since 2009).

# 1.1 (May 27th, 2018)

 * Various functions have been changed to take immutable `const` pointers.
   There are numerous functions in the C API which take mutable pointers to objects where there is
   no intention to actually mutate those objects. Patches have been sent in to the PA project to
   correct many of these cases. There was no point in waiting for those to be accepted before
   fixing our representation of the API here, since the change is so obviously correct.

# 1.0.5 (May 27th, 2018)

 * Minor, non-functional consistency fix only.

Note, some version numbers skipped, bumping number into line with the other crates.

# 1.0.2 (February 9th, 2018)

 * Added travis badge.

# 1.0.1 (February 2nd, 2018)

 * Fixed toml file license string `LGPL-2.1` → `LGPL-2.1+`.
 * Fixed toml file missing author email address.

# 1.0 (January 24th, 2018)

 * Original release. (By the new crate owner with the replacement codebase).

# 0.0.0 (January 11th, 2016)

This was the original version available on crates.io, built by a different author in a different
code repository. Version 1.0 above represents the first published version from the replacement
codebase. (To be clear, version 0.0.0 cannot be found in the current repository).

[issue26]: https://github.com/jnqnfe/pulse-binding-rust/issues/26
[nomicon-ros]: https://doc.rust-lang.org/nomicon/ffi.html#representing-opaque-structs
