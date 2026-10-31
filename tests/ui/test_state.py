import hashlib
from dataclasses import FrozenInstanceError, make_dataclass, replace
from datetime import date
from decimal import Decimal

import pytest

from src.models.entry.statement_review import StatementReview
from src.models.statements.statement_account import StatementAccount
from src.models.statements.statement_balance import StatementBalance
from src.models.statements.statement_extraction import StatementExtraction
from src.models.statements.statement_institution import StatementInstitution
from src.ui.state import StatementReviewSession
from src.ui.statement_edit import statement_row
from tests.statement_fixtures import statement_extraction


@pytest.fixture
def extraction():
    return statement_extraction()


def test_review_binds_upload_kind_and_validated_extraction(extraction):
    review = StatementReview.create(b"fictional", "asset", extraction)
    assert review.file_digest == hashlib.sha256(b"fictional").hexdigest()
    assert review.institution == "DBS Singapore"
    assert review.suggested_alias == "DBS"
    assert review.matches(b"fictional", "asset")
    assert not review.matches(b"changed", "asset")
    assert not review.matches(b"fictional", "liability")
    with pytest.raises(FrozenInstanceError):
        setattr(review, "kind", "liability")


def test_review_owns_alias_normalization_and_currency_pocket_snapshots(extraction):
    review = StatementReview.create(b"fictional", "asset", extraction)
    snapshots = review.snapshots("  My savings  ")
    assert len(snapshots) == 1
    assert snapshots[0].account == "My savings SGD"
    assert snapshots[0].balance == extraction.balances[0].balance
    assert snapshots[0].as_of == extraction.balances[0].as_of
    assert snapshots[0].source == "statement"
    for alias in ("", " ", "alias" * 30):
        with pytest.raises(ValueError, match="[Aa]ccount name"):
            review.snapshots(alias)


def test_review_confirmation_identity_changes_with_every_reviewed_input(extraction):
    review = StatementReview.create(b"fictional", "asset", extraction)
    confirmation = review.confirmation_key("DBS")
    assert confirmation == review.confirmation_key("  DBS ")
    assert confirmation != review.confirmation_key("Another account")
    assert confirmation != replace(review, kind="liability").confirmation_key("DBS")
    assert confirmation != StatementReview.create(
        b"changed", "asset", extraction,
    ).confirmation_key("DBS")
    identity = extraction.institution
    assert identity
    other_institution = replace(extraction, institution=replace(identity, name="Another Bank"))
    assert confirmation != StatementReview.create(
        b"fictional", "asset", other_institution,
    ).confirmation_key("DBS")
    assert confirmation != review.confirmation_key("DBS", "Another Bank")
    assert confirmation != review.confirmation_key("DBS", "")
    long_name_extraction = replace(extraction, institution=replace(identity, name="X" * 100))
    long_name_review = StatementReview.create(b"fictional", "asset", long_name_extraction)
    assert len(long_name_review.snapshots(long_name_review.suggested_alias)[0].account) == 100


def test_review_rejects_missing_institution_and_invalid_kind_before_preview(extraction):
    with pytest.raises(ValueError, match="could not identify"):
        StatementReview.create(b"fictional", "asset", replace(extraction, institution=None))
    with pytest.raises(ValueError, match="Kind"):
        StatementReview.create(b"fictional", "unknown", extraction)
    with pytest.raises(ValueError, match="uploaded file"):
        StatementReview("not-a-digest", "asset", extraction)


def test_session_owns_preview_alias_and_revision_without_touching_other_state(extraction):
    state = {"unrelated": "preserve"}
    real = StatementReviewSession(state)
    assert real.preview is None
    assert real.upload_revision == 0
    real.start(b"real", "asset", extraction)
    real_preview = real.preview
    assert real_preview
    assert state[real.alias_key(real_preview)] == "DBS"
    assert real.preview == real_preview
    assert real_preview.matches(b"real", "asset")
    assert real.upload_revision == 0
    real.clear()
    assert real.preview is None
    assert state["unrelated"] == "preserve"


def test_new_upload_revision_has_a_fresh_alias_widget(extraction):
    state = {}
    session = StatementReviewSession(state)
    session.start(b"fictional", "asset", extraction)
    previous_preview = session.preview
    assert previous_preview
    previous_key = session.alias_key(previous_preview)
    state[previous_key] = "Edited alias"
    session.finish()
    session.start(b"fictional", "asset", extraction)
    current_preview = session.preview
    assert current_preview
    assert session.alias_key(current_preview) != previous_key
    assert state[session.alias_key(current_preview)] == "DBS"
    session.finish()
    assert session.upload_revision == 2


def test_clearing_review_removes_only_review_confirmation(extraction):
    state = {
        "statement_confirmation_old": True,
        "unrelated_setting": "preserve",
    }
    session = StatementReviewSession(state)
    session.start(b"fictional", "asset", extraction)
    session.clear()

    assert session.preview is None
    assert "statement_confirmation_old" not in state
    assert state["unrelated_setting"] == "preserve"


def test_invalid_session_start_cannot_publish_an_unusable_preview(extraction):
    state = {}
    session = StatementReviewSession(state)
    with pytest.raises(ValueError):
        session.start(b"fictional", "unknown", extraction)
    assert session.preview is None
    assert not state


def test_pending_aliases_use_review_edits_and_exclude_saved_accounts(extraction):
    state = {}
    session = StatementReviewSession(state, lambda name: "isolated_" + name)
    session.start(b"fictional", "asset", extraction)
    review = session.preview
    assert review
    number = next(iter(review.suggested_aliases))
    assert session.pending_aliases(review) == review.suggested_aliases
    state[session.account_alias_key(review, number)] = "Edited alias"
    assert session.pending_aliases(review) == {number: "Edited alias"}
    session.mark_account_saved(number)
    assert session.pending_aliases(review) == {}


@pytest.mark.parametrize("finish", ["cancel_edit", "clear", "finish"])
def test_editor_rows_and_decisions_are_cleared_without_touching_other_batches(extraction, finish):
    state = {}
    first = StatementReviewSession(state, lambda name: "first_" + name)
    second = StatementReviewSession(state, lambda name: "second_" + name)
    account = extraction.accounts[0]
    for session in (first, second):
        session.start(b"review", "asset", extraction)
        session.begin_edit(account.number)
        state[session.editor_key(account.number) + "_data"] = [statement_row(row) for row in account.balances]
        state[session.editor_key(account.number) + "_error"] = "Invalid draft"
    first_key = first.editor_key(account.number) + "_data"
    second_key = second.editor_key(account.number) + "_data"
    getattr(first, finish)()
    assert first_key not in state
    assert first_key.removesuffix("_data") + "_error" not in state
    assert second_key in state
    assert second_key.removesuffix("_data") + "_error" in state
    first.begin_edit(account.number)
    assert first.editor_key(account.number) + "_data" not in state


def test_typed_alias_suggestions_follow_type_changes_but_preserve_custom_aliases(extraction):
    extraction = replace(extraction, accounts=(
        replace(extraction.accounts[0], account_type="Savings"),
        replace(extraction.accounts[0], number="5678", account_type="Fixed deposit"),
    ))
    state = {}
    session = StatementReviewSession(state)
    session.start(b"typed", "asset", extraction)
    review = session.preview
    assert review
    assert review.suggested_aliases == {
        "TEST1234": "DBS Savings 1", "5678": "DBS Fixed deposit 2",
    }
    alias_key = session.account_alias_key(review, "TEST1234")
    session.update_suggested_alias(review, "TEST1234", "Current")
    assert state[alias_key] == "DBS Current 1"
    state[alias_key] = "My custom account"
    session.update_suggested_alias(review, "TEST1234", "Savings")
    assert state[alias_key] == "My custom account"
    assert state[session.account_alias_key(review, "5678")] == "DBS Fixed deposit 2"
    long_alias = review.suggest_account_alias("5678", "x" * 100)
    assert len(long_alias) <= 96
    assert long_alias.endswith(" 2")


def _balance(balance, withdrawal=None, deposit=None):
    return StatementBalance(
        Decimal(balance), "SGD", date(2022, 4, 2),
        None if withdrawal is None else Decimal(withdrawal),
        None if deposit is None else Decimal(deposit), "Printed description",
    )


def test_session_restores_stale_review_without_losing_accounts_or_draft():
    account = StatementAccount("1234", (_balance("100", deposit="1"), _balance("120", "20")), "Savings")
    original = StatementReview.create(
        b"statement", "asset", StatementExtraction((account,), StatementInstitution("Example Bank")),
    )
    stale_class = make_dataclass("StatementReview", [], bases=(StatementReview,), frozen=True)
    stale = stale_class(
        original.file_digest, original.kind,
        replace(original.extraction, accounts=(
            *original.extraction.accounts, StatementAccount("5678", (_balance("50"),), "Savings"),
        )),
    )
    draft = {"edited_rows": {0: {"Balance": "125"}}}
    state = {"statement_preview": stale, "statement_editor_1234_0": draft}
    session = StatementReviewSession(state)
    session.begin_edit("1234")
    restored = session.preview
    assert type(restored) is StatementReview
    assert (restored.file_digest, restored.kind) == (original.file_digest, original.kind)
    assert restored.extraction == stale.extraction
    assert state["statement_editor_1234_0"] is draft
    assert session.editing_account == "1234"
    session.apply_balances("1234", (_balance("125", deposit="25"),))
    assert session.preview.extraction.accounts[1] == stale.extraction.accounts[1]
    assert session.preview.extraction.balances[0].balance == Decimal("125")
