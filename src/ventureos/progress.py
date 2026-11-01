"""Optional local progress channel containing phase names only, never payloads."""
from ventureos.logging_utils import logged
import os
from pathlib import Path

PHASES = {
    'checking': 'Checking configuration and model',
    'searching': 'Searching for company sources',
    'scraping': 'Scraping source pages',
    'processing': 'Processing scraped results',
    'validating': 'Validating findings and citations',
    'saving': 'Saving the company report',
}


@logged
def report_phase(phase):
    if phase not in PHASES:
        raise ValueError('Unknown research phase')
    from .diagnostics import phase as current_phase
    current_phase.set(phase)
    target = os.environ.get('VENTUREOS_PROGRESS_FILE')
    if target:
        try:
            Path(target).write_text(phase)
        except OSError:
            pass  # Progress delivery must not change task acceptance.
