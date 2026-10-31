from src.log_messages import error as error_messages
from src.models.portfolio.exchange_rate_observation import ExchangeRateObservation
from src.models.portfolio.portfolio import Portfolio
from src.providers.exchange_rates import (
    ExchangeRateFetchError,
    FrankfurterExchangeRateProvider,
)
from src.repo.portfolio import PortfolioStore


class ExchangeRateRefresh:
    def __init__(self, provider: FrankfurterExchangeRateProvider, writer: PortfolioStore):
        self._provider = provider
        self._writer = writer

    def refresh(self, portfolio: Portfolio) -> tuple[ExchangeRateObservation, ...]:
        currencies = portfolio.required_rate_currencies()
        if not currencies:
            return ()
        observations = self._provider.fetch(currencies, portfolio.as_of)
        self._writer.save_fetched_rates(observations)
        return observations

    def refresh_historical(self, portfolio: Portfolio) -> tuple[ExchangeRateObservation, ...]:
        currencies = portfolio.required_rate_currencies()
        if not currencies:
            return ()
        missing = currencies - self._writer.historical_fx_currencies(portfolio.as_of)
        if not missing:
            return ()
        observations = self._provider.fetch(missing, portfolio.as_of)
        if (
            {item.currency for item in observations} != missing
            or len(observations) != len(missing)
            or any(item.as_of > portfolio.as_of for item in observations)
        ):
            raise ExchangeRateFetchError(error_messages.HISTORICAL_FX_REFRESH_RETURNED_INCOMPLETE_OR_FUTURE_RATES)
        self._writer.save_historical_rates(observations, portfolio.as_of)
        return observations
