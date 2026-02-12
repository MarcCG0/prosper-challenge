class EHRError(Exception):
    """Base exception for all EHR-related errors."""


class EHRUnavailableError(EHRError):
    """Raised when the EHR system is unreachable or not responding."""


class AppointmentCreationError(EHRError):
    """Raised when an appointment cannot be created."""

    def __init__(self, reason: str, patient_id: str | None = None) -> None:
        self.reason = reason
        self.patient_id = patient_id
        super().__init__(f"Failed to create appointment: {reason}")


class AppointmentCancellationError(EHRError):
    """Raised when an appointment cannot be cancelled."""

    def __init__(self, reason: str, appointment_id: str | None = None) -> None:
        self.reason = reason
        self.appointment_id = appointment_id
        super().__init__(f"Failed to cancel appointment: {reason}")
