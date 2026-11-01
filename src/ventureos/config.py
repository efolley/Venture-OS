"""Load local development configuration without overriding process settings."""
from ventureos.logging_utils import logged
from pathlib import Path


@logged
def load_local_env(path=None):
    path = Path(path) if path else Path(__file__).resolve().parents[2] / '.env'
    if not path.is_file():
        return
    try:
        from dotenv import load_dotenv
    except ImportError:
        raise ValueError('Install runtime or UI extras to read .env configuration') from None
    load_dotenv(path, override=False, interpolate=False)
