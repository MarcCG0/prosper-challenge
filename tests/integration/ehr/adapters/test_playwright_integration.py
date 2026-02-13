"""Integration tests for the Playwright Healthie adapter.

These tests run against a real Healthie instance and require:
  - HEALTHIE_EMAIL and HEALTHIE_PASSWORD set in .env (or env vars)
  - Playwright browsers installed (``uv run playwright install chromium``)
  - At least one patient named "Test" in the Healthie system

Run explicitly with::

    uv run pytest -m integration
"""

import datetime as dt
import os
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from dotenv import load_dotenv

from prosper.domain.models import AppointmentRequest, AppointmentStatus
from prosper.ehr.adapters.playwright import PlaywrightHealthieClient

load_dotenv(override=True)

_EMAIL = os.environ.get("HEALTHIE_EMAIL", "")
_PASSWORD = os.environ.get("HEALTHIE_PASSWORD", "")
_BASE_URL = os.environ.get("HEALTHIE_BASE_URL", "https://secure.gethealthie.com")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.asyncio,
    pytest.mark.skipif(
        not _EMAIL or not _PASSWORD,
        reason="HEALTHIE_EMAIL and HEALTHIE_PASSWORD must be set",
    ),
]


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[PlaywrightHealthieClient]:
    """A Playwright client with real credentials — closed after each test."""
    c = PlaywrightHealthieClient(
        email=_EMAIL,
        password=_PASSWORD,
        base_url=_BASE_URL,
        headless=True,
    )
    yield c
    await c.close()


class TestHealthCheck:
    async def test_returns_true_when_healthy(self, client: PlaywrightHealthieClient) -> None:
        assert await client.health_check() is True


class TestSearchPatients:
    async def test_finds_known_patient(self, client: PlaywrightHealthieClient) -> None:
        patients = await client.search_patients("Test")

        assert len(patients) >= 1

    async def test_returns_empty_for_nonexistent(self, client: PlaywrightHealthieClient) -> None:
        patients = await client.search_patients("Zzzzxnonexistent12345")

        assert patients == []


class TestCreateAndCancelAppointment:
    async def test_create_and_cancel_round_trip(self, client: PlaywrightHealthieClient) -> None:
        patients = await client.search_patients("Test")
        assert len(patients) >= 1
        patient_id = patients[0].patient_id

        request = AppointmentRequest(
            patient_id=patient_id,
            date=dt.date(2026, 9, 15),
            time=dt.time(14, 0),
        )
        appointment = await client.create_appointment(request)

        assert appointment.patient_id == patient_id
        assert appointment.date == request.date
        assert appointment.time == request.time
        assert appointment.status == AppointmentStatus.SCHEDULED

        cancelled = await client.cancel_appointment(patient_id, request.date, request.time)

        assert cancelled.status == AppointmentStatus.CANCELLED


class TestClose:
    async def test_close_is_idempotent(self, client: PlaywrightHealthieClient) -> None:
        await client.close()
        await client.close()  # should not raise
