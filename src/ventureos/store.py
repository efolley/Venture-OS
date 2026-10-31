"""PostgreSQL task ledger. Each mutation is tenant-scoped and transactional."""
from dataclasses import dataclass
import hashlib
import json
import uuid
from .execution import Task, Artifact, json_payload


class LeaseLost(RuntimeError):
    pass


def task_hash(task: Task) -> str:
    return hashlib.sha256(json.dumps(task.to_dict(),sort_keys=True).encode()).hexdigest()


@dataclass(frozen=True)
class Lease:
    task: Task
    token: str
    attempt: int
    checkpoint: dict


SCHEMA = '''
CREATE TABLE IF NOT EXISTS ventureos_tasks (
 tenant_id text NOT NULL, task_id text NOT NULL, run_id text NOT NULL,
 task jsonb NOT NULL, task_hash text NOT NULL,
 status text NOT NULL, attempts integer NOT NULL DEFAULT 0,
 max_attempts integer NOT NULL, budget_units bigint NOT NULL,
 spent_units bigint NOT NULL DEFAULT 0, deadline double precision,
 lease_token text, lease_until double precision, worker text,
 available_at double precision NOT NULL DEFAULT 0,
 checkpoint jsonb NOT NULL DEFAULT '{}', artifact jsonb,
 approved boolean NOT NULL DEFAULT false,
 PRIMARY KEY(tenant_id,task_id)
);
CREATE INDEX IF NOT EXISTS ventureos_ready ON ventureos_tasks(tenant_id,status,available_at);
CREATE TABLE IF NOT EXISTS ventureos_audit (
 id bigserial PRIMARY KEY, tenant_id text NOT NULL, task_id text NOT NULL,
 event text NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
'''


class PostgresStore:
    def __init__(self, dsn: str):
        self.dsn = dsn

    def connect(self):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as error:
            raise RuntimeError('Install ventureos[runtime] for PostgreSQL execution') from error
        return psycopg.connect(self.dsn, row_factory=dict_row)

    def initialize(self):
        with self.connect() as conn:
            conn.execute(SCHEMA)

    @staticmethod
    def _audit(conn, tenant, task, event):
        conn.execute('INSERT INTO ventureos_audit(tenant_id,task_id,event) VALUES (%s,%s,%s)',(tenant,task,event))

    def submit(self, task: Task):
        # Roundtrip makes persisted input independent of mutable caller payloads.
        task = Task.from_dict(json.loads(json.dumps(task.to_dict())))
        with self.connect() as conn:
            row = conn.execute('''INSERT INTO ventureos_tasks
                (tenant_id,task_id,run_id,task,task_hash,status,max_attempts,budget_units,deadline)
                VALUES (%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s)
                ON CONFLICT DO NOTHING RETURNING task_id''',
                (task.tenant_id,task.task_id,task.run_id,json.dumps(task.to_dict()),task_hash(task),
                 'waiting_approval' if task.requires_approval else 'ready',task.max_attempts,task.budget_units,task.deadline)).fetchone()
            if row:
                self._audit(conn,task.tenant_id,task.task_id,'submitted')
            else:
                old = conn.execute('SELECT task_hash FROM ventureos_tasks WHERE tenant_id=%s AND task_id=%s',(task.tenant_id,task.task_id)).fetchone()
                if old['task_hash'] != task_hash(task):
                    raise ValueError('task ID already bound to different input')

    def get(self, tenant: str, task: str):
        with self.connect() as conn:
            return conn.execute('SELECT * FROM ventureos_tasks WHERE tenant_id=%s AND task_id=%s',(tenant,task)).fetchone()

    def claim(self, tenant: str, worker: str, lease_seconds: float = 60, allowed_agents: tuple[str, ...] | None = None):
        if lease_seconds <= 0:
            raise ValueError('lease duration must be positive')
        if allowed_agents == ():
            return None
        token = str(uuid.uuid4())
        with self.connect() as conn:
            # Terminalize exhausted or expired work before selecting eligible tasks.
            conn.execute('''UPDATE ventureos_tasks SET status='failed',lease_token=NULL
                WHERE tenant_id=%s AND status IN ('ready','running','waiting_approval')
                AND ((deadline IS NOT NULL AND deadline<=extract(epoch FROM clock_timestamp()))
                OR (attempts>=max_attempts AND (status='ready' OR lease_until<=extract(epoch FROM clock_timestamp()))))''',(tenant,))
            row = conn.execute('''WITH candidate AS (
                SELECT tenant_id,task_id FROM ventureos_tasks WHERE tenant_id=%s
                AND (%s::text[] IS NULL OR task->>'agent_id'=ANY(%s::text[]))
                AND attempts<max_attempts AND (deadline IS NULL OR deadline>extract(epoch FROM clock_timestamp()))
                AND ((status='ready' AND available_at<=extract(epoch FROM clock_timestamp()))
                OR (status='running' AND lease_until<=extract(epoch FROM clock_timestamp())))
                ORDER BY task_id FOR UPDATE SKIP LOCKED LIMIT 1)
                UPDATE ventureos_tasks t SET status='running', attempts=t.attempts+1,
                lease_token=%s, worker=%s, lease_until=extract(epoch FROM clock_timestamp())+%s
                FROM candidate c WHERE t.tenant_id=c.tenant_id AND t.task_id=c.task_id RETURNING t.*''',
                (tenant,list(allowed_agents) if allowed_agents is not None else None,list(allowed_agents) if allowed_agents is not None else None,token,worker,lease_seconds)).fetchone()
            if row:
                self._audit(conn,tenant,row['task_id'],'claimed')
                return Lease(Task.from_dict(row['task']),token,row['attempts'],row['checkpoint'])
        return None

    def _locked(self, conn, lease: Lease):
        row = conn.execute('''SELECT *, extract(epoch FROM clock_timestamp()) AS now_epoch
            FROM ventureos_tasks WHERE tenant_id=%s AND task_id=%s FOR UPDATE''',
            (lease.task.tenant_id,lease.task.task_id)).fetchone()
        if (not row or row['status']!='running' or row['lease_token']!=lease.token
            or row['lease_until']<=row['now_epoch']):
            raise LeaseLost('stale or expired task lease')
        return row

    def checkpoint(self, lease: Lease, value: dict):
        json_payload(value)
        with self.connect() as conn:
            self._locked(conn,lease)
            conn.execute('UPDATE ventureos_tasks SET checkpoint=%s::jsonb WHERE tenant_id=%s AND task_id=%s',
                         (json.dumps(value),lease.task.tenant_id,lease.task.task_id))
            self._audit(conn,lease.task.tenant_id,lease.task.task_id,'checkpoint')

    def heartbeat(self, lease: Lease, seconds: float = 60):
        if seconds<=0: raise ValueError('lease duration must be positive')
        with self.connect() as conn:
            self._locked(conn,lease)
            conn.execute('UPDATE ventureos_tasks SET lease_until=extract(epoch FROM clock_timestamp())+%s WHERE tenant_id=%s AND task_id=%s',
                         (seconds,lease.task.tenant_id,lease.task.task_id))

    def reserve(self, lease: Lease, units: int):
        if type(units) is not int or units<0: raise ValueError('units must be nonnegative')
        with self.connect() as conn:
            row = self._locked(conn,lease)
            if row['deadline'] is not None and row['deadline']<=row['now_epoch']:
                raise ValueError('deadline exceeded')
            if row['spent_units']+units>row['budget_units']: raise ValueError('budget exceeded')
            conn.execute('UPDATE ventureos_tasks SET spent_units=spent_units+%s WHERE tenant_id=%s AND task_id=%s',
                         (units,lease.task.tenant_id,lease.task.task_id))
            self._audit(conn,lease.task.tenant_id,lease.task.task_id,'budget_reserved')

    def complete(self, lease: Lease, artifact: Artifact):
        if (artifact.tenant_id,artifact.run_id,artifact.task_id)!=(lease.task.tenant_id,lease.task.run_id,lease.task.task_id):
            raise ValueError('artifact identity mismatch')
        with self.connect() as conn:
            row = self._locked(conn,lease)
            if row['deadline'] is not None and row['deadline']<=row['now_epoch']:
                raise ValueError('deadline exceeded')
            conn.execute("UPDATE ventureos_tasks SET status='succeeded',artifact=%s::jsonb,lease_token=NULL WHERE tenant_id=%s AND task_id=%s",
                         (json.dumps(artifact.to_dict()),lease.task.tenant_id,lease.task.task_id))
            self._audit(conn,lease.task.tenant_id,lease.task.task_id,'succeeded')

    def fail(self, lease: Lease, *, retryable: bool, delay: float = 0):
        if delay<0: raise ValueError('retry delay must be nonnegative')
        with self.connect() as conn:
            row = self._locked(conn,lease)
            retry = retryable and row['attempts']<row['max_attempts'] and (row['deadline'] is None or row['deadline']>row['now_epoch']+delay)
            status = 'ready' if retry else 'failed'
            conn.execute('UPDATE ventureos_tasks SET status=%s,lease_token=NULL,available_at=extract(epoch FROM clock_timestamp())+%s WHERE tenant_id=%s AND task_id=%s',
                         (status,delay,lease.task.tenant_id,lease.task.task_id))
            self._audit(conn,lease.task.tenant_id,lease.task.task_id,'retry_scheduled' if retry else 'failed')

    def approve(self, tenant: str, task: str, digest: str):
        with self.connect() as conn:
            row = conn.execute("UPDATE ventureos_tasks SET status='ready',approved=true WHERE tenant_id=%s AND task_id=%s AND task_hash=%s AND status='waiting_approval' RETURNING task_id",(tenant,task,digest)).fetchone()
            if row: self._audit(conn,tenant,task,'approved')
            return bool(row)

    def audit(self, tenant: str, task: str):
        with self.connect() as conn:
            return conn.execute('SELECT event FROM ventureos_audit WHERE tenant_id=%s AND task_id=%s ORDER BY id',(tenant,task)).fetchall()

    def reject(self, tenant: str, task: str, digest: str):
        with self.connect() as conn:
            row = conn.execute("UPDATE ventureos_tasks SET status='rejected' WHERE tenant_id=%s AND task_id=%s AND task_hash=%s AND status='waiting_approval' RETURNING task_id",(tenant,task,digest)).fetchone()
            if row: self._audit(conn,tenant,task,'rejected')
            return bool(row)
