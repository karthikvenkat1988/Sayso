import pytest

from sayso.core.modes import Mode
from sayso.llm.offline import OfflineRewriter
from sayso.llm.prompts import PromptContext

SPEC = "hey can you tell john I'll be late"


@pytest.mark.parametrize("mode", [Mode.PROFESSIONAL, Mode.EMAIL, Mode.CHAT])
def test_spec_example_addresses_john(mode):
    out = OfflineRewriter.apply(SPEC, mode)
    assert out.startswith("Hi John,")
    assert "I'll be late" in out


def test_email_has_greeting_and_closing():
    out = OfflineRewriter.apply(SPEC, Mode.EMAIL)
    assert out.splitlines()[0] == "Hi John,"
    assert out.rstrip().endswith("Thanks,")


def test_team_becomes_everyone():
    assert OfflineRewriter.apply("let the team know the build is fixed", Mode.CHAT).startswith("Hi everyone,")


def test_pronoun_flip():
    out = OfflineRewriter.apply("tell sarah I sent it to her", Mode.CHAT)
    assert out == "Hi Sarah, I sent it to you."


def test_rewrite_text_cleans_and_punctuates():
    assert OfflineRewriter.apply("um this is a test", Mode.REWRITE_TEXT) == "This is a test."


def test_raw_and_command_not_punctuated():
    assert OfflineRewriter.apply("make it shorter", Mode.COMMAND) == "Make it shorter"
    assert OfflineRewriter.apply("hello", Mode.RAW_TRANSCRIPT) == "Hello"


def test_professional_non_relay():
    assert OfflineRewriter.apply("the report is done", Mode.PROFESSIONAL) == "The report is done."


def test_email_non_relay_gets_wrapper():
    assert OfflineRewriter.apply("the report is done", Mode.EMAIL) == "Hi,\n\nThe report is done.\n\nThanks,"


def test_meeting_notes_bullets():
    out = OfflineRewriter.apply("we agreed on the date. john owns the follow up", Mode.MEETING_NOTES)
    assert out.splitlines() == ["- We agreed on the date.", "- John owns the follow up."]


def test_provider_interface_streams_delta():
    seen: list[str] = []
    r = OfflineRewriter().rewrite(
        "hello", Mode.REWRITE_TEXT, PromptContext(), share_context=False, on_delta=seen.append
    )
    assert r.provider == "offline" and seen == [r.text]
