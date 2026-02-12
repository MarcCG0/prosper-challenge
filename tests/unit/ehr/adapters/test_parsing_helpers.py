import datetime as dt

import pytest

from prosper.ehr.adapters.parsing_helpers import extract_id_from_url, parse_name_dob


class TestParseNameDob:
    """Extracts (first_name, last_name, dob) from Healthie's patient row text."""

    @pytest.mark.parametrize(
        ("text", "expected_first", "expected_last", "expected_dob"),
        [
            ("Marc Camps (5/18/2003)", "Marc", "Camps", dt.date(2003, 5, 18)),
            ("Jane Doe (01/05/1990)", "Jane", "Doe", dt.date(1990, 1, 5)),
            ("Ana Garcia-Lopez (3/15/1985)", "Ana", "Garcia-Lopez", dt.date(1985, 3, 15)),
            ("Mary Jane Watson (12/1/2000)", "Mary", "Jane Watson", dt.date(2000, 12, 1)),
        ],
        ids=["standard", "zero-padded", "hyphenated-last-name", "three-part-name"],
    )
    def test_valid_formats(
        self,
        text: str,
        expected_first: str,
        expected_last: str,
        expected_dob: dt.date,
    ) -> None:
        result = parse_name_dob(text)

        assert result is not None
        first, last, dob = result
        assert first == expected_first
        assert last == expected_last
        assert dob == expected_dob

    def test_strips_surrounding_whitespace(self) -> None:
        result = parse_name_dob("  Marc Camps   (5/18/2003) ")

        assert result is not None
        assert result[0] == "Marc"
        assert result[1] == "Camps"

    def test_extracts_from_multiline_ui_text(self) -> None:
        text = "View Profile\nMarc Camps (5/18/2003)\nActive"

        result = parse_name_dob(text)

        assert result is not None
        assert result[0] == "Marc"

    @pytest.mark.parametrize(
        "text",
        [
            "No date here",
            "Madonna (5/18/2003)",  # single name -> None (need first + last)
            "",
            "12345 (1/1/2000)",  # name starts with digit
        ],
        ids=["no-parens", "single-name", "empty", "digit-prefix"],
    )
    def test_returns_none_for_invalid_input(self, text: str) -> None:
        assert parse_name_dob(text) is None


class TestExtractIdFromUrl:
    """Extracts the numeric patient/user ID from a Healthie profile URL."""

    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            ("/users/12345", "12345"),
            ("/patients/67890", "67890"),
            ("/clients/111", "111"),
            ("https://app.healthie.com/users/42/overview", "42"),
        ],
        ids=["users", "patients", "clients", "full-url-with-suffix"],
    )
    def test_extracts_id(self, url: str, expected: str) -> None:
        assert extract_id_from_url(url) == expected

    @pytest.mark.parametrize(
        "url",
        ["/dashboard", "", "/settings/profile"],
        ids=["no-match", "empty", "wrong-path"],
    )
    def test_returns_none_when_no_id(self, url: str) -> None:
        assert extract_id_from_url(url) is None
