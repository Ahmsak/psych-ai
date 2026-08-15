"""Sprint 16 unit tests: Client layer (grouping Client -> Sessions).

Uses a real SQLite store on a temp DB (no Whisper, no GUI). The transcription
backend is irrelevant here — we only assert Client/Session persistence and the
Orchestrator delegation.
"""
from __future__ import annotations

import os

from db.session_store import SessionStore
from orchestrator.orchestrator import Orchestrator


def _store(tmp_path):
    return SessionStore(str(tmp_path / "clients.db"))


def test_create_client_global_sequence(tmp_path):
    store = _store(tmp_path)
    c1 = store.create_client("Тест")
    c2 = store.create_client("Тест")          # same name -> next global number
    c3 = store.create_client("Иван")           # different name -> next global
    assert c1.client_number == 1
    assert c2.client_number == 2
    assert c3.client_number == 3
    # display_name keeps the base name only ("Тест"), number is separate
    assert c1.display_name == "Тест"
    assert c2.display_name == "Тест"
    assert c3.display_name == "Иван"


def test_client_label_format(tmp_path):
    from ui.state import client_label

    assert client_label({"display_name": "Тест", "client_number": 1}) == "Тест 001"
    assert client_label({"display_name": "Иван", "client_number": 3}) == "Иван 003"
    assert client_label({"display_name": "", "client_number": 7}) == "Клиент 007"


def test_list_clients_stable_order(tmp_path):
    store = _store(tmp_path)
    for n in ("Б", "А", "В"):
        store.create_client(n)
    labels = [c["display_name"] for c in store.list_clients()]
    # ordered by client_number (1,2,3), not by name
    assert labels == ["Б", "А", "В"]


def test_session_binds_to_correct_client(tmp_path):
    store = _store(tmp_path)
    client = store.create_client("Тест")
    sid = store.create_session(started_at=None, client_id=client.id)
    got = store.get_session(sid)
    assert got["client_id"] == client.id
    assert got["client_name"] == "Тест"
    assert got["client_number"] == client.client_number


def test_list_client_sessions_excludes_others(tmp_path):
    store = _store(tmp_path)
    c1 = store.create_client("Тест")
    c2 = store.create_client("Иван")
    s1 = store.create_session(started_at=None, client_id=c1.id)
    s2 = store.create_session(started_at=None, client_id=c2.id)
    s1b = store.create_session(started_at=None, client_id=c1.id)
    c1_sessions = store.list_client_sessions(c1.id)
    ids = {s["id"] for s in c1_sessions}
    assert ids == {s1, s1b}
    assert s2 not in ids


def test_legacy_sessions_null_client(tmp_path):
    store = _store(tmp_path)
    # legacy session without a client
    sid = store.create_session(started_at=None)
    got = store.get_session(sid)
    assert got["client_id"] is None
    groups = _group(store.list_sessions())
    # legacy sessions appear under "Без клиента" group only
    labels = [g["label"] for g in groups]
    assert "Без клиента" in labels


def test_orchestrator_create_and_list_clients(tmp_path):
    orch = Orchestrator(db_path=str(tmp_path / "orch.db"))
    orch.create_client("Тест")
    orch.create_client("Тест")
    clients = orch.list_clients()
    assert [c["client_number"] for c in clients] == [1, 2]
    assert all(c["display_name"] == "Тест" for c in clients)


def test_orchestrator_start_recording_saves_client_id(tmp_path):
    orch = Orchestrator(db_path=str(tmp_path / "orch2.db"))
    client = orch.create_client("Тест")
    state = orch.start_recording(client_id=client["id"])
    sid = state.get("session_id")
    assert sid is not None
    sess = orch.get_session(sid)
    assert sess["client_id"] == client["id"]


def _group(sessions):
    from ui.state import client_session_groups

    return client_session_groups(sessions)
