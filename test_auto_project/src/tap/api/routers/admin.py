"""관리자 메뉴 — 상태 그래프 · 보정 규칙 · Baseline · 다시 빌드 · 전처리 (전처리는 혜정 코드에서 옮김)."""
from __future__ import annotations

from fastapi import APIRouter, Request

from tap.api import services
from tap.api.deps import dump, state
from tap.api.models import (DATA_PART_MODELS, BaselineRequest, GraphMatchRequest, GraphMatchResult, GraphSaveRequest,
                            GraphSaveResult, PreprocessingBaselineRequest, RuleRequest, doc)
from tap.ui.export import ui_data

router = APIRouter(prefix="/api/admin", tags=["관리자 메뉴"])


@router.put("/graphs/{graph_id}", responses=doc(GraphSaveResult, 400))
def save_graph(request: Request, graph_id: str, req: GraphSaveRequest):
    """노드 흐름만 저장 — 기존 파일 위에 합치고 이전 파일은 data/out/graph_history/ 에."""
    return services.save_graph(state(request).root, graph_id, req.yaml)


@router.post("/rules", responses=doc(None, 400))
def add_rule(request: Request, req: RuleRequest | None = None):
    """화면 보정 규칙 → data/config/rules.ui.yaml + 다시 빌드. 잘못된 규칙이면 400 (파일은 되돌림)."""
    root = state(request).root
    return {"build": services.save_rule(root, dump(req)), "data": ui_data(root)}


@router.delete("/rules/{rule_id}")
def delete_rule(request: Request, rule_id: int):
    root = state(request).root
    return {"build": services.delete_rule(root, rule_id), "data": ui_data(root)}


@router.put("/baselines", responses=doc(None, 400))
def save_baseline(request: Request, req: BaselineRequest):
    root = state(request).root
    dest = services.save_baseline(root, req.api_id, req.body)
    return {"file": str(dest.relative_to(root)), "data": ui_data(root)}


@router.post("/build")
def build(request: Request):
    return services.build_again(state(request).root)


@router.post("/preprocessing/refresh")
def refresh_preprocessing(request: Request):
    return services.refresh_preprocessing(state(request).root)


@router.put("/preprocessing/baselines", responses=doc(None, 400))
def save_preprocessing(request: Request, req: PreprocessingBaselineRequest):
    """전처리 Baseline 등록 — 값에서 지시문 검사."""
    return services.save_preprocessing(state(request).root, dump(req))


# ─── 화면 데이터 (나눠서) · 그래프 매칭 — React 전환 R0 ───────────────────────────────────────

def _part(name: str):
    def read(request: Request):
        return services.data_part(state(request).root, name)
    read.__name__ = f"read_{name}"
    read.__doc__ = f"화면 데이터 — {name} ({' · '.join(services.DATA_PARTS[name])})"
    return read


for _name in services.DATA_PARTS:
    router.add_api_route(f"/{_name}", _part(_name), methods=["GET"], responses=doc(DATA_PART_MODELS.get(_name)))


@router.get("/graph-review")
def graph_review(request: Request):
    """전사 검수 목록의 상태 그래프 부분 — API 를 못 찾을 것 같은 화살표 · 애매한 조회."""
    return {"items": services.graph_review(state(request).root)}


@router.post("/graphs/match", responses=doc(GraphMatchResult, 400))
def graph_match(request: Request, req: GraphMatchRequest | None = None):
    """그래프 편집기의 API 후보 미리보기 — {edges:[{name, from_name, to_name, to_code}], lookups:[{state_name, state_code}], state_field, domains}."""
    return services.graph_match(state(request).root, dump(req))
