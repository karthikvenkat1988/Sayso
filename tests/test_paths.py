from sayso.core.paths import is_portable, resolve_paths


def test_flag_file_enables_portable(tmp_path, monkeypatch):
    monkeypatch.delenv("SAYSO_PORTABLE", raising=False)
    monkeypatch.delenv("SAYSO_HOME", raising=False)
    assert not is_portable(tmp_path)
    (tmp_path / "portable").write_text("")
    assert is_portable(tmp_path)
    p = resolve_paths(tmp_path)
    assert p.portable
    assert p.config_dir == tmp_path / "data" / "config"
    assert p.settings_file == tmp_path / "data" / "config" / "settings.json"
    assert p.history_db == tmp_path / "data" / "history.sqlite3"


def test_env_flag(tmp_path, monkeypatch):
    monkeypatch.delenv("SAYSO_HOME", raising=False)
    monkeypatch.setenv("SAYSO_PORTABLE", "1")
    assert is_portable(tmp_path)


def test_home_override(tmp_path, monkeypatch):
    monkeypatch.setenv("SAYSO_HOME", str(tmp_path / "h"))
    p = resolve_paths(tmp_path)
    assert p.data_dir == tmp_path / "h" / "data"
    assert p.portable


def test_installed_layout_uses_appdata(tmp_path, monkeypatch):
    monkeypatch.delenv("SAYSO_PORTABLE", raising=False)
    monkeypatch.delenv("SAYSO_HOME", raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    p = resolve_paths(tmp_path / "app")
    assert not p.portable
    assert p.config_dir == tmp_path / "roaming" / "Sayso"
    assert p.data_dir == tmp_path / "local" / "Sayso"


def test_policy_lookup_prefers_file_next_to_exe(tmp_path, monkeypatch):
    monkeypatch.delenv("SAYSO_PORTABLE", raising=False)
    monkeypatch.delenv("SAYSO_HOME", raising=False)
    monkeypatch.setenv("PROGRAMDATA", str(tmp_path / "pd"))
    assert resolve_paths(tmp_path).policy_file == tmp_path / "pd" / "Sayso" / "policy.json"
    (tmp_path / "policy.json").write_text("{}")
    assert resolve_paths(tmp_path).policy_file == tmp_path / "policy.json"


def test_ensure_creates_dirs(tmp_paths):
    assert tmp_paths.models_dir.is_dir()
    assert tmp_paths.log_file.parent.is_dir()
