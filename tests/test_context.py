from sayso.core.config import AppProfile, Settings
from sayso.core.context import FocusContext, resolve
from sayso.core.modes import Mode


def test_password_field_blocked():
    r = resolve(Settings(), FocusContext(process="chrome", is_password=True))
    assert r.blocked and r.mode is Mode.RAW_TRANSCRIPT and not r.allow_cloud


def test_blocked_app():
    r = resolve(Settings(), FocusContext(process="KeePassXC.exe"))
    assert r.blocked and "blocked" in r.reason


def test_profile_match_case_insensitive_and_exe_suffix():
    s = Settings()
    assert resolve(s, FocusContext(process="outlook.EXE")).mode is Mode.EMAIL
    assert resolve(s, FocusContext(process="Teams")).mode is Mode.CHAT
    assert resolve(s, FocusContext(process="notepad")).mode is s.general.default_mode


def test_profile_tone_and_override():
    s = Settings()
    r = resolve(s, FocusContext(process="OUTLOOK"))
    assert r.tone
    assert resolve(s, FocusContext(process="OUTLOOK"), override=Mode.CHAT).mode is Mode.CHAT


def test_profile_without_mode_uses_default():
    s = Settings(profiles=[AppProfile(["foo"], None, "tone")])
    assert resolve(s, FocusContext(process="foo")).mode is s.general.default_mode


def test_no_cloud_apps_and_offline_only():
    s = Settings()
    s.privacy.no_cloud_apps = ["epic"]
    assert not resolve(s, FocusContext(process="Epic.exe")).allow_cloud
    assert resolve(s, FocusContext(process="notepad")).allow_cloud
    s.privacy.offline_only = True
    assert not resolve(s, FocusContext(process="notepad")).allow_cloud


def test_command_requires_flag():
    s = Settings()
    assert resolve(s, FocusContext(process="notepad"), command=True).mode is Mode.COMMAND
    assert resolve(s, FocusContext(process="notepad")).mode is not Mode.COMMAND
