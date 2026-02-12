import datetime as dt
from enum import Enum

from pydantic import BaseModel, ConfigDict


class AppointmentStatus(str, Enum):
    """Possible states of an appointment in the EHR system."""

    SCHEDULED = "scheduled"
    CANCELLED = "cancelled"


class Patient(BaseModel):
    """A patient record from the EHR system."""

    model_config = ConfigDict(frozen=True)

    patient_id: str
    first_name: str
    last_name: str
    date_of_birth: dt.date | None = None

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"


class AppointmentRequest(BaseModel):
    """A request to create an appointment."""

    model_config = ConfigDict(frozen=True)

    patient_id: str
    date: dt.date
    time: dt.time


class Appointment(BaseModel):
    """A confirmed appointment in the EHR system."""

    model_config = ConfigDict(frozen=True)

    appointment_id: str
    patient_id: str
    date: dt.date | None = None
    time: dt.time | None = None
    status: AppointmentStatus = AppointmentStatus.SCHEDULED
