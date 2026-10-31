from sayso.core.capabilities import Probes, http_reach, probe


def test_defaults_report_unknown(settings, tmp_paths):
    settings.privacy.offline_only = True
    r = probe(settings, tmp_paths)
    assert r.microphone == ("unknown", "") and r.internet[0] == "ok" and r.portable
    d = r.to_dict()
    assert d["microphone"] == ["unknown", ""] and isinstance(d["providers"], dict)


def test_probes_are_injected(settings, tmp_paths):
    p = Probes(
        microphone=lambda: ("blocked", "denied"),
        elevated=lambda: True,
        stt_engines=lambda: {"faster_whisper": ("ok", "")},
        providers=lambda: {"anthropic": ("blocked", "403")},
        reach=lambda url: ("ok", "HTTP 200"),
    )
    r = probe(settings, tmp_paths, probes=p)
    assert r.microphone == ("blocked", "denied") and r.elevated
    assert r.stt_engines["faster_whisper"][0] == "ok" and r.providers["anthropic"] == ("blocked", "403")
    assert r.internet[0] == "ok"


def test_internet_blocked_when_nothing_reachable(settings, tmp_paths):
    r = probe(settings, tmp_paths, probes=Probes(reach=lambda url: ("blocked", "ConnectError")))
    assert r.internet == ("blocked", "ConnectError")


def test_quick_skips_network(settings, tmp_paths):
    def boom(url):
        raise AssertionError("should not be called")

    assert probe(settings, tmp_paths, quick=True, probes=Probes(reach=boom)).internet[0] == "unknown"


def test_no_cloud_providers_configured(settings, tmp_paths):
    settings.llm.chain = ["ollama", "offline"]
    assert probe(settings, tmp_paths, probes=Probes()).internet[1] == "no cloud service configured"


def test_http_reach_maps_errors():
    import httpx
    import respx

    with respx.mock:
        respx.head("https://a.example").mock(return_value=httpx.Response(401))
        assert http_reach("https://a.example")[0] == "ok"
        respx.head("https://b.example").mock(return_value=httpx.Response(407))
        assert http_reach("https://b.example")[0] == "blocked"
        respx.head("https://c.example").mock(side_effect=httpx.ConnectError("x"))
        assert http_reach("https://c.example") == ("blocked", "ConnectError")
