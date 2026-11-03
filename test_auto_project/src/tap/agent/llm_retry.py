"""Transport retries only; model responses and mapping repairs are not retried here."""
import time
from copy import deepcopy
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from openai import APITimeoutError


def retry_delay(error, config, attempt):
    body = getattr(error, 'body', None)
    body = body.get('error', body) if isinstance(body, dict) else {}
    if not isinstance(body, dict): body = {}
    codes = {str(body.get(k, '')).lower() for k in ('code', 'type')}
    if codes.intersection(config['non_retryable_codes']): return None
    status = getattr(error, 'status_code', None)
    if not isinstance(error, (APITimeoutError, TimeoutError)) and status not in [429, *config['retry_statuses']]:
        return None
    delay = config['retry_base_seconds'] * 2 ** attempt
    headers = getattr(getattr(error, 'response', None), 'headers', {})
    try:
        if headers.get('retry-after-ms') is not None:
            delay = max(delay, float(headers['retry-after-ms']) / 1000)
        if headers.get('retry-after') is not None:
            value = headers['retry-after']
            try: after = float(value)
            except ValueError:
                after = (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds()
            delay = max(delay, after)
    except (TypeError, ValueError, OverflowError):
        pass
    return delay


def create_with_retry(create, kwargs, config, emit, remaining):
    for attempt in range(config['policy']['llm_transport_max_retries'] + 1):
        _, seconds = remaining()
        emit('llm_attempt_start', attempt=attempt+1, request={'attempt': attempt+1})
        started = time.monotonic()
        try:
            response = create(**{**deepcopy(kwargs), 'timeout': seconds})
        except Exception as error:
            delay = retry_delay(error, config, attempt)
            emit('llm_attempt_error', attempt=attempt+1, backend_seconds=time.monotonic()-started,
                 result={'error': str(error), 'retryable': delay is not None})
            if delay is None or attempt >= config['policy']['llm_transport_max_retries']:
                raise
            _, seconds = remaining()
            if delay >= seconds:
                raise ValueError(config['errors']['retry_wait_budget']) from error
            emit('llm_retry', attempt=attempt+1, request={'next_attempt': attempt+2, 'wait_seconds': delay},
                 result={'error': str(error), 'wait_seconds': delay})
            deadline = time.monotonic() + delay
            while time.monotonic() < deadline:
                time.sleep(min(0.25, max(0, deadline-time.monotonic())))
            continue
        emit('llm_attempt_complete', attempt=attempt+1, backend_seconds=time.monotonic()-started,
             result={'status': response.status, 'response_id': response.id})
        return response
