import re

from loguru import logger
from playwright.async_api import Browser, Page, async_playwright

from prosper.domain.exceptions import (
    AppointmentCancellationError,
    AppointmentCreationError,
    EHRUnavailableError,
)
from prosper.domain.models import Appointment, AppointmentRequest, AppointmentStatus, Patient
from prosper.ehr.adapters.datetime_helpers import date_to_us_long, time_to_12h
from prosper.ehr.adapters.parsing_helpers import extract_id_from_url, parse_name_dob

# Timeout constants (milliseconds unless noted)
_LOGIN_TIMEOUT_MS = 30_000
_ELEMENT_TIMEOUT_MS = 15_000
_FORM_FIELD_TIMEOUT_MS = 5_000
_SUBMIT_TIMEOUT_MS = 10_000
_POST_LOGIN_DELAY_MS = 3_000
_POST_NAV_DELAY_MS = 2_000
_MODAL_OPEN_DELAY_MS = 1_500
_SELECT_OPEN_DELAY_MS = 500
_SELECT_ARROW_DELAY_MS = 150
_DATEPICKER_CLOSE_DELAY_MS = 300
_POLL_INTERVAL_MS = 500
_MAX_POLL_ATTEMPTS = 20


# Healthie DOM selectors
_SEL_EMAIL = 'input[name="email"]'
_SEL_PASSWORD = 'input[name="password"]'
_SEL_LOGIN_BTN = 'button:has-text("Log In")'
_SEL_SEARCH = 'input[name="keywords"]'
_SEL_PROFILE_LINK = 'a[href*="/users/"]:has-text("View Profile")'
_SEL_ADD_APPT_BTN = 'button[data-testid="add-appointment-button"]'
_SEL_APPT_MODAL = '[data-testid="appointment-form-modal"]'
_SEL_DATE = 'input[name="date"]'
_SEL_TIME = 'input[name="time"]'
_SEL_MODAL_SUBMIT = '[data-testid="appointment-form-modal"] button[data-testid="primaryButton"]'
_SEL_MODAL_WARNING = '[class*="warning"], [class*="alert"], [class*="error"]'

# Appointment detail modal selectors (used by cancel)
_SEL_APPT_PREVIEW_ITEM = 'li[data-testid="appointment-preview-item"]'
_SEL_APPT_DETAIL_POPUP = '[data-testid="appointment-detail-popup"]'
_SEL_APPT_DETAIL_CLOSE = '[data-testid="asideModalCloseButton"]'
_SEL_APPT_STATUS = '[data-testid="appointment-status"]'


class PlaywrightHealthieClient:
    """Healthie client via Playwright browser automation."""

    def __init__(
        self,
        email: str,
        password: str,
        base_url: str,
        headless: bool = True,
    ) -> None:
        self._email = email
        self._password = password
        self._base_url = base_url
        self._headless = headless
        self._playwright = None
        self._browser: Browser | None = None
        self._page: Page | None = None

    async def _ensure_logged_in(self) -> Page:
        """Ensure we have an authenticated Healthie session."""
        if self._page is not None:
            try:
                if "sign_in" in self._page.url:
                    logger.warning("Healthie session expired — re-authenticating")
                    await self.close()
                else:
                    logger.debug("Reusing existing Healthie session")
                    return self._page
            except Exception:
                logger.warning("Healthie session check failed — re-authenticating")
                await self.close()

        if not self._email or not self._password:
            raise EHRUnavailableError("HEALTHIE_EMAIL and HEALTHIE_PASSWORD must be set")

        logger.info("Logging into Healthie...")
        try:
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(headless=self._headless)
            self._page = await self._browser.new_page(viewport={"width": 1440, "height": 900})

            await self._page.route("**/use.fontawesome.com/**", lambda route: route.abort())

            await self._page.goto(
                f"{self._base_url}/users/sign_in",
                wait_until="commit",
            )

            email_input = self._page.locator(_SEL_EMAIL)
            await email_input.wait_for(state="visible", timeout=_LOGIN_TIMEOUT_MS)
            await email_input.fill(self._email)

            password_input = self._page.locator(_SEL_PASSWORD)
            await password_input.wait_for(state="visible", timeout=_LOGIN_TIMEOUT_MS)
            await password_input.fill(self._password)

            submit_button = self._page.locator(_SEL_LOGIN_BTN)
            await submit_button.wait_for(state="visible", timeout=_LOGIN_TIMEOUT_MS)
            await submit_button.click()

            await self._page.wait_for_timeout(_POST_LOGIN_DELAY_MS)

            if "sign_in" in self._page.url:
                self._page = None
                raise EHRUnavailableError("Healthie login failed — still on sign-in page")

            logger.info("Successfully logged into Healthie")
            return self._page

        except EHRUnavailableError:
            raise
        except Exception as exc:
            await self.close()
            raise EHRUnavailableError(f"Healthie login error: {exc}") from exc

    async def search_patients(self, keywords: str) -> list[Patient]:
        """Search for patients via the Healthie UI."""
        page = await self._ensure_logged_in()

        try:
            await page.goto(
                f"{self._base_url}/all_patients",
                wait_until="commit",
            )

            search_input = page.locator(_SEL_SEARCH)
            await search_input.wait_for(state="visible", timeout=_ELEMENT_TIMEOUT_MS)
            await search_input.fill(keywords)
            await page.wait_for_timeout(_POST_NAV_DELAY_MS)

            return await self._parse_patient_results(page)

        except EHRUnavailableError:
            raise
        except Exception as exc:
            logger.error("Error searching for patient: {}", exc)
            raise EHRUnavailableError(f"Patient search failed: {exc}") from exc

    async def create_appointment(self, request: AppointmentRequest) -> Appointment:
        """Create an appointment via the Healthie UI."""
        page = await self._ensure_logged_in()

        try:
            await page.goto(
                f"{self._base_url}/users/{request.patient_id}",
                wait_until="commit",
            )
            await page.wait_for_timeout(_POST_NAV_DELAY_MS)

            add_btn = page.locator(_SEL_ADD_APPT_BTN)
            await add_btn.wait_for(state="visible", timeout=_ELEMENT_TIMEOUT_MS)
            await add_btn.click()
            await page.wait_for_timeout(_MODAL_OPEN_DELAY_MS)

            await self._select_react_option(page, "appointment_type_id", option_index=0)
            await self._select_react_option(page, "contact_type", option_index=0)

            date_input = page.locator(_SEL_DATE)
            await date_input.wait_for(state="visible", timeout=_FORM_FIELD_TIMEOUT_MS)
            await date_input.click(click_count=3)
            us_date = date_to_us_long(request.date)
            await date_input.fill(us_date)
            await page.wait_for_timeout(_SELECT_OPEN_DELAY_MS)
            await date_input.press("Escape")
            await page.wait_for_timeout(_DATEPICKER_CLOSE_DELAY_MS)

            time_input = page.locator(_SEL_TIME)
            await time_input.wait_for(state="visible", timeout=_FORM_FIELD_TIMEOUT_MS)
            await time_input.click()
            await page.wait_for_timeout(_SELECT_OPEN_DELAY_MS)

            time_12h = time_to_12h(request.time)
            time_option = page.locator(
                f'{_SEL_APPT_MODAL} li[class*="time-list"]:text-is("{time_12h}")'
            )
            if await time_option.count() > 0:
                await time_option.click()
            else:
                await time_input.click(click_count=3)
                await page.keyboard.press("Backspace")
                await time_input.press_sequentially(time_12h, delay=30)
            await page.wait_for_timeout(_DATEPICKER_CLOSE_DELAY_MS)

            submit_btn = page.locator(_SEL_MODAL_SUBMIT)
            await submit_btn.wait_for(state="visible", timeout=_SUBMIT_TIMEOUT_MS)
            await submit_btn.click()

            modal = page.locator(_SEL_APPT_MODAL)
            for _ in range(_MAX_POLL_ATTEMPTS):
                await page.wait_for_timeout(_POLL_INTERVAL_MS)
                if await modal.count() == 0:
                    break
                warning = modal.locator(_SEL_MODAL_WARNING).first
                if await warning.count() > 0:
                    warning_text = (await warning.inner_text()).strip()
                    raise AppointmentCreationError(
                        reason=warning_text, patient_id=request.patient_id
                    )
            else:
                raise AppointmentCreationError(
                    reason="Appointment form did not close after submit",
                    patient_id=request.patient_id,
                )

            appointment_id = "unknown"
            current_url = page.url
            url_id_match = re.search(r"/appointments?/(\d+)", current_url)
            if url_id_match:
                appointment_id = url_id_match.group(1)

            return Appointment(
                appointment_id=appointment_id,
                patient_id=request.patient_id,
                date=request.date,
                time=request.time,
                status=AppointmentStatus.SCHEDULED,
            )

        except AppointmentCreationError:
            raise
        except Exception as exc:
            logger.error("Error creating appointment: {}", exc)
            raise AppointmentCreationError(reason=str(exc), patient_id=request.patient_id) from exc

    async def cancel_appointment(self, appointment_id: str) -> Appointment:
        """Cancel an appointment via the Healthie UI.

        Opens the appointment detail modal (by finding the appointment on the
        patient profile or navigating directly), sets the status dropdown to
        "Cancelled", and clicks "Save changes".
        """
        page = await self._ensure_logged_in()

        try:
            # If we're already on a patient profile, try to find the appointment
            # in the current list; otherwise we need to open the modal some other way.
            # The most reliable approach: click through appointment list items on
            # the current page until we find the one with the matching ID.
            modal_opened = await self._open_appointment_modal(page, appointment_id)
            if not modal_opened:
                raise AppointmentCancellationError(
                    reason="Could not find appointment in the UI",
                    appointment_id=appointment_id,
                )

            # Set status to "Cancelled" via the react-select dropdown.
            modal = page.locator(_SEL_APPT_DETAIL_POPUP)
            status_section = modal.locator(_SEL_APPT_STATUS)
            await status_section.wait_for(state="visible", timeout=_ELEMENT_TIMEOUT_MS)

            # Open the status dropdown via JS (the input is inside the
            # modal's scroll container and Playwright can't click it normally).
            await page.evaluate("""() => {
                const input = document.querySelector('#pm_status');
                input.focus();
                input.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
            }""")
            await page.wait_for_timeout(_SELECT_OPEN_DELAY_MS)

            # Select "Cancelled" — use keyboard to avoid viewport issues
            # with the dropdown menu as well.  "Cancelled" is the 2nd option
            # (Occurred, Cancelled, Late Cancellation, No-Show, Re-Scheduled).
            status_input = status_section.locator("input#pm_status")
            await status_input.press("ArrowDown")
            await page.wait_for_timeout(_SELECT_ARROW_DELAY_MS)
            await status_input.press("ArrowDown")
            await page.wait_for_timeout(_SELECT_ARROW_DELAY_MS)
            await status_input.press("Enter")
            await page.wait_for_timeout(_SELECT_OPEN_DELAY_MS)

            # Click "Save changes" via JS (same viewport issue).
            await page.evaluate("""() => {
                const popup = document.querySelector('[data-testid="appointment-detail-popup"]');
                const btn = popup.querySelector('[data-testid="primaryButton"]');
                btn.click();
            }""")
            await page.wait_for_timeout(_SELECT_OPEN_DELAY_MS)

            # Wait for the modal to close or show a success indication.
            for _ in range(_MAX_POLL_ATTEMPTS):
                await page.wait_for_timeout(_POLL_INTERVAL_MS)
                if await modal.count() == 0:
                    break
            else:
                # Modal didn't close — check if save succeeded anyway
                logger.warning(
                    "Appointment detail modal did not close after saving, "
                    "but the status change may have succeeded"
                )

            logger.info("Appointment {} cancelled via UI", appointment_id)
            return Appointment(
                appointment_id=appointment_id,
                patient_id="",
                status=AppointmentStatus.CANCELLED,
            )

        except AppointmentCancellationError:
            raise
        except Exception as exc:
            raise AppointmentCancellationError(
                reason=str(exc), appointment_id=appointment_id
            ) from exc

    async def health_check(self) -> bool:
        try:
            page = await self._ensure_logged_in()
            response = await page.goto(
                f"{self._base_url}",
                wait_until="commit",
                timeout=10000,
            )
            return response is not None and response.ok
        except Exception as exc:
            logger.warning("Healthie health check failed: {}", exc)
            return False

    async def close(self) -> None:
        if self._browser:
            await self._browser.close()
            self._browser = None
            self._page = None
            logger.info("Healthie browser session closed")
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

    async def _parse_patient_results(self, page: Page) -> list[Patient]:
        """Parse patient search results from the Healthie UI into Patient objects."""
        results: list[Patient] = []

        profile_links = page.locator(_SEL_PROFILE_LINK)
        count = await profile_links.count()
        if count == 0:
            return results

        for i in range(count):
            link = profile_links.nth(i)
            href = await link.get_attribute("href") or ""
            patient_id = extract_id_from_url(href)
            if not patient_id:
                continue

            row = link.locator("xpath=ancestor::*[contains(., '(')]").first
            row_text = await row.inner_text() if await row.count() > 0 else ""

            parsed = parse_name_dob(row_text)
            if parsed is None:
                continue

            first_name, last_name, dob_iso = parsed
            results.append(
                Patient(
                    patient_id=patient_id,
                    first_name=first_name,
                    last_name=last_name,
                    date_of_birth=dob_iso,
                )
            )

        return results

    async def _select_react_option(
        self, page: Page, input_id: str, *, option_index: int = 0
    ) -> None:
        input_el = page.locator(f"input#{input_id}")
        await input_el.click()
        await page.wait_for_timeout(_SELECT_OPEN_DELAY_MS)
        for _ in range(option_index + 1):
            await input_el.press("ArrowDown")
            await page.wait_for_timeout(_SELECT_ARROW_DELAY_MS)
        await input_el.press("Enter")
        await page.wait_for_timeout(_SELECT_OPEN_DELAY_MS)

    async def _extract_appointment_id_from_modal(self, page: Page) -> str | None:
        """Extract the numeric appointment ID from the open detail modal.

        Looks for a ``data-testid="appointment-{id}"`` element inside the modal.
        """
        testids = await page.evaluate("""() => {
            const els = document.querySelectorAll('[data-testid]');
            const result = [];
            for (const el of els) {
                const tid = el.dataset.testid;
                if (tid && /^appointment-\\d+$/.test(tid)) {
                    result.push(tid);
                }
            }
            return result;
        }""")
        if testids:
            # Format: "appointment-619123263"
            return testids[0].split("-", 1)[1]
        return None

    async def _open_appointment_modal(self, page: Page, appointment_id: str) -> bool:
        """Open the appointment detail modal for the given appointment ID.

        Clicks through each appointment preview item on the current page until
        the modal with the matching appointment ID is found.
        """
        items = page.locator(_SEL_APPT_PREVIEW_ITEM)
        count = await items.count()

        for i in range(count):
            await items.nth(i).click()
            await page.wait_for_timeout(_MODAL_OPEN_DELAY_MS)

            found_id = await self._extract_appointment_id_from_modal(page)
            if found_id == appointment_id:
                return True

            # Not the right appointment — close the modal and try next.
            close_btn = page.locator(_SEL_APPT_DETAIL_CLOSE)
            if await close_btn.count() > 0:
                await close_btn.click()
                await page.wait_for_timeout(_SELECT_OPEN_DELAY_MS)

        return False
