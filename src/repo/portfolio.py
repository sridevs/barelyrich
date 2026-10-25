
from datetime import date
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from sqlite3 import Connection, Row
from typing import Literal

from src.log_messages import error as error_messages
from src import config
from src.repo.db import database_session
from src.repo.queries import load_query
from src.models.portfolio.account_value import AccountValue
from src.models.portfolio.balance_snapshot import BalanceSnapshot
from src.models.portfolio.exchange_rate_observation import ExchangeRateObservation
from src.models.portfolio.exchange_rates import ExchangeRates
from src.models.portfolio.institution import Institution
from src.models.portfolio.portfolio import Portfolio
from src.models.portfolio.validation import account_number, account_product_type, institution_name, observation_date
from src.models.entry.statement_review import StatementReview


class PortfolioStore:
    """SQLite adapter; imports remain atomic and observations retain their dates."""

    def __init__(self, path: Path):
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def save(self, snapshots: list[BalanceSnapshot]) -> int:
        with database_session(self._path) as conn:
            if not snapshots:
                raise ValueError(error_messages.NO_ACCOUNT_BALANCES_WERE_PROVIDED)
            operation = _BalanceImport(conn)
            return sum(operation.save(item) for item in snapshots)

    def save_statement(
        self, review: StatementReview, alias: str | dict[str, str], institution: str,
    ) -> int:
        return self.save(review.snapshots(alias, institution))

    def institutions(self) -> tuple[Institution, ...]:
        with database_session(self._path) as conn:
            rows = conn.execute(load_query("select_tracked_institutions")).fetchall()
        return tuple(
            Institution(row["key"], row["name"], row["country_code"], row["account_type"])
            for row in rows
        )

    def save_rate(self, currency: str, rate: str, as_of: date) -> None:
        self._save_rates((ExchangeRateObservation.parse(currency, rate, as_of),), "manual")

    def portfolio(self, as_of: date, base_currency: str | None = None) -> Portfolio:
        if base_currency is None:
            base_currency = config.DEFAULT_DISPLAY_CURRENCY
        if base_currency not in config.DISPLAY_CURRENCIES:
            raise ValueError(
                error_messages.DISPLAY_CURRENCY_REQUIRED.format(currencies=" or ".join(config.DISPLAY_CURRENCIES))
            )
        observation_date(as_of.isoformat())
        with database_session(self._path) as conn:
            balances = self._latest_balances(conn, as_of)
            rates = self._exchange_rates(conn, as_of)
        values = tuple(self._account_value(row, rates, base_currency) for row in balances)
        return Portfolio(values, base_currency, as_of)

    def save_fetched_rates(self, observations: tuple[ExchangeRateObservation, ...]) -> None:
        self._save_rates(observations, "frankfurter")

    def historical_fx_currencies(self, as_of: date) -> set[str]:
        with database_session(self._path) as conn:
            rows = conn.execute(
                load_query("select_historical_fx_currencies"), (as_of.isoformat(),),
            ).fetchall()
        return {row["currency"] for row in rows}

    def save_historical_rates(
        self, observations: tuple[ExchangeRateObservation, ...], requested_date: date,
    ) -> None:
        observation_date(requested_date.isoformat())
        if any(item.as_of > requested_date for item in observations):
            raise ValueError(error_messages.FUTURE_HISTORICAL_FX_DATE)
        with database_session(self._path) as conn:
            conn.executemany(load_query("upsert_exchange_rate"), [
                (item.currency, item.as_of.isoformat(), str(item.rate), "frankfurter")
                for item in observations
            ])
            conn.executemany(load_query("upsert_historical_fx_request"), [
                (item.currency, requested_date.isoformat(), item.as_of.isoformat())
                for item in observations
            ])

    def _save_rates(
        self,
        observations: tuple[ExchangeRateObservation, ...],
        source: Literal["manual", "frankfurter"],
    ) -> None:
        statement = load_query("upsert_exchange_rate")
        with database_session(self._path) as conn:
            conn.executemany(
                statement,
                [
                    (item.currency, item.as_of.isoformat(), str(item.rate), source)
                    for item in observations
                ],
            )

    @staticmethod
    def _latest_balances(conn: Connection, as_of: date) -> list[Row]:
        return conn.execute(
            load_query("select_latest_account_balances"),
            (as_of.isoformat(),),
        ).fetchall()

    @staticmethod
    def _exchange_rates(conn: Connection, as_of: date) -> ExchangeRates:
        rows = conn.execute(
            load_query("select_latest_inr_exchange_rates"),
            (as_of.isoformat(),),
        ).fetchall()
        return ExchangeRates({
            row["base_currency"]: (Decimal(row["rate"]), date.fromisoformat(row["rate_date"]))
            for row in rows
        }, as_of)

    @staticmethod
    def _account_value(row: Row, rates: ExchangeRates, base: str) -> AccountValue:
        rate, rate_date = rates.conversion(row["currency"], base)
        return AccountValue(
            row["name"], row["institution"], row["currency"], Decimal(row["balance"]),
            "liability" if row["is_liability"] else "asset",
            date.fromisoformat(row["as_of"]), row["source"], row["recorded_at"], rate, rate_date,
            row["institution_name"], row["institution_country"], row["institution_type"],
            row["account_number"],
            row["product_type"],
        )

    def balance_history(self, as_of: date) -> list[dict[str, str]]:
        observation_date(as_of.isoformat())
        with database_session(self._path) as conn:
            rows = conn.execute(
                load_query("select_balance_history"),
                (as_of.isoformat(),),
            ).fetchall()
        return [dict(row) for row in rows]

    def rate_on(self, currency: str, as_of: date) -> Decimal:
        with database_session(self._path) as conn:
            row = conn.execute(
                load_query("select_manual_inr_exchange_rate_on_date"), (currency, as_of.isoformat()),
            ).fetchone()
        if row is None:
            raise ValueError(error_messages.DATED_INR_RATE_MISSING.format(currency=currency, as_of=as_of))
        return Decimal(row["rate"])


class _BalanceImport:
    """Track duplicate identities and replaced currency sets within one transaction."""

    def __init__(self, conn: Connection):
        self._conn = conn
        self._seen: set[tuple[str, str, date] | tuple[str, str, str, date]] = set()
        self._replaced_statements: set[tuple[str, str, str]] = set()
        self._statement = load_query("upsert_account_balance")

    def save(self, item: BalanceSnapshot) -> int:
        institution = self._resolve_institution(item.institution)
        item = replace(item, institution=institution.key)
        self._replace_statement_pockets(item)
        if item.identity in self._seen:
            raise ValueError(
                error_messages.DUPLICATE_IMPORT_ACCOUNT_DATE
            )
        self._seen.add(item.identity)
        account_id = self._account_id(item, institution)
        return self._conn.execute(
            self._statement, (account_id, item.as_of.isoformat(), str(item.balance), item.source),
        ).rowcount

    def _replace_statement_pockets(self, item: BalanceSnapshot) -> None:
        if item.source != "statement" or item.account_number is None:
            return
        identity = (item.as_of.isoformat(), item.institution, account_number(item.account_number))
        if identity not in self._replaced_statements:
            self._conn.execute(load_query("delete_statement_pockets_on_date"), identity)
            self._replaced_statements.add(identity)

    def _account_id(self, item: BalanceSnapshot, institution: Institution) -> int:
        number = None if item.account_number is None else account_number(item.account_number)
        existing = self._find_account(item, number)
        if existing:
            item.ensure_account_compatible(existing["currency"], bool(existing["is_liability"]))
            account_id = existing["id"]
            if number:
                self._conn.execute(load_query("update_account_alias"), (item.account, account_id))
        else:
            account_id = self._insert_account(item, institution, number)
        if number:
            self._conn.execute(load_query("update_account_product_type"), (
                account_product_type(item.product_type), item.institution, number,
            ))
        return account_id

    def _find_account(self, item: BalanceSnapshot, number: str | None) -> Row | None:
        return self._conn.execute(
            load_query("select_account_identity" if number is None else "select_numbered_account"),
            (item.account, item.institution) if number is None else
            (item.institution, number, item.currency),
        ).fetchone()

    def _insert_account(
        self, item: BalanceSnapshot, institution: Institution, number: str | None,
    ) -> int:
        cursor = self._conn.execute(
            load_query("insert_account_returning_id"),
            (item.account, item.institution, institution.country,
             institution.account_type, item.currency, int(item.is_liability), number,
             account_product_type(item.product_type)),
        )
        return cursor.fetchone()["id"]

    def _resolve_institution(self, name: str) -> Institution:
        normalized = institution_name(name, max_length=300).casefold()
        parameters = (normalized, normalized, normalized)
        existing = self._conn.execute(load_query("select_institution"), parameters).fetchone()
        if existing is None:
            self._insert_institution(Institution.from_name(name))
            existing = self._conn.execute(load_query("select_institution"), parameters).fetchone()
        if existing is None:
            raise ValueError(error_messages.INSTITUTION_IDENTITY_CONFLICTS_WITH_AN_EXISTING_RECORD)
        return Institution(
            existing["key"], existing["name"], existing["country_code"], existing["account_type"],
        )

    def _insert_institution(self, candidate: Institution) -> None:
        self._conn.execute(
            load_query("insert_institution"),
            (candidate.key, candidate.name, candidate.normalized_name,
             candidate.country, candidate.account_type),
        )
