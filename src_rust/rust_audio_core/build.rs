fn main() {
    println!("cargo:rustc-link-lib=asound");
    println!("cargo:rustc-link-lib=gstbase-1.0");
    if pkg_config::Config::new()
        .atleast_version("0.22")
        .probe("lilv-0")
        .is_err()
    {
        println!("cargo:rustc-link-lib=lilv-0");
    }

    // GLIBC compatibility: wrap log10f to avoid requiring GLIBC_2.43.
    // On Fedora 44 the linker resolves log10f to GLIBC_2.43; --wrap
    // redirects all calls to our __wrap_log10f (logf-based) instead.
    cc::Build::new()
        .file("glibc_compat.c")
        .compile("glibc_compat");
    println!("cargo:rustc-link-arg=-Wl,--wrap=log10f");
    println!("cargo:rustc-link-arg=-Wl,--wrap=__isoc23_strtol");
    println!("cargo:rustc-link-arg=-Wl,--wrap=__isoc23_sscanf");
    println!("cargo:rustc-link-arg=-Wl,--wrap=__isoc23_vsscanf");
}
