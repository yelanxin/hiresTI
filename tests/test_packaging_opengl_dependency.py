from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


def test_packaging_inputs_include_pyopengl():
    requirements = (REPO_ROOT / "requirements.txt").read_text()
    package_sh = (REPO_ROOT / "package.sh").read_text()
    flatpak_requirements = (REPO_ROOT / "flatpak" / "requirements-flatpak.txt").read_text()
    flatpak_json = (REPO_ROOT / "flatpak" / "python3-requirements.json").read_text()

    assert "PyOpenGL>=" in requirements
    assert "PyOpenGL>=" in flatpak_requirements
    assert "PyOpenGL" in package_sh
    assert '"OpenGL"' in package_sh
    assert '"name": "python3-pyopengl"' in flatpak_json


def test_system_package_builds_declare_opengl_dependency():
    package_sh = (REPO_ROOT / "package.sh").read_text()
    pkgbuild = (REPO_ROOT / "aur" / "hiresti" / "PKGBUILD").read_text()
    srcinfo = (REPO_ROOT / "aur" / "hiresti" / ".SRCINFO").read_text()
    readme = (REPO_ROOT / "README.md").read_text()
    test_ui = (REPO_ROOT / "test_ui.sh").read_text()
    pyinstaller = (REPO_ROOT / "tools" / "build_py_binary.sh").read_text()

    assert "python3-opengl" in package_sh
    assert "python3-pyopengl" in package_sh
    assert "depend = python-opengl" in package_sh
    assert "'python-opengl'" in pkgbuild
    assert "depends = python-opengl" in srcinfo
    assert "`PyOpenGL`" in readme
    assert "python3-opengl" in test_ui
    assert "--collect-submodules OpenGL" in pyinstaller
