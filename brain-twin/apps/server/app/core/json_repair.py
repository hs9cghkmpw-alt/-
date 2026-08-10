"""依存フリー(標準ライブラリのみ)。Ollamaの出力(JSON文字列のはず)を
できるだけ寛容に解析し、packages/shared-types/src/thought_split.schema.json に対して
検証する。外部ライブラリ(jsonschema)は追加せず、このスキーマが実際に使う
機能(type/enum/required/properties/additionalProperties/items/$ref/文字列長/配列長/
数値範囲)のみをサポートする軽量な自前バリデータで足りると判断した。"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.core.paths import packages_dir


@dataclass
class ParseResult:
    ok: bool
    data: dict[str, Any] | None = None
    error_summary: str | None = None


@lru_cache(maxsize=1)
def _default_schema() -> dict:
    path = Path(packages_dir()) / "shared-types" / "src" / "thought_split.schema.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _strip_code_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", text)
        if text.endswith("```"):
            text = text[: -len("```")]
    return text.strip()


def _extract_json_object(text: str) -> str | None:
    text = _strip_code_fences(text)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    return text[start : end + 1]


def _try_parse(text: str) -> Any | None:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # 末尾カンマの除去程度の軽い修復のみを試みる(意味を変える大掛かりな修復はしない)。
    repaired = re.sub(r",\s*([}\]])", r"\1", text)
    try:
        return json.loads(repaired)
    except json.JSONDecodeError:
        return None


def _resolve(schema: dict, root: dict) -> dict:
    if "$ref" in schema:
        ref = schema["$ref"]
        if not ref.startswith("#/definitions/"):
            raise ValueError(f"未対応の$ref: {ref}")
        return root["definitions"][ref[len("#/definitions/") :]]
    return schema


def _type_ok(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    return True


def _validate(value: Any, schema: dict, root: dict, path: str, errors: list[str]) -> None:
    schema = _resolve(schema, root)

    expected_types = schema.get("type")
    if expected_types is not None:
        types = expected_types if isinstance(expected_types, list) else [expected_types]
        if not any(_type_ok(value, t) for t in types):
            errors.append(f"{path}: 型が不正です(期待: {types}, 実際: {type(value).__name__})")
            return

    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: 許可されていない値です: {value!r}")
        return

    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append(f"{path}: 文字数が足りません")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errors.append(f"{path}: 文字数が多すぎます")
        if "pattern" in schema and re.match(schema["pattern"], value) is None:
            errors.append(f"{path}: パターンに一致しません")

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: 最小値未満です")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: 最大値超過です")

    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append(f"{path}: 要素数が足りません")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(f"{path}: 要素数が多すぎます")
        item_schema = schema.get("items")
        if item_schema is not None:
            for i, item in enumerate(value):
                _validate(item, item_schema, root, f"{path}[{i}]", errors)

    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}.{key}: 必須項目がありません")
        properties: dict = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            for key in value.keys():
                if key not in properties:
                    errors.append(f"{path}.{key}: 許可されていない項目です")
        for key, sub_schema in properties.items():
            if key in value:
                _validate(value[key], sub_schema, root, f"{path}.{key}", errors)


def validate_against_schema(data: Any, schema: dict) -> list[str]:
    errors: list[str] = []
    _validate(data, schema, schema, "$", errors)
    return errors


def parse_and_validate_thought_split(raw_text: str, schema: dict | None = None) -> ParseResult:
    schema = schema if schema is not None else _default_schema()

    json_text = _extract_json_object(raw_text)
    if json_text is None:
        return ParseResult(ok=False, error_summary="AI出力からJSONオブジェクトを抽出できませんでした")

    data = _try_parse(json_text)
    if data is None:
        return ParseResult(ok=False, error_summary="AI出力のJSON構文が不正です")

    errors = validate_against_schema(data, schema)
    if errors:
        return ParseResult(ok=False, error_summary="AI出力がスキーマに一致しません: " + "; ".join(errors[:5]))

    return ParseResult(ok=True, data=data)
