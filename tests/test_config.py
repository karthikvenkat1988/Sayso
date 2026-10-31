import json

from sayso.core.config import (
    LoadedSettings,
    Settings,
    deep_merge,
    flatten_keys,
    load_settings,
    save_settings,
)
from sayso.core.modes import Mode


def test_defaults_round_trip():
    s = Settings()
    again = Settings.from_dict(json.loads(json.dumps(s.to_dict())))
    assert again == s
    assert again.general.default_mode is Mode.REWRITE_TEXT


def test_partial_provider_override_keeps_other_defaults():
    s = Settings.from_dict({"llm": {"providers": {"ollama": {"model": "qwen2.5:7b"}}}})
    assert s.llm.providers["ollama"].model == "qwen2.5:7b"
    assert s.llm.providers["ollama"].base_url == "http://127.0.0.1:11434/v1"
    assert "anthropic" in s.llm.providers


def test_invalid_values_fall_back_to_defaults():
    s = Settings.from_dict({"general": {"default_mode": "nonsense"}, "audio": {"vad_threshold_db": "loud"}})
    assert s.general.default_mode is Mode.REWRITE_TEXT
    assert isinstance(s.audio.vad_threshold_db, (int, float))


def test_int_accepted_for_float():
    s = Settings.from_dict({"llm": {"timeout_s": 4}})
    assert s.llm.timeout_s == 4.0


def test_profiles_parse_modes():
    s = Settings.from_dict({"profiles": [{"processes": ["x"], "mode": "chat_mode"}]})
    assert s.profiles[0].mode is Mode.CHAT


def test_deep_merge_and_flatten():
    assert deep_merge({"a": {"b": 1, "c": 2}}, {"a": {"b": 9}}) == {"a": {"b": 9, "c": 2}}
    assert flatten_keys({"a": {"b": 1, "c": {"d": 2}}, "e": []}) == {"a.b", "a.c.d", "e"}


def test_policy_merge_and_locked_keys(tmp_path):
    user = tmp_path / "settings.json"
    policy = tmp_path / "policy.json"
    user.write_text(json.dumps({"privacy": {"offline_only": False}, "general": {"sounds": False}}))
    policy.write_text(json.dumps({"$comment": "hi", "privacy": {"offline_only": True}}))
    loaded = load_settings(user, policy)
    assert loaded.settings.privacy.offline_only is True
    assert loaded.settings.general.sounds is False
    assert loaded.policy_present
    assert loaded.is_locked("privacy.offline_only")
    assert loaded.is_locked("privacy")  # parent of a locked key
    assert not loaded.is_locked("general.sounds")
    assert "$comment" not in loaded.locked


def test_missing_and_corrupt_files(tmp_path):
    bad = tmp_path / "settings.json"
    bad.write_text("{not json")
    loaded = load_settings(bad, tmp_path / "nope.json")
    assert loaded.settings == Settings()
    assert not loaded.policy_present
    assert isinstance(loaded, LoadedSettings)


def test_utf8_bom_is_tolerated(tmp_path):
    f = tmp_path / "settings.json"
    f.write_bytes(b"\xef\xbb\xbf" + json.dumps({"general": {"sounds": False}}).encode())
    assert load_settings(f, None).settings.general.sounds is False


def test_save_drops_locked_keys(tmp_path):
    s = Settings()
    s.privacy.offline_only = True
    s.general.sounds = False
    f = tmp_path / "sub" / "settings.json"
    save_settings(s, f, locked={"privacy.offline_only"})
    data = json.loads(f.read_text())
    assert "offline_only" not in data["privacy"]
    assert data["general"]["sounds"] is False
    assert not f.with_suffix(".tmp").exists()
