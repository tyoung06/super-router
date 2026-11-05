"""Brief 30, decision 20: the regenerated demo shows the new parts, from invented placeholder data only: Setup's Router
notes with placeholder lines in each section; a project's Notes with a pinned note; a card with Pin to notes and Save to
project; a saved file's entry in a project's block; a forgotten card with Remember again. (The claims in Details come
with part K.) The demo answers 409 to every POST, these actions among them."""
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "demo"


def _doc(name):
    return json.loads((DEMO / name).read_text(encoding="utf-8"))


def test_setup_reads_router_notes_with_a_placeholder_line_in_each_section():
    status = _doc("status.json")["notes"]
    assert status["state"] == "set" and all(status["sections"][k] for k in status["sections"])
    found = _doc("notes.json")["notes"]
    assert found["hash"] == status["hash"] and all(line.startswith(("## ", "<")) or not line
                                                   for line in found["text"].splitlines())


def test_a_projects_notes_hold_a_pinned_note_and_its_block_a_saved_files_entry():
    found = _doc("project-notes/garden-site.json")["notes"]
    assert "### Pinned from #" in found["notes"] and "· saved: docs/lending-rules.md (from #" in found["block"]


def test_a_card_offers_pin_and_save_and_a_forgotten_card_offers_remember_again():
    tasks = _doc("log.json")["tasks"]
    assert any(t["card_actions"]["pin"] and t["card_actions"]["save"] and t.get("save_path") for t in tasks)
    gone = [t for t in tasks if t["forgotten"]]
    assert len(gone) == 1 and gone[0]["card_actions"] == {"pin": True, "save": True, "forget": False, "remember": True}


@pytest.mark.parametrize("request_", [{"action": "notes_save", "expect": "0123456789abcdef", "text": "x"},
                                      {"action": "forget", "task_id": "sr-20261019-090100-0001"}])
def test_the_demo_answers_409_to_the_new_actions(request_):
    import threading
    from router import page
    from tests.test_page_server import _call
    srv = page.make_server(0, demo=True, platform="darwin")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        assert _call(srv, "POST", "/api/run", request_)[0].status == 409
        assert _call(srv, "GET", "/api/notes")[0].status == 200
        assert _call(srv, "GET", "/api/project-notes?name=garden-site")[0].status == 200
    finally:
        srv.shutdown()
        srv.server_close()
