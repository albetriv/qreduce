"""S&P500 price data loader with validation and preprocessing.

This module provides:
- CSV loading with schema validation
- Date parsing (DD/MM/YYYY format)
- Duplicate and missing value detection
- Aligned time series extraction
- Return calculation (simple or logarithmic)

The dataset format matches the verified S&P500.csv structure:
- Separator: semicolon (;)
- Encoding: UTF-8 (with optional BOM)
- Columns: Societa, Ticker Yahoo, Settore, Data, Open, High, Low, Close,
           Volume, Adjusted Close, Currency
- Date format: DD/MM/YYYY
"""

import csv
import hashlib
import io
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from types import MappingProxyType
from typing import Literal

import numpy as np

# Type aliases
ReturnType = Literal["simple", "log"]


class DatasetValidationError(ValueError):
    """Raised when the dataset fails validation checks."""


@dataclass(frozen=True, slots=True)
class AssetData:
    """Validated price and metadata for a single asset."""

    ticker: str
    company_name: str
    sector: str
    currency: str
    dates: tuple[date, ...]
    adjusted_close: tuple[float, ...]

    def __post_init__(self) -> None:
        if not self.ticker.strip():
            raise ValueError("Ticker cannot be blank.")
        if len(self.dates) != len(self.adjusted_close):
            raise ValueError("Dates and prices must have equal length.")
        if len(self.dates) == 0:
            raise ValueError("Asset must have at least one observation.")
        for price in self.adjusted_close:
            if not math.isfinite(price) or price <= 0:
                raise ValueError(f"Adjusted close must be finite and positive: {price}")


@dataclass(frozen=True, slots=True)
class SP500Dataset:
    """Validated S&P500 price dataset ready for return calculation.

    This is an immutable container of aligned price series. All assets share
    the same date sequence. Sector and currency metadata are preserved.
    """

    source_path: str
    source_sha256: str
    tickers: tuple[str, ...]
    dates: tuple[date, ...]
    sectors: Mapping[str, str]
    currencies: Mapping[str, str]
    company_names: Mapping[str, str]
    adjusted_close: Mapping[str, tuple[float, ...]]
    exclusion_reasons: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Copy before wrapping so callers cannot mutate provenance indirectly.
        object.__setattr__(
            self, "exclusion_reasons", MappingProxyType(dict(self.exclusion_reasons))
        )

    @property
    def ticker_count(self) -> int:
        """Number of unique tickers in the dataset."""
        return len(self.tickers)

    @property
    def date_count(self) -> int:
        """Number of trading dates in the aligned series."""
        return len(self.dates)

    @property
    def sector_set(self) -> frozenset[str]:
        """Set of unique sectors in the dataset."""
        return frozenset(self.sectors.values())

    def tickers_in_sector(self, sector: str) -> tuple[str, ...]:
        """Return tickers belonging to the specified sector."""
        return tuple(t for t in self.tickers if self.sectors[t] == sector)

    def to_dict(self) -> dict[str, object]:
        """Serialize dataset metadata for artifact storage."""
        return {
            "source_path": self.source_path,
            "source_sha256": self.source_sha256,
            "ticker_count": self.ticker_count,
            "date_count": self.date_count,
            "sectors": dict(self.sectors),
            "exclusion_reasons": dict(self.exclusion_reasons),
            "date_range": {
                "start": self.dates[0].isoformat() if self.dates else None,
                "end": self.dates[-1].isoformat() if self.dates else None,
            },
        }


@dataclass
class _ParsedRow:
    """Internal representation of a parsed CSV row."""

    company_name: str
    ticker: str
    sector: str
    trade_date: date
    adjusted_close: float
    currency: str


def load_sp500_prices(
    csv_path: str | Path,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    required_sectors: Sequence[str] | None = None,
    required_currency: str = "USD",
) -> SP500Dataset:
    """Load and validate S&P500 price data from a CSV file.

    Args:
        csv_path: Path to the CSV file.
        start_date: Optional start date filter (inclusive).
        end_date: Optional end date filter (inclusive).
        required_sectors: Optional list of sectors that must be present.
        required_currency: Required currency for all prices. Default: USD.

    Returns:
        Validated SP500Dataset with aligned price series. Tickers missing any
        selected date are excluded and recorded in immutable exclusion_reasons.

    Raises:
        FileNotFoundError: If the CSV file does not exist.
        DatasetValidationError: If validation fails.
    """
    path = Path(csv_path)
    if not path.is_file():
        raise FileNotFoundError(f"Dataset file not found: {path}")

    # Read file and compute hash
    content_bytes = path.read_bytes()
    sha256_hash = hashlib.sha256(content_bytes).hexdigest()

    # Handle BOM if present
    content = content_bytes.decode("utf-8-sig")
    reader = csv.reader(io.StringIO(content, newline=""), delimiter=";", strict=True)
    records: list[tuple[int, list[str]]] = []
    try:
        for parts in reader:
            records.append((reader.line_num, parts))
    except csv.Error as e:
        raise DatasetValidationError(f"Line {reader.line_num}: Invalid CSV: {e}") from e

    if len(records) < 2:
        raise DatasetValidationError("CSV file must have a header and at least one data row.")

    # Validate header
    header = records[0][1]
    expected_columns = [
        "Societa", "Ticker Yahoo", "Settore", "Data", "Open", "High",
        "Low", "Close", "Volume", "Adjusted Close", "Currency",
    ]
    if header != expected_columns:
        raise DatasetValidationError(
            f"Invalid CSV header. Expected: {expected_columns}, got: {header}"
        )

    # Parse rows
    rows: list[_ParsedRow] = []
    seen_ticker_dates: set[tuple[str, date]] = set()

    for line_num, parts in records[1:]:
        if not parts or (len(parts) == 1 and not parts[0].strip()):
            continue

        if len(parts) != 11:
            raise DatasetValidationError(
                f"Line {line_num}: Expected 11 columns, got {len(parts)}"
            )

        company_name, ticker, sector, date_str = parts[0], parts[1], parts[2], parts[3]
        adj_close_str, currency = parts[9], parts[10]

        # Validate non-blank identifiers
        if not ticker.strip():
            raise DatasetValidationError(f"Line {line_num}: Blank ticker")
        if not sector.strip():
            raise DatasetValidationError(f"Line {line_num}: Blank sector")
        if not currency.strip():
            raise DatasetValidationError(f"Line {line_num}: Blank currency")

        # Parse date (DD/MM/YYYY)
        try:
            day, month, year = date_str.split("/")
            trade_date = date(int(year), int(month), int(day))
        except (ValueError, AttributeError) as e:
            raise DatasetValidationError(
                f"Line {line_num}: Invalid date format '{date_str}'. Expected DD/MM/YYYY."
            ) from e

        # Parse adjusted close
        try:
            adjusted_close = float(adj_close_str)
        except ValueError as e:
            raise DatasetValidationError(
                f"Line {line_num}: Invalid adjusted close '{adj_close_str}'"
            ) from e

        if not math.isfinite(adjusted_close) or adjusted_close <= 0:
            raise DatasetValidationError(
                f"Line {line_num}: Adjusted close must be finite and positive: {adjusted_close}"
            )

        # Check currency
        if currency != required_currency:
            raise DatasetValidationError(
                f"Line {line_num}: Expected currency {required_currency}, got {currency}"
            )

        # Check for duplicate (ticker, date)
        key = (ticker, trade_date)
        if key in seen_ticker_dates:
            raise DatasetValidationError(
                f"Line {line_num}: Duplicate ticker-date pair ({ticker}, {trade_date})"
            )
        seen_ticker_dates.add(key)

        rows.append(_ParsedRow(
            company_name=company_name,
            ticker=ticker,
            sector=sector,
            trade_date=trade_date,
            adjusted_close=adjusted_close,
            currency=currency,
        ))

    if not rows:
        raise DatasetValidationError("No valid data rows found.")

    # Group by ticker
    ticker_data: dict[str, list[_ParsedRow]] = {}
    for row in rows:
        ticker_data.setdefault(row.ticker, []).append(row)

    # Sort each ticker's data by date
    for ticker_rows in ticker_data.values():
        ticker_rows.sort(key=lambda r: r.trade_date)

    # Get all unique dates and tickers
    all_dates = sorted({row.trade_date for row in rows})
    all_tickers = sorted(ticker_data.keys())

    # Apply date filters
    if start_date is not None:
        all_dates = [d for d in all_dates if d >= start_date]
    if end_date is not None:
        all_dates = [d for d in all_dates if d <= end_date]

    if not all_dates:
        raise DatasetValidationError("No dates remain after applying date filters.")

    date_set = set(all_dates)

    # Validate alignment: each ticker must have data for all dates in range
    aligned_tickers: list[str] = []
    sectors: dict[str, str] = {}
    currencies: dict[str, str] = {}
    company_names: dict[str, str] = {}
    adjusted_close: dict[str, tuple[float, ...]] = {}
    exclusion_reasons: dict[str, str] = {}

    for ticker in all_tickers:
        ticker_rows = ticker_data[ticker]

        # Filter to requested date range
        filtered_rows = [r for r in ticker_rows if r.trade_date in date_set]

        if len({r.sector for r in filtered_rows}) > 1:
            raise DatasetValidationError(
                f"Inconsistent sector metadata for ticker {ticker} in selected date window."
            )

        if len(filtered_rows) != len(all_dates):
            # Ticker doesn't have complete data for the date range
            exclusion_reasons[ticker] = "incomplete_price_history"
            continue

        # Verify dates match exactly
        filtered_dates = [r.trade_date for r in filtered_rows]
        if filtered_dates != all_dates:
            exclusion_reasons[ticker] = "incomplete_price_history"
            continue

        # Extract metadata (consistent across rows for same ticker)
        first_row = filtered_rows[0]
        aligned_tickers.append(ticker)
        sectors[ticker] = first_row.sector
        currencies[ticker] = first_row.currency
        company_names[ticker] = first_row.company_name
        adjusted_close[ticker] = tuple(r.adjusted_close for r in filtered_rows)

    if not aligned_tickers:
        raise DatasetValidationError(
            "No tickers have complete data for the requested date range."
        )

    # Validate required sectors
    if required_sectors:
        available_sectors = set(sectors.values())
        missing = set(required_sectors) - available_sectors
        if missing:
            raise DatasetValidationError(
                f"Required sectors missing from aligned tickers: {sorted(missing)}"
            )

    return SP500Dataset(
        source_path=str(path.resolve()),
        source_sha256=sha256_hash,
        tickers=tuple(aligned_tickers),
        dates=tuple(all_dates),
        sectors=MappingProxyType(sectors),
        currencies=MappingProxyType(currencies),
        company_names=MappingProxyType(company_names),
        adjusted_close=MappingProxyType({
            k: v for k, v in adjusted_close.items()
        }),
        exclusion_reasons=exclusion_reasons,
    )


@dataclass(frozen=True, slots=True)
class ReturnStatistics:
    """Computed return statistics for portfolio optimization.

    All values are annualized using the provided annualization factor.
    Tickers with non-positive mean returns are excluded.
    """

    source_dataset: SP500Dataset
    return_convention: ReturnType
    annualization_factor: int
    tickers: tuple[str, ...]
    mean_returns: Mapping[str, float]
    covariance: tuple[tuple[float, ...], ...]
    excluded_tickers: tuple[str, ...]
    exclusion_reasons: Mapping[str, str]

    @property
    def ticker_count(self) -> int:
        """Number of tickers with positive mean returns."""
        return len(self.tickers)

    def to_dict(self) -> dict[str, object]:
        """Serialize statistics metadata for artifact storage."""
        return {
            "return_convention": self.return_convention,
            "annualization_factor": self.annualization_factor,
            "ticker_count": self.ticker_count,
            "excluded_count": len(self.excluded_tickers),
            "excluded_tickers": list(self.excluded_tickers),
            "exclusion_reasons": dict(self.exclusion_reasons),
        }


def compute_return_statistics(
    dataset: SP500Dataset,
    *,
    return_convention: ReturnType = "log",
    annualization_factor: int = 252,
    positive_mean_tolerance: float = 1e-12,
) -> ReturnStatistics:
    """Compute annualized return statistics from price data.

    Args:
        dataset: Validated price dataset with at least 3 dates (2 returns).
        return_convention: 'simple' for arithmetic returns, 'log' for logarithmic.
        annualization_factor: Trading days per year. Default: 252.
        positive_mean_tolerance: Minimum mean return to consider positive.

    Returns:
        ReturnStatistics with annualized mean and covariance.

    Raises:
        ValueError: If parameters are invalid.
        DatasetValidationError: If covariance computation fails.
    """
    if annualization_factor < 1:
        raise ValueError("annualization_factor must be at least 1.")
    if positive_mean_tolerance < 0:
        raise ValueError("positive_mean_tolerance must be non-negative.")
    if return_convention not in ("simple", "log"):
        raise ValueError(f"Invalid return_convention: {return_convention}")

    tickers = list(dataset.tickers)
    n_tickers = len(tickers)
    n_dates = dataset.date_count

    if n_dates < 3:
        raise DatasetValidationError("Need at least 3 dates to compute sample covariance.")

    # Build price matrix (n_dates x n_tickers)
    prices = np.zeros((n_dates, n_tickers))
    for i, ticker in enumerate(tickers):
        prices[:, i] = dataset.adjusted_close[ticker]

    # Compute returns
    if return_convention == "simple":
        returns = (prices[1:] - prices[:-1]) / prices[:-1]
    else:  # log
        returns = np.log(prices[1:] / prices[:-1])

    returns.shape[0]

    # Compute sample statistics
    mean_daily = np.mean(returns, axis=0)
    cov_daily = np.cov(returns, rowvar=False)

    # Ensure cov is 2D even for single ticker
    if cov_daily.ndim == 0:
        cov_daily = cov_daily.reshape((1, 1))

    # Annualize
    mean_annual = mean_daily * annualization_factor
    cov_annual = cov_daily * annualization_factor

    # Filter tickers with positive mean returns
    eligible_tickers: list[str] = []
    eligible_indices: list[int] = []
    excluded_tickers: list[str] = []
    exclusion_reasons: dict[str, str] = {}

    for i, ticker in enumerate(tickers):
        mu = mean_annual[i]
        if mu > positive_mean_tolerance:
            eligible_tickers.append(ticker)
            eligible_indices.append(i)
        else:
            excluded_tickers.append(ticker)
            exclusion_reasons[ticker] = f"non_positive_mean_return:{mu:.6g}"

    if not eligible_tickers:
        raise DatasetValidationError(
            "No tickers have positive mean returns after annualization."
        )

    # Extract submatrices for eligible tickers
    mean_returns = {
        ticker: float(mean_annual[i])
        for ticker, i in zip(eligible_tickers, eligible_indices)
    }
    cov_eligible = cov_annual[np.ix_(eligible_indices, eligible_indices)]

    # Validate covariance properties
    # Symmetry check
    if not np.allclose(cov_eligible, cov_eligible.T, rtol=1e-10, atol=1e-12):
        raise DatasetValidationError("Computed covariance is not symmetric.")

    # Positive diagonal check
    diag = np.diag(cov_eligible)
    if np.any(diag <= 0):
        raise DatasetValidationError("Covariance diagonal must be positive.")

    # Check positive semi-definiteness via Cholesky
    try:
        np.linalg.cholesky(cov_eligible + 1e-10 * np.eye(len(eligible_tickers)))
    except np.linalg.LinAlgError as e:
        raise DatasetValidationError(
            "Covariance matrix is not positive semi-definite."
        ) from e

    # Convert to nested tuples
    covariance = tuple(tuple(float(v) for v in row) for row in cov_eligible)

    return ReturnStatistics(
        source_dataset=dataset,
        return_convention=return_convention,
        annualization_factor=annualization_factor,
        tickers=tuple(eligible_tickers),
        mean_returns=MappingProxyType(mean_returns),
        covariance=covariance,
        excluded_tickers=tuple(excluded_tickers),
        exclusion_reasons=MappingProxyType(exclusion_reasons),
    )
