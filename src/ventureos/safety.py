"""Small deterministic content checks, not a complete injection or DLP defense."""
from ventureos.logging_utils import logged
import re
from .execution import json_payload


class UnsafeContent(ValueError):
    pass


class ContentPolicy:
    injection = re.compile(r'ignore\s+(?:all\s+)?(?:previous|prior)\s+instructions|\[system\]|<\|(?:system|im_start)\|>|reveal\s+(?:your\s+)?(?:secrets|system\s+prompt)',re.I)
    email = re.compile(r'\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b',re.I)
    phone = re.compile(r'(?<!\w)(?:\+1[ .-]?)?\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}(?!\w)')

    @logged
    def check(self, value):
        if isinstance(value,str):
            if self.injection.search(value): raise UnsafeContent('content policy blocked instruction pattern')
            return self.phone.sub('[PHONE]',self.email.sub('[EMAIL]',value))
        if isinstance(value,dict):
            # Never silently change field names: reject sensitive or instructional keys.
            for key in value:
                if not isinstance(key,str) or self.check(key)!=key:
                    raise UnsafeContent('unsafe content key')
            return {k:self.check(v) for k,v in value.items()}
        if isinstance(value,(list,tuple)):
            return [self.check(v) for v in value]
        return value
