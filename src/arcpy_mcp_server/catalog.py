from pathlib import Path

import jsonschema
import yaml
from pydantic import BaseModel, Field


class ArtifactInputDefinition(BaseModel):
    artifact_id_field: str
    path_field: str
    multiple: bool = False
    container_field: str | None = None


class OutputDefinition(BaseModel):
    name_field: str
    kind: str


class ToolDefinition(BaseModel):
    id: str
    title: str
    category: str
    description: str
    timeout_seconds: int
    required_extensions: list[str] = Field(default_factory=list)
    inputs: list[ArtifactInputDefinition] = Field(default_factory=list)
    output: OutputDefinition | None = None
    parameters: dict


class ToolCatalog:
    def __init__(self, tools: dict[str, ToolDefinition]):
        self.tools = tools

    @classmethod
    def load(cls, path: Path) -> "ToolCatalog":
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        definitions = [
            ToolDefinition.model_validate(item)
            for item in payload["tools"]
        ]
        tools = {item.id: item for item in definitions}
        if len(tools) != len(definitions):
            raise ValueError("tool IDs must be unique")
        return cls(tools)

    def search(
        self, query: str, category: str | None = None
    ) -> list[ToolDefinition]:
        needle = query.casefold()
        results = []
        for tool in self.tools.values():
            if category and tool.category != category:
                continue
            haystack = (
                f"{tool.id} {tool.title} {tool.description}".casefold()
            )
            if needle in haystack:
                results.append(tool)
        return sorted(results, key=lambda item: item.id)

    def describe(self, tool_id: str) -> ToolDefinition:
        try:
            return self.tools[tool_id]
        except KeyError as error:
            raise ValueError("tool is not allowlisted") from error

    def validate_request(self, tool_id: str, parameters: dict) -> dict:
        definition = self.describe(tool_id)
        try:
            jsonschema.validate(parameters, definition.parameters)
        except jsonschema.ValidationError as error:
            raise ValueError(error.message) from error
        return parameters
