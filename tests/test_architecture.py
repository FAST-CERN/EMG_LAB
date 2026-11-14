"""Enforce the application boundary without importing a desktop toolkit."""

import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_backend_and_contracts_never_import_desktop_code():
    for folder in ("backend", "contracts"):
        for path in (ROOT / "emg_lab" / folder).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
            for node in ast.walk(tree):
                modules = (
                    [node.module or ""]
                    if isinstance(node, ast.ImportFrom)
                    else [alias.name for alias in node.names]
                    if isinstance(node, ast.Import)
                    else []
                )
                for module in modules:
                    assert not module.startswith(("PySide", "PyQt", "emg_lab.frontend")), (
                        path,
                        module,
                    )
                    if folder == "contracts":
                        assert not module.startswith("emg_lab.backend"), (path, module)


def test_frontend_imports_only_ports_and_presentation():
    for path in (ROOT / "emg_lab/frontend").rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("emg_lab.backend"), path
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Attribute):
                if node.value.attr == "backend":
                    assert not node.attr.startswith("_"), (path, node.attr)


def test_service_and_legacy_dds_import_without_qt():
    code = """
import sys
from emg_lab.backend.application import ApplicationService
from emg_lab.robot import DdsBroadcast
from tempfile import TemporaryDirectory
from pathlib import Path
with TemporaryDirectory() as root:
    service=ApplicationService(Path(root),local_root=Path(root)/'logs',background=False)
    service.select_task('hand5')
    assert service.task.selector=='hand5'
    service.close()
assert not any(name.startswith(('PySide6','emg_lab.frontend')) for name in sys.modules)
"""
    subprocess.run([sys.executable, "-c", code], cwd=ROOT, check=True)


def test_page_component_exports_exist_statically():
    components = ast.parse((ROOT / "emg_lab/frontend/components.py").read_text())
    exported = set()
    for node in components.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            exported.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            exported.update(alias.asname or alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.Assign):
            exported.update(target.id for target in node.targets if isinstance(target, ast.Name))
    for path in (ROOT / "emg_lab/frontend").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom) and node.module == "emg_lab.frontend.components":
                assert {alias.name for alias in node.names} <= exported, path
