use std::env;
use std::path::{Path, PathBuf};
use std::process::{Command, ExitCode, Stdio};

fn resolve_app_dir() -> PathBuf {
    // Check for src/main.py in new directory structure
    let flatpak_packaged = PathBuf::from("/app/share/hiresti");
    if flatpak_packaged.join("src/main.py").is_file() {
        return flatpak_packaged;
    }

    let packaged = PathBuf::from("/usr/share/hiresti");
    if packaged.join("src/main.py").is_file() {
        return packaged;
    }

    // Also check old structure for backwards compatibility
    if flatpak_packaged.join("main.py").is_file() {
        return flatpak_packaged;
    }
    if packaged.join("main.py").is_file() {
        return packaged;
    }

    if let Ok(exe) = env::current_exe() {
        if let Some(exe_dir) = exe.parent() {
            // Check src/main.py (new structure)
            if exe_dir.join("src/main.py").is_file() {
                return exe_dir.to_path_buf();
            }
            // Check main.py (old structure / development)
            if exe_dir.join("main.py").is_file() {
                return exe_dir.to_path_buf();
            }
            // Check parent/src/main.py
            if let Some(parent) = exe_dir.parent() {
                if parent.join("src/main.py").is_file() {
                    return parent.to_path_buf();
                }
                if parent.join("main.py").is_file() {
                    return parent.to_path_buf();
                }
            }
        }
    }

    env::current_dir().unwrap_or_else(|_| PathBuf::from("."))
}

fn merged_pythonpath(app_dir: &Path) -> String {
    let libs = app_dir.join("libs");
    let libs_str = libs.to_string_lossy().to_string();
    match env::var("PYTHONPATH") {
        Ok(existing) if !existing.trim().is_empty() => format!("{libs_str}:{existing}"),
        _ => libs_str,
    }
}

fn main() -> ExitCode {
    let app_dir = resolve_app_dir();
    let bundled_bin = app_dir.join("hiresti_app").join("hiresti_app");
    if bundled_bin.is_file() {
        let mut cmd = Command::new(&bundled_bin);
        cmd.args(env::args().skip(1))
            .current_dir(&app_dir)
            .stdin(Stdio::inherit())
            .stdout(Stdio::inherit())
            .stderr(Stdio::inherit());
        return match cmd.status() {
            Ok(status) => match status.code() {
                Some(code) => ExitCode::from(code as u8),
                None => ExitCode::from(1),
            },
            Err(err) => {
                eprintln!(
                    "hiresti launcher error: failed to spawn bundled binary {}: {err}",
                    bundled_bin.display()
                );
                ExitCode::from(1)
            }
        };
    }

    // Check both src/main.py (new) and main.py (old) for backwards compatibility
    let _main_py = if app_dir.join("src/main.py").is_file() {
        app_dir.join("src/main.py")
    } else if app_dir.join("main.py").is_file() {
        app_dir.join("main.py")
    } else {
        eprintln!("hiresti launcher error: main.py not found in {}", app_dir.display());
        return ExitCode::from(1);
    };

    let main_py_arg = if app_dir.join("src/main.py").is_file() {
        "src/main.py"
    } else {
        "main.py"
    };

    let mut cmd = Command::new("python3");
    cmd.arg(main_py_arg)
        .args(env::args().skip(1))
        .current_dir(&app_dir)
        .env("PYTHONPATH", merged_pythonpath(&app_dir))
        .stdin(Stdio::inherit())
        .stdout(Stdio::inherit())
        .stderr(Stdio::inherit());

    match cmd.status() {
        Ok(status) => match status.code() {
            Some(code) => ExitCode::from(code as u8),
            None => ExitCode::from(1),
        },
        Err(err) => {
            eprintln!("hiresti launcher error: failed to spawn python3: {err}");
            ExitCode::from(1)
        }
    }
}
