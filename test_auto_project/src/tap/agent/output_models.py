"""Pydantic schema for Structured Outputs returned by one STEP analysis."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictOutputModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class Evidence(StrictOutputModel):
    source_id: str | None
    source_pointer: str | None
    quote: str | None


class StepInput(StrictOutputModel):
    field: str | None
    parameter_path: str | None
    xml_path: str | None
    type: str | None
    source: Literal['fixed', 'bind', 'run_input', 'unresolved']
    origin: Literal['user_condition', 'schema', 'parameter_kb', 'previous_output', 'run_input', 'unresolved']
    value: str | int | float | bool | None
    ref: str | None
    reason: str | None
    evidence: list[Evidence]


class StepOutput(StrictOutputModel):
    name: str
    response_key: str | None
    content_type: str | None
    response_path: str | None
    path_type: str | None
    type: str | None
    row_scope: str | None
    evidence: list[Evidence]


class BindingSource(StrictOutputModel):
    from_step_id: str
    output_name: str
    response_key: str | None
    content_type: str | None
    response_path: str
    path_type: str | None
    row_scope: str | None


class Binding(StrictOutputModel):
    binding_id: str
    from_: BindingSource = Field(alias='from')
    to_parameter_path: str

    # Keep the public JSON key named "from" while avoiding Python's keyword.
    model_config = ConfigDict(extra='forbid', strict=True, populate_by_name=True)


class Assertion(StrictOutputModel):
    name: str | None
    response_path: str | None
    operator: str | None
    expected: str | int | float | bool | None
    evidence: list[Evidence]


class Unresolved(StrictOutputModel):
    dependency_ids: list[str]
    reason: str
    required_input: str | None
    parameter_paths: list[str]
    evidence: list[Evidence]


class StepMappingResult(StrictOutputModel):
    step_id: str
    inputs: list[StepInput]
    outputs: list[StepOutput]
    bindings: list[Binding]
    assertions: list[Assertion]
    unresolved: list[Unresolved]
