import datetime as dt
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from pytest_httpx import HTTPXMock

from prosper.domain.exceptions import (
    AppointmentCancellationError,
    AppointmentCreationError,
    EHRUnavailableError,
)
from prosper.domain.models import AppointmentRequest, AppointmentStatus
from prosper.ehr.adapters.graphql import GraphQLHealthieClient

API_URL = "https://api.healthie.test/graphql"


@pytest.fixture
def client() -> GraphQLHealthieClient:
    """A GraphQL client with a pre-set token (skips signIn flow)."""
    return GraphQLHealthieClient(api_url=API_URL, token="test-token")


def _gql_ok(data: dict[str, Any]) -> dict[str, Any]:
    """Wrap ``data`` in the standard GraphQL success envelope."""
    return {"data": data}


def _gql_error(message: str) -> dict[str, Any]:
    """Build a GraphQL-level error response."""
    return {"errors": [{"message": message}]}


class TestSearchPatients:
    @pytest.mark.asyncio
    async def test_parses_patients_with_valid_dob(
        self, client: GraphQLHealthieClient, httpx_mock: HTTPXMock
    ) -> None:
        httpx_mock.add_response(
            json=_gql_ok(
                {
                    "users": [
                        {
                            "id": "42",
                            "first_name": "Marc",
                            "last_name": "Camps",
                            "dob": "2003-05-18",
                        },
                    ]
                }
            )
        )

        patients = await client.search_patients("Marc")

        assert len(patients) == 1
        assert patients[0].patient_id == "42"
        assert patients[0].first_name == "Marc"
        assert patients[0].last_name == "Camps"
        assert patients[0].date_of_birth == dt.date(2003, 5, 18)

    @pytest.mark.asyncio
    async def test_null_dob_becomes_none(
        self, client: GraphQLHealthieClient, httpx_mock: HTTPXMock
    ) -> None:
        httpx_mock.add_response(
            json=_gql_ok(
                {"users": [{"id": "1", "first_name": "No", "last_name": "Dob", "dob": None}]}
            )
        )

        patients = await client.search_patients("No")

        assert patients[0].date_of_birth is None

    @pytest.mark.asyncio
    async def test_malformed_dob_becomes_none(
        self, client: GraphQLHealthieClient, httpx_mock: HTTPXMock
    ) -> None:
        httpx_mock.add_response(
            json=_gql_ok(
                {
                    "users": [
                        {"id": "1", "first_name": "Bad", "last_name": "Date", "dob": "not-a-date"}
                    ]
                }
            )
        )

        patients = await client.search_patients("Bad")

        assert patients[0].date_of_birth is None

    @pytest.mark.asyncio
    async def test_empty_result_set(
        self, client: GraphQLHealthieClient, httpx_mock: HTTPXMock
    ) -> None:
        httpx_mock.add_response(json=_gql_ok({"users": []}))

        patients = await client.search_patients("Nobody")

        assert patients == []

    @pytest.mark.asyncio
    async def test_graphql_error_raises_ehr_unavailable(
        self, client: GraphQLHealthieClient, httpx_mock: HTTPXMock
    ) -> None:
        httpx_mock.add_response(json=_gql_error("Internal server error"))

        with pytest.raises(EHRUnavailableError, match="Internal server error"):
            await client.search_patients("Marc")

    @pytest.mark.asyncio
    async def test_http_error_raises_ehr_unavailable(
        self, client: GraphQLHealthieClient, httpx_mock: HTTPXMock
    ) -> None:
        httpx_mock.add_response(status_code=502)

        with pytest.raises(EHRUnavailableError):
            await client.search_patients("Marc")


class TestCreateAppointment:
    @pytest.fixture
    def request_(self) -> AppointmentRequest:
        return AppointmentRequest(patient_id="42", date=dt.date(2026, 3, 15), time=dt.time(14, 30))

    @pytest.mark.asyncio
    async def test_returns_appointment_on_success(
        self,
        client: GraphQLHealthieClient,
        httpx_mock: HTTPXMock,
        request_: AppointmentRequest,
    ) -> None:
        httpx_mock.add_response(
            json=_gql_ok(
                {
                    "appointmentTypes": [
                        {"id": "7", "name": "Consultation", "available_contact_types": ["Phone"]},
                    ]
                }
            )
        )
        httpx_mock.add_response(
            json=_gql_ok(
                {
                    "createAppointment": {
                        "appointment": {"id": "999", "date": "2026-03-15", "pm_status": None},
                        "messages": None,
                    }
                }
            )
        )

        appt = await client.create_appointment(request_)

        assert appt.appointment_id == "999"
        assert appt.patient_id == "42"
        assert appt.date == dt.date(2026, 3, 15)
        assert appt.time == dt.time(14, 30)
        assert appt.status == AppointmentStatus.SCHEDULED

    @pytest.mark.asyncio
    async def test_sends_correctly_formatted_datetime(
        self,
        client: GraphQLHealthieClient,
        httpx_mock: HTTPXMock,
    ) -> None:
        clinic_tz = ZoneInfo("America/New_York")
        httpx_mock.add_response(
            json=_gql_ok(
                {
                    "appointmentTypes": [
                        {"id": "7", "name": "Consult", "available_contact_types": ["Phone"]},
                    ]
                }
            )
        )
        httpx_mock.add_response(
            json=_gql_ok(
                {
                    "createAppointment": {
                        "appointment": {"id": "1", "date": "", "pm_status": None},
                        "messages": None,
                    }
                }
            )
        )
        request = AppointmentRequest(patient_id="42", date=dt.date(2026, 3, 15), time=dt.time(9, 5))

        await client.create_appointment(request)

        create_request = httpx_mock.get_requests()[1]
        body: dict[str, Any] = create_request.extensions.get("json") or {}
        # pytest-httpx may not expose json directly — parse content instead
        import json

        body = json.loads(create_request.content)
        expected_dt = dt.datetime.combine(dt.date(2026, 3, 15), dt.time(9, 5), tzinfo=clinic_tz)
        assert body["variables"]["datetime"] == expected_dt.strftime("%Y-%m-%d %H:%M:%S %z")

    @pytest.mark.asyncio
    async def test_api_messages_raise_creation_error(
        self,
        client: GraphQLHealthieClient,
        httpx_mock: HTTPXMock,
        request_: AppointmentRequest,
    ) -> None:
        httpx_mock.add_response(
            json=_gql_ok(
                {
                    "appointmentTypes": [
                        {"id": "7", "name": "Consult", "available_contact_types": ["Phone"]},
                    ]
                }
            )
        )
        httpx_mock.add_response(
            json=_gql_ok(
                {
                    "createAppointment": {
                        "appointment": None,
                        "messages": [{"field": "datetime", "message": "Slot unavailable"}],
                    }
                }
            )
        )

        with pytest.raises(AppointmentCreationError, match="Slot unavailable"):
            await client.create_appointment(request_)

    @pytest.mark.asyncio
    async def test_caches_appointment_type_across_calls(
        self,
        client: GraphQLHealthieClient,
        httpx_mock: HTTPXMock,
    ) -> None:
        # One appointmentTypes fetch + two createAppointment calls = 3 requests
        httpx_mock.add_response(
            json=_gql_ok(
                {
                    "appointmentTypes": [
                        {"id": "7", "name": "Consult", "available_contact_types": ["Phone"]},
                    ]
                }
            )
        )
        for _ in range(2):
            httpx_mock.add_response(
                json=_gql_ok(
                    {
                        "createAppointment": {
                            "appointment": {"id": "1", "date": "", "pm_status": None},
                            "messages": None,
                        }
                    }
                )
            )
        request = AppointmentRequest(
            patient_id="42", date=dt.date(2026, 3, 15), time=dt.time(14, 0)
        )

        await client.create_appointment(request)
        await client.create_appointment(request)

        assert len(httpx_mock.get_requests()) == 3


class TestCancelAppointment:
    @pytest.mark.asyncio
    async def test_parses_cancelled_appointment_with_date(
        self, client: GraphQLHealthieClient, httpx_mock: HTTPXMock
    ) -> None:
        httpx_mock.add_response(
            json=_gql_ok(
                {
                    "updateAppointment": {
                        "appointment": {
                            "id": "100",
                            "date": "2026-09-15 16:00:00 +0200",
                            "pm_status": "Cancelled",
                        },
                        "messages": None,
                    }
                }
            )
        )

        appt = await client.cancel_appointment("100")

        assert appt.appointment_id == "100"
        assert appt.date == dt.date(2026, 9, 15)
        # 16:00 +0200 = 14:00 UTC = 10:00 EDT (America/New_York, UTC-4 in Sep)
        assert appt.time == dt.time(10, 0)
        assert appt.status == AppointmentStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_unparseable_date_yields_none_fields(
        self, client: GraphQLHealthieClient, httpx_mock: HTTPXMock
    ) -> None:
        httpx_mock.add_response(
            json=_gql_ok(
                {
                    "updateAppointment": {
                        "appointment": {"id": "100", "date": "", "pm_status": "Cancelled"},
                        "messages": None,
                    }
                }
            )
        )

        appt = await client.cancel_appointment("100")

        assert appt.date is None
        assert appt.time is None
        assert appt.status == AppointmentStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_api_messages_raise_cancellation_error(
        self, client: GraphQLHealthieClient, httpx_mock: HTTPXMock
    ) -> None:
        httpx_mock.add_response(
            json=_gql_ok(
                {
                    "updateAppointment": {
                        "appointment": None,
                        "messages": [{"field": "id", "message": "Not found"}],
                    }
                }
            )
        )

        with pytest.raises(AppointmentCancellationError, match="Not found"):
            await client.cancel_appointment("999")

    @pytest.mark.asyncio
    async def test_sends_cancelled_pm_status(
        self, client: GraphQLHealthieClient, httpx_mock: HTTPXMock
    ) -> None:
        httpx_mock.add_response(
            json=_gql_ok(
                {
                    "updateAppointment": {
                        "appointment": {"id": "100", "date": "", "pm_status": "Cancelled"},
                        "messages": None,
                    }
                }
            )
        )

        await client.cancel_appointment("100")

        import json

        body: dict[str, Any] = json.loads(httpx_mock.get_requests()[0].content)
        assert body["variables"]["pm_status"] == "Cancelled"


class TestHealthCheck:
    @pytest.mark.asyncio
    async def test_returns_true_on_success(
        self, client: GraphQLHealthieClient, httpx_mock: HTTPXMock
    ) -> None:
        httpx_mock.add_response(json=_gql_ok({"users": [{"id": "1"}]}))

        assert await client.health_check() is True

    @pytest.mark.asyncio
    async def test_returns_false_on_graphql_error(
        self, client: GraphQLHealthieClient, httpx_mock: HTTPXMock
    ) -> None:
        httpx_mock.add_response(json=_gql_error("Internal error"))

        assert await client.health_check() is False

    @pytest.mark.asyncio
    async def test_returns_false_on_network_error(
        self, client: GraphQLHealthieClient, httpx_mock: HTTPXMock
    ) -> None:
        httpx_mock.add_exception(ConnectionError("refused"))

        assert await client.health_check() is False


class TestAuthentication:
    @pytest.mark.asyncio
    async def test_token_sends_bearer_auth_header(
        self, client: GraphQLHealthieClient, httpx_mock: HTTPXMock
    ) -> None:
        httpx_mock.add_response(json=_gql_ok({"users": []}))

        await client.search_patients("test")

        request = httpx_mock.get_requests()[0]
        assert request.headers["Authorization"] == "Bearer test-token"
        assert request.headers["AuthorizationSource"] == "Web"

    @pytest.mark.asyncio
    async def test_no_credentials_raises_ehr_unavailable(self, httpx_mock: HTTPXMock) -> None:
        client = GraphQLHealthieClient(api_url=API_URL)

        with pytest.raises(EHRUnavailableError, match="No email/password"):
            await client.search_patients("test")

    @pytest.mark.asyncio
    async def test_sign_in_uses_bearer_auth(self, httpx_mock: HTTPXMock) -> None:
        # First call: signIn returns a token
        httpx_mock.add_response(
            json={"data": {"signIn": {"token": "session-tok", "messages": None}}}
        )
        # Second call: the actual query
        httpx_mock.add_response(json=_gql_ok({"users": []}))
        client = GraphQLHealthieClient(api_url=API_URL, email="a@b.com", password="secret")

        await client.search_patients("test")

        query_request = httpx_mock.get_requests()[1]
        assert query_request.headers["Authorization"] == "Bearer session-tok"
        assert query_request.headers["AuthorizationSource"] == "Web"

    @pytest.mark.asyncio
    async def test_sign_in_failure_raises(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            json={"data": {"signIn": {"token": None, "messages": [{"message": "Bad creds"}]}}}
        )
        client = GraphQLHealthieClient(api_url=API_URL, email="a@b.com", password="wrong")

        with pytest.raises(EHRUnavailableError, match="Bad creds"):
            await client.search_patients("test")
