"""명시된 문서와 현재 L7 record로 만드는 비영구 Evidence Context package."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from .lifecycle import LifecycleError, LifecycleService
from .record import DataPathError, normalize_relative_path, paths_overlap, resolve_consumer_path
from .store import InputContractError, RecordNotFoundError


PACKAGE_VERSION = 1
DEFAULT_MAX_CHARACTERS = 12_000
PACKAGE_FIELDS = frozenset(
    {"package_version", "purpose", "settings", "selected", "excluded", "metrics", "fingerprint"}
)
DATA_MARKER = re.compile(
    r"^<!-- project-data:v1 kind=(?P<kind>[a-z][a-z0-9-]*) key=(?P<key>[a-z0-9]+(?:-[a-z0-9]+)*) -->$"
)
FENCE_PATTERN = re.compile(r"^(?P<indent> {0,3})(?P<fence>`{3,}|~{3,})(?P<tail>.*)$")
BLOCK_FIELDS = frozenset({"key", "kind", "status", "source_refs", "payload"})


class EvidenceContextError(InputContractError):
    """Context 요청이나 명시된 문서가 계약을 위반한다."""

    kind = "evidence_context_error"


class EvidenceContextLimitError(EvidenceContextError):
    """직접 선택한 필수 내용만으로 문자 예산을 넘었다."""

    kind = "evidence_context_limit"


def _non_empty(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise EvidenceContextError(f"{field}는 NUL 없는 비어 있지 않은 문자열이어야 한다")
    if value != value.strip():
        raise EvidenceContextError(f"{field} 앞뒤에는 공백을 둘 수 없다")
    return value


def _unique_strings(values: Any, field: str) -> list[str]:
    if not isinstance(values, list):
        raise EvidenceContextError(f"{field}는 문자열 목록이어야 한다")
    rendered = [_non_empty(value, field) for value in values]
    if len(rendered) != len(set(rendered)):
        raise EvidenceContextError(f"{field}에는 중복을 둘 수 없다")
    return rendered


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise EvidenceContextError(f"문서 data block에 중복 JSON key가 있다: {key}")
        result[key] = value
    return result


def _decode_object(raw: str, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            raw,
            object_pairs_hook=_strict_object,
            parse_constant=lambda item: (_ for _ in ()).throw(
                EvidenceContextError(f"{label}에 비유한 숫자가 있다: {item}")
            ),
        )
    except EvidenceContextError:
        raise
    except json.JSONDecodeError as exc:
        raise EvidenceContextError(f"{label}이 유효한 JSON이 아니다") from exc
    if not isinstance(value, dict):
        raise EvidenceContextError(f"{label}은 JSON object여야 한다")
    return value


def _marker_lines(text: str) -> list[tuple[int, re.Match[str]]]:
    markers: list[tuple[int, re.Match[str]]] = []
    active_character: str | None = None
    active_length = 0
    for index, line in enumerate(text.splitlines()):
        fence = FENCE_PATTERN.fullmatch(line)
        if active_character is not None:
            if fence is not None:
                token = fence.group("fence")
                if (
                    token[0] == active_character
                    and len(token) >= active_length
                    and not fence.group("tail").strip()
                ):
                    active_character = None
                    active_length = 0
            continue
        if fence is not None:
            token = fence.group("fence")
            if token[0] != "`" or "`" not in fence.group("tail"):
                active_character = token[0]
                active_length = len(token)
                continue
        if line.startswith(("    ", "\t")):
            continue
        marker = DATA_MARKER.fullmatch(line)
        if marker is not None:
            markers.append((index, marker))
        elif line.startswith("<!-- project-data:v1"):
            raise EvidenceContextError(f"{index + 1}번 줄의 project-data marker가 잘못됐다")
    return markers


def _document_blocks(text: str, owner: str) -> list[dict[str, Any]]:
    lines = text.splitlines()
    blocks: list[dict[str, Any]] = []
    keys: set[str] = set()
    for index, marker in _marker_lines(text):
        if index + 3 >= len(lines) or lines[index + 1] != "```json":
            raise EvidenceContextError(f"{owner}:{index + 1} marker 뒤에는 ```json이 필요하다")
        try:
            fence_end = lines.index("```", index + 2)
        except ValueError as exc:
            raise EvidenceContextError(f"{owner}:{index + 2} JSON fence가 닫히지 않았다") from exc
        if fence_end + 1 >= len(lines) or lines[fence_end + 1] != "<!-- /project-data -->":
            raise EvidenceContextError(f"{owner}:{index + 1} data block 종료 marker가 없다")
        block = _decode_object("\n".join(lines[index + 2 : fence_end]), f"{owner} data block")
        if set(block) != BLOCK_FIELDS:
            raise EvidenceContextError(f"{owner} data block field가 정확하지 않다: {sorted(BLOCK_FIELDS)}")
        key = _non_empty(block["key"], "key")
        kind = _non_empty(block["kind"], "kind")
        status = _non_empty(block["status"], "status")
        if key != marker.group("key") or kind != marker.group("kind"):
            raise EvidenceContextError(f"{owner} marker의 kind/key와 JSON 값이 다르다")
        if key in keys:
            raise EvidenceContextError(f"{owner}에 중복 data_key가 있다: {key}")
        keys.add(key)
        source_refs = _unique_strings(block["source_refs"], "source_refs")
        if not isinstance(block["payload"], Mapping):
            raise EvidenceContextError(f"{owner} data block payload는 object여야 한다")
        blocks.append(
            {
                "key": key,
                "kind": kind,
                "status": status,
                "source_refs": source_refs,
                "payload": dict(block["payload"]),
                "owner": owner,
            }
        )
    return blocks


def _canonical_text(value: Mapping[str, Any]) -> str:
    try:
        return json.dumps(
            dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
    except (TypeError, ValueError) as exc:
        raise EvidenceContextError("context 내용은 유효한 JSON 값이어야 한다") from exc


def _fingerprint(value: Mapping[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(_canonical_text(value).encode("utf-8")).hexdigest()


def _matches_filters(item: Mapping[str, Any], filters: Mapping[str, str]) -> bool:
    content = item.get("data", {})
    payload = content.get("payload", {}) if isinstance(content, Mapping) else {}
    values = {
        "kind": item.get("kind"),
        "record_type": item.get("record_type"),
        "state": item.get("state"),
        "data_kind": item.get("data_kind"),
        "status": item.get("status"),
        "scope": payload.get("scope") if isinstance(payload, Mapping) else None,
        "verification_status": payload.get("verification_status")
        if isinstance(payload, Mapping)
        else None,
        "evidence_role": payload.get("evidence_role") if isinstance(payload, Mapping) else None,
    }
    return all(values.get(key) == expected for key, expected in filters.items())


def _item_key(item: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(item.get("kind", "")),
        str(item.get("ref", "")),
        str(item.get("data_key", item.get("record_id", ""))),
    )


class EvidenceContextService:
    """전체 저장소를 탐색하지 않고 호출자가 지목한 evidence만 묶는다."""

    def __init__(self, lifecycle: LifecycleService) -> None:
        if not isinstance(lifecycle, LifecycleService):
            raise EvidenceContextError("EvidenceContextService에는 LifecycleService가 필요하다")
        self.lifecycle = lifecycle
        self.store = lifecycle.store

    def _document_target(self, ref: str) -> tuple[Path, str]:
        try:
            relative = normalize_relative_path(ref, label="document ref")
            if relative.suffix.lower() != ".md":
                raise DataPathError("document ref는 Markdown 파일이어야 한다")
            if paths_overlap(relative, self.store.storage_root):
                raise DataPathError("document ref가 Runtime storage와 겹친다")
            target = resolve_consumer_path(
                self.store.root, relative, protected_paths=self.store.protected_paths
            )
        except DataPathError as exc:
            raise EvidenceContextError(str(exc)) from exc
        if not target.is_file():
            raise EvidenceContextError(f"명시한 document가 없다: {relative.as_posix()}")
        return target, relative.as_posix()

    def _read_document(self, ref: str) -> tuple[str, str]:
        target, normalized = self._document_target(ref)
        try:
            raw = target.read_bytes()
        except OSError as exc:
            raise EvidenceContextError(f"document를 읽을 수 없다: {normalized}") from exc
        if raw.startswith(b"\xef\xbb\xbf"):
            raise EvidenceContextError(f"document에 UTF-8 BOM을 사용할 수 없다: {normalized}")
        if b"\x00" in raw:
            raise EvidenceContextError(f"document에 NUL이 있다: {normalized}")
        try:
            return raw.decode("utf-8", "strict"), normalized
        except UnicodeDecodeError as exc:
            raise EvidenceContextError(f"document가 strict UTF-8이 아니다: {normalized}") from exc

    def _document_item(self, ref: str, *, data_key: str | None, reason: str) -> dict[str, Any]:
        text, normalized = self._read_document(ref)
        if data_key is None:
            return {
                "kind": "document",
                "ref": normalized,
                "reason": reason,
                "content": text,
                "characters": len(text),
            }
        key = _non_empty(data_key, "data_key")
        matches = [block for block in _document_blocks(text, normalized) if block["key"] == key]
        if len(matches) != 1:
            raise EvidenceContextError(
                f"{normalized}에서 data_key {key}를 정확히 하나 찾아야 한다: {len(matches)}"
            )
        block = matches[0]
        data = {name: block[name] for name in ("key", "kind", "status", "source_refs", "payload")}
        content = _canonical_text(data)
        return {
            "kind": "document_data",
            "ref": normalized,
            "data_key": key,
            "data_kind": block["kind"],
            "status": block["status"],
            "reason": reason,
            "source_refs": block["source_refs"],
            "data": data,
            "content": content,
            "characters": len(content),
        }

    def _record_item(self, record_id: str, *, reason: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        try:
            state = self.lifecycle.get_state(record_id)
        except (RecordNotFoundError, LifecycleError) as exc:
            raise EvidenceContextError(f"record 또는 lifecycle 상태를 읽을 수 없다: {record_id}") from exc
        if state["payload"]["state"] != "current":
            return None, {"kind": "record", "ref": f"record:{record_id}", "reason": "not_current"}
        record = self.store.get_record(record_id)
        content = _canonical_text(record)
        return (
            {
                "kind": "record",
                "ref": f"record:{record_id}",
                "record_id": record_id,
                "record_type": record["record_type"],
                "state": "current",
                "reason": reason,
                "data": record,
                "content": content,
                "characters": len(content),
            },
            None,
        )

    def build(
        self,
        *,
        purpose: str,
        documents: Sequence[Mapping[str, Any]] = (),
        record_ids: Sequence[str] = (),
        candidate_documents: Sequence[str] = (),
        search: str | None = None,
        filters: Mapping[str, str] | None = None,
        max_characters: int = DEFAULT_MAX_CHARACTERS,
    ) -> dict[str, Any]:
        """직접 선택을 우선하고 명시한 후보 안에서만 검색해 package를 만든다."""

        purpose = _non_empty(purpose, "purpose")
        if isinstance(max_characters, bool) or not isinstance(max_characters, int) or max_characters < 1:
            raise EvidenceContextError("max_characters는 1 이상의 정수여야 한다")
        query = None if search is None else _non_empty(search, "search")
        normalized_filters: dict[str, str] = {}
        allowed_filters = {
            "kind", "record_type", "state", "data_kind", "status", "scope",
            "verification_status", "evidence_role",
        }
        if filters is not None:
            if not isinstance(filters, Mapping) or any(key not in allowed_filters for key in filters):
                raise EvidenceContextError(f"지원하지 않는 filter가 있다: {sorted(set(filters) - allowed_filters)}")
            normalized_filters = {
                _non_empty(key, "filter key"): _non_empty(value, f"filters.{key}")
                for key, value in filters.items()
            }

        selected: list[dict[str, Any]] = []
        excluded: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str]] = set()
        used = 0

        def include(item: dict[str, Any], *, required: bool) -> None:
            nonlocal used
            key = _item_key(item)
            if key in seen:
                return
            seen.add(key)
            projected = used + item["characters"]
            if projected > max_characters:
                if required:
                    raise EvidenceContextLimitError(
                        f"직접 선택 내용이 문자 예산을 넘는다: {projected}/{max_characters}"
                    )
                excluded.append({"kind": item["kind"], "ref": item["ref"], "reason": "size_limit"})
                return
            selected.append(item)
            used = projected

        for selection in documents:
            if not isinstance(selection, Mapping) or set(selection) - {"ref", "data_key"} or "ref" not in selection:
                raise EvidenceContextError("documents 항목은 ref와 선택적 data_key만 가져야 한다")
            include(
                self._document_item(
                    _non_empty(selection["ref"], "documents.ref"),
                    data_key=selection.get("data_key"),
                    reason="direct",
                ),
                required=True,
            )
        for record_id in record_ids:
            item, omission = self._record_item(_non_empty(record_id, "record_id"), reason="direct")
            if omission is not None:
                excluded.append(omission)
            elif item is not None:
                include(item, required=True)

        candidates: list[dict[str, Any]] = []
        if query is not None or normalized_filters:
            catalog = _unique_strings(list(candidate_documents), "candidate_documents")
            for ref in sorted(catalog):
                text, normalized = self._read_document(ref)
                for block in _document_blocks(text, normalized):
                    if block["status"] != "current":
                        continue
                    candidates.append(
                        self._document_item(
                            normalized, data_key=block["key"], reason="search_or_filter"
                        )
                    )
            for record in self.lifecycle.current_records():
                item, _ = self._record_item(record["id"], reason="search_or_filter")
                if item is not None:
                    candidates.append(item)
            query_folded = query.casefold() if query is not None else None
            for item in sorted(candidates, key=_item_key):
                if normalized_filters and not _matches_filters(item, normalized_filters):
                    continue
                if query_folded is not None and query_folded not in item["content"].casefold():
                    continue
                include(item, required=False)

        selected.sort(key=_item_key)
        excluded.sort(key=_item_key)
        body: dict[str, Any] = {
            "package_version": PACKAGE_VERSION,
            "purpose": purpose,
            "settings": {
                "max_characters": max_characters,
                "search": query,
                "filters": dict(sorted(normalized_filters.items())),
                "candidate_documents": sorted(set(candidate_documents)),
            },
            "selected": selected,
            "excluded": excluded,
            "metrics": {
                "selected_items": len(selected),
                "selected_characters": used,
                "excluded_items": len(excluded),
            },
        }
        body["fingerprint"] = _fingerprint(body)
        return body


def validate_context_package(package: Mapping[str, Any]) -> None:
    """저장·전송 전 v1 package의 구조와 fingerprint를 다시 확인한다."""

    if not isinstance(package, Mapping) or set(package) != PACKAGE_FIELDS:
        raise EvidenceContextError(f"context package field가 정확하지 않다: {sorted(PACKAGE_FIELDS)}")
    if type(package["package_version"]) is not int or package["package_version"] != PACKAGE_VERSION:
        raise EvidenceContextError(f"package_version은 {PACKAGE_VERSION}이어야 한다")
    if not isinstance(package["purpose"], str) or not package["purpose"]:
        raise EvidenceContextError("purpose는 비어 있지 않은 문자열이어야 한다")
    settings = package["settings"]
    if not isinstance(settings, dict) or set(settings) != {"max_characters", "search", "filters", "candidate_documents"}:
        raise EvidenceContextError("settings field가 정확하지 않다")
    if type(settings["max_characters"]) is not int or settings["max_characters"] < 1:
        raise EvidenceContextError("max_characters는 양의 정수여야 한다")
    if settings["search"] is not None and not isinstance(settings["search"], str):
        raise EvidenceContextError("search는 문자열 또는 null이어야 한다")
    filters = settings["filters"]
    if not isinstance(filters, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in filters.items()):
        raise EvidenceContextError("filters는 문자열 key/value object여야 한다")
    candidates = settings["candidate_documents"]
    if not isinstance(candidates, list) or any(not isinstance(v, str) for v in candidates) or len(candidates) != len(set(candidates)):
        raise EvidenceContextError("candidate_documents는 중복 없는 문자열 배열이어야 한다")
    for field in ("selected", "excluded"):
        if not isinstance(package[field], list) or any(not isinstance(v, dict) for v in package[field]):
            raise EvidenceContextError(f"{field}는 object 배열이어야 한다")
    metrics = package["metrics"]
    if not isinstance(metrics, dict) or set(metrics) != {"selected_items", "selected_characters", "excluded_items"}:
        raise EvidenceContextError("metrics field가 정확하지 않다")
    if any(type(v) is not int or v < 0 for v in metrics.values()):
        raise EvidenceContextError("metrics 값은 음수가 아닌 정수여야 한다")
    if not isinstance(package["fingerprint"], str) or re.fullmatch(r"sha256:[0-9a-f]{64}", package["fingerprint"]) is None:
        raise EvidenceContextError("fingerprint 형식이 정확하지 않다")
    try:
        expected = _fingerprint({key: value for key, value in package.items() if key != "fingerprint"})
    except (TypeError, ValueError) as exc:
        raise EvidenceContextError("context package가 유효한 JSON이 아니다") from exc
    if package["fingerprint"] != expected:
        raise EvidenceContextError("context package fingerprint가 내용과 다르다")
