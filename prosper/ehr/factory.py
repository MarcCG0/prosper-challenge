from typing import Callable

from loguru import logger

from prosper.config import AppConfig, EHRAdapter
from prosper.ehr.adapters.graphql import GraphQLHealthieClient
from prosper.ehr.adapters.playwright import PlaywrightHealthieClient
from prosper.ehr.service import EHRService


def _build_graphql(config: AppConfig) -> EHRService:
    client = GraphQLHealthieClient(
        api_url=config.healthie.api_url,
        email=config.healthie.email,
        password=config.healthie.password,
        clinic_timezone=config.clinic_timezone,
    )
    return EHRService(client)


def _build_playwright(config: AppConfig) -> EHRService:
    client = PlaywrightHealthieClient(
        email=config.healthie.email,
        password=config.healthie.password,
        base_url=config.healthie.base_url,
        headless=config.healthie.headless,
    )
    return EHRService(client)


_BUILDERS: dict[EHRAdapter, Callable[[AppConfig], EHRService]] = {
    EHRAdapter.GRAPHQL: _build_graphql,
    EHRAdapter.PLAYWRIGHT: _build_playwright,
}


def build_ehr_service(config: AppConfig) -> EHRService:
    """Build the appropriate EHR service based on config."""
    adapter = config.healthie.adapter
    logger.info("Building EHR service with adapter: {}", adapter.value)
    return _BUILDERS[adapter](config)
