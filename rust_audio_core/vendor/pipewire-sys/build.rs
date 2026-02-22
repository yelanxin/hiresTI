// Copyright The pipewire-rs Contributors.
// SPDX-License-Identifier: MIT

use std::env;
use std::path::PathBuf;

fn main() {
    let libs = system_deps::Config::new()
        .probe()
        .expect("Cannot find libpipewire");
    let libpipewire = libs.get_by_name("libpipewire").unwrap();

    // Tell cargo to invalidate the built crate whenever the wrapper changes
    println!("cargo:rerun-if-changed=wrapper.h");

    let builder = bindgen::Builder::default()
        .header("wrapper.h")
        // Tell cargo to invalidate the built crate whenever any of the
        // included header files changed.
        .parse_callbacks(Box::new(bindgen::CargoCallbacks::new()))
        .size_t_is_usize(true)
        .allowlist_function("pw_.*")
        .allowlist_type("pw_.*")
        .allowlist_var("pw_.*")
        .allowlist_var("PW_.*")
        .blocklist_function("spa_.*")
        .blocklist_type("spa_.*")
        .blocklist_item("spa_.*")
        .raw_line("use spa_sys::*;");

    let builder = libpipewire
        .include_paths
        .iter()
        .fold(builder, |builder, l| {
            let arg = format!("-I{}", l.to_string_lossy());
            builder.clang_arg(arg)
        });

    let bindings = builder.generate().expect("Unable to generate bindings");

    // Write the bindings to the $OUT_DIR/bindings.rs file.
    let out_path = PathBuf::from(env::var("OUT_DIR").unwrap());
    bindings
        .write_to_file(out_path.join("bindings.rs"))
        .expect("Couldn't write bindings!");
}
