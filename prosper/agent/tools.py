import datetime as dt
from typing import Any

from loguru import logger
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.services.llm_service import FunctionCallParams, LLMService

from prosper.agent.fillers import ToolCall
from prosper.domain.exceptions import EHRError
from prosper.domain.models import AppointmentRequest
from prosper.ehr.adapters.datetime_helpers import resolve_timezone
from prosper.ehr.ports import AbstractEHRService

FIND_PATIENT_SCHEMA = FunctionSchema(
    name=ToolCall.FIND_PATIENT.value,
    description=(
        "Search for a patient in the clinic's system by their full name and "
        "date of birth. Call this after collecting the patient's identity."
    ),
    properties={
        "name": {
            "type": "string",
            "description": "The patient's full name (first and last name).",
        },
        "date_of_birth": {
            "type": "string",
            "description": (
                "The patient's date of birth in ISO 8601 format (YYYY-MM-DD). "
                "Convert any natural language date to this format."
            ),
        },
    },
    required=["name", "date_of_birth"],
)

CREATE_APPOINTMENT_SCHEMA = FunctionSchema(
    name=ToolCall.CREATE_APPOINTMENT.value,
    description=(
        "Create an appointment for a patient. ONLY call this after the patient "
        "has explicitly confirmed the appointment details."
    ),
    properties={
        "patient_id": {
            "type": "string",
            "description": "The patient's unique ID from the find_patient result.",
        },
        "date": {
            "type": "string",
            "description": (
                "The appointment date in ISO 8601 format (YYYY-MM-DD). "
                "Convert any natural language date to this format."
            ),
        },
        "time": {
            "type": "string",
            "description": (
                "The appointment time in 24-hour format (HH:MM). "
                "Convert any natural language time to this format."
            ),
        },
    },
    required=["patient_id", "date", "time"],
)


CANCEL_APPOINTMENT_SCHEMA = FunctionSchema(
    name=ToolCall.CANCEL_APPOINTMENT.value,
    description=(
        "Cancel an existing appointment. ONLY call this after the patient "
        "has explicitly confirmed they want to cancel."
    ),
    properties={
        "appointment_id": {
            "type": "string",
            "description": "The appointment ID to cancel.",
        },
    },
    required=["appointment_id"],
)


def get_tools_schema() -> ToolsSchema:
    """Return the ToolsSchema with all available tools."""
    return ToolsSchema(
        standard_tools=[
            FIND_PATIENT_SCHEMA,
            CREATE_APPOINTMENT_SCHEMA,
            CANCEL_APPOINTMENT_SCHEMA,
        ]
    )


def _parse_iso_date(value: object, field_name: str) -> tuple[dt.date | None, str | None]:
    """Parse an ISO 8601 date string. Returns ``(date, None)`` or ``(None, error_msg)``."""
    if not isinstance(value, str):
        return (
            None,
            f"Invalid date format for '{field_name}': must be a string in YYYY-MM-DD format.",
        )
    try:
        return dt.date.fromisoformat(value), None
    except (ValueError, TypeError):
        return None, f"Invalid date format for '{field_name}': '{value}'. Expected YYYY-MM-DD."


def _parse_iso_time(value: object, field_name: str) -> tuple[dt.time | None, str | None]:
    """Parse an ISO 8601 time string. Returns ``(time, None)`` or ``(None, error_msg)``."""
    if not isinstance(value, str):
        return None, f"Invalid time format for '{field_name}': must be a string in HH:MM format."
    try:
        return dt.time.fromisoformat(value), None
    except (ValueError, TypeError):
        return None, f"Invalid time format for '{field_name}': '{value}'. Expected HH:MM."


class ToolHandlers:
    """Encapsulates all tool handler methods for the voice agent."""

    def __init__(
        self,
        ehr_service: AbstractEHRService,
        clinic_timezone: str = "America/New_York",
    ) -> None:
        self._ehr = ehr_service
        self._clinic_tz = resolve_timezone(clinic_timezone)

    async def handle_find_patient(self, params: FunctionCallParams) -> None:
        name: str = params.arguments.get("name", "")
        date_of_birth_str: str = params.arguments.get("date_of_birth", "")

        if not name or not date_of_birth_str:
            await params.result_callback(
                {
                    "found": False,
                    "error": True,
                    "message": "Both 'name' and 'date_of_birth' are required.",
                }
            )
            return

        date_of_birth, err = _parse_iso_date(date_of_birth_str, "date_of_birth")
        if err or date_of_birth is None:
            await params.result_callback(
                {
                    "found": False,
                    "error": True,
                    "message": err or "Invalid date.",
                }
            )
            return

        logger.debug("Tool call: find_patient")

        try:
            patients = await self._ehr.find_patient(name, date_of_birth)

            if not patients:
                result: dict[str, Any] = {
                    "found": False,
                    "message": f"No patient found with name '{name}' and date of birth '{date_of_birth}'.",
                }
            elif len(patients) == 1:
                p = patients[0]
                result = {
                    "found": True,
                    "patient_id": p.patient_id,
                    "name": p.full_name,
                    "date_of_birth": p.date_of_birth.isoformat() if p.date_of_birth else "",
                }
            else:
                result = {
                    "found": True,
                    "multiple_matches": True,
                    "patients": [
                        {
                            "patient_id": p.patient_id,
                            "name": p.full_name,
                            "date_of_birth": p.date_of_birth.isoformat() if p.date_of_birth else "",
                        }
                        for p in patients
                    ],
                    "message": "Multiple patients found. Please ask the caller to confirm which one.",
                }

            await params.result_callback(result)

        except EHRError as exc:
            await params.result_callback(
                {
                    "found": False,
                    "error": True,
                    "message": str(exc),
                }
            )
        except Exception as exc:
            logger.exception("Unexpected error in find_patient")
            await params.result_callback(
                {
                    "found": False,
                    "error": True,
                    "message": "An unexpected error occurred while searching for the patient.",
                }
            )

    async def handle_cancel_appointment(self, params: FunctionCallParams) -> None:
        appointment_id: str = params.arguments.get("appointment_id", "")

        if not appointment_id:
            await params.result_callback(
                {
                    "success": False,
                    "error": True,
                    "message": "'appointment_id' is required.",
                }
            )
            return

        logger.debug("Tool call: cancel_appointment")

        try:
            appointment = await self._ehr.cancel_appointment(appointment_id)

            await params.result_callback(
                {
                    "success": True,
                    "appointment_id": appointment.appointment_id,
                    "message": "Appointment cancelled successfully.",
                }
            )

        except EHRError as exc:
            await params.result_callback(
                {
                    "success": False,
                    "error": True,
                    "message": str(exc),
                }
            )
        except Exception as exc:
            logger.exception("Unexpected error in cancel_appointment")
            await params.result_callback(
                {
                    "success": False,
                    "error": True,
                    "message": "An unexpected error occurred while cancelling the appointment.",
                }
            )

    async def handle_create_appointment(self, params: FunctionCallParams) -> None:
        patient_id: str = params.arguments.get("patient_id", "")
        date_str: str = params.arguments.get("date", "")
        time_str: str = params.arguments.get("time", "")

        if not patient_id or not date_str or not time_str:
            await params.result_callback(
                {
                    "success": False,
                    "error": True,
                    "message": "'patient_id', 'date', and 'time' are all required.",
                }
            )
            return

        date_val, date_err = _parse_iso_date(date_str, "date")
        time_val, time_err = _parse_iso_time(time_str, "time")
        err = date_err or time_err
        if err or date_val is None or time_val is None:
            await params.result_callback(
                {
                    "success": False,
                    "error": True,
                    "message": err or "Invalid date/time format.",
                }
            )
            return

        now = dt.datetime.now(self._clinic_tz)
        appointment_dt = dt.datetime.combine(date_val, time_val, tzinfo=self._clinic_tz)
        if appointment_dt < now:
            await params.result_callback(
                {
                    "success": False,
                    "error": True,
                    "message": "Appointment time is in the past. Please provide a future date and time.",
                }
            )
            return

        logger.debug("Tool call: create_appointment")

        try:
            request = AppointmentRequest(
                patient_id=patient_id,
                date=date_val,
                time=time_val,
            )
            appointment = await self._ehr.create_appointment(request)

            await params.result_callback(
                {
                    "success": True,
                    "appointment_id": appointment.appointment_id,
                    "patient_id": appointment.patient_id,
                    "date": appointment.date.isoformat() if appointment.date else "",
                    "time": appointment.time.strftime("%H:%M") if appointment.time else "",
                    "status": appointment.status.value,
                    "message": "Appointment created successfully.",
                }
            )

        except EHRError as exc:
            await params.result_callback(
                {
                    "success": False,
                    "error": True,
                    "message": str(exc),
                }
            )
        except Exception as exc:
            logger.exception("Unexpected error in create_appointment")
            await params.result_callback(
                {
                    "success": False,
                    "error": True,
                    "message": "An unexpected error occurred while creating the appointment.",
                }
            )


def register_tools(
    llm: LLMService,
    ehr_service: AbstractEHRService,
    *,
    clinic_timezone: str = "America/New_York",
) -> None:
    """Register all tool handlers on the LLM service."""
    handlers = ToolHandlers(ehr_service, clinic_timezone=clinic_timezone)
    llm.register_function(ToolCall.FIND_PATIENT.value, handlers.handle_find_patient)  # type: ignore[reportUnknownMemberType]
    llm.register_function(ToolCall.CREATE_APPOINTMENT.value, handlers.handle_create_appointment)  # type: ignore[reportUnknownMemberType]
    llm.register_function(ToolCall.CANCEL_APPOINTMENT.value, handlers.handle_cancel_appointment)  # type: ignore[reportUnknownMemberType]
