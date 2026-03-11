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
}
