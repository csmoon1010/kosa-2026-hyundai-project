"""관리자 메뉴 — 상태 그래프 · 보정 규칙 · Baseline · 다시 빌드 · 전처리 (전처리는 혜정 코드에서 옮김)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from tap.api import services
from tap.api.deps import json_body, state
from tap.ui.export import ui_data

router = APIRouter(prefix="/api/admin", tags=["관리자 메뉴"])


@router.put("/graphs/{graph_id}")
def save_graph(request: Request, graph_id: str, body: dict = Depends(json_body)):
    """노드 흐름만 저장 — 기존 파일 위에 합치고 이전 파일은 data/out/graph_history/ 에."""
    return services.save_graph(state(request).root, graph_id, body["yaml"])


@router.post("/rules")
def add_rule(request: Request, body: dict = Depends(json_body)):
    """화면 보정 규칙 → data/config/rules.ui.yaml + 다시 빌드. 잘못된 규칙이면 400 (파일은 되돌림)."""
    root = state(request).root
    return {"build": services.save_rule(root, body), "data": ui_data(root)}


@router.delete("/rules/{rule_id}")
def delete_rule(request: Request, rule_id: int):
    root = state(request).root
    return {"build": services.delete_rule(root, rule_id), "data": ui_data(root)}


@router.put("/baselines")
def save_baseline(request: Request, body: dict = Depends(json_body)):
    root = state(request).root
    dest = services.save_baseline(root, body["api_id"], body["body"])
    return {"file": str(dest.relative_to(root)), "data": ui_data(root)}


@router.post("/build")
def build(request: Request):
    return services.build_again(state(request).root)


@router.post("/preprocessing/refresh")
def refresh_preprocessing(request: Request):
    return services.refresh_preprocessing(state(request).root)


@router.put("/preprocessing/baselines")
def save_preprocessing(request: Request, body: dict = Depends(json_body)):
    """전처리 Baseline 등록 — 값에서 지시문 검사."""
    return services.save_preprocessing(state(request).root, body)
