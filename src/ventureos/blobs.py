"""Tenant-scoped local source snapshots; no vector retrieval."""
import hashlib
import os
from pathlib import Path
import re
import tempfile
from .logging_utils import logged


class LocalBlobStore:
    @logged
    def __init__(self, root=None):
        self.root=Path(root) if root else Path(__file__).resolve().parents[2]/'runs'/'blobs'

    @logged
    def _path(self, tenant, key):
        if not re.fullmatch('[0-9a-f]{64}',key):
            raise ValueError('invalid snapshot reference')
        return self.root/hashlib.sha256(tenant.encode()).hexdigest()/key

    @logged
    def put(self, principal, tenant, text):
        principal.authorize(tenant,'agent:web_intelligence')
        encoded=text.encode('utf-8')
        key=hashlib.sha256(encoded).hexdigest()
        path=self._path(tenant,key)
        path.parent.mkdir(parents=True,exist_ok=True)
        descriptor,name=tempfile.mkstemp(dir=path.parent)
        try:
            with os.fdopen(descriptor,'wb') as output:
                output.write(encoded)
            os.replace(name,path)
        finally:
            if os.path.exists(name): os.unlink(name)
        return key

    @logged
    def get(self, principal, tenant, key):
        principal.authorize(tenant,'research:read')
        return self._path(tenant,key).read_text()
