# 2.30.1 (April 19th, 2025)

 * Added a length check to the stream `new_extended()` method (missed in previous version).
 * Added a length check to the stream restore `write()` method (missed in previous version).

# 2.30.0 (April 19th, 2025)

 * Added `to_owned()` methods to a bunch of introspection objects (as requested back in 2021 in
   issue 44). Thanks to @t4ccer on github for prompting this and providing an initial partial
   implementation.
 * Added `set_corked_state()` method to `Stream` providing an alternative to using `cork()` and
   `uncork()`.
 * Added length checks to the `set_prop_int_array()` and `set_prop_string_array()` methods of
   `format::Info`. Now should you happen to pass in an array with a length larger than can fit
   within the `len` parameter of the C function, it will panic.
 * Dropped additional long-deprecated constants, missed in the previous version.
 * Dropped long-deprecated `check_version()` function.
 * Dropped deprecated `CardProfileInfo2` introspection alias.

# 2.29.0 (March 3rd, 2025)

 * Bumped MSRV from 1.56 to 1.63 per libc dependency.
 * Fixed warnings by removing explicit calls to `clone()` that have become unnecessary.
 * Fixed warnings by bumping `num-derive` dependency.
 * Bumped `bitflags` dependency to version 2.x (required adding `Debug` to a few flagsets).
 * Dropped various constants that were deprecated back in versions 2.20 and 2.21 (December 2020).
 * Updated with PA version 17 changes (just an increase to max. sample rate).
 * Updated required dependencies:
    - `libpulse-sys` from 1.21 to 1.22.
    - `num-derive` from 0.3 to 0.4.
    - `bitflags` from 1.2 to 2.x.

# 2.28.3 (March 2nd, 2025)

 * Clarify in documenation that mainloop and context objects must both live for the entire duration.

# 2.28.2 (November 27th, 2024)

 * Fixed crash when audio device has null device but non-null name, thanks to @AdriaanPrinsloo on
   github.
 * Fixed a couple documentation typos.

# 2.28.1 (July 18th, 2023)

 * Fixed cross-crate version requirement.

# 2.28.0 (July 18th, 2023)

 * Fixed 'double-reference clone' warnings.
 * Fixed docs.rs build failure.
 * Dropped PA v4 support.

# 2.27.1 (January 9th, 2023)

 * Fixed broken build status badge in readme.

# 2.27.0 (January 9th, 2023)

 * Bumped Rust edition to 2021.
 * Bumped MSRV from 1.46 to 1.56.
 * Added `rust-version` (MSRV) attribute to `cargo.toml` file.
 * Tweaked some doc-tests to work with rust v1.63+ (at the expense of not working with older
   versions). This relates to float-point calculation changes in `Duration::try_from_secs_f32/64`
   made in rust stdlib version 1.60 and further tweaked in 1.63. See [this issue][issue48].
 * Updated required dependencies:
    - `libpulse-sys` from 1.19 to 1.20.

# 2.26.0 (January 13th, 2022)

 * Changed the type of the `timestamp` member of `def::TimingInfo` from `Timeval` to `UnixTs` since
   it is actually a system time not a generic duration.
 * Time: Added missing `#[repr(transparent)]` marker to `MicroSeconds`.
 * Time: Made use of `#[track_caller]` such that panics from overflows and such in math operation
   implementations will point to the caller as the source of the problem.

# 2.25.0 (August 29th, 2021)

 * Made the attributes of `MainloopInner` private. Methods `new()` and `get_api_ptr()` were added to
   support this, while `get_ptr()` was marked `unsafe`.
 * Converted `channelmap::Position::to_mask()` to `const fn`.
 * Bumped MSRV from 1.41 to 1.46 to better reflect practical requirement since bitflags v1.3 now
   requires 1.46 and I expect it likely that most projects will promptly be upgrading it.
 * Minor tweaks not worth documenting.
 * Fixed wrong version for previous changelog entry.

# 2.24.0 (July 28th, 2021)

 * Added PA v15 support (API additions):
    - Added `Introspector::send_message_to_object()`.
    - Added `proplist::properties::{CONTEXT_FORCE_DISABLE_SHM, BLUETOOTH_CODEC}`.
 * Updated required dependencies:
    - `libpulse-sys` from 1.18 to 1.19.

# 2.23.1 (April 9th, 2021)

 * Minor documentation tweaks.

# 2.23.0 (January 30th, 2021)

 * Implemented `std::error::Error` for `error::{Code, PAErr}`.
 * Implemented `Debug` for `ListResult`.
 * Now using intra-doc-linking introduced in Rust 1.48. The MSRV remains unchanged at 1.41; this is
   too great a simplification to maintaining documentation to not implement immediately; the only
   negative is that links will be broken in locally generated documentation when built with an older
   Rust compiler than version 1.48.
 * Minor documentation fixes.
 * Re-implemented list-callback handling (internal change only).
 * Updated required dependencies:
    - `libpulse-sys` from 1.17 to 1.18.

# 2.22.0 (December 22nd, 2020)

 * The `Context` creation functions `new()` and `new_with_proplist()` will now fail if the version
   of the PulseAudio client system library is older then the minimum compatibility level set via use
   of the version feature flags. This is done to block use of the library in such a circumstance as
   a means of helping to prevent the undefined behaviour that could result from the possible
   “forward” compatibility problems discussed in the project `COMPATIBILITY.md` documentation.
 * Added the following functions to help check the version of the PA system library at runtime:
   `version::get_library_version_numbers()`, `version::compare_with_library_version()` and
   `version::library_version_is_too_old()`.
 * Tweaked version constants.
 * Deprecated `version::check_version()`.
 * Updated required dependencies:
    - `libpulse-sys` from 1.16 to 1.17.

# 2.21.0 (December 15th, 2020)

 * Converted `context::FlagSet` to a [`bitflags`] type, moving the `context::flags::*` constants
   to associated constants of it, deprecating the old constant set. This was overlooked in 2.20.

# 2.20.1 (December 15th, 2020)

 * Fixed mistake made trying to conditionally enable `#[cfg(doc)]` for docs.rs.

# 2.20.0 (December 14th, 2020)

 * Made some changes to cargo features:
    - Removed the now obsolete `dox` cargo feature.
    - Removed the `pa_latest` and `pa_latest_common` cargo features.
    - Changed the default version feature level to `pa_v8`.
 * MSRV bumped from 1.40 to 1.41.
 * Re-wrote the `COMPATIBILITY.md` guide (available in the code repo), including adding important
   discussion of the hazard of “forward compatibility” concerns.
 * Improved the basic implementations of integer operations `Add`, `Sub`, `Mul`, `Div` and `Rem`
   for time types, such that those that were not previously making use of “checked” calculations
   now do so, and thus overflow causes a panic rather than being wrapped. If panicing is not wanted,
   the “checked” methods should be used directly which return a `None` on failure.
 * Added an `Option` wrapper to the `volume` param of `Context::play_sample()` and
   `Context::play_sample_with_proplist()` “scache” methods to simplify usage. Supplying `None` is
   a nicer alternative to passing `Volume::INVALID`.
 * Moved the following functions from the `sample` mod to methods of `sample::Spec`:
   `format_is_valid()`, `rate_is_valid()` and `channels_are_valid()`, having noticed that they
   clearly relate to the attributes of that type and so should have been there all along.
 * Shrunk the type of the `channels` param of `channelmap::Map` methods `init_auto()` and
   `init_extend()` from `u32` to `u8`.
 * Shrunk the `sample::CHANNELS_MAX` type from `usize` to `u8`.
 * Moved many existing constants to be associated constants (long overdue):
    - Deprecated `sample::{CHANNELS_MAX, RATE_MAX}`.
    - Added `sample::Spec::{CHANNELS_MAX, RATE_MAX}` replacements.
    - Added `volume::ChannelVolumes::CHANNELS_MAX` replacement.
    - Deprecated `volume::{VOLUME_NORM, VOLUME_MUTED, VOLUME_MAX, VOLUME_INVALID}`.
    - Added `volume::Volume::{NORMAL, MUTED, MAX, INVALID}` replacements.
    - Deprecated `volume::DECIBEL_MINUS_INFINITY`.
    - Added `volume::VolumeDB::MINUS_INFINITY` replacement.
    - Deprecated `time::{USEC_INVALID, USEC_MAX}`.
    - Added `time::MicroSeconds::{INVALID, MAX}` replacements.
    - Deprecated `context::subscribe::{FACILITY_MASK, OPERATION_MASK}`.
    - Added `context::subscribe::{Facility::MASK, Operation::MASK}` replacements.
 * Made some improvements to `MicroSeconds`:
    - Added `MicroSeconds::{MIN, ZERO, SECOND, MILLISECOND}` associated constants.
    - Added `MicroSeconds::is_zero()`, `MicroSeconds::from_secs()`, `MicroSeconds::from_millis()`,
      `MicroSeconds::inner()`, `MicroSeconds::as_secs()`, `MicroSeconds::as_millis()`,
      and `MicroSeconds::diff()`.
    - Additionally added `MicroSeconds::from_secs_f64()`, `MicroSeconds::from_secs_f32()`,
      `MicroSeconds::as_secs_f64()` and `MicroSeconds::as_secs_f32()` for converting to/from
      floating point form, and `MicroSeconds::mul_f32()`, `MicroSeconds::mul_f64()`,
      `MicroSeconds::div_f32()` and `MicroSeconds::div_f64()` for multiplication and division by
      floats.
    - Removed the restriction using `Mul` operations between an integer primitive and a
      `MicroSeconds` that required the Rhs to be the integer, by extending the implementation. Thus
      you can now do `2 * MicroSeconds(20)` not just `MicroSeconds(20) * 2`.
    - Enabled `MicroSeconds` to be added or subtracted from a `Duration`, not just the other way
      around.
 * Improved handling of flag sets through making use of [`bitflags`] (long overdue). The following
   types which have been simple integer primitive type aliases have now been changed to [`bitflags`]
   wrappers. The set of flags associated with them have been thus assigned as associated constants
   to them, and the separate set marked as deprecated.
    - `stream::FlagSet`, with its `stream::flags::*` flags.
    - `def::{SinkFlagSet, SourceFlagSet}` and their `def::sink_flags::*` and `def::source_flags::*`
       flag sets.
    - `direction::FlagSet` and its `direction::flags::*` flags.
    - `mainloop::events::io::IoEventFlagSet` and its `mainloop::events::io::flags::*` flags.
    - `context::subscribe::InterestMaskSet` and its `context::subscribe::subscription_masks` flags.
 * Renamed the `mainloop::events::io::IoEventFlagSet` type to simply `FlagSet`.
 * Renamed the `MASK_CARD` constant from `context::subscribe` to simply `CARD`, since the inclusion
   of `MASK_` in the name was a mistake (part of a prefix removed from others but mistakenly left
   in place for this one).
 * Moved `direction::is_valid()` and `direction::to_string()` to methods of `direction::FlagSet`.
 * Added `MonotonicTs::checked_add_duration()` and `MonotonicTs::checked_sub_duration()` along with
   corresponding `Add[Assign]` and `Sub[Assign]` impls for adding a `Duration` to `MonotonicTs`.
   This complements the existing functionality for adding a `MicroSeconds`, without requiring
   conversion of a `Duration` to a `MicroSeconds`.
 * Made use of `#[cfg(doc)]` to always include stuff behind PA version feature guards in generated
   documentation. (Required bump of minimum supported Rust version from 1.40 to 1.41).
 * Added support for feature tagging in documentation (requires nightly Rust version, so only
   enabled if a certain config flag is used, as for the docs.rs copy).
 * Marked `version::Compatibility` as `#[non_exhaustive]`.
 * Updated required dependencies:
    - `libpulse-sys` from 1.15 to 1.16.
    - `bitflags` 1.2 now required.

# 2.19.0 (December 8th, 2020)

 * Fixed broken conversions between `Duration` and other time duration types (`MicroSeconds` and
   `Timeval`), which were mistakenly converting based upon milliseconds rather than microseconds and
   thus were off by a scale of 1000. Lack of tests failed to catch this, which have now been added.
 * Added missing `Default` implementation for `channelmap::MapDef`.
 * Added documentation for `version::check_version()`. If you use it, please double check that it
   actually does what you think it does. It does **not** involve talking to the client library.

# 2.18.1 (November 25th, 2020)

 * Fixed deprecated license attribute syntax.

# 2.18.0 (November 25th, 2020)

 * Marked `format::Encoding` as `#[non_exhaustive]`.
 * Replaced the `From<PAErr> for Code` impl with `TryFrom<PAErr> for Code`, since the conversion is
   fallible and now that `TryFrom` has been stable for a while (since 1.40). Unfortunately it was
   not possible to leave the `From` version in place with a deprecation notice due to conflicts that
   result. The solution was also re-implemented based upon `FromPrimitive`.
 * Implemented `std::fmt::Display` for `error::Code`.
 * Added derive of `FromPrimitive` and `ToPrimitive` from the `num-derive` crate on basic enums.
 * Fixed an extremely unlikely but possible source of undefined behaviour in introspection. This
   relates to translation of a few integers into enum variants. Previously values that did not match
   an enum variant would be transmuted to the enum type anyway, resulting in undefined behaviour.
   Now a panic will occur instead. Pragmatically you should never encounter this, so no advisory is
   being issued - it would only occur via a bug in PulseAudio, the mapping, or a mismatch in version
   compatibility with the running PulseAudio client library, with this latter issue being something
   dangerous that users must avoid anyway.
 * Some test additions.
 * Updated required dependencies:
    - `libpulse-sys` from 1.14 to 1.15.
    - `num-traits` 0.2 now required.
    - `num-derive` 0.3 now required.

# 2.17.0 (November 24th, 2020)

 * Added PA v14 support (API additions).
 * Mainloop (standard): Changed the `prepare()` method to take an `Option<MicroSeconds>` instead of
   `Option<i32>`.
 * Renamed the error `Code::Io` enum variant to `Code::IO`.
 * Updated required dependencies:
    - `libpulse-sys` from 1.13 to 1.14.

# 2.16.3 (November 21st, 2020)

 * Trivial documentation fixes.
 * Trivial internal tidy-up in volume module.

# 2.16.2 (September 9th, 2020)

 * Bumped `pa_latest_common` feature to target PA v13.

# 2.16.1 (July 10th, 2020)

 * Fixed some dangling pointer issues with handling of string arrays, thanks to @yatinmaan on
   github.

# 2.16.0 (April 18th, 2020)

 * Made the attributes of `channelmap::{ChannelVolumes, Map}` types private.
   (Direct access had been deprecated previously).
 * Removed deprecated comparison methods.
 * Removed deprecated proplist methods.
 * Removed deprecated Cargo features.
 * Updated required dependencies:
    - `libpulse-sys` from 1.12 to 1.13.

# 2.15.1 (April 18th, 2020)

 * Fixed issues with a threaded mainloop example in the documentation.
 * Fixed miscellaneous other documentation mistakes.

# 2.15.0 (December 29th, 2019)

 * Updated required dependencies:
    - `libpulse-sys` from 1.11 to 1.12.

# 2.14.1 (December 29th, 2019)

 * Fixed issues compiling on Windows:
   - Needed to reference a different `pollfd` definition
   - Needed to reference different inner `timeval` attribute type definitions
   Thanks to @allquixotic on github for reporting.

# 2.14.0 (October 28th, 2019)

 * Reverted "Changed the `mainloop` param of `Context::rttime_new()` from trait object to generic
   (`dyn` to`impl`)" from v2.7. Failed to test sufficiently. This introduces an E0632 error in a
   test app and I was unsuccessful in finding a compilable workaround.

# 2.13.0 (September 17th, 2019)

 * Changed the license model from LGPL to dual MIT and Apache-2.0. See [here][issue26] for details.
 * Updated required dependencies:
    - `libpulse-sys` from 1.10 to 1.11.

# 2.12.0 (September 15th, 2019)

 * Implemented PA v13 enhancements, including:
    - Added `get_sample_format()`, `get_rate()`, `get_channel_count()` and `get_channel_map()`
      methods to `format::Info`.
    - Added `util::make_thread_realtime()`.
    - Added `Encoding::TRUEHD_IEC61937` and `Encoding::DTSHD_IEC61937`.
    - A wrapper for `pa_threaded_mainloop_once_unlocked` has not been added at this time.
 * Changed the `ss` param of `Context::get_tile_size()` to add an `Option` wrapper.
   The C API function allows a null pointer to be used for this param, which was not a use case
   allowed in the binding, for no particular reason. This enables it.
 * Added PA v13 compatibility control feature.
 * Updated required dependencies:
    - `libpulse-sys` from 1.9 to 1.10.

# 2.11.1 (August 19th, 2019)

 * Fixed broken doc.rs documentation generation.

# 2.11.0 (August 19th, 2019)

 * Extended support to even older versions of PA, specifically up to and including v4.
 * Revised `version::Compatibility` variants to make more sense.
 * Simplified feature flags, old ones left as temporary aliases, to be removed later.
 * Added a `dox` feature flag, for use with `cargo doc`.
   It enables the very latest PA version compatibility, while bypassing the pkg-config check, thus
   is useful for generating documentation that includes information on features from versions of PA
   that may be newer than the version you have installed.
 * Improved version documentation further.
 * Updated required dependencies:
    - `libpulse-sys` from 1.8 to 1.9.

# 2.10.1 (August 17th, 2019)

 * Version: Improved mod documentation.
 * Added missing version info to deprecation notices.

# 2.10.0 (August 15th, 2019)

 * Modified `channelmap::{ChannelVolumes, Map}` types to be more Rust-like.
   Both of these types hold an array of size `sample::CHANNELS_MAX`, along with a `channels`
   attribute which controls how much of the initial portion of that array is “active” (equivalent to
   the `len()` of a `Vec`). Previously the array and len were simply public attributes, with changes
   to be applied directly. While for the time being they remain publicly accessible for backwards
   compatibility, this will become private in a future release. These types should now be used in a
   way more similar to a `Vec`:
    - New methods `len()` and `set_len()` get read/write access to the `channels` attribute that
      records how much of the array is considered “active”.
    - Traits `Borrow<[_]>` and `BorrowMut<[_]>` have been implemented, along with the addition of
      new methods `get()` and `get_mut()` (for convenience - you can avoid type ambiguity), for
      accessing the array as a slice (of just the “active” portion).
 * Updated `use` conventions to that of Rust 1.30/1.31.
 * Specified edition in toml file.
 * Made the following functions `const`:
    - `version::get_compatibility()`.
    - `Volume::is_valid()`.
    - `Timeval::new()` and `Timeval::new_zero()`.
    - `subscribe::Facility::to_interest_mask()`.
 * Version: purged deprecated items.
 * Updated required dependencies:
    - `libpulse-sys` from 1.6 to 1.8.

Note: versions 2.8 and 2.9 skipped, used only for `libpulse-glib-binding` crate changes.

# 2.7.1 (August 13th, 2019)

 * Fixed overlooked use of new method names in docs.

# 2.7.0 (August 12th, 2019)

 * Renamed a few methods of `Proplist` for clarity:
    - `Proplist::sets()` to `Proplist::set_str()`.
    - `Proplist::gets()` to `Proplist::get_str()`.
    - `Proplist::setp()` to `Proplist::set_pl()`.
 * Added `Stream::write_copy()` which is just a simplified interface for asking PA to make an
   internal copy of the to-be-written data (same as providing `None` in the `free_cb` param of
   `Stream::write()`.
 * Changed the `mainloop` param of `Context::rttime_new()` from trait object to generic (`dyn` to
   `impl`).
 * Made better use of `PartialEq` implementations:
    - Deprecated `ChannelMap::is_equal_to()`, `ChannelVolumes::equal_to()`,
      `ChannelVolumes::channels_equal_to()`, `Spec::equal_to()`, and `Proplist::equal_to()` in
      favour of `PartialEq` implementations.
    - Added implementation for `Proplist` and `PartialEq<Volume>` impl for `ChannelVolumes`.
 * Changed `PartialEq` implementations for `channelmap::{Map, Spec, ChannelVolumes}` to delegate the
   logic to the C API.
 * Removed stray `repr(C)` attribute from `SinkPortInfo` introspection type.
 * Added a new `latest_pa_common_compatibility` feature flag, used by default now instead of
   `latest_pa_compatibility`.
 * Added tests to assert that size and alignment of certain structs and enums are identical to their
   `sys` crate counterparts.
 * Updated required dependencies:
    - `libpulse-sys` from 1.5 to 1.6.

# 2.6.0 (March 10th, 2019)

 * Implemented use of `std::panic::catch_unwind()` in callbacks.

# 2.5.0 (December 22nd, 2018)

**Note: This includes a security fix!**

 * Fixed potential use-after-free with `proplist::Iterator` (not to be confused with the
   `std::iter::Iterator` trait). An instance of this object type is created from a `Proplist` object
   and holds a copy of the same raw pointer to the underlying C object; the `Proplist` object had
   sole responsibility for destroying it via its `Drop` implementation. There was no actual lifetime
   association however linking the lifetime of the `Iterator` object to the `Proplist` object, and
   thus it was possible for the `Proplist` object to be destroyed first, leaving the `Iterator`
   object working on a freed C object. This is unlikely to have been done in actual user code, but
   would have been trivial to achieve, including simply by using the `into_iter()` function. This
   affects versions all the way back to 1.0.5.
 * Enabled `Send`+`Sync` for various types.
   This was previously not done due to uncertainty as to whether or not it was safe to do so, but I
   have now reconsidered it and arrived at the conclusion that it should be okay: With the threaded
   mainloop, a lock must be held when using objects; this is taken by the mainloop dispatcher when
   executing callbacks, and otherwise must be taken by the user before using objects within any
   thread. With that locking mechanism, it should be safe I presume for these objects to be marked
   Send+Sync. It is not ideal that the user can so easily just forget to grab the lock, as opposed
   to the Rust design of `Arc<Mutex<_>>` forcing unlocking to get at things, but it’s not certain
   that we can easily really do anything to address this. So long as users stick to the principle of
   grabbing the mainloop lock though, they should be fine.
 * Simplified converting `Duration` to `MicroSeconds` or `Timeval` using
   `Duration::subsec_millis()`.
 * Made `proplist::Iterator::new()` private, since it’s very unlikely anyone needs it.
 * Added the new `latest_pa_compatibility` and `pa_v12_compatibility` feature flags, and deprecated
   `pa_encoding_from_string` in favour of `pa_v12_compatibility`.
 * Removed unnecessary `From` conversion implementation to/from C type for `format::Info`.
 * Updated required dependencies:
    - `libpulse-sys` from 1.4 to 1.5.

# 2.4.0 (November 28th, 2018)

 * Changed the `channelmap::Map::new_from_string()` method return value to use a `Result` wrapper.
   Previously failure was just ignored, expecting strings provided to always be valid, as obtained
   from the `Map::print()` and `Map::to_name()` methods, but let's be more cautious.
 * Updated out-of-date documentation of return types for a large number of functions, particularly
   introspection ones, which had not been updated following the removal of the `Option` wrapper back
   in v2.0. Thanks to @0xpr03 on github for noticing a discrepancy.
 * Restored the `Option` wrapper to the `Context::drain()` return value. It was incorrectly removed
   from this function at the same time as legitimately being removed from many others.
 * Changed the `Drop` implementation on `Stream` to no longer unwrap the `Result` returned by the
   `disconnect()` attempt it makes. This should fix [this problem][issue11] encountered by @futpib
   on github.

# 2.3.0 (November 4th, 2018)

 * Improved the `version` mod:
    - Constants now vary depending upon backwards compatibility flags, correctly indicating the
      newest supported PA version.
    - Added the `Compatibility` enum and `get_compatibility()` function.
    - Renamed `BINDING_TARGET_VERSION` to `TARGET_VERSION_STRING`.
    - Introduced `TARGET_VERSION` and deprecated `MAJOR`, `MINOR` and `MICRO`.
    - Deprecated `get_headers_version()`.
 * Clarified PA version compatibility in `version` mod.
 * Clarified `pa_encoding_from_string` feature purpose.
 * Updated required dependencies:
    - `libpulse-sys` from 1.3 to 1.4.

# 2.2.6 (October 28th, 2018)

 * Minor tweaks, improving code clarity and such.

# 2.2.5 (October 8th, 2018)

 * Fixed broken attempt to include license file in bundled package.

# 2.2.4 (October 8th, 2018)

 * Added dedicated changelog, split off from the old single project overview one.
 * Included copy of license file in bundled package and excluded the `.gitignore` and `README.md`
   files.

# 2.2.3 (September 20th, 2018)

 * Fixed feature control.

# 2.2.2 (September 3rd, 2018)

 * Added homepage and repo links, thanks to @berkus on github for the patch.

# 2.2.1 (August 29th, 2018)

 * Fixed reported compilation errors in the `time` mode on macOS and raspberry pi platforms. Thanks
   to @noahbkim on github for reporting and @ssendev for the suggested solution.

# 2.2 (August 21st, 2018)

 * Renamed `mainloop::standard::InterateResult` to `IterateResult`, fixing an unintentional typo.
   Thanks to @HyperHamster on github for reporting.
 * Fixed a couple of compile time warnings in the `time` mod.

# 2.1 (July 17th, 2018)

 * Renamed the `timeval` mod to `time`.
 * Added `UnixTs` and `MonotonicTs` timestamp types, and put them to use with functions handling
   time events.
 * Replaced `rtclock::now()` with `MonotonicTs::now()`.
 * Mainloop events now take closures for callbacks, like the rest of the API.
 * `Operation`: Fixed possible memory leak with cancellation.
 * `Context`: Now takes a ref to the mainloop instead of the mainloop’s API in creation methods.
 * Mainloop/api: Moved the `mainloop_api_once()` method to the `Mainloop` trait from the mainloop
   API structure, and renamed it to `once_event()`.
 * Mainloop/signals: Converted to a trait and implemented on mainloops, rather than being
   implemented as methods implemented on the mainloop API structure.
 * Mainloop API objects now correctly treated as immutable. The PA devs have informed me that
   these structures are not intended to be mutated. Patches have been sent to them to correct it in
   the PA C API itself. No point in waiting for those to be accepted. The get/set userdata methods
   have been removed.
 * Mainloop/api: Added method for creating time events using monotonic time values, as an alternate
   to the similar method available on the `Context` object.
 * Added `TimeEvent::restart_rt()` method, taking monotonic time.
 * Removed `Context::rttime_restart()` method, made obsolete by the new `TimeEvent::restart_rt()`
   method on the event itself.
 * Removed the `Stream::get_context()` method.
   This method returned a ‘weak’ wrapper object, where ‘weak’ means that it deliberately will not
   decrement the ref count of the underlying C object on drop. This was exactly what was wanted
   back in v1.x, however in v2.0 we introduced closure based callbacks, and the `Context` object
   (wrapper) was extended to hold saved multi-use callbacks. This causes a problem. If you use this
   `get_context()` method to get a weak ref, then use it to change a multi-use callback, the new
   callback gets saved into the ‘weak’ object, and then you need both that and the original context
   object wrapper to both exist for the lifetime that you want the new callback to remain in use.
   Not ideal, and not obvious. To fix it would require that `Stream` creation methods take the
   `Context` with an `Rc` wrapper so it can hold onto a cloned `Rc` ref, instead of taking a
   reference, and then returning a cloned `Rc` from `get_context()`. The more simple option was to
   just remove this method, as I have done.
 * Removed the `set_destroy_cb()` event methods, which became obsolete with the switch to closure
   based callbacks.
 * Split the `DeferEvent::enable()` method into separate `DeferEvent::enable()` and
   `DeferEvent::disable()` methods.
 * Events/timer: Fixed api pointer type in callback types. Was using C API (sys) type instead of
   binding type, unlike other event callbacks.
 * Added convenience `Timeval::new()` and `Timeval::new_zero()` methods.
 * `Timeval`: Added math operation implementations, and removed the `Timeval::add()` and
   `Timeval::sub()` methods in favour of them. Also removed the `Timeval::set()` method since you
   can convert and assign from `MicroSeconds` simply with `From` and `into()`.
 * Enabled conversions between `Duration` and `MicroSeconds`, and between `Duration` and `Timeval`.
 * Added math operation implementations to `MicroSeconds` and `Timeval` for adding/subtracting
   `Duration`.
 * Removed the `Timeval::get_time_of_day()` method, preferring use of the new timestamp types.
 * Changed the `Stream::get_device_name()` method to return a `Cow<str>` instead of a `CStr`.
 * Avoided creating owned copies of static strings in a few places, returning `Cow<str>` instead.
   This includes `channelmap::Position::to_string()`, `channelmap::Map::to_name()`,
   `format::Encoding::to_string()` and `sample::Format::to_string()`.
 * Default-enabled the feature enabling the `format::Encoding::from_string()` method, for which the
   underlying function symbol was missing from PA's symbol file and thus not available in the client
   library before v12.
 * Fixed `format::Encoding::from_string()`, which would not compile due to a return type mismatch.
   (As mentioned above, the underlying symbol was missing before PA v12, leaving this previously
   untested, and it unfortunately turned out to have been broken).
 * Simplified callback proxy / setup code (internal change only).
 * Purged context documentation discussing ref counting.
 * Moved documentation discussing mainloop abstraction from the `context` mod to the `mainloop` mod.
 * Added mainloop documentation discussing callback execution.
 * Updated required dependencies:
    - `libpulse-sys` from 1.2 to 1.3.

# 2.0.1 (June 26th, 2018)

 * Updated declared PA version compatibility (11.0 → 12.0).
 * `Operation`: Documented possible memory leak.
 * `Proplist`: Fixed debug output to use comma separator rather than newline (for consistency in
   dumping introspection data), and output in list style instead of mixed struct/list style.
 * Documentation typo fixes.
 * Updated version in `README` usage example.

# 2.0 (June 16th, 2018)

 * Changed handling of callbacks to support closures!
   Now you can simply supply a closure, instead of an `extern C` function and a raw `c_void` data
   pointer, in almost any place across the binding’s API that takes a callback. (Note, there are a
   few places that have not been changed: Tackling the mainloop API stuff has been postponed to look
   at later; same for the stream write method’s optional ‘free’ callback; the `SpawnApi` has no
   userdata arg and thus cannot be done, which is not a big deal; finally the standard mainloop’s
   function for specifying an alternate ‘poll’ function has been left, at least for now).
 * Introspection: Big clean up.
   Previously we simply transmuted from the raw C structs, which was very efficient, and some
   attributes (like enums) transmuted perfectly to binding counterparts thus were ‘clean’. A lot of
   attributes however were ugly, exposing raw pointers, particularly with strings and lists. Now
   instead a proper conversion is done. This takes more effort, but gives a much more pleasant to
   use interface. Note, the `Debug` trait has been implemented, thus combined with the new support
   of closures for callbacks, makes it very easy to dump a copy of introspection data.
 * Cleaned up `context::ext_*` in the same way as introspection.
 * Renamed `CVolume` to `ChannelVolumes`.
 * Removed `Option` wrapper around `Operation` objects, using assertion that the inner pointer is
   not null.
 * Context: Handful of methods changed to take immutable `self`, per respective change in version
   1.2 of `libpulse-sys`.
 * Simplified `Format`: The inner pointer to a raw `InfoInternal` object (mistakenly hidden in v1.1,
   restored in v1.2.2) has been hidden, replaced with cleaner set/get methods. A method already
   existed for setting the encoding; one has now also been added for reading it, saving users from
   having to do an unsafe raw pointer dereference. Also, with respect to the property list, if the
   existing convenience methods are insufficient and direct access is needed, this is also now far
   cleaner; not only is the unsafe raw pointer dereference avoided, but now you are given access to
   a clean `Proplist` wrapper (see `Format::get_properties()` and `Format::get_properties_mut()`).
 * Assert added to block use of threaded mainloop `lock()` method from within the event loop thread
   (i.e. within most instances of callback execution).
 * Renamed `Stream::proplist_remove()` to `Stream::remove_proplist()`.
 * Common `Stream::set_event_callback()` callback event names moved to submodule.
 * Introspection: Removed unnecessary converters.
   The `From` trait was implemented for introspection objects in both directions between the binding
   and the sys instances. While this is necessary for the sys to binding direction, the other really
   wasn’t needed.
 * Purged subscribe autoload API (deprecated in PulseAudio since 2009).
 * Updated required dependencies:
    - `libpulse-sys` from 1.1 to 1.2.

# 1.2.2 (June 16th, 2018)

 * Restored access to `format::Info`’s `ptr` attribute.

# 1.2.1 (June 15th, 2018)

**Note: This includes a security fix!**

 * Fixed use-after-frees with `Stream::get_format_info()` and `Stream::get_context()`. These should
   have used `Stream::from_raw_weak()` instead of `Stream::from_raw()` to avoid incorrectly freeing
   the underlying C object, leaving a dangling pointer.

# 1.2 (June 1st, 2018)

 * Fixed lifetime issues with a handful of stream methods.
 * Fixed lifetime issues with `get_api()` mainloop method.
 * mainloop/standard: Fixed `run()` method’s return data. Incorrectly was returning function call
   result, while claiming in the documentation that this was the quit retval, which wasn’t returned
   at all.
 * Tidied up error code handling:
    - Added `PAErr` wrapper for the `i32` error type, for cleaner interfaces.
    - Moved the `strerror()` function to be a method of this new `PAErr` type
      (`PAErr::to_string()`).
    - Renamed `Code::strerror()` to `Code::to_string()`.
    - Converted the error `CStr` to `String` for users; no need to make users do it.
    - Implemented `From` for converting between `PAErr` and `Code` error types.
 * Simplified volume handling:
    - `Volume` and `VolumeDB` are now wrappers rather than type aliases.
    - Added the `VolumeLinear` wrapper. I had mistakenly taken floating point volumes to all be dB
      values, but there is actually a distinction between dB and ‘linear factor’, as per the C API
      conversion functions. This is now used in linear related conversions, which thus no longer
      incorrectly portray such values to be dB scale.
    - Renamed `DECIBEL_MININFTY` to `DECIBEL_MINUS_INFINITY`.
    - Renamed `CVolume::inc()` to `CVolume::increase()` and `CVolume::dec()` to
      `CVolume::decrease()` for clarity (could have been confused as increment and decrement
      functions).
 * Improved `Stream::begin_write()`:
    - The buffer returned is now converted to a slice for you, rather than burdening the caller.
    - The return type has ditched the custom `BufferResult` object.
 * Derived more common traits for a handful of structs/enums.
 * Implemented `PartialEq` for `channelmap::Map` and `volume::CVolume`.
 * Removed `Copy` and `Clone` derives from `def::SpawnApi`.
 * Improved time handling:
    - Added `Timeval` wrapper.
    - Introduced `MicroSeconds` as an `u64` wrapper, replacing use of `sample::Usecs` (now removed).
    - Tidied up conversion constants. Note, names (and in some cases types) have changed.
    - Re-exported `libc::timeval` (primarily for timer event callback use) from the `timeval` mod
      instead of `mainloop::events::timer`.
 * Added and put to use wrapper for ‘quit return values’.
 * Changed a handful of methods to return `String` rather than `CStr`. The original intention was
   to avoid unnecessary conversion, but users most likely would prefer `String`s, and there should
   definitely not be a problem with “lossy” utf8 conversion in these cases.
 * Changed return value of `Stream::get_underflow_index()` to unsigned.
 * Hid string printing length constants, only used internally.
 * Rewrote string printing functions to use a `Vec` as the string buffer instead of
   `libc::malloc()`, thus more simple, and removed the `Option` result wrapper.
 * Changed several `sample::Format` related functions to methods.
 * Minor `Stream` documentation fixes.

# 1.1 (May 27th, 2018)

 * Privatised the `from_raw()` method of various objects, having become aware of the more granular
   `pub(crate)` type scope limiting syntax. Note, `from_raw_weak()` methods designed for use in
   callbacks are still available.
 * Also privatised inner pointer attributes of structs in a few places on the same basis.
 * Privatised the `utils::unwrap_optional_callback()` function.
 * Privatised timer event's `get_ptr()` method.
 * Various functions have been changed to take immutable references for certain params, reflecting
   the change in version 1.1 of the `libpulse-sys` crate.
 * Promoted `self` reference to mutable for various methods across context, mainloops, streams,
   proplist and operation objects. Although our objects in these cases can be used immutably (no
   change in the wrapped pointer), we should reflect mutability needs of the operation being
   performed on the underlying C objects.
 * Updated required dependencies:
    - `libpulse-sys` from 1.0 to 1.1.

# 1.0.5 (May 27th, 2018)

 * Fixed and simplified `Proplist` iteration:
    - Fixed an infinite loop bug: I misread the documentation, it’s the return value from the C
      function call that will be NULL when it reaches the end of the list, not the state variable.
    - Fixed infinite loop bug #2: The state tracking variable used for the underlying C function
      cannot be hidden within the iterate function, it causes an infinite loop whereby the function
      always just returns the first entry wrapped in `Some`. I don’t know what I was thinking.
    - Implemented proper iterator semantics. The `iterate()` method was renamed `iter()` and now
      returns an actual Rust `Iterator` object, which makes iterating much more simple and tidy.
 * Made `self` immutable for `CVolume::is_muted()` and `CVolume::is_norm()`.
 * Fixed unwanted double option wrapping of callback fn ptr with `Stream` write methods.
 * Combined `Stream::write_ext_free()`’s `free_cb_data` param with `free_cb` as tuple, as done
   elsewhere.

Note, version number 1.0.4 skipped (it was used for non-crate project changes).

# 1.0.3 (February 10th, 2018)

 * Added `From` methods for transmuting between certain introspection structs and their `sys`
   counterparts. (They are identical, and only duplicated in the binding to add documentation).

# 1.0.2 (February 9th, 2018)

 * Added travis badge.

# 1.0.1 (February 2nd, 2018)

 * Fixed toml file license string `LGPL-2.1` → `LGPL-2.1+`.
 * Fixed toml file missing author email address.
 * Removed obsolete readme doc links.

# 1.0 (January 24th, 2018)

 * Original release.

[`bitflags`]: https://docs.rs/bitflags
[issue11]: https://github.com/jnqnfe/pulse-binding-rust/issues/11
[issue26]: https://github.com/jnqnfe/pulse-binding-rust/issues/26
[issue48]: https://github.com/jnqnfe/pulse-binding-rust/issues/48
