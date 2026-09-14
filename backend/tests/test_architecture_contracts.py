import ast
from pathlib import Path


APP_ROOT = Path(__file__).parents[1] / "app"


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_application_layer_does_not_import_http_or_llm_sdk() -> None:
    application_files = [
        APP_ROOT / "models.py",
        APP_ROOT / "repository.py",
        APP_ROOT / "service.py",
        *sorted((APP_ROOT / "memory").glob("*.py")),
    ]

    for path in application_files:
        imports = imported_modules(path)
        assert not any(
            name == "fastapi" or name.startswith("fastapi.")
            for name in imports
        ), path
        assert not any(
            name == "openai" or name.startswith("openai.")
            for name in imports
        ), path


def test_agent_loop_depends_on_provider_contract_not_deepseek_adapter() -> None:
    imports = imported_modules(APP_ROOT / "agent" / "service.py")

    assert "app.llm.provider" in imports
    assert "app.tools.registry" in imports
    assert "app.llm.deepseek" not in imports
    assert not any(name == "openai" or name.startswith("openai.") for name in imports)


def test_tool_handlers_do_not_access_sqlalchemy_directly() -> None:
    for path in sorted((APP_ROOT / "tools").glob("*.py")):
        imports = imported_modules(path)
        assert not any(
            name == "sqlalchemy" or name.startswith("sqlalchemy.")
            for name in imports
        ), path
