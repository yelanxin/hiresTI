"""
Common path utilities for cache, config, and data directories.
"""
import os


def _get_xdg_dir(env_var: str, fallback: str) -> str:
    """Get XDG-compatible directory with fallback."""
    xdg = os.environ.get(env_var)
    if xdg:
        return os.path.join(xdg, 'hiresti')
    return os.path.expanduser(fallback)


def get_cache_dir() -> str:
    """
    Get cache directory for app data.
    Supports XDG_CACHE_HOME (automatically set by Flatpak).
    """
    return _get_xdg_dir('XDG_CACHE_HOME', '~/.cache/hiresti')


def get_config_dir() -> str:
    """
    Get config directory for app settings.
    Supports XDG_CONFIG_HOME (automatically set by Flatpak).
    """
    return _get_xdg_dir('XDG_CONFIG_HOME', '~/.config/hiresti')


def get_data_dir() -> str:
    """
    Get data directory for app data.
    Supports XDG_DATA_HOME (automatically set by Flatpak).
    """
    return _get_xdg_dir('XDG_DATA_HOME', '~/.local/share/hiresti')
