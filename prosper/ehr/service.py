import datetime as dt

from loguru import logger

from prosper.domain.exceptions import (
    AppointmentCancellationError,
    AppointmentCreationError,
    EHRUnavailableError,
)
from prosper.domain.models import Appointment, AppointmentRequest, Patient
from prosper.ehr.ports import AbstractEHRService, EHRClientProtocol


class EHRService(AbstractEHRService):
    """EHR service that delegates to an EHRClientProtocol and adds business rules."""

    def __init__(self, client: EHRClientProtocol) -> None:
        self._client = client

    async def find_patient(self, name: str, date_of_birth: dt.date | None = None) -> list[Patient]:
        """Search for patients by name, then filter by DOB."""
        logger.info("Searching for patient with provided identity details")

        try:
            patients = await self._client.search_patients(name)
        except EHRUnavailableError:
            raise
        except Exception as exc:
            raise EHRUnavailableError(f"Patient search failed: {exc}") from exc

        if date_of_birth:
            patients = [p for p in patients if p.date_of_birth == date_of_birth]

        if patients:
            logger.info("Found {} patient(s) matching criteria", len(patients))
        else:
            logger.info("No patients found for name={}, dob={}", name, date_of_birth)

        return patients

    async def create_appointment(self, request: AppointmentRequest) -> Appointment:
        """Create the appointment via the underlying client."""
        logger.info(
            "Creating appointment request: date={}, time={}",
            request.date,
            request.time,
        )

        try:
            appointment = await self._client.create_appointment(request)
        except (AppointmentCreationError, EHRUnavailableError):
            raise
        except Exception as exc:
            raise AppointmentCreationError(reason=str(exc), patient_id=request.patient_id) from exc

        logger.info("Appointment created: id={}", appointment.appointment_id)
        return appointment

    async def cancel_appointment(self, appointment_id: str) -> Appointment:
        """Cancel an appointment."""
        logger.info("Cancelling appointment")

        try:
            appointment = await self._client.cancel_appointment(appointment_id)
        except (AppointmentCancellationError, EHRUnavailableError):
            raise
        except Exception as exc:
            raise AppointmentCancellationError(
                reason=str(exc), appointment_id=appointment_id
            ) from exc

        logger.info("Appointment cancelled: id={}", appointment.appointment_id)
        return appointment

    async def health_check(self) -> bool:
        return await self._client.health_check()

    async def close(self) -> None:
        await self._client.close()
