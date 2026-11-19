"""Unit tests for datasets.py - CSV loader and preprocessing."""

import math
from dataclasses import replace
from datetime import date
from pathlib import Path

import numpy as np
import pytest

from qreduce.experiments.portfolio_sr.datasets import (
    DatasetValidationError,
    ReturnStatistics,
    SP500Dataset,
    compute_return_statistics,
    load_sp500_prices,
)


class TestLoadSP500Prices:
    """Tests for load_sp500_prices function."""

    def test_quoted_company_loads(self, tmp_path: Path) -> None:
        """Quoted delimiters, escaped quotes and newlines remain in company names."""
        csv_file = tmp_path / "quoted.csv"
        csv_file.write_text(
            'Societa;Ticker Yahoo;Settore;Data;Open;High;Low;Close;Volume;Adjusted Close;Currency\n'
            '"Company; ""A""\nHoldings";AAA;Technology;01/01/2020;100;100;100;100;1;100;USD\n',
            encoding="utf-8",
        )

        dataset = load_sp500_prices(csv_file)

        assert dataset.company_names["AAA"] == 'Company; "A"\nHoldings'
        assert dataset.adjusted_close["AAA"] == (100.0,)

    @pytest.mark.parametrize("row", [
        'Company A;AAA;Technology;01/01/2020;100;100;100;100;1;100',
        'Company A;AAA;Technology;01/01/2020;100;100;100;100;1;100;USD;extra',
    ])
    def test_wrong_row_width_rejected(self, tmp_path: Path, row: str) -> None:
        """CSV parsing retains strict row width validation."""
        csv_file = tmp_path / "wrong_width.csv"
        csv_file.write_text(
            "Societa;Ticker Yahoo;Settore;Data;Open;High;Low;Close;Volume;Adjusted Close;Currency\n"
            + row + "\n",
            encoding="utf-8",
        )

        with pytest.raises(DatasetValidationError, match="Line 2: Expected 11 columns"):
            load_sp500_prices(csv_file)

    def test_malformed_csv_rejected(self, tmp_path: Path) -> None:
        """Malformed quoting is reported as dataset validation failure."""
        csv_file = tmp_path / "malformed.csv"
        csv_file.write_text(
            'Societa;Ticker Yahoo;Settore;Data;Open;High;Low;Close;Volume;Adjusted Close;Currency\n'
            '"Unterminated company;AAA;Technology;01/01/2020;100;100;100;100;1;100;USD\n',
            encoding="utf-8",
        )

        with pytest.raises(DatasetValidationError, match="Invalid CSV"):
            load_sp500_prices(csv_file)

    def test_incomplete_ticker_reported(self, tmp_path: Path) -> None:
        """Incomplete histories are excluded, not used to shrink the date union."""
        csv_file = tmp_path / "incomplete.csv"
        csv_file.write_text(
            "Societa;Ticker Yahoo;Settore;Data;Open;High;Low;Close;Volume;Adjusted Close;Currency\n"
            "Company A;AAA;Technology;01/01/2020;100;100;100;100;1;100;USD\n"
            "Company A;AAA;Technology;02/01/2020;110;110;110;110;1;110;USD\n"
            "Company B;BBB;Technology;01/01/2020;100;100;100;100;1;100;USD\n",
            encoding="utf-8",
        )

        dataset = load_sp500_prices(csv_file)

        assert dataset.tickers == ("AAA",)
        assert dataset.dates == (date(2020, 1, 1), date(2020, 1, 2))
        assert dataset.exclusion_reasons == {"BBB": "incomplete_price_history"}
        assert dataset.to_dict()["exclusion_reasons"] == dict(dataset.exclusion_reasons)
        with pytest.raises(TypeError):
            dataset.exclusion_reasons["BBB"] = "changed"
        serialized = dataset.to_dict()
        serialized["exclusion_reasons"]["BBB"] = "changed"
        assert dataset.exclusion_reasons["BBB"] == "incomplete_price_history"
        filtered = load_sp500_prices(csv_file, end_date=date(2020, 1, 1))
        assert filtered.tickers == ("AAA", "BBB")
        assert filtered.exclusion_reasons == {}

    def test_inconsistent_sector_rejected_in_selected_window(self, tmp_path: Path) -> None:
        """Sector changes are rejected only inside the selected date window."""
        csv_file = tmp_path / "sector_change.csv"
        csv_file.write_text(
            "Societa;Ticker Yahoo;Settore;Data;Open;High;Low;Close;Volume;Adjusted Close;Currency\n"
            "Company A;AAA;Technology;01/01/2020;100;100;100;100;1;100;USD\n"
            "Company A;AAA;Health Care;02/01/2020;110;110;110;110;1;110;USD\n",
            encoding="utf-8",
        )

        with pytest.raises(DatasetValidationError, match="Inconsistent sector.*AAA"):
            load_sp500_prices(csv_file)
        dataset = load_sp500_prices(csv_file, start_date=date(2020, 1, 2))
        assert dataset.sectors["AAA"] == "Health Care"

    def test_valid_csv_loads_successfully(self, tmp_path: Path) -> None:
        """A valid CSV file loads without errors."""
        csv_content = (
            "Societa;Ticker Yahoo;Settore;Data;Open;High;Low;Close;Volume;Adjusted Close;Currency\n"
            "Company A;AAA;Technology;01/01/2020;100.0;105.0;99.0;104.0;1000000;104.0;USD\n"
            "Company A;AAA;Technology;02/01/2020;104.0;110.0;103.0;108.0;1100000;108.0;USD\n"
            "Company B;BBB;Health Care;01/01/2020;50.0;52.0;49.0;51.0;500000;51.0;USD\n"
            "Company B;BBB;Health Care;02/01/2020;51.0;54.0;50.0;53.0;550000;53.0;USD\n"
        )
        csv_file = tmp_path / "test.csv"
        csv_file.write_text(csv_content, encoding="utf-8")

        dataset = load_sp500_prices(csv_file)

        assert isinstance(dataset, SP500Dataset)
        assert dataset.ticker_count == 2
        assert dataset.date_count == 2
        assert "AAA" in dataset.tickers
        assert "BBB" in dataset.tickers

    def test_bom_encoding_handled(self, tmp_path: Path) -> None:
        """UTF-8 BOM is handled correctly."""
        csv_content = (
            "Societa;Ticker Yahoo;Settore;Data;Open;High;Low;Close;Volume;Adjusted Close;Currency\n"
            "Company A;AAA;Technology;01/01/2020;100.0;105.0;99.0;104.0;1000000;104.0;USD\n"
        )
        csv_file = tmp_path / "test_bom.csv"
        csv_file.write_bytes(b"\xef\xbb\xbf" + csv_content.encode("utf-8"))

        dataset = load_sp500_prices(csv_file)

        assert dataset.ticker_count == 1
        assert "AAA" in dataset.tickers

    def test_invalid_header_rejected(self, tmp_path: Path) -> None:
        """CSV with wrong header structure is rejected."""
        csv_content = (
            "Wrong;Header;Format\n"
            "Company A;AAA;Technology\n"
        )
        csv_file = tmp_path / "bad_header.csv"
        csv_file.write_text(csv_content, encoding="utf-8")

        with pytest.raises(DatasetValidationError, match="Invalid CSV header"):
            load_sp500_prices(csv_file)

    def test_duplicate_ticker_date_rejected(self, tmp_path: Path) -> None:
        """Duplicate ticker-date pairs are rejected."""
        csv_content = (
            "Societa;Ticker Yahoo;Settore;Data;Open;High;Low;Close;Volume;Adjusted Close;Currency\n"
            "Company A;AAA;Technology;01/01/2020;100.0;105.0;99.0;104.0;1000000;104.0;USD\n"
            "Company A;AAA;Technology;01/01/2020;101.0;106.0;100.0;105.0;1000000;105.0;USD\n"
        )
        csv_file = tmp_path / "duplicate.csv"
        csv_file.write_text(csv_content, encoding="utf-8")

        with pytest.raises(DatasetValidationError, match="Duplicate ticker-date"):
            load_sp500_prices(csv_file)

    def test_non_positive_price_rejected(self, tmp_path: Path) -> None:
        """Non-positive adjusted close is rejected."""
        csv_content = (
            "Societa;Ticker Yahoo;Settore;Data;Open;High;Low;Close;Volume;Adjusted Close;Currency\n"
            "Company A;AAA;Technology;01/01/2020;100.0;105.0;99.0;104.0;1000000;-104.0;USD\n"
        )
        csv_file = tmp_path / "negative.csv"
        csv_file.write_text(csv_content, encoding="utf-8")

        with pytest.raises(DatasetValidationError, match="must be finite and positive"):
            load_sp500_prices(csv_file)

    def test_invalid_date_format_rejected(self, tmp_path: Path) -> None:
        """Invalid date format is rejected."""
        csv_content = (
            "Societa;Ticker Yahoo;Settore;Data;Open;High;Low;Close;Volume;Adjusted Close;Currency\n"
            "Company A;AAA;Technology;2020-01-01;100.0;105.0;99.0;104.0;1000000;104.0;USD\n"
        )
        csv_file = tmp_path / "bad_date.csv"
        csv_file.write_text(csv_content, encoding="utf-8")

        with pytest.raises(DatasetValidationError, match="Invalid date format"):
            load_sp500_prices(csv_file)

    def test_wrong_currency_rejected(self, tmp_path: Path) -> None:
        """Non-USD currency is rejected by default."""
        csv_content = (
            "Societa;Ticker Yahoo;Settore;Data;Open;High;Low;Close;Volume;Adjusted Close;Currency\n"
            "Company A;AAA;Technology;01/01/2020;100.0;105.0;99.0;104.0;1000000;104.0;EUR\n"
        )
        csv_file = tmp_path / "euro.csv"
        csv_file.write_text(csv_content, encoding="utf-8")

        with pytest.raises(DatasetValidationError, match="Expected currency USD"):
            load_sp500_prices(csv_file)

    def test_date_filter_applied(self, tmp_path: Path) -> None:
        """Date range filter is applied correctly."""
        csv_content = (
            "Societa;Ticker Yahoo;Settore;Data;Open;High;Low;Close;Volume;Adjusted Close;Currency\n"
            "Company A;AAA;Technology;01/01/2020;100.0;105.0;99.0;104.0;1000000;104.0;USD\n"
            "Company A;AAA;Technology;01/06/2020;110.0;115.0;109.0;114.0;1000000;114.0;USD\n"
            "Company A;AAA;Technology;01/12/2020;120.0;125.0;119.0;124.0;1000000;124.0;USD\n"
        )
        csv_file = tmp_path / "dates.csv"
        csv_file.write_text(csv_content, encoding="utf-8")

        dataset = load_sp500_prices(
            csv_file,
            start_date=date(2020, 5, 1),
            end_date=date(2020, 7, 1),
        )

        assert dataset.date_count == 1
        assert dataset.dates[0] == date(2020, 6, 1)

    def test_missing_file_raises(self) -> None:
        """Missing file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            load_sp500_prices("/nonexistent/path.csv")


class TestComputeReturnStatistics:
    """Tests for compute_return_statistics function."""

    def _create_dataset(self, tmp_path: Path, prices: dict[str, list[float]]) -> SP500Dataset:
        """Helper to create a test dataset."""
        lines = [
            "Societa;Ticker Yahoo;Settore;Data;Open;High;Low;Close;Volume;Adjusted Close;Currency"
        ]
        dates = [f"{i+1:02d}/01/2020" for i in range(len(next(iter(prices.values()))))]

        for ticker, price_list in prices.items():
            for i, price in enumerate(price_list):
                lines.append(
                    f"Company {ticker};{ticker};Technology;{dates[i]};"
                    f"{price};{price};{price};{price};1000000;{price};USD"
                )

        csv_file = tmp_path / "test.csv"
        csv_file.write_text("\n".join(lines), encoding="utf-8")
        return load_sp500_prices(csv_file)

    def test_log_returns_computed_correctly(self, tmp_path: Path) -> None:
        """Log returns are computed as ln(P_t / P_{t-1})."""
        # Prices: 100, 105, 110.25, 115.7625 -> log returns approx ln(1.05)
        # Using varying prices to get non-zero variance
        dataset = self._create_dataset(tmp_path, {"AAA": [100.0, 105.0, 112.0, 118.0]})

        stats = compute_return_statistics(dataset, return_convention="log", annualization_factor=1)

        # Calculate expected mean manually: 3 returns
        r1 = math.log(105 / 100)  # 0.04879
        r2 = math.log(112 / 105)  # 0.06454
        r3 = math.log(118 / 112)  # 0.05220
        expected = (r1 + r2 + r3) / 3
        assert abs(stats.mean_returns["AAA"] - expected) < 1e-6

    def test_simple_returns_computed_correctly(self, tmp_path: Path) -> None:
        """Simple returns are computed as (P_t - P_{t-1}) / P_{t-1}."""
        # Prices: 100, 105, 112, 118 -> simple returns = [0.05, 0.0667, 0.0536]
        dataset = self._create_dataset(tmp_path, {"AAA": [100.0, 105.0, 112.0, 118.0]})

        stats = compute_return_statistics(dataset, return_convention="simple", annualization_factor=1)

        # Calculate expected mean manually: 3 returns
        r1 = (105 - 100) / 100  # 0.05
        r2 = (112 - 105) / 105  # 0.0667
        r3 = (118 - 112) / 112  # 0.0536
        expected = (r1 + r2 + r3) / 3
        assert abs(stats.mean_returns["AAA"] - expected) < 1e-6

    def test_annualization_applied(self, tmp_path: Path) -> None:
        """Annualization factor scales mean returns and covariance."""
        dataset = self._create_dataset(tmp_path, {"AAA": [100.0, 110.0, 115.0]})

        stats_daily = compute_return_statistics(dataset, annualization_factor=1)
        stats_annual = compute_return_statistics(dataset, annualization_factor=252)

        # Mean should scale linearly
        ratio = stats_annual.mean_returns["AAA"] / stats_daily.mean_returns["AAA"]
        assert abs(ratio - 252) < 1e-6

    def test_non_positive_mean_excluded(self, tmp_path: Path) -> None:
        """Tickers with non-positive mean return are excluded."""
        dataset = self._create_dataset(tmp_path, {
            "AAA": [100.0, 110.0, 120.0],  # Positive return
            "BBB": [100.0, 90.0, 85.0],    # Negative return
        })

        stats = compute_return_statistics(dataset)

        assert "AAA" in stats.tickers
        assert "BBB" not in stats.tickers
        assert "BBB" in stats.excluded_tickers

    def test_covariance_is_symmetric(self, tmp_path: Path) -> None:
        """Computed covariance matrix is symmetric."""
        dataset = self._create_dataset(tmp_path, {
            "AAA": [100.0, 110.0, 115.0, 120.0],
            "BBB": [50.0, 55.0, 54.0, 58.0],
        })

        stats = compute_return_statistics(dataset)

        cov = np.array(stats.covariance)
        assert np.allclose(cov, cov.T)

    def test_covariance_is_psd(self, tmp_path: Path) -> None:
        """Computed covariance matrix is positive semi-definite."""
        dataset = self._create_dataset(tmp_path, {
            "AAA": [100.0, 110.0, 115.0, 120.0, 125.0],
            "BBB": [50.0, 55.0, 54.0, 58.0, 60.0],
            "CCC": [200.0, 205.0, 210.0, 215.0, 220.0],
        })

        stats = compute_return_statistics(dataset)

        cov = np.array(stats.covariance)
        eigenvalues = np.linalg.eigvalsh(cov)
        assert all(ev >= -1e-10 for ev in eigenvalues)

    @pytest.mark.parametrize("price_count", [1, 2])
    @pytest.mark.parametrize("ticker_count", [1, 2])
    @pytest.mark.parametrize("return_convention", ["simple", "log"])
    def test_insufficient_dates_rejected(
        self, tmp_path: Path, price_count: int, ticker_count: int, return_convention: str
    ) -> None:
        """One or two prices cannot provide two returns for sample covariance."""
        dataset = self._create_dataset(tmp_path, {
            ticker: [100.0, 110.0][:price_count]
            for ticker in ("AAA", "BBB")[:ticker_count]
        })

        with pytest.raises(DatasetValidationError, match="at least 3 dates.*sample covariance"):
            compute_return_statistics(dataset, return_convention=return_convention)


class TestSP500DatasetProperties:
    """Tests for SP500Dataset properties and methods."""

    def test_sector_set_returns_unique_sectors(self, tmp_path: Path) -> None:
        """sector_set returns unique sector names."""
        csv_content = (
            "Societa;Ticker Yahoo;Settore;Data;Open;High;Low;Close;Volume;Adjusted Close;Currency\n"
            "Company A;AAA;Technology;01/01/2020;100.0;105.0;99.0;104.0;1000000;104.0;USD\n"
            "Company B;BBB;Technology;01/01/2020;50.0;52.0;49.0;51.0;500000;51.0;USD\n"
            "Company C;CCC;Health Care;01/01/2020;75.0;77.0;74.0;76.0;600000;76.0;USD\n"
        )
        csv_file = tmp_path / "sectors.csv"
        csv_file.write_text(csv_content, encoding="utf-8")

        dataset = load_sp500_prices(csv_file)

        assert dataset.sector_set == frozenset({"Technology", "Health Care"})

    def test_tickers_in_sector_returns_correct_tickers(self, tmp_path: Path) -> None:
        """tickers_in_sector returns tickers belonging to specified sector."""
        csv_content = (
            "Societa;Ticker Yahoo;Settore;Data;Open;High;Low;Close;Volume;Adjusted Close;Currency\n"
            "Company A;AAA;Technology;01/01/2020;100.0;105.0;99.0;104.0;1000000;104.0;USD\n"
            "Company B;BBB;Technology;01/01/2020;50.0;52.0;49.0;51.0;500000;51.0;USD\n"
            "Company C;CCC;Health Care;01/01/2020;75.0;77.0;74.0;76.0;600000;76.0;USD\n"
        )
        csv_file = tmp_path / "sectors.csv"
        csv_file.write_text(csv_content, encoding="utf-8")

        dataset = load_sp500_prices(csv_file)

        tech_tickers = dataset.tickers_in_sector("Technology")
        assert set(tech_tickers) == {"AAA", "BBB"}

    def test_to_dict_serialization(self, tmp_path: Path) -> None:
        """to_dict produces valid serialization."""
        csv_content = (
            "Societa;Ticker Yahoo;Settore;Data;Open;High;Low;Close;Volume;Adjusted Close;Currency\n"
            "Company A;AAA;Technology;01/01/2020;100.0;105.0;99.0;104.0;1000000;104.0;USD\n"
        )
        csv_file = tmp_path / "test.csv"
        csv_file.write_text(csv_content, encoding="utf-8")

        dataset = load_sp500_prices(csv_file)
        data = dataset.to_dict()

        assert "source_path" in data
        assert "source_sha256" in data
        assert "ticker_count" in data
        assert "date_count" in data
        assert data["exclusion_reasons"] == {}

        # Existing constructors can omit the new field; caller mappings are copied.
        legacy = SP500Dataset(
            dataset.source_path, dataset.source_sha256, dataset.tickers, dataset.dates,
            dataset.sectors, dataset.currencies, dataset.company_names, dataset.adjusted_close,
        )
        assert legacy.exclusion_reasons == {}
        reasons = {"BBB": "incomplete_price_history"}
        copied = replace(legacy, exclusion_reasons=reasons)
        reasons["BBB"] = "changed"
        assert copied.exclusion_reasons["BBB"] == "incomplete_price_history"


class TestReturnStatisticsProperties:
    """Tests for ReturnStatistics properties and methods."""

    def _create_stats(self, tmp_path: Path) -> ReturnStatistics:
        """Helper to create test statistics."""
        csv_content = (
            "Societa;Ticker Yahoo;Settore;Data;Open;High;Low;Close;Volume;Adjusted Close;Currency\n"
            "Company A;AAA;Technology;01/01/2020;100.0;105.0;99.0;104.0;1000000;104.0;USD\n"
            "Company A;AAA;Technology;02/01/2020;104.0;110.0;103.0;108.0;1100000;108.0;USD\n"
            "Company A;AAA;Technology;03/01/2020;108.0;112.0;107.0;111.0;1200000;111.0;USD\n"
        )
        csv_file = tmp_path / "test.csv"
        csv_file.write_text(csv_content, encoding="utf-8")

        dataset = load_sp500_prices(csv_file)
        return compute_return_statistics(dataset)

    def test_ticker_count_property(self, tmp_path: Path) -> None:
        """ticker_count returns number of eligible tickers."""
        stats = self._create_stats(tmp_path)
        assert stats.ticker_count == 1

    def test_to_dict_includes_exclusion_info(self, tmp_path: Path) -> None:
        """to_dict includes exclusion information."""
        stats = self._create_stats(tmp_path)
        data = stats.to_dict()

        assert "return_convention" in data
        assert "annualization_factor" in data
        assert "excluded_count" in data
        assert "exclusion_reasons" in data
