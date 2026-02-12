import datetime as dt
from abc import ABC, abstractmethod
from typing import Protocol

from prosper.domain.models import Appointment, AppointmentRequest, Patient


class AbstractEHRService(ABC):
    """Abstract base class for Electronic Health Record operations."""

    @abstractmethod
    async def find_patient(self, name: str, date_of_birth: dt.date | None = None) -> list[Patient]:
        """Search for patients by name and date of birth.

        Args:
            name: Patient's full name (first and last).
            date_of_birth: Patient's DOB, or None to skip DOB filtering.

        Returns:
            List of matching patients. Empty list if none found.

        Raises:
            EHRUnavailableError: If the EHR system is unreachable.
        """

    @abstractmethod
    async def create_appointment(self, request: AppointmentRequest) -> Appointment:
        """Create an appointment for a patient.

        Args:
            request: The appointment details.

        Returns:
            The created appointment with its assigned ID.

        Raises:
            AppointmentCreationError: If the appointment cannot be created.
            EHRUnavailableError: If the EHR system is unreachable.
        """

    @abstractmethod
    async def cancel_appointment(self, appointment_id: str) -> Appointment:
        """Cancel an existing appointment.

        Args:
            appointment_id: The appointment's unique ID.

        Returns:
            The cancelled appointment.

        Raises:
            AppointmentCancellationError: If the appointment cannot be cancelled.
            EHRUnavailableError: If the EHR system is unreachable.
        """

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if the EHR system is reachable and responding.

        Returns:
            True if the system is healthy, False otherwise.
        """

    @abstractmethod
    async def close(self) -> None:
        """Release resources held by this service."""


class EHRClientProtocol(Protocol):
    """Low-level interface for EHR communication."""

    async def search_patients(self, keywords: str) -> list[Patient]:
        """Search for patients by keyword."""
        ...

    async def create_appointment(self, request: AppointmentRequest) -> Appointment:
        """Create an appointment."""
        ...

    async def cancel_appointment(self, appointment_id: str) -> Appointment:
        """Cancel an appointment."""
        ...

    async def health_check(self) -> bool:
        """Check if the EHR system is reachable."""
        ...

    async def close(self) -> None:
        """Release resources."""
        ...
