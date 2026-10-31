from datetime import date
from decimal import Decimal

import pytest

from src.agents.extraction_merger import ExtractionMerger
from src.agents.response import StatementParsingError
from src.models.dto.statement_page import StatementPage
from src.models.statements.statement_account import StatementAccount
from src.models.statements.statement_balance import StatementBalance
from src.models.statements.statement_document import StatementDocument
from src.models.statements.statement_extraction import StatementExtraction
from src.models.statements.statement_institution import StatementInstitution

CHUNK = StatementDocument((StatementPage(4, "text"), StatementPage(6, "text")))


def extraction(account_type="Savings", institution="Example Bank", day=1):
    balance = StatementBalance(Decimal("100"), "SGD", date(2025, 1, day), deposit=Decimal("1"))
    return StatementExtraction(
        (StatementAccount("1234", (balance,), account_type),),
        StatementInstitution(institution) if institution else None,
    )


def test_chunks_append_rows_per_account_and_drop_disagreeing_product_type():
    merger = ExtractionMerger()
    merger.add(extraction(), CHUNK)
    merger.add(extraction("Current", institution=None, day=2), CHUNK)
    (account,) = merger.result().accounts
    assert [row.as_of.day for row in account.balances] == [1, 2]
    assert account.account_type == ""
    assert merger.institution.name == "Example Bank"


def test_conflicting_institutions_name_the_chunk_pages():
    merger = ExtractionMerger()
    merger.add(extraction(), CHUNK)
    with pytest.raises(StatementParsingError, match="4-6"):
        merger.add(extraction(institution="Other Bank"), CHUNK)
