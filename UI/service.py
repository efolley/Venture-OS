"""Run the existing research CLI without shell interpolation or secret output."""
from ventureos.logging_utils import logged
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from ventureos.progress import PHASES

from ventureos.web_intelligence import ResearchRequest
from ventureos.config import load_local_env

REQUIRED = ('TAVILY_API_KEY', 'VENTUREOS_DATABASE_URL')


@logged
def missing_configuration():
    load_local_env()
    required = REQUIRED + (() if os.environ.get('MODEL_PROVIDER','anthropic') == 'ollama' else ('ANTHROPIC_API_KEY','ANTHROPIC_MODEL'))
    return [name for name in required if not os.environ.get(name)]


@logged
def research(company, website, *, demo=False, on_progress=None):
    root = Path(__file__).resolve().parents[1]
    command = [sys.executable, '-m', 'ventureos.research']
    if demo:
        command.append('--fixture')
    else:
        website = website.strip()
        if website.startswith('http://'):
            website = 'https://' + website[len('http://'):]
        if website and '://' not in website:
            website = 'https://' + website
        ResearchRequest(company.strip(), website)
        missing = missing_configuration()
        if missing:
            raise ValueError('Configure locally: ' + ', '.join(missing))
        command += ['--company', company.strip(), '--website', website,
                    '--provider', os.environ.get('MODEL_PROVIDER','anthropic'),
                    '--model', os.environ.get('OLLAMA_MODEL','qwen3:8b') if os.environ.get('MODEL_PROVIDER') == 'ollama' else os.environ['ANTHROPIC_MODEL'], '--tenant', 'local-ui']
    env = {**os.environ, 'PYTHONPATH': str(root / 'src')}
    try:
        with tempfile.TemporaryDirectory(prefix='ventureos-progress-') as directory:
            progress_path = Path(directory) / 'phase'
            env['VENTUREOS_PROGRESS_FILE'] = str(progress_path)
            if on_progress is None:
                process = subprocess.run(command, cwd=root, env=env, capture_output=True,
                                         text=True, timeout=600, check=False)
            else:
                on_progress('Preparing research')
                with ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(subprocess.run, command, cwd=root, env=env,
                                             capture_output=True, text=True, timeout=600, check=False)
                    previous = None
                    while not future.done():
                        try:
                            phase = progress_path.read_text()
                        except OSError:
                            phase = None
                        if phase in PHASES and phase != previous:
                            on_progress(PHASES[phase])
                            previous = phase
                        time.sleep(0.1)
                    process = future.result()
    except subprocess.TimeoutExpired:
        raise ValueError('Research timed out. Check connectivity and try again.') from None
    # Relay payload-free worker logs to the Streamlit terminal after completion.
    for line in getattr(process, 'stderr', '').splitlines():
        if line.startswith('VENTUREOS '):
            print(line, file=sys.stderr)
    if process.returncode:
        try:
            detail = json.loads(process.stdout).get('error')
        except (ValueError, AttributeError):
            detail = None
        if isinstance(detail, dict) and all(isinstance(detail.get(k),str) for k in ('stage','function','exception','message')):
            raise ValueError('Research failed during ' + detail['stage'] + '. Function: ' + detail['function']
                             + ' | ' + detail['exception'] + ' | ' + detail['message'])
        if 'Ollama model is not installed' in process.stderr:
            raise ValueError('Ollama model is not installed yet. Wait for `ollama pull qwen3:8b` to finish, then retry.')
        if 'Ollama server is unavailable' in process.stderr:
            raise ValueError('Ollama server is unavailable. Start Ollama locally and retry.')
        raise ValueError('Research failed. Check your API access, model, PostgreSQL connection, and final HTTPS website URL.')
    result = json.loads(process.stdout)
    if result.get('status') != 'succeeded' or not result.get('artifact'):
        raise ValueError('Research did not return an accepted report.')
    return result


@logged
def saved_reports():
    """Local operator history for the UI and CLI's fixed local scopes."""
    load_local_env()
    dsn=os.environ.get('VENTUREOS_DATABASE_URL')
    if not dsn:
        raise ValueError('Set VENTUREOS_DATABASE_URL in .env to view saved results.')
    from ventureos.store import PostgresStore
    from ventureos.gateways import Principal
    from ventureos.web_intelligence import list_saved_research
    try:
        store=PostgresStore(dsn)
        reports=[]
        for tenant in ('local-ui','local'):
            reports.extend(list_saved_research(store,Principal(tenant,frozenset({'research:read'})),tenant))
        return sorted(reports,key=lambda report:report['saved_at'],reverse=True)[:100]
    except Exception:
        raise ValueError('Cannot load saved results. Check the local PostgreSQL connection and initialized VentureOS tables.') from None


@logged
def history_labels(reports):
    """Readable local dates; duplicate iterations count from oldest to newest."""
    from collections import defaultdict
    from datetime import datetime
    from zoneinfo import ZoneInfo
    groups=defaultdict(list)
    labels=['']*len(reports)
    for index, report in enumerate(reports):
        stamp=datetime.fromisoformat(report['saved_at']).astimezone(ZoneInfo('America/New_York'))
        company=report['artifact']['content']['company']
        groups[(company,stamp.date())].append((stamp,index))
    months=('Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec')
    for (company, day), entries in groups.items():
        for iteration, (_, index) in enumerate(sorted(entries),1):
            label=f'{company} | {months[day.month-1]} {day.day}'
            if len(entries)>1:
                label+=f', ({iteration})'
            labels[index]=label
    return labels
