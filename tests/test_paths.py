"""Tests for path utilities."""

import os
from pathlib import Path

from gcontact_sync.utils.paths import (
    CONFIG_DIR_ENV_VAR,
    DEFAULT_CONFIG_DIR,
    resolve_config_dir,
)


class TestDefaultConfigDir:
    """Test DEFAULT_CONFIG_DIR constant."""

    def test_default_config_dir_is_in_home(self):
        """Default config dir should be in user's home directory."""
        assert Path.home() / ".gcontact-sync" == DEFAULT_CONFIG_DIR

    def test_default_config_dir_is_path(self):
        """Default config dir should be a Path object."""
        assert isinstance(DEFAULT_CONFIG_DIR, Path)


class TestResolveConfigDir:
    """Test resolve_config_dir function."""

    def test_explicit_path_string(self, tmp_path):
        """Explicit path string should be used."""
        result = resolve_config_dir(str(tmp_path))
        assert result == tmp_path.resolve()

    def test_explicit_path_object(self, tmp_path):
        """Explicit Path object should be used."""
        result = resolve_config_dir(tmp_path)
        assert result == tmp_path.resolve()

    def test_explicit_path_with_tilde(self):
        """Explicit path with ~ should be expanded."""
        result = resolve_config_dir("~/custom-config")
        assert result == Path.home() / "custom-config"

    def test_env_var_override(self, tmp_path, monkeypatch):
        """Environment variable should override default when no explicit path."""
        monkeypatch.setenv(CONFIG_DIR_ENV_VAR, str(tmp_path))
        result = resolve_config_dir(None)
        assert result == tmp_path.resolve()

    def test_env_var_with_tilde(self, monkeypatch):
        """Environment variable with ~ should be expanded."""
        monkeypatch.setenv(CONFIG_DIR_ENV_VAR, "~/env-config")
        result = resolve_config_dir(None)
        assert result == Path.home() / "env-config"

    def test_default_when_no_explicit_and_no_env(self, monkeypatch):
        """Default should be used when no explicit path and no env var."""
        monkeypatch.delenv(CONFIG_DIR_ENV_VAR, raising=False)
        result = resolve_config_dir(None)
        assert result == DEFAULT_CONFIG_DIR.expanduser().resolve()

    def test_explicit_overrides_env_var(self, tmp_path, monkeypatch):
        """Explicit path should override environment variable."""
        env_path = tmp_path / "env"
        env_path.mkdir()
        monkeypatch.setenv(CONFIG_DIR_ENV_VAR, str(env_path))

        explicit_path = tmp_path / "explicit"
        explicit_path.mkdir()

        result = resolve_config_dir(str(explicit_path))
        assert result == explicit_path.resolve()

    def test_result_is_always_absolute(self, tmp_path, monkeypatch):
        """Result should always be an absolute path."""
        # Change to tmp_path so relative paths work
        original_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            result = resolve_config_dir("relative-dir")
            assert result.is_absolute()
        finally:
            os.chdir(original_cwd)
