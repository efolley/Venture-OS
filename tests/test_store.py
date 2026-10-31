import os
import time
import unittest
from ventureos.execution import Task, Artifact
from ventureos.store import PostgresStore, LeaseLost

@unittest.skipUnless(os.environ.get('VENTUREOS_TEST_DSN'), 'requires disposable PostgreSQL database')
class StoreTests(unittest.TestCase):
    def setUp(self):
        self.store = PostgresStore(os.environ['VENTUREOS_TEST_DSN'])
        self.store.initialize()
        import uuid
        self.tenant = str(uuid.uuid4())
        self.task = Task(self.tenant, 'run', 'task', 'research', {})
        self.store.submit(self.task)

    def test_claim_is_exclusive_and_tenant_scoped(self):
        lease = self.store.claim(self.tenant, 'worker', 30)
        self.assertIsNotNone(lease)
        self.assertIsNone(self.store.claim(self.tenant, 'other', 30))
        self.assertIsNone(self.store.get('other-tenant', 'task'))
        self.assertEqual(self.store.get(self.tenant,'task')['status'], 'running')

    def test_expired_worker_fenced_checkpoint_survives_restart(self):
        first = self.store.claim(self.tenant,'first',30)
        self.store.checkpoint(first, {'page': 2})
        with self.store.connect() as conn:
            conn.execute('UPDATE ventureos_tasks SET lease_until=0 WHERE tenant_id=%s', (self.tenant,))
        restarted = PostgresStore(os.environ['VENTUREOS_TEST_DSN'])
        second = restarted.claim(self.tenant,'second',30)
        self.assertEqual(second.checkpoint, {'page': 2})
        with self.assertRaises(LeaseLost):
            self.store.complete(first, Artifact(self.tenant,'run','task','brief',{}))
        restarted.complete(second, Artifact(self.tenant,'run','task','brief',{'ok':True}))
        self.assertEqual(restarted.get(self.tenant,'task')['status'], 'succeeded')
        self.assertIsNone(restarted.claim(self.tenant,'third',30))

    def test_budget_atomic_and_checkpoint_json(self):
        lease = self.store.claim(self.tenant,'worker',30)
        self.store.reserve(lease, 9999)
        with self.assertRaises(ValueError): self.store.reserve(lease, 2)
        self.assertEqual(self.store.get(self.tenant,'task')['spent_units'],9999)
        with self.assertRaises(ValueError): self.store.checkpoint(lease, {'bad':object()})

    def test_duplicate_submit_and_approval_binding(self):
        self.store.submit(self.task)
        with self.assertRaises(ValueError):
            self.store.submit(Task(self.tenant,'run','task','research',{'changed':True}))
        approved = Task(self.tenant,'run','approval','research',{}, requires_approval=True)
        self.store.submit(approved)
        self.assertFalse(self.store.approve(self.tenant,'approval','wrong'))
        digest = self.store.get(self.tenant,'approval')['task_hash']
        self.assertTrue(self.store.approve(self.tenant,'approval',digest))

    def test_skip_locked_does_not_wait_for_locked_task(self):
        with self.store.connect() as conn:
            conn.execute('SELECT * FROM ventureos_tasks WHERE tenant_id=%s FOR UPDATE', (self.tenant,))
            self.assertIsNone(self.store.claim(self.tenant,'other',30))

    def test_attempts_exhausted_on_crash(self):
        one = Task(self.tenant,'run','one','research',{},max_attempts=1)
        self.store.submit(one)
        with self.store.connect() as conn:
            conn.execute("UPDATE ventureos_tasks SET status='failed' WHERE tenant_id=%s AND task_id='task'",(self.tenant,))
        self.store.claim(self.tenant,'worker',30)
        with self.store.connect() as conn:
            conn.execute("UPDATE ventureos_tasks SET lease_until=0 WHERE tenant_id=%s AND task_id='one'",(self.tenant,))
        self.assertIsNone(self.store.claim(self.tenant,'worker2',30))
        self.assertEqual(self.store.get(self.tenant,'one')['status'],'failed')

    def test_real_concurrent_claims_and_budget_reservations(self):
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=4) as workers:
            leases=list(workers.map(lambda n:self.store.claim(self.tenant,str(n),30),range(4)))
        claimed=[lease for lease in leases if lease is not None]
        self.assertEqual(len(claimed),1)
        def reserve(_):
            try:
                self.store.reserve(claimed[0],6000)
                return True
            except ValueError:
                return False
        with ThreadPoolExecutor(max_workers=2) as workers:
            self.assertEqual(sum(workers.map(reserve,range(2))),1)

    def test_completed_task_identity_and_deadline(self):
        lease=self.store.claim(self.tenant,'worker',30)
        with self.assertRaises(ValueError):
            self.store.complete(lease,Artifact('other','run','task','brief',{}))
        with self.store.connect() as conn:
            conn.execute('UPDATE ventureos_tasks SET deadline=0 WHERE tenant_id=%s',(self.tenant,))
        with self.assertRaises(ValueError):
            self.store.complete(lease,Artifact(self.tenant,'run','task','brief',{}))
        self.store.fail(lease,retryable=True)
        self.assertEqual(self.store.get(self.tenant,'task')['status'],'failed')
