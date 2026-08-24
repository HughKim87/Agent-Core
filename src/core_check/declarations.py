"""Core와 소비 저장소의 기계 판독 선언 해석기.

Core 역할 선언은 Core 안에서, 소비 계약은 소비 저장소의 선언된 정책 파일
한 곳에서만 읽는다. 부모 저장소와 submodule을 한 트리로 재귀 검색하지 않는다.
"""

from __future__ import annotations

from collections.abc import Iterable
import json
from pathlib import Path
import re

from .primitives import CheckError, resolve_inside

MD_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
DOCUMENT_ROLES_BLOCK = re.compile(
    r"<!--\s*core-document-roles:v2\s*-->\s*```json\s*(.*?)```", re.S
)
MODULE_LAYERS_BLOCK = re.compile(
    r"<!--\s*core-module-layers:v1\s*-->\s*```json\s*(.*?)```", re.S
)
RULE_ROUTES_BLOCK = re.compile(
    r"<!--\s*core-rule-routes:v1\s*-->(.*?)<!--\s*/core-rule-routes:v1\s*-->", re.S
)
CONSUMER_CONTRACT_BLOCK = re.compile(
    r"<!--\s*agent-core-consumer:v1\s*-->\s*```json\s*(.*?)```"
    r"\s*<!--\s*/agent-core-consumer:v1\s*-->",
    re.S,
)
COMPAT_BLOCK = re.compile(
    r"<!--\s*core-compatibility:v1\s*-->\s*```json\s*(.*?)```", re.S
)
SKIP_DIRS = {".git", "tmp", "__pycache__", ".obsidian"}
COMPATIBILITY_FIELDS = frozenset(
    {
        "core_version",
        "contract_version",
        "python_min",
        "required_dependencies",
        "optional_dependencies",
        "optional_capabilities",
    }
)
OPTIONAL_CAPABILITY_FIELDS = frozenset(
    {"version", "entry_module", "commands", "request_schema", "result_schema", "schemas"}
)


def walk_markdown(root: Path, *, excluded_roots: Iterable[Path] = ()) -> Iterable[Path]:
    root = root.resolve()
    excluded = [path.resolve() for path in excluded_roots]
    for path in sorted(root.rglob("*.md")):
        resolved = path.resolve()
        if any(base == resolved or base in resolved.parents for base in excluded):
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        yield path


def _json_object(payload: str, label: str, source: Path) -> dict[str, object]:
    try:
        value = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise CheckError(f"{source}의 {label} JSON이 잘못됐다: {exc}") from exc
    if not isinstance(value, dict):
        raise CheckError(f"{label} 선언은 객체여야 한다")
    return value


def _single_json_declaration(root: Path, pattern: re.Pattern[str], label: str) -> dict[str, object]:
    matches: list[tuple[Path, str]] = []
    for path in walk_markdown(root):
        for match in pattern.finditer(path.read_text(encoding="utf-8")):
            matches.append((path, match.group(1)))
    if len(matches) != 1:
        raise CheckError(f"{label} 선언이 {len(matches)}개다")
    path, payload = matches[0]
    return _json_object(payload, label, path)


def _relative_path(root: Path, value: object, label: str, *, must_exist: str | None = None) -> Path:
    if not isinstance(value, str) or not value:
        raise CheckError(f"{label}이 유효한 상대경로가 아니다")
    candidate = Path(value)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise CheckError(f"{label}은 선언된 뿌리 안쪽의 상대경로여야 한다: {value}")
    resolved = resolve_inside(root, candidate)
    if must_exist == "file" and not resolved.is_file():
        raise CheckError(f"{label} 파일이 없다: {value}")
    if must_exist == "dir" and not resolved.is_dir():
        raise CheckError(f"{label} 디렉터리가 없다: {value}")
    return resolved


def optional_capability_installation_state(
    core_root: Path, capability_id: str, declaration: dict[str, object]
) -> str:
    """선택 기능의 완전 설치·완전 부재를 구분하고 부분 결손을 거부한다."""
    module = declaration["entry_module"]
    module_root = _relative_path(
        core_root, str(module).replace(".", "/"), f"{capability_id}.entry_module"
    )
    artifacts: list[tuple[Path, str]] = [
        (module_root, "dir"),
        (module_root / "__main__.py", "file"),
    ]
    for field in ("request_schema", "result_schema"):
        artifacts.append(
            (_relative_path(core_root, declaration[field], f"{capability_id}.{field}"), "file")
        )
    for schema in declaration["schemas"]:  # type: ignore[union-attr]
        artifacts.append(
            (_relative_path(core_root, schema, f"{capability_id}.schemas"), "file")
        )

    present = [path.is_dir() if kind == "dir" else path.is_file() for path, kind in artifacts]
    if not any(present):
        return "absent"
    missing = [
        path.relative_to(core_root).as_posix()
        for (path, _kind), exists in zip(artifacts, present)
        if not exists
    ]
    if missing:
        raise CheckError(f"{capability_id} 선택 기능이 부분 설치 상태다: {missing}")
    return "installed"


def document_roles(core_root: Path) -> dict[str, object]:
    roles = _single_json_declaration(core_root, DOCUMENT_ROLES_BLOCK, "Core 문서 역할")
    _relative_path(core_root, roles.get("core_policy"), "Core 정책", must_exist="file")
    consumer_policy = roles.get("consumer_policy")
    if not isinstance(consumer_policy, str) or not consumer_policy:
        raise CheckError("소비 정책 기본 경로가 유효하지 않다")
    candidate = Path(consumer_policy)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise CheckError("소비 정책 기본 경로는 상대경로여야 한다")
    return roles


def module_layers(core_root: Path) -> dict[str, list[str]]:
    raw = _single_json_declaration(core_root, MODULE_LAYERS_BLOCK, "모듈 계층")
    layers: dict[str, list[str]] = {}
    for layer in ("L5", "L6", "L7"):
        paths = raw.get(layer)
        if not isinstance(paths, list) or not all(isinstance(p, str) and p for p in paths):
            raise CheckError(f"모듈 계층 {layer}는 경로 배열이어야 한다")
        layers[layer] = list(paths)
    return layers


def core_policy_path(core_root: Path) -> Path:
    value = document_roles(core_root).get("core_policy")
    return _relative_path(core_root, value, "Core 정책", must_exist="file")


def consumer_policy_path(core_root: Path, consumer_root: Path) -> Path:
    value = document_roles(core_root).get("consumer_policy")
    return _relative_path(consumer_root, value, "소비 정책", must_exist="file")


def role_path(core_root: Path, role: str) -> Path:
    """v2 내부 호환 helper. Core가 소유하는 역할만 반환한다."""
    if role in {"policy", "core_policy"}:
        return core_policy_path(core_root)
    raise CheckError(f"Core가 소유하지 않는 문서 역할이다: {role}")


def _route_targets(policy: Path) -> list[str]:
    matches = list(RULE_ROUTES_BLOCK.finditer(policy.read_text(encoding="utf-8")))
    if len(matches) != 1:
        raise CheckError(f"{policy}의 규칙 route 선언이 {len(matches)}개다")
    return MD_LINK.findall(matches[0].group(1))


def routed_rule_paths(core_root: Path) -> list[str]:
    return [target for target in _route_targets(core_policy_path(core_root)) if target.startswith("rules/")]


def consumer_routed_rule_paths(core_root: Path, consumer_root: Path) -> list[str]:
    contract = consumer_contract(core_root, consumer_root)
    roots = tuple(f"{Path(value).as_posix().rstrip('/')}/" for value in contract["rule_roots"])
    targets = _route_targets(consumer_policy_path(core_root, consumer_root))
    invalid = [target for target in targets if not target.startswith(roots)] if roots else targets
    if invalid:
        raise CheckError(f"소비 route가 선언된 rule_roots 밖을 가리킨다: {invalid}")
    return targets


def consumer_contract(core_root: Path, consumer_root: Path) -> dict[str, object]:
    core_root = core_root.resolve()
    consumer_root = consumer_root.resolve()
    policy = consumer_policy_path(core_root, consumer_root)
    matches = list(CONSUMER_CONTRACT_BLOCK.finditer(policy.read_text(encoding="utf-8")))
    if len(matches) != 1:
        raise CheckError(f"소비 계약 선언이 {len(matches)}개다: {policy}")
    contract = _json_object(matches[0].group(1), "소비 계약", policy)

    version = contract.get("contract_version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise CheckError("contract_version은 양의 정수여야 한다")
    if contract.get("consumer_role") not in {"maintainer", "host"}:
        raise CheckError("consumer_role은 maintainer 또는 host여야 한다")

    declared_core = _relative_path(
        consumer_root, contract.get("core_path"), "core_path", must_exist="dir"
    )
    if declared_core != core_root:
        raise CheckError("실행 Core와 소비 계약의 core_path가 다르다")
    state = _relative_path(consumer_root, contract.get("state"), "state", must_exist="file")

    pointers = contract.get("entry_pointers")
    if not isinstance(pointers, dict) or set(pointers) != {"codex", "claude"}:
        raise CheckError("entry_pointers는 codex와 claude 경로를 가져야 한다")
    pointer_paths = [
        _relative_path(consumer_root, value, f"entry_pointers.{agent}", must_exist="file")
        for agent, value in pointers.items()
    ]

    rule_roots = contract.get("rule_roots")
    if not isinstance(rule_roots, list) or not all(isinstance(p, str) and p for p in rule_roots):
        raise CheckError("rule_roots는 상대경로 배열이어야 한다")
    rule_root_paths = [
        _relative_path(consumer_root, value, "rule_roots", must_exist="dir")
        for value in rule_roots
    ]

    required_capabilities = contract.get("required_core_capabilities", {})
    if not isinstance(required_capabilities, dict):
        raise CheckError("required_core_capabilities는 object여야 한다")
    for capability_id, minimum_version in required_capabilities.items():
        if (
            not isinstance(capability_id, str)
            or re.fullmatch(r"[a-z][a-z0-9_]*", capability_id) is None
        ):
            raise CheckError(f"요구 선택 기능 ID가 lower snake case가 아니다: {capability_id}")
        if (
            isinstance(minimum_version, bool)
            or not isinstance(minimum_version, int)
            or minimum_version < 1
        ):
            raise CheckError(f"required_core_capabilities.{capability_id}는 양의 정수여야 한다")
    contract["required_core_capabilities"] = dict(required_capabilities)

    protected = contract.get("protected_paths")
    if not isinstance(protected, list) or not all(isinstance(p, str) and p for p in protected):
        raise CheckError("protected_paths는 상대경로 배열이어야 한다")
    protected_paths = [
        _relative_path(consumer_root, value, "protected_paths") for value in protected
    ]
    contract_surface = [policy, declared_core, state, *pointer_paths, *rule_root_paths]
    for protected_path in protected_paths:
        if any(
            protected_path == owned
            or protected_path in owned.parents
            or owned in protected_path.parents
            for owned in contract_surface
        ):
            raise CheckError(
                "protected_paths는 Core·정책·상태·진입 포인터·rule_roots와 겹칠 수 없다"
            )
    return contract


def declared_compatibility(core_root: Path) -> dict[str, object]:
    matches: list[tuple[Path, str]] = []
    docs = core_root / "docs"
    for path in sorted(docs.glob("*.md")) if docs.is_dir() else []:
        for match in COMPAT_BLOCK.finditer(path.read_text(encoding="utf-8")):
            matches.append((path, match.group(1)))
    if len(matches) != 1:
        raise CheckError(f"호환성 선언이 {len(matches)}개다")
    path, payload = matches[0]
    declaration = _json_object(payload, "호환성", path)
    if set(declaration) != COMPATIBILITY_FIELDS:
        raise CheckError(f"호환성 field가 정확하지 않다: {sorted(COMPATIBILITY_FIELDS)}")
    if not isinstance(declaration["core_version"], str) or not re.fullmatch(
        r"\d+\.\d+\.\d+", declaration["core_version"]
    ):
        raise CheckError("core_version은 major.minor.patch 형식이어야 한다")
    version = declaration["contract_version"]
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise CheckError("contract_version은 양의 정수여야 한다")
    minimum = declaration["python_min"]
    if not isinstance(minimum, str) or re.fullmatch(r"\d+\.\d+", minimum) is None:
        raise CheckError("python_min은 major.minor 형식이어야 한다")
    for field in ("required_dependencies", "optional_dependencies"):
        values = declaration[field]
        if not isinstance(values, list) or not all(isinstance(item, str) and item for item in values):
            raise CheckError(f"{field}는 문자열 목록이어야 한다")
        if len(values) != len(set(values)):
            raise CheckError(f"{field}에는 중복을 둘 수 없다")
    capabilities = declaration["optional_capabilities"]
    if not isinstance(capabilities, dict):
        raise CheckError("optional_capabilities는 object여야 한다")
    for capability_id, raw in capabilities.items():
        if not isinstance(capability_id, str) or re.fullmatch(r"[a-z][a-z0-9_]*", capability_id) is None:
            raise CheckError(f"선택 기능 ID가 lower snake case가 아니다: {capability_id}")
        if not isinstance(raw, dict) or set(raw) != OPTIONAL_CAPABILITY_FIELDS:
            raise CheckError(
                f"{capability_id} 선택 기능 field가 정확하지 않다: {sorted(OPTIONAL_CAPABILITY_FIELDS)}"
            )
        capability_version = raw["version"]
        if isinstance(capability_version, bool) or not isinstance(capability_version, int) or capability_version < 1:
            raise CheckError(f"{capability_id}.version은 양의 정수여야 한다")
        module = raw["entry_module"]
        if not isinstance(module, str) or re.fullmatch(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*", module) is None:
            raise CheckError(f"{capability_id}.entry_module이 유효하지 않다")
        _relative_path(core_root, module.replace(".", "/"), f"{capability_id}.entry_module")
        commands = raw["commands"]
        if (
            not isinstance(commands, list)
            or not commands
            or not all(isinstance(item, str) and item for item in commands)
            or len(commands) != len(set(commands))
        ):
            raise CheckError(f"{capability_id}.commands는 중복 없는 문자열 목록이어야 한다")
        for field in ("request_schema", "result_schema"):
            _relative_path(core_root, raw[field], f"{capability_id}.{field}")
        schemas = raw["schemas"]
        if (
            not isinstance(schemas, list)
            or not schemas
            or not all(isinstance(item, str) and item for item in schemas)
            or len(schemas) != len(set(schemas))
        ):
            raise CheckError(f"{capability_id}.schemas는 중복 없는 schema 경로 목록이어야 한다")
        for schema in schemas:
            _relative_path(core_root, schema, f"{capability_id}.schemas")
        optional_capability_installation_state(core_root, capability_id, raw)
    return declaration
