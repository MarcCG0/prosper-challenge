"""Healthie EHR integration module.

This module provides functions to interact with Healthie for patient management
and appointment scheduling.
"""

import os

from playwright.async_api import async_playwright, Browser, Page
from loguru import logger

_browser: Browser | None = None
_page: Page | None = None


async def login_to_healthie() -> Page:
    """Log into Healthie and return an authenticated page instance.

    This function handles the login process using credentials from environment
    variables. The browser and page instances are stored for reuse by other
    functions in this module.

    Returns:
        Page: An authenticated Playwright Page instance ready for use.

    Raises:
        ValueError: If required environment variables are missing.
        Exception: If login fails for any reason.
    """
    global _browser, _page

    email = os.environ.get("HEALTHIE_EMAIL")
    password = os.environ.get("HEALTHIE_PASSWORD")

    if not email or not password:
        raise ValueError("HEALTHIE_EMAIL and HEALTHIE_PASSWORD must be set in environment variables")

    if _page is not None:
        logger.info("Using existing Healthie session")
        return _page

    logger.info("Logging into Healthie...")
    playwright = await async_playwright().start()
    _browser = await playwright.chromium.launch(headless=True)
    _page = await _browser.new_page()

    await _page.goto("https://secure.gethealthie.com/users/sign_in", wait_until="domcontentloaded")
    
    # Wait for the email input to be visible
    email_input = _page.locator('input[name="email"]')
    await email_input.wait_for(state="visible", timeout=30000)
    await email_input.fill(email)
    
    # Wait for password input
    password_input = _page.locator('input[name="password"]')
    await password_input.wait_for(state="visible", timeout=30000)
    await password_input.fill(password)
    
    # Find and click the Log In button
    submit_button = _page.locator('button:has-text("Log In")')
    await submit_button.wait_for(state="visible", timeout=30000)
    await submit_button.click()
    
    # Wait for navigation after login
    await _page.wait_for_timeout(3000)
    
    # Check if we've navigated away from the sign-in page
    current_url = _page.url
    if "sign_in" in current_url:
        raise Exception("Login may have failed - still on sign-in page")

    logger.info("Successfully logged into Healthie")
    return _page


async def find_patient(name: str, date_of_birth: str) -> dict | None:
    """Find a patient in Healthie by name and date of birth.

    Args:
        name: The patient's full name.
        date_of_birth: The patient's date of birth in a format that Healthie accepts.

    Returns:
        dict | None: A dictionary containing patient information if found,
            including at least a 'patient_id' field. Returns None if the patient
            is not found or if an error occurs.

    Example return value:
        {
            "patient_id": "12345",
            "name": "John Doe",
            "date_of_birth": "1990-01-15",
            ...
        }
    """
    # TODO: Implement patient search functionality using Playwright
    # 1. Ensure you're logged in by calling login_to_healthie()
    # 2. Enter the patient's name and date of birth into the search field
    # 3. Submit the search
    # 4. Parse the results and return patient information
    # 5. Handle cases where the patient is not found
    pass


async def create_appointment(patient_id: str, date: str, time: str) -> dict | None:
    """Create an appointment in Healthie for the specified patient.

    Args:
        patient_id: The unique identifier for the patient in Healthie.
        date: The desired appointment date in a format that Healthie accepts.
        time: The desired appointment time in a format that Healthie accepts.

    Returns:
        dict | None: A dictionary containing appointment information if created
            successfully, including at least an 'appointment_id' field.
            Returns None if appointment creation fails.

    Example return value:
        {
            "appointment_id": "67890",
            "patient_id": "12345",
            "date": "2026-02-15",
            "time": "10:00 AM",
            ...
        }
    """
    # TODO: Implement appointment creation functionality using Playwright
    # 1. Ensure you're logged in by calling login_to_healthie()
    # 2. Navigate to the appointment creation page for the patient
    # 3. Fill in the date and time fields
    # 4. Submit the appointment creation form
    # 5. Verify the appointment was created successfully
    # 6. Return appointment information
    # 7. Handle errors (e.g., time slot unavailable, invalid date/time)
    pass
