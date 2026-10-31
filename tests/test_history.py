import time

from sayso.core.history import History


def add(h, text="hello", app="notepad", **kw):
    return h.add(app=app, mode="chat_mode", transcript="raw " + text, text=text, stt_engine="fake", llm_provider="ai",
                 latency_ms=500, confidence=0.8, **kw)


def test_add_recent_search_delete_clear(tmp_path):
    h = History(tmp_path / "h.db")
    a, b = add(h, "alpha"), add(h, "beta", app="OUTLOOK")
    items = h.recent()
    assert [i.text for i in items] == ["beta", "alpha"]
    assert items[0].app == "OUTLOOK" and items[0].confidence == 0.8
    assert [i.text for i in h.recent(query="alp")] == ["alpha"]
    assert [i.text for i in h.recent(query="outlook")] == ["beta"]
    assert len(h.recent(limit=1)) == 1
    h.delete(a)
    assert [i.id for i in h.recent()] == [b]
    h.clear()
    assert h.recent() == []
    h.close()


def test_disabled_stores_nothing(tmp_path):
    h = History(tmp_path / "h.db", enabled=False)
    assert add(h) is None and h.recent() == []


def test_retention_prunes_old(tmp_path):
    h = History(tmp_path / "h.db", retention_days=1)
    add(h, "new")
    h._db.execute("INSERT INTO history (created, app, text, transcript) VALUES (?,?,?,?)", (time.time() - 3 * 86400, "a", "old", "old"))
    h._db.commit()
    h.prune()
    assert [i.text for i in h.recent()] == ["new"]


def test_retention_zero_keeps_everything(tmp_path):
    h = History(tmp_path / "h.db", retention_days=0)
    h._db.execute("INSERT INTO history (created, app, text, transcript) VALUES (?,?,?,?)", (1.0, "a", "ancient", "x"))
    h._db.commit()
    h.prune()
    assert len(h.recent()) == 1
