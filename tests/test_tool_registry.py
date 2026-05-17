from src.tools import ALL_TOOLS
from src.tools.api_caller import ApiCallerTool
from src.tools.code_edit import CodeEditTool
from src.tools.database import DatabaseTool
from src.tools.file_ops import FileOpsTool
from src.tools.notifier import NotifierTool
from src.tools.shell import ShellTool
from src.tools.web_fetch import WebFetchTool


def test_registry_contains_all_seven_tools():
    expected = {
        FileOpsTool,
        ShellTool,
        WebFetchTool,
        CodeEditTool,
        DatabaseTool,
        NotifierTool,
        ApiCallerTool,
    }
    assert expected.issubset(set(ALL_TOOLS))
    # And the registry contains exactly these (no extras yet)
    assert set(ALL_TOOLS) == expected


def test_registry_tool_classes_are_instantiable():
    """Every class in ALL_TOOLS can be instantiated with no required args
    and exposes the required attrs."""
    for cls in ALL_TOOLS:
        instance = cls()
        assert isinstance(instance.name, str) and instance.name
        assert isinstance(instance.description, str) and instance.description
        assert isinstance(instance.parameters_schema, dict)
        assert instance.parameters_schema.get("type") == "object"
        assert instance.risk_level in {"low", "high"}


def test_registry_tool_names_are_unique():
    names = [cls().name for cls in ALL_TOOLS]
    assert len(names) == len(set(names)), f"duplicate tool names: {names}"
