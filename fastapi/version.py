import subprocess
from datetime import date


def _get_version() -> str:
    """Lee el número de commits del repo como versión. Fallback a fecha."""
    try:
        count = subprocess.check_output(
            ["git", "rev-list", "--count", "HEAD"],
            stderr=subprocess.DEVNULL
        ).decode().strip()
        return f"1.{count}"
    except Exception:
        return f"1.0-{date.today().strftime('%m%d')}"


VERSION = _get_version()
RELEASE_DATE = date.today().isoformat()
