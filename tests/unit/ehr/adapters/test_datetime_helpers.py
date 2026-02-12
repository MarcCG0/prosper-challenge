import datetime as dt

import pytest

from prosper.ehr.adapters.datetime_helpers import date_to_us_long, time_to_12h


class TestDateToUsLong:
    """Converts dt.date → US long format string for Healthie's date picker."""

    @pytest.mark.parametrize(
        ("date", "expected"),
        [
            (dt.date(2026, 3, 22), "March 22, 2026"),
            (dt.date(2026, 1, 5), "January 5, 2026"),
            (dt.date(2026, 12, 25), "December 25, 2026"),
            (dt.date(2028, 2, 29), "February 29, 2028"),
            (dt.date(2026, 6, 1), "June 1, 2026"),
        ],
        ids=["standard", "single-digit-day", "december", "leap-day", "june-first"],
    )
    def test_formats_correctly(self, date: dt.date, expected: str) -> None:
        assert date_to_us_long(date) == expected


class TestTimeTo12h:
    """Converts dt.time → 12-hour string for Healthie's time picker.

    Healthie uses no leading zero on the hour (e.g. ``2:30 PM`` not ``02:30 PM``).
    """

    @pytest.mark.parametrize(
        ("time", "expected"),
        [
            (dt.time(14, 30), "2:30 PM"),
            (dt.time(9, 0), "9:00 AM"),
            (dt.time(12, 0), "12:00 PM"),
            (dt.time(0, 0), "12:00 AM"),
            (dt.time(11, 59), "11:59 AM"),
            (dt.time(13, 0), "1:00 PM"),
            (dt.time(23, 59), "11:59 PM"),
        ],
        ids=["afternoon", "morning", "noon", "midnight", "before-noon", "1pm", "before-midnight"],
    )
    def test_formats_correctly(self, time: dt.time, expected: str) -> None:
        assert time_to_12h(time) == expected
