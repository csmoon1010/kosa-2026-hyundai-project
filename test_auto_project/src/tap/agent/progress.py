"""Safe transport snapshots for the visible execution log (not model reasoning)."""
import json
import os
import re

SENSITIVE = re.compile(r'^(authorization|api[_-]?key|openai_api_key|oausekey|password|secret|access_token|refresh_token)$', re.I)


def snapshot(value):
    secrets = [v for k, v in os.environ.items() if SENSITIVE.match(k) and v]
    def clean(v):
        if isinstance(v, dict):
            identity = str(v.get('field', v.get('name', v.get('parameter_name', ''))))
            path = str(v.get('parameter_path', v.get('path', ''))).split('.')[-1]
            sensitive_value = SENSITIVE.match(identity) or SENSITIVE.match(path)
            return {k: '[비공개]' if SENSITIVE.match(k) or (sensitive_value and k in ['value','example','raw_example']) else clean(x) for k,x in v.items()}
        if isinstance(v, list): return [clean(x) for x in v]
        if isinstance(v, str):
            for secret in secrets: v = v.replace(secret, '[비공개]')
            if v.lstrip().startswith(('{', '[')):
                try: return json.dumps(clean(json.loads(v)), ensure_ascii=False)
                except (ValueError, TypeError): pass
        return v
    return clean(value)
