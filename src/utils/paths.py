"""
Common path utilities for cache, config, and data directories.
"""
import os


def get_cache_dir() -> str:
    """
    Get cache directory for app data.
    Supports XDG_CACHE_HOME (automatically set by Flatpak).
    """
    xdg_cache = os.environ.get('XDG_CACHE_HOME')
    if xdg_cache:
        return os.path.join(xdg_cache, 'hiresti')
    return os.path.expanduser('~/.cache/hiresti')


def get_config_dir() -> str:
    """
    Get config directory for app settings.
    Supports XDG_CONFIG_HOME (automatically set by Flatpak).
    """
    xdg_config = os.environ.get('XDG_CONFIG_HOME')
    if xdg_config:
        return os.path.join(xdg_config, 'hiresti')
    return os.path.expanduser('~/.config/hiresti')


def get_data_dir() -> str:
    """
    Get data directory for app data.
    Supports XDG_DATA_HOME (automatically set by Flatpak).
    """
    xdg_data = os.environ.get('XDG_DATA_HOME')
    if xdg_data:
        return os.path.join(xdg_data, 'hiresti')
    return os.path.expanduser('~/.local/share/hiresti')
