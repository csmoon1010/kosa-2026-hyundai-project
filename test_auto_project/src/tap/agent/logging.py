"""One flushed JSONL journal per generation, independent of the UI connection."""
import json
import os
import time
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from .progress import snapshot


def log_url(file):
    return '/api/inspect/ir/logs/' + Path(file).name


class GenerationJournal:
    def __init__(self, root):
        now = datetime.now(ZoneInfo('Asia/Seoul'))
        self.run_id = f'IRRUN-{now:%Y%m%d-%H%M%S}-{uuid.uuid4().hex}'
        path = Path(root) / 'data/out/scenario_ir_logs' / f'{self.run_id}.jsonl'
        path.parent.mkdir(parents=True, exist_ok=True)
        self.file = str(path.relative_to(root))
        self.url = log_url(self.file)
        # Review events may append after the gate opens while generation is
        # still returning its terminal event. Always write at EOF.
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_APPEND, 0o600)
        self.handle = os.fdopen(descriptor, 'w', encoding='utf-8')
        self.sequence = 0
        self.started = time.monotonic()
        self.usage = {}
        self.budget = None
        self.budget_usage = {}
        self.budget_reason = None

    def append(self, event):
        self.sequence += 1
        self.budget = event.get("budget") or self.budget
        self.budget_usage = event.get("budget_usage") or self.budget_usage
        self.budget_reason = event.get("reason_code") or self.budget_reason
        event = {**event, "budget":self.budget, "budget_usage":self.budget_usage, "budget_reason":self.budget_reason}
        if 'usage' in event:
            self.usage = dict(event['usage'])
        record = snapshot({**event, 'run_id': self.run_id, 'sequence': self.sequence,
                           'recorded_at': datetime.now(ZoneInfo('Asia/Seoul')).isoformat(),
                           'run_elapsed_seconds': round(time.monotonic()-self.started, 3)})
        self.handle.write(json.dumps(record, ensure_ascii=False) + '\n')
        self.handle.flush()
        return record

    def close(self):
        self.handle.close()
