import datetime as dt
from typing import Any

import httpx
from loguru import logger

from prosper.domain.exceptions import (
    AppointmentCancellationError,
    AppointmentCreationError,
    EHRUnavailableError,
)
from prosper.domain.models import Appointment, AppointmentRequest, AppointmentStatus, Patient
from prosper.ehr.adapters.datetime_helpers import resolve_timezone

_SIGN_IN_MUTATION = """
mutation signIn($email: String!, $password: String!) {
  signIn(input: { email: $email, password: $password }) {
    token
    messages {
      field
      message
    }
  }
}
"""

_USERS_QUERY = """
query users($keywords: String!) {
  users(keywords: $keywords, should_paginate: true) {
    id
    first_name
    last_name
    dob
  }
}
"""

_APPOINTMENT_TYPES_QUERY = """
query appointmentTypes {
  appointmentTypes {
    id
    name
    available_contact_types
  }
}
"""

_CREATE_APPOINTMENT_MUTATION = """
mutation createAppointment(
  $user_id: String!,
  $datetime: String!,
  $appointment_type_id: String!,
  $contact_type: String!
) {
  createAppointment(input: {
    user_id: $user_id,
    datetime: $datetime,
    appointment_type_id: $appointment_type_id,
    contact_type: $contact_type
  }) {
    appointment {
      id
      date
      pm_status
    }
    messages {
      field
      message
    }
  }
}
"""

_UPDATE_APPOINTMENT_MUTATION = """
mutation updateAppointment($id: ID!, $pm_status: String) {
  updateAppointment(input: { id: $id, pm_status: $pm_status }) {
    appointment {
      id
      date
      pm_status
    }
    messages {
      field
      message
    }
  }
}
"""

_HEALTH_CHECK_QUERY = """
query healthCheck {
  users(keywords: "", should_paginate: true, offset: 0) {
    id
  }
}
"""


class GraphQLHealthieClient:
    """Healthie client via GraphQL API."""

    def __init__(
        self,
        api_url: str,
        *,
        email: str = "",
        password: str = "",
        token: str = "",
        clinic_timezone: str = "America/New_York",
    ) -> None:
        self._api_url = api_url
        self._email = email
        self._password = password
        self._token: str | None = token or None
        self._client = httpx.AsyncClient(timeout=30)
        self._appointment_type_id: str | None = None
        self._contact_type: str | None = None
        self._clinic_timezone = clinic_timezone
        self._clinic_tz = resolve_timezone(clinic_timezone)

    async def _ensure_authenticated(self) -> str:
        """Return a valid bearer token, logging in if necessary."""
        if self._token:
            return self._token

        if not self._email or not self._password:
            raise EHRUnavailableError("No email/password credentials configured for Healthie")

        logger.info("Authenticating with Healthie GraphQL API via signIn mutation...")
        try:
            resp = await self._client.post(
                self._api_url,
                headers={"AuthorizationSource": "Web", "Content-Type": "application/json"},
                json={
                    "query": _SIGN_IN_MUTATION,
                    "variables": {"email": self._email, "password": self._password},
                },
            )
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
        except Exception as exc:
            raise EHRUnavailableError(f"Healthie signIn request failed: {exc}") from exc

        sign_in: dict[str, Any] = data.get("data", {}).get("signIn", {})
        messages: list[dict[str, str]] = sign_in.get("messages") or []
        if messages:
            error_text = "; ".join(m.get("message", "") for m in messages)
            raise EHRUnavailableError(f"Healthie signIn failed: {error_text}")

        token: str | None = sign_in.get("token")
        if not token:
            raise EHRUnavailableError("Healthie signIn returned no token")

        self._token = token
        logger.info("Authenticated with Healthie — token cached for subsequent requests")
        return token

    def _auth_headers(self, token: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
            "AuthorizationSource": "Web",
            "Content-Type": "application/json",
        }

    async def _graphql(
        self,
        query: str,
        variables: dict[str, Any] | None = None,
        *,
        _retry_on_auth: bool = True,
    ) -> dict[str, Any]:
        """Execute an authenticated GraphQL request."""
        token = await self._ensure_authenticated()
        try:
            resp = await self._client.post(
                self._api_url,
                headers=self._auth_headers(token),
                json={"query": query, "variables": variables or {}},
            )
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if _retry_on_auth and status in {401, 403}:
                logger.warning(
                    "Healthie token rejected (status {}), retrying authentication",
                    status,
                )
                self._token = None
                return await self._graphql(query, variables, _retry_on_auth=False)
            raise EHRUnavailableError(f"Healthie GraphQL request failed: {exc}") from exc
        except Exception as exc:
            raise EHRUnavailableError(f"Healthie GraphQL request failed: {exc}") from exc

        errors: list[dict[str, str]] | None = data.get("errors")
        if errors:
            msgs = "; ".join(e.get("message", "") for e in errors)
            if _retry_on_auth and self._looks_like_auth_error(msgs):
                logger.warning("Healthie GraphQL auth error, retrying authentication")
                self._token = None
                return await self._graphql(query, variables, _retry_on_auth=False)
            raise EHRUnavailableError(f"Healthie GraphQL error: {msgs}")
        return data

    async def search_patients(self, keywords: str) -> list[Patient]:
        data: dict[str, Any] = await self._graphql(_USERS_QUERY, {"keywords": keywords})
        raw_users: list[dict[str, Any]] = data.get("data", {}).get("users") or []
        patients: list[Patient] = []
        for u in raw_users:
            dob_raw: str = u.get("dob") or ""
            try:
                dob = dt.date.fromisoformat(dob_raw) if dob_raw else None
            except ValueError:
                dob = None
            patients.append(
                Patient(
                    patient_id=str(u["id"]),
                    first_name=u.get("first_name", ""),
                    last_name=u.get("last_name", ""),
                    date_of_birth=dob,
                )
            )
        return patients

    async def create_appointment(self, request: AppointmentRequest) -> Appointment:
        appt_type_id, contact_type = await self._ensure_appointment_type()
        clinic_dt = dt.datetime.combine(request.date, request.time, tzinfo=self._clinic_tz)
        datetime_str = clinic_dt.strftime("%Y-%m-%d %H:%M:%S %z")

        data: dict[str, Any] = await self._graphql(
            _CREATE_APPOINTMENT_MUTATION,
            {
                "user_id": request.patient_id,
                "datetime": datetime_str,
                "appointment_type_id": appt_type_id,
                "contact_type": contact_type,
            },
        )

        result: dict[str, Any] = data.get("data", {}).get("createAppointment", {})
        messages: list[dict[str, str]] = result.get("messages") or []
        if messages:
            error_text = "; ".join(m.get("message", "") for m in messages)
            raise AppointmentCreationError(reason=error_text, patient_id=request.patient_id)

        appointment_data: dict[str, Any] = result.get("appointment") or {}
        appointment_id: str = str(appointment_data.get("id", "unknown"))

        return Appointment(
            appointment_id=appointment_id,
            patient_id=request.patient_id,
            date=request.date,
            time=request.time,
            status=AppointmentStatus.SCHEDULED,
        )

    async def cancel_appointment(self, appointment_id: str) -> Appointment:
        data: dict[str, Any] = await self._graphql(
            _UPDATE_APPOINTMENT_MUTATION,
            {"id": appointment_id, "pm_status": "Cancelled"},
        )

        result: dict[str, Any] = data.get("data", {}).get("updateAppointment", {})
        messages: list[dict[str, str]] = result.get("messages") or []
        if messages:
            error_text = "; ".join(m.get("message", "") for m in messages)
            raise AppointmentCancellationError(reason=error_text, appointment_id=appointment_id)

        appointment_data: dict[str, Any] = result.get("appointment") or {}
        raw_date: str = appointment_data.get("date", "")
        date_val: dt.date | None = None
        time_val: dt.time | None = None
        try:
            aware_dt = dt.datetime.strptime(raw_date, "%Y-%m-%d %H:%M:%S %z")
            local_dt = aware_dt.astimezone(self._clinic_tz)
            date_val = local_dt.date()
            time_val = local_dt.time().replace(second=0, microsecond=0)
        except ValueError:
            pass

        return Appointment(
            appointment_id=str(appointment_data.get("id", appointment_id)),
            patient_id="",
            date=date_val,
            time=time_val,
            status=AppointmentStatus.CANCELLED,
        )

    async def health_check(self) -> bool:
        try:
            await self._graphql(_HEALTH_CHECK_QUERY)
            return True
        except Exception as exc:
            logger.warning("Healthie GraphQL health check failed: {}", exc)
            return False

    async def close(self) -> None:
        await self._client.aclose()
        logger.info("Healthie GraphQL client closed")

    def _looks_like_auth_error(self, message: str) -> bool:
        msg = message.lower()
        return any(
            key in msg
            for key in (
                "unauthorized",
                "not authorized",
                "forbidden",
                "expired",
                "invalid token",
                "jwt",
                "authentication",
            )
        )

    async def _ensure_appointment_type(self) -> tuple[str, str]:
        """Fetch and cache the first available appointment type + contact type."""
        if self._appointment_type_id and self._contact_type:
            return self._appointment_type_id, self._contact_type

        logger.info("Fetching appointment types from Healthie...")
        data: dict[str, Any] = await self._graphql(_APPOINTMENT_TYPES_QUERY)
        types: list[dict[str, Any]] = data.get("data", {}).get("appointmentTypes") or []

        if not types:
            raise AppointmentCreationError(reason="No appointment types configured in Healthie")

        appt_type: dict[str, Any] = types[0]
        self._appointment_type_id = str(appt_type["id"])

        contact_types: list[str] = appt_type.get("available_contact_types") or []
        self._contact_type = contact_types[0] if contact_types else "Healthie Video Call"

        logger.info(
            "Using appointment type: id={}, contact_type={}",
            self._appointment_type_id,
            self._contact_type,
        )
        return self._appointment_type_id, self._contact_type
