from tests.statement_fixtures import statement_extraction
from src.ui.statement_batch import StatementBatchSession


def test_batch_navigation_is_bounded_and_each_review_is_independent():
    state = {}
    batch = StatementBatchSession(state)
    files = [("first.pdf", b"first"), ("second.pdf", b"second")]
    batch.begin(files, "asset")
    extraction = statement_extraction()
    for index, (_, content) in enumerate(files):
        batch.review_session(index).start(content, "asset", extraction)
    assert batch.matches(files, "asset")
    assert not batch.matches(files, "liability")
    assert not batch.matches(list(reversed(files)), "asset")
    assert not batch.matches([("first.pdf", b"changed"), files[1]], "asset")
    first = batch.review_session(0).preview
    second = batch.review_session(1).preview
    assert first is not None and second is not None
    assert batch.review_session(0).alias_key(first) != batch.review_session(1).alias_key(second)
    batch.move(-1)
    assert batch.index == 0
    batch.move(1)
    batch.mark_saved()
    assert not batch.items[0].saved
    assert batch.items[1].saved
    batch.move(1)
    assert batch.index == 1
    batch.move(-1)
    batch.fail(0, "Unable to parse PDF.")
    assert batch.items[0].error == "Unable to parse PDF."
    assert batch.review_session(1).preview == second
    batch.clear()
    assert not batch.items
    assert batch.index == 0
    assert batch.review_session(0).preview is None


def test_identical_uploads_have_independent_review_state():
    state = {}
    real = StatementBatchSession(state)
    files = [("same.pdf", b"same"), ("same.pdf", b"same")]
    real.begin(files, "asset")
    assert real.review_session(0).widget_key("confirmation") != real.review_session(1).widget_key("confirmation")
    real.mark_saved()
    real.clear()
    assert not real.items


def test_pending_snapshots_use_edits_skip_saved_and_failed_and_reset_confirmation():
    state = {}
    batch = StatementBatchSession(state)
    files = [("first.pdf", b"first"), ("second.pdf", b"second"), ("bad.pdf", b"bad")]
    batch.begin(files, "asset")
    extraction = statement_extraction()
    for index in (0, 1):
        batch.review_session(index).start(files[index][1], "asset", extraction)
    batch.fail(2, "Invalid PDF")
    original = batch.confirmation_key(batch.pending_snapshots())
    review = batch.review_session(0).preview
    assert review is not None
    state[batch.review_session(0).alias_key(review)] = "Edited account"
    state[batch.institution_key(0, review)] = "Edited Bank"
    snapshots = batch.pending_snapshots()
    assert snapshots[0].account == "Edited account SGD"
    assert snapshots[0].institution == "Edited Bank"
    assert batch.confirmation_key(snapshots) != original
    alias_confirmation = batch.confirmation_key(snapshots)
    state[batch.review_session(0).account_type_key(review, "TEST1234")] = "Fixed deposit"
    snapshots = batch.pending_snapshots()
    assert snapshots[0].product_type == "Fixed deposit"
    assert snapshots[1].product_type == ""
    assert batch.confirmation_key(snapshots) != alias_confirmation
    batch.mark_saved()
    assert batch.pending_indices() == (1,)
    assert len(batch.pending_snapshots()) == 1
    batch.mark_pending_saved()
    assert not batch.pending_snapshots()
    state[batch.confirmation_key([])] = True
    batch.begin(files, "asset")
    assert not any("statement_batch_confirmation_" in key for key in state)
