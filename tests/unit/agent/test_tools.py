"""Unit tests for agent tool handlers."""

import datetime as dt
from unittest.mock import AsyncMock, MagicMock

import pytest

from prosper.agent.tools import ToolHandlers
from prosper.domain.exceptions import EHRUnavailableError
from prosper.domain.models import Patient
from prosper.ehr.adapters.fake import FakeEHRClient
from prosper.ehr.service import EHRService

# Fixtures (fake_client, service) provided by tests/conftest.py


@pytest.fixture
def handlers(service: EHRService) -> ToolHandlers:
    return ToolHandlers(service)


def _make_params(arguments: dict[str, str]) -> MagicMock:
    """Create a mock FunctionCallParams with the given arguments."""
    params = MagicMock()
    params.arguments = arguments
    params.result_callback = AsyncMock()
    return params


class TestHandleFindPatient:
    @pytest.mark.asyncio
    async def test_missing_name_returns_error(self, handlers: ToolHandlers) -> None:
        params = _make_params({"name": "", "date_of_birth": "2000-01-01"})
        await handlers.handle_find_patient(params)
        result = params.result_callback.call_args[0][0]
        assert result["error"] is True
        assert result["found"] is False

    @pytest.mark.asyncio
    async def test_missing_dob_returns_error(self, handlers: ToolHandlers) -> None:
        params = _make_params({"name": "Marc", "date_of_birth": ""})
        await handlers.handle_find_patient(params)
        result = params.result_callback.call_args[0][0]
        assert result["error"] is True

    @pytest.mark.asyncio
    async def test_invalid_date_returns_error(self, handlers: ToolHandlers) -> None:
        params = _make_params({"name": "Marc", "date_of_birth": "not-a-date"})
        await handlers.handle_find_patient(params)
        result = params.result_callback.call_args[0][0]
        assert result["error"] is True
        assert "Invalid date" in result["message"]

    @pytest.mark.asyncio
    async def test_single_match(self, handlers: ToolHandlers, fake_client: FakeEHRClient) -> None:
        fake_client.patients = [
            Patient(
                patient_id="1",
                first_name="Marc",
                last_name="Camps",
                date_of_birth=dt.date(2003, 5, 18),
            ),
        ]
        params = _make_params({"name": "Marc", "date_of_birth": "2003-05-18"})
        await handlers.handle_find_patient(params)
        result = params.result_callback.call_args[0][0]
        assert result["found"] is True
        assert result["patient_id"] == "1"
        assert result["name"] == "Marc Camps"

    @pytest.mark.asyncio
    async def test_multiple_matches(
        self, handlers: ToolHandlers, fake_client: FakeEHRClient
    ) -> None:
        fake_client.patients = [
            Patient(
                patient_id="1", first_name="Marc", last_name="A", date_of_birth=dt.date(2003, 5, 18)
            ),
            Patient(
                patient_id="2", first_name="Marc", last_name="B", date_of_birth=dt.date(2003, 5, 18)
            ),
        ]
        params = _make_params({"name": "Marc", "date_of_birth": "2003-05-18"})
        await handlers.handle_find_patient(params)
        result = params.result_callback.call_args[0][0]
        assert result["found"] is True
        assert result["multiple_matches"] is True
        assert len(result["patients"]) == 2

    @pytest.mark.asyncio
    async def test_no_match(self, handlers: ToolHandlers, fake_client: FakeEHRClient) -> None:
        fake_client.patients = []
        params = _make_params({"name": "Nobody", "date_of_birth": "2000-01-01"})
        await handlers.handle_find_patient(params)
        result = params.result_callback.call_args[0][0]
        assert result["found"] is False

    @pytest.mark.asyncio
    async def test_ehr_error_returns_error_result(
        self, handlers: ToolHandlers, fake_client: FakeEHRClient
    ) -> None:
        fake_client.search_error = EHRUnavailableError("down")
        params = _make_params({"name": "Marc", "date_of_birth": "2003-05-18"})
        await handlers.handle_find_patient(params)
        result = params.result_callback.call_args[0][0]
        assert result["error"] is True


class TestHandleCreateAppointment:
    @pytest.mark.asyncio
    async def test_missing_fields_returns_error(self, handlers: ToolHandlers) -> None:
        params = _make_params({"patient_id": "", "date": "2026-03-15", "time": "14:00"})
        await handlers.handle_create_appointment(params)
        result = params.result_callback.call_args[0][0]
        assert result["error"] is True
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_invalid_date_returns_error(self, handlers: ToolHandlers) -> None:
        params = _make_params({"patient_id": "1", "date": "bad", "time": "14:00"})
        await handlers.handle_create_appointment(params)
        result = params.result_callback.call_args[0][0]
        assert result["error"] is True
        assert "Invalid date" in result["message"]

    @pytest.mark.asyncio
    async def test_invalid_time_returns_error(self, handlers: ToolHandlers) -> None:
        params = _make_params({"patient_id": "1", "date": "2027-06-15", "time": "bad"})
        await handlers.handle_create_appointment(params)
        result = params.result_callback.call_args[0][0]
        assert result["error"] is True
        assert "Invalid time" in result["message"]

    @pytest.mark.asyncio
    async def test_past_date_returns_error(self, handlers: ToolHandlers) -> None:
        params = _make_params({"patient_id": "1", "date": "2020-01-01", "time": "14:00"})
        await handlers.handle_create_appointment(params)
        result = params.result_callback.call_args[0][0]
        assert result["error"] is True
        assert "past" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_successful_creation(self, handlers: ToolHandlers) -> None:
        params = _make_params({"patient_id": "1", "date": "2027-06-15", "time": "14:00"})
        await handlers.handle_create_appointment(params)
        result = params.result_callback.call_args[0][0]
        assert result["success"] is True
        assert result["appointment_id"] == "new-1"
        assert result["date"] == "2027-06-15"
        assert result["time"] == "14:00"

    @pytest.mark.asyncio
    async def test_ehr_error_returns_error_result(
        self, handlers: ToolHandlers, fake_client: FakeEHRClient
    ) -> None:
        fake_client.create_error = EHRUnavailableError("down")
        params = _make_params({"patient_id": "1", "date": "2027-06-15", "time": "14:00"})
        await handlers.handle_create_appointment(params)
        result = params.result_callback.call_args[0][0]
        assert result["error"] is True
        assert result["success"] is False


class TestHandleCancelAppointment:
    @pytest.mark.asyncio
    async def test_missing_appointment_id_returns_error(self, handlers: ToolHandlers) -> None:
        params = _make_params({"appointment_id": ""})
        await handlers.handle_cancel_appointment(params)
        result = params.result_callback.call_args[0][0]
        assert result["error"] is True
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_successful_cancellation(self, handlers: ToolHandlers) -> None:
        params = _make_params({"appointment_id": "a1"})
        await handlers.handle_cancel_appointment(params)
        result = params.result_callback.call_args[0][0]
        assert result["success"] is True
        assert result["appointment_id"] == "a1"

    @pytest.mark.asyncio
    async def test_ehr_error_returns_error_result(
        self, handlers: ToolHandlers, fake_client: FakeEHRClient
    ) -> None:
        fake_client.cancel_error = EHRUnavailableError("down")
        params = _make_params({"appointment_id": "a1"})
        await handlers.handle_cancel_appointment(params)
        result = params.result_callback.call_args[0][0]
        assert result["error"] is True
        assert result["success"] is False
