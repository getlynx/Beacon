"""Beacon package."""

import subprocess
import os

def _get_version_from_git():
    """Get version from git tags, falling back to a default if not available."""
    # Cache the version to avoid repeated subprocess calls
    if hasattr(_get_version_from_git, '_cached_version'):
        return _get_version_from_git._cached_version

    try:
        # Check if we're in a git repository
        git_dir = os.path.join(os.path.dirname(__file__), '..', '.git')
        if not os.path.exists(git_dir):
            version = "0.1.0"  # Default version if not in git repo
        else:
            # Get the most recent tag that matches the current commit
            result = subprocess.run(
                ['git', 'describe', '--tags', '--exact-match'],
                capture_output=True,
                text=True,
                cwd=os.path.dirname(__file__),
                timeout=5
            )

            if result.returncode == 0:
                # We're on a tagged commit, use that tag
                version = result.stdout.strip()
            else:
                # Not on a tagged commit, get the most recent tag with commit info
                result = subprocess.run(
                    ['git', 'describe', '--tags', '--always'],
                    capture_output=True,
                    text=True,
                    cwd=os.path.dirname(__file__),
                    timeout=5
                )
                if result.returncode == 0:
                    version = result.stdout.strip()
                    # If it contains a commit hash (e.g., v2.27.0-5-g1234567),
                    # mark it as a development version
                    if '-' in version and not version.replace('-', '').replace('.', '').isdigit():
                        parts = version.split('-')
                        base_version = parts[0]
                        commits_ahead = parts[1] if len(parts) > 1 else "0"
                        version = f"{base_version}.dev{commits_ahead}"
                else:
                    version = "0.1.0"

            # Remove 'v' prefix if present
            if version.startswith('v'):
                version = version[1:]

    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        # Git not available or other error
        version = "0.1.0"

    # Cache the version
    _get_version_from_git._cached_version = version
    return version

__version__ = _get_version_from_git()
