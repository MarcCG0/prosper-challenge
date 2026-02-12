import pytest

from prosper.ehr.adapters.fake import FakeEHRClient
from prosper.ehr.service import EHRService


@pytest.fixture
def fake_client() -> FakeEHRClient:
    return FakeEHRClient()


@pytest.fixture
def service(fake_client: FakeEHRClient) -> EHRService:
    return EHRService(client=fake_client)
