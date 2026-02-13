import datetime as dt

import pytest

from prosper.domain.exceptions import (
    AppointmentCancellationError,
    AppointmentCreationError,
    EHRUnavailableError,
)
from prosper.domain.models import AppointmentRequest, AppointmentStatus, Patient
from prosper.ehr.adapters.fake import FakeEHRClient
from prosper.ehr.service import EHRService

# Fixtures (fake_client, service) provided by tests/conftest.py


class TestFindPatient:
    @pytest.mark.asyncio
    async def test_filters_by_dob(self, service: EHRService, fake_client: FakeEHRClient) -> None:
        fake_client.patients = [
            Patient(
                patient_id="1", first_name="Marc", last_name="A", date_of_birth=dt.date(2003, 5, 18)
            ),
            Patient(
                patient_id="2", first_name="Marc", last_name="B", date_of_birth=dt.date(1990, 1, 1)
            ),
        ]

        result = await service.find_patient("Marc", dt.date(2003, 5, 18))

        assert len(result) == 1
        assert result[0].patient_id == "1"

    @pytest.mark.asyncio
    async def test_skips_dob_filter_when_none(
        self, service: EHRService, fake_client: FakeEHRClient
    ) -> None:
        fake_client.patients = [
            Patient(
                patient_id="1", first_name="Marc", last_name="A", date_of_birth=dt.date(2003, 5, 18)
            ),
            Patient(
                patient_id="2", first_name="Marc", last_name="B", date_of_birth=dt.date(1990, 1, 1)
            ),
        ]

        result = await service.find_patient("Marc", None)

        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_match(
        self, service: EHRService, fake_client: FakeEHRClient
    ) -> None:
        fake_client.patients = []

        result = await service.find_patient("Nobody", dt.date(2000, 1, 1))

        assert result == []

    @pytest.mark.asyncio
    async def test_wraps_unexpected_error_as_ehr_unavailable(
        self, service: EHRService, fake_client: FakeEHRClient
    ) -> None:
        fake_client.search_error = RuntimeError("connection reset")

        with pytest.raises(EHRUnavailableError, match="Patient search failed"):
            await service.find_patient("Marc", dt.date(2003, 5, 18))

    @pytest.mark.asyncio
    async def test_propagates_ehr_unavailable_directly(
        self, service: EHRService, fake_client: FakeEHRClient
    ) -> None:
        fake_client.search_error = EHRUnavailableError("service down")

        with pytest.raises(EHRUnavailableError, match="service down"):
            await service.find_patient("Marc", dt.date(2003, 5, 18))


class TestCreateAppointment:
    @pytest.fixture
    def request_(self) -> AppointmentRequest:
        return AppointmentRequest(patient_id="42", date=dt.date(2026, 3, 15), time=dt.time(14, 30))

    @pytest.mark.asyncio
    async def test_delegates_to_client(
        self,
        service: EHRService,
        fake_client: FakeEHRClient,
        request_: AppointmentRequest,
    ) -> None:
        appt = await service.create_appointment(request_)

        assert appt.appointment_id == "new-1"
        assert appt.status == AppointmentStatus.SCHEDULED
        assert fake_client.created == [request_]

    @pytest.mark.asyncio
    async def test_wraps_unexpected_error(
        self,
        service: EHRService,
        fake_client: FakeEHRClient,
        request_: AppointmentRequest,
    ) -> None:
        fake_client.create_error = RuntimeError("boom")

        with pytest.raises(AppointmentCreationError, match="boom"):
            await service.create_appointment(request_)


class TestCancelAppointment:
    @pytest.mark.asyncio
    async def test_delegates_to_client(
        self, service: EHRService, fake_client: FakeEHRClient
    ) -> None:
        appt = await service.cancel_appointment("p1", dt.date(2026, 6, 15), dt.time(10, 0))

        assert appt.status == AppointmentStatus.CANCELLED
        assert fake_client.cancelled == [("p1", dt.date(2026, 6, 15), dt.time(10, 0))]

    @pytest.mark.asyncio
    async def test_wraps_unexpected_error(
        self, service: EHRService, fake_client: FakeEHRClient
    ) -> None:
        fake_client.cancel_error = RuntimeError("network")

        with pytest.raises(AppointmentCancellationError, match="network"):
            await service.cancel_appointment("p1", dt.date(2026, 6, 15), dt.time(10, 0))

    @pytest.mark.asyncio
    async def test_propagates_known_errors(
        self, service: EHRService, fake_client: FakeEHRClient
    ) -> None:
        fake_client.cancel_error = AppointmentCancellationError(
            reason="already cancelled", patient_id="p1"
        )

        with pytest.raises(AppointmentCancellationError, match="already cancelled"):
            await service.cancel_appointment("p1", dt.date(2026, 6, 15), dt.time(10, 0))


class TestLifecycle:
    @pytest.mark.asyncio
    async def test_health_check_delegates(self, service: EHRService) -> None:
        assert await service.health_check() is True

    @pytest.mark.asyncio
    async def test_close_delegates(self, service: EHRService, fake_client: FakeEHRClient) -> None:
        await service.close()

        assert fake_client.closed is True
