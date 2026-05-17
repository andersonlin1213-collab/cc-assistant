from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field


class TextBlock(BaseModel):
    type: Literal["text"] = "text"
    text: str


class ToolUseBlock(BaseModel):
    type: Literal["tool_use"] = "tool_use"
    id: str
    name: str
    input: dict


class ToolResultBlock(BaseModel):
    type: Literal["tool_result"] = "tool_result"
    tool_use_id: str
    content: str
    is_error: bool = False


# Blocks that can appear in a message sent TO the model
ContentBlock = Annotated[
    Union[TextBlock, ToolUseBlock, ToolResultBlock],
    Field(discriminator="type"),
]

# Blocks that can appear in a response FROM the model
ResponseBlock = Annotated[
    Union[TextBlock, ToolUseBlock],
    Field(discriminator="type"),
]


class Message(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: Union[str, list[ContentBlock]]


class ToolDefinition(BaseModel):
    name: str
    description: str
    input_schema: dict


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0


class LLMResponse(BaseModel):
    content: list[ResponseBlock]
    stop_reason: str  # "end_turn" | "tool_use" | "max_tokens" | "stop_sequence"
    usage: Usage
    model: str
