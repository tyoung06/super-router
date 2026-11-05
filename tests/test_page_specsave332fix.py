"""Brief 33.2 fix 2 (the owner's decision 2, item 3 option B), the server's half: a spec save that ended well drops the
kept status at the run's end, so the page's read right after it is fresh (the project's `spec` and its labels); a
refused save keeps it, and nothing is dropped at a run's start. The page's half is tests/js/specsave332fix.test.js.
Every value here is fake."""
from router import page


class Reader:
    def __init__(self):
        self.dropped = 0

    def forget_status(self):
        self.dropped += 1


def test_a_spec_save_that_ended_well_drops_the_kept_status():
    reader = Reader()
    page._after_run(reader, {"request": {"action": "project_spec_save", "name": "garden"}}, 0)
    assert reader.dropped == 1


def test_a_refused_spec_save_keeps_it():
    reader = Reader()
    page._after_run(reader, {"request": {"action": "project_spec_save", "name": "garden"}}, 2)
    assert reader.dropped == 0
