"""Shared fixtures: a fresh, initialised portfolio database per test."""

import pytest

from src import config
from src.repo.db import initialise
from src.repo.portfolio import PortfolioStore


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / config.PORTFOLIO_DATABASE
    initialise(path)
    return path


@pytest.fixture
def store(db_path):
    return PortfolioStore(db_path)
