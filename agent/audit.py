"""No prompts, result rows, paths, raw exceptions or credentials in audit records."""
from datetime import datetime, timezone
import hashlib
import json
import os


def record(root, context, request_id, status, spec=None):
    event = dict(request_id=request_id, status=status, time=datetime.now(timezone.utc).isoformat(),
                 subject_hash=hashlib.sha256(context.tenant.encode()).hexdigest()[:16],
                 report=context.report, fingerprint=context.fingerprint,
                 spec_hash=hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest() if spec else None)
    data = (json.dumps(event, ensure_ascii=True) + '\n').encode('utf-8')
    path = root / '.agent_audit.jsonl'
    # One append write keeps each small event intact in the local single-user app.
    fd = os.open(str(path), os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)
