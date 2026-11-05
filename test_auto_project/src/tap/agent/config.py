"""Configuration data and validation, separate from tools and the runtime loop."""
from copy import deepcopy

from .output_models import StepMappingResult
from .prompts import SYSTEM, VALIDATION_INSTRUCTIONS

DEFAULTS = dict(max_turns=16, max_tokens=150000, max_seconds=180, max_output_tokens=4096)
DEFAULT_OPTIONS = dict(stop_retry=False, kb_rag=False, dependency_projection=False,
                       approval_gate=False)   # IR 입력 검토 — 화면에서 뺐다(2026-11-05), API 로만 켤 수 있음
# 인젝션 대응(injection_guard) 옵션은 뺐다 (2026-11-05 지은 결정) — 인젝션 감지 · 차단은 지은 ①②③ 하나뿐
# (요청 원문은 ① 직후, 사람이 넣는 값은 서버에서). 자료 속 지시문은 validate_mapping · 사람 확정이 막는다.
# approval_gate = 'IR 입력 검토' — 미해결 입력을 사람이 지금 입력 · 실행 시 입력으로 정해 확정. 실행 단계가 생기면
#   승인 게이트와 하나로 합칠 예정이라(TODO, 중간발표 뒤) 지금은 화면에서 빼고 기본값을 끔으로 두었다.
# 권한 등급 · 계획 승인을 하는 '승인 게이트'는 지은 ①②③ 쪽 하나뿐이다 (tap.apis.gate).
DEFAULT_GENERATION_MODE = 'basic'
GENERATION_MODES = [dict(value='basic', label='기본 모드'), dict(value='validated', label='정지·재시도 적용 모드')]
MODE_POLICIES = {
    'basic': dict(mapping_validation=False, final_ir_validation=False,
                  llm_transport_max_retries=0, mapping_repair_limit_per_step=None),
    'validated': dict(mapping_validation=True, final_ir_validation=True,
                      llm_transport_max_retries=1, mapping_repair_limit_per_step=1),
}

CONFIG = {
    **DEFAULTS,
    'instructions': SYSTEM,
    'model_env': 'OPENAI_DEFAULT_MODEL',
    'max_retries': 0,
    'retry_base_seconds': 0.5,
    'retry_statuses': [408, 500, 502, 503, 504],
    'non_retryable_codes': ['insufficient_quota', 'billing_hard_limit_reached', 'usage_limit_reached',
                            'organization_usage_limit_exceeded', 'project_usage_limit_exceeded'],
    'basic_tool': 'get_parameter_knowledge',
    'kb_top_k': 5,
    'kb_max_distance': 0.85,
    'store': False,
    'include': ['reasoning.encrypted_content'],
    'text': {
        'format': {
            'type': 'json_schema',
            'name': 'step_mapping_result',
            'strict': True,
            'schema': StepMappingResult.model_json_schema(by_alias=True),
        },
    },
    'errors': {
        'settings': '생성 설정은 양의 정수여야 합니다',
        'mode': '허용되지 않은 생성 모드입니다',
        'recovery_stopped': '정지·재시도 정책에 따라 중단했습니다: {reason}',
        'repair': '검증 결과의 오류 항목과 직접 연결된 항목을 수정하고 StepMappingResult로 반환하세요',
        'mode_locked': '생성 중에는 모드를 변경할 수 없습니다',
        'material_stalled': '같은 자료 부족 상태가 반복되고 있습니다',
        'tool_stalled': '같은 도구·인자·결과가 반복되고 있습니다',
        'repair_exhausted': 'STEP 수정 기회를 사용한 뒤에도 검증 오류가 남았습니다',
        'llm_stopped': 'LLM 요청 또는 응답 처리 실패',
        'retry_wait_budget': '재시도 대기 시간이 남은 생성 시간을 초과합니다',
        'artifact_read': '자료 오류: {e}',
        'final_backend': '최종 IR의 백엔드 조립 오류',
        'final_check': '최종 IR 검사 중 백엔드 오류',
        'output_budget': '출력 토큰은 누적 토큰 이하여야 합니다',
        'model': '{model_env}이 필요합니다',
        'budget': 'IR 생성 설정 한도 도달: {usage}',
        'output_length': '출력 토큰 한도 도달: 설정을 늘려 다시 생성하세요',
        'response_status': 'LLM 응답이 완료되지 않았습니다: {status} · {details}',
        'refusal': 'LLM이 결과 생성을 거절했습니다: {reason}',
        'disabled_validator': 'validate_mapping은 Baseline 대체 항목 분석 중 비활성화되어 있습니다',
        'step_id': '현재 step_id를 가진 JSON 객체가 필요합니다',
        'unknown_tool': '알 수 없는 도구',
        'arguments': '도구 인자는 JSON 객체여야 합니다',
        'candidate': '최종 작성안은 JSON 객체여야 합니다',
        'tool': '{e}',
        'incomplete': '현재 API의 ParameterKB(schema 포함)를 먼저 기본 조회한 뒤 매핑 후보를 작성하세요',
        'materials': '결과에 필요한 자료가 부족합니다. needed_materials에 지정한 자료만 추가 조회하세요',
        'dependency_coverage': '조회 결과 의존성이 남아 있습니다. 후속 업무용 outputs 또는 실제 입력과 연결된 bindings를 작성하세요. 조회 후에도 대응을 확정할 수 없다면 unresolved.dependency_ids에 해당 ID와 구체적인 사유를 기록하세요',
        'material_missing': '자료가 없습니다: {tool} · {api}',
        'api_scope': '현재 STEP의 API를 사용하세요. 응답 출력은 완료된 앞 STEP의 API도 조회할 수 있습니다',
        'previous_output': '앞 STEP 출력이나 조회된 응답 정의와 일치하는 출력 참조가 필요합니다. 출처 API를 먼저 조회하고 확인된 경로로 Binding을 작성하세요. 조회 후에도 확인할 수 없다면 해당 dependency_ids와 사유를 unresolved에 남기세요',
        'assertions': 'assertions는 빈 배열로 반환하세요. 응답 검증 조건 생성은 제외되어 있습니다',
    },
}


def configuration(values=None):
    """Validate only the four numeric settings exposed by the existing UI/API."""
    if values is not None and not isinstance(values, dict):
        raise ValueError(CONFIG['errors']['settings'])
    result = {**DEFAULTS, **(values or {})}
    if set(result) != set(DEFAULTS) or any(type(v) is not int or v <= 0 for v in result.values()):
        raise ValueError(CONFIG['errors']['settings'])
    if result['max_output_tokens'] > result['max_tokens']:
        raise ValueError(CONFIG['errors']['output_budget'])
    return result


def generation_policy(mode=None):
    mode = DEFAULT_GENERATION_MODE if mode is None else mode
    if not isinstance(mode, str) or mode not in MODE_POLICIES:
        raise ValueError(CONFIG['errors']['mode'])
    return mode, deepcopy(MODE_POLICIES[mode])


def generation_options(values=None, mode=None):
    if mode is not None:
        generation_policy(mode)
    if values is not None and (not isinstance(values, dict) or set(values) - set(DEFAULT_OPTIONS)
                               or any(type(v) is not bool for v in values.values())):
        raise ValueError('생성 옵션은 ' + '/'.join(DEFAULT_OPTIONS) + '의 boolean 객체여야 합니다')
    result = {**DEFAULT_OPTIONS, **(values or {})}
    if mode is not None:
        legacy = mode == 'validated'
        if values is not None and 'stop_retry' in values and result['stop_retry'] != legacy:
            raise ValueError('generation_mode와 generation_options.stop_retry가 충돌합니다')
        result['stop_retry'] = legacy
    return result


def harness_configuration(values=None, generation_mode=None, options=None):
    """Create a per-generation snapshot without adding private config to the IR."""
    result = deepcopy(CONFIG)
    result.update(configuration(values))
    result['options'] = generation_options(options, generation_mode)
    result['execution_mode'], result['policy'] = generation_policy('validated' if result['options']['stop_retry'] else 'basic')
    from .prompts import KB_RETRIEVAL_INSTRUCTIONS, PROJECTION_INSTRUCTIONS
    if result['options']['kb_rag']:
        result['instructions'] += '\n\n' + KB_RETRIEVAL_INSTRUCTIONS
    if result['options']['dependency_projection']:
        result['instructions'] += '\n\n' + PROJECTION_INSTRUCTIONS
    if result['policy']['mapping_validation']:
        result['instructions'] += '\n\n' + VALIDATION_INSTRUCTIONS
    return result
