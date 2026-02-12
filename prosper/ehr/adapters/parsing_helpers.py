import datetime as dt
import re


def parse_name_dob(text: str) -> tuple[str, str, dt.date] | None:
    """Extract name and DOB from text like ``"Marc Camps (5/18/2003)"``."""
    match = re.search(
        r"([A-Za-z][A-Za-z\- ]+?)\s*\((\d{1,2})/(\d{1,2})/(\d{4})\)",
        text,
    )
    if not match:
        return None

    full_name = match.group(1).strip()
    month, day, year = match.group(2), match.group(3), match.group(4)
    dob = dt.date(int(year), int(month), int(day))

    name_parts = full_name.split()
    if len(name_parts) < 2:
        return None

    first_name = name_parts[0]
    last_name = " ".join(name_parts[1:])
    return first_name, last_name, dob


def extract_id_from_url(url: str) -> str | None:
    """Extract the numeric patient/user ID from a Healthie profile URL."""
    match = re.search(r"/(?:patients|clients|users)/(\d+)", url)
    return match.group(1) if match else None
