import os
import re


def test_flatpak_metainfo_top_release_matches_version_txt():
    repo_root = os.path.join(os.path.dirname(__file__), "..")
    version_path = os.path.join(repo_root, "version.txt")
    metainfo_path = os.path.join(repo_root, "flatpak", "com.hiresti.player.metainfo.xml")

    with open(version_path, "r", encoding="utf-8") as f:
        version = f.read().strip()

    with open(metainfo_path, "r", encoding="utf-8") as f:
        metainfo = f.read()

    match = re.search(r'<release version="([^"]+)" date="([^"]+)"\s*/>', metainfo)
    assert match is not None, "flatpak metainfo is missing a <release> entry"
    assert match.group(1) == version
