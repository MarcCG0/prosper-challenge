import datetime as dt

from prosper.domain.models import Appointment, AppointmentRequest, AppointmentStatus, Patient


class FakeEHRClient:
    """In-memory test double for the EHRClientProtocol protocol.

    Pre-load ``patients`` to control what the client returns.  Set
    ``search_error``, ``create_error``, etc. to make the corresponding
    method raise on the next call.

    After calls, inspect ``created`` and ``cancelled`` to verify what was
    passed to the client.
    """

    def __init__(self) -> None:
        self.patients: list[Patient] = []
        self.created: list[AppointmentRequest] = []
        self.cancelled: list[tuple[str, dt.date, dt.time]] = []
        self.closed: bool = False

        self.search_error: Exception | None = None
        self.create_error: Exception | None = None
        self.cancel_error: Exception | None = None

    async def search_patients(self, keywords: str) -> list[Patient]:
        if self.search_error:
            raise self.search_error
        return [p for p in self.patients if keywords.lower() in p.first_name.lower()]

    async def create_appointment(self, request: AppointmentRequest) -> Appointment:
        if self.create_error:
            raise self.create_error
        self.created.append(request)
        return Appointment(
            appointment_id="new-1",
            patient_id=request.patient_id,
            date=request.date,
            time=request.time,
            status=AppointmentStatus.SCHEDULED,
        )

    async def cancel_appointment(
        self, patient_id: str, date: dt.date, time: dt.time
    ) -> Appointment:
        if self.cancel_error:
            raise self.cancel_error
        self.cancelled.append((patient_id, date, time))
        return Appointment(
            appointment_id="cancelled-1",
            patient_id=patient_id,
            date=date,
            time=time,
            status=AppointmentStatus.CANCELLED,
        )

    async def health_check(self) -> bool:
        return True

    async def close(self) -> None:
        self.closed = True
