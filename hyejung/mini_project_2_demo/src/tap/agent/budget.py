"""Server-owned STEP budget policy and immutable calculation."""
from copy import deepcopy
POLICY = dict(version='step_budget_v1', per_step=dict(llm_calls=5,tokens=50000,seconds=60),
              reserve=dict(llm_calls=2,tokens=30000,seconds=30),
              absolute=dict(llm_calls=40,tokens=400000,seconds=600), max_output_tokens=4096)

def calculate(count, legacy=None):
    if type(count) is not int or count < 1:
        raise ValueError('STEP 수는 양의 정수여야 합니다')
    raw = {k:count*POLICY['per_step'][k]+POLICY['reserve'][k] for k in POLICY['absolute']}
    limits = {k:min(v,POLICY['absolute'][k]) for k,v in raw.items()}
    if legacy is not None:
        limits = dict(llm_calls=legacy['max_turns'],tokens=legacy['max_tokens'],seconds=legacy['max_seconds'])
    return dict(version='legacy_fixed_v1' if legacy else POLICY['version'],step_count=count,
                policy=deepcopy(POLICY),calculated=raw,limits=limits,
                capped={k:limits[k]<raw[k] for k in raw},
                max_output_tokens=legacy['max_output_tokens'] if legacy else 4096)

def configuration_for(budget):
    limits=budget['limits']
    return dict(max_turns=limits['llm_calls'],max_tokens=limits['tokens'],
                max_seconds=limits['seconds'],max_output_tokens=4096)
