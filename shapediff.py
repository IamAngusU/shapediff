#!/usr/bin/env python3
"""ShapeDiff: evidence-aware comparison of observed JSON response structures.

Run directly with Python 3.10+ or install the console entry point. No runtime
packages, remote services, telemetry, or files written during comparison.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from html import escape as html_escape
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any, Iterable, Sequence
from urllib.parse import urlsplit

__version__ = "0.1.0a4"

ERROR = "ERROR"
WARN = "WARN"
INFO = "INFO"
ARRAY = object()
MAP_VALUE = object()
EMPTY_LINE = object()
PathTokens = tuple[object, ...]
_IDENT = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")
_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATETIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$")
_EXTENSIONS = frozenset((".json", ".jsonl", ".ndjson"))
_HEADER_NAME = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")


class InputError(Exception):
    """Expected invalid or unsupported user input."""


@dataclass
class Field:
    shape: Shape = field(default_factory=lambda: Shape())
    present: int = 0


@dataclass
class Shape:
    kinds: Counter[str] = field(default_factory=Counter)
    fields: dict[str, Field] = field(default_factory=dict)
    objects: int = 0
    elements: Shape | None = None
    array_items: int = 0
    map_values: Shape | None = None
    map_items: int = 0
    string_formats: Counter[str] = field(default_factory=Counter)


@dataclass(frozen=True)
class Options:
    ignore: tuple[tuple[str, ...], ...] = ()
    maps: tuple[tuple[str, ...], ...] = ()
    strict_integers: bool = False
    formats: bool = False
    coverage_drop: float | None = None
    min_coverage_objects: int = 3
    max_depth: int = 128
    max_document_bytes: int = 32 * 1024 * 1024
    max_samples: int = 100000
    max_shape_nodes: int = 250000
    recursive: bool = False
    stdin_format: str = "json"


@dataclass
class Dataset:
    label: str
    shape: Shape = field(default_factory=Shape)
    documents: int = 0
    files: int = 0
    bytes_read: int = 0
    object_observations: int = 0
    array_elements: int = 0
    shape_nodes: int = 1
    matched_maps: set[tuple[str, ...]] = field(default_factory=set)

    def metadata(self) -> dict[str, object]:
        return {
            "source": self.label,
            "documents": self.documents,
            "files": self.files,
            "bytes_read": self.bytes_read,
            "object_observations": self.object_observations,
            "array_elements": self.array_elements,
            "shape_nodes": self.shape_nodes,
        }


@dataclass(frozen=True)
class Finding:
    level: str
    code: str
    path: PathTokens
    message: str
    baseline: dict[str, object] = field(default_factory=dict)
    current: dict[str, object] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {
            "level": self.level,
            "code": self.code,
            "path": render_path(self.path),
            "pointer": render_pointer(self.path),
            "message": self.message,
            "baseline": self.baseline,
            "current": self.current,
        }


def kind_of(value: Any, strict_integers: bool) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "integer" if strict_integers and isinstance(value, int) else "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    raise InputError(f"unsupported JSON value: {type(value).__name__}")


def detect_string_format(value: str) -> str:
    if len(value) > 256:
        return "plain"
    if _UUID.fullmatch(value):
        return "uuid"
    if _DATETIME.fullmatch(value):
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            return "date-time"
        except ValueError:
            pass
    if _DATE.fullmatch(value):
        try:
            date.fromisoformat(value)
            return "date"
        except ValueError:
            pass
    if _EMAIL.fullmatch(value):
        return "email"
    if value.startswith(("https://", "http://")):
        try:
            parsed = urlsplit(value)
            if parsed.netloc and not any(ch.isspace() for ch in value):
                return "url"
        except ValueError:
            pass
    return "plain"


def _decode_segment(part: str) -> str:
    if re.search(r"~(?![01])", part):
        raise InputError("invalid selector escape: use ~0 for ~ and ~1 for /")
    return part.replace("~1", "/").replace("~0", "~")


def parse_selector(raw: str) -> tuple[str, ...]:
    """JSON Pointer-style selectors; '*' and '**' are complete-segment globs."""
    if raw == "":
        return ()
    if raw.startswith("/"):
        return tuple(_decode_segment(part) for part in raw[1:].split("/"))
    dot_pattern = (
        r"[A-Za-z_$][A-Za-z0-9_$]*(?:\[\*\])?"
        r"(?:\.[A-Za-z_$][A-Za-z0-9_$]*(?:\[\*\])?)*"
    )
    if re.fullmatch(dot_pattern, raw):
        bits = re.findall(r"\[\*\]|[A-Za-z_$][A-Za-z0-9_$]*", raw)
        return tuple("*" if bit == "[*]" else bit for bit in bits)
    raise InputError(f"invalid selector {raw!r}; use JSON Pointer syntax, e.g. /items/*/etag")


def selector_matches(path: PathTokens, spec: tuple[str, ...]) -> bool:
    """Match a full path, including a '**' selector spanning zero+ segments."""
    memo: dict[tuple[int, int], bool] = {}

    def visit(i: int, j: int) -> bool:
        key = (i, j)
        if key in memo:
            return memo[key]
        if j == len(spec):
            answer = i == len(path)
        elif spec[j] == "**":
            answer = visit(i, j + 1) or (i < len(path) and visit(i + 1, j))
        elif i == len(path):
            answer = False
        else:
            token = path[i]
            matched = spec[j] == "*" or (isinstance(token, str) and token == spec[j])
            answer = matched and visit(i + 1, j + 1)
        memo[key] = answer
        return answer

    return visit(0, 0)


def is_ignored(path: PathTokens, opts: Options) -> bool:
    # An ignored parent also covers every descendant; observation is skipped there.
    return any(selector_matches(path[:i], p) for p in opts.ignore for i in range(len(path) + 1))


def new_shape(opts: Options, stats: Dataset) -> Shape:
    stats.shape_nodes += 1
    if stats.shape_nodes > opts.max_shape_nodes:
        raise InputError(
            f"shape exceeds --max-shape-nodes {opts.max_shape_nodes}; "
            "add --map or --ignore for dynamic keys"
        )
    return Shape()


def observe(
    shape: Shape, value: Any, path: PathTokens,
    opts: Options, stats: Dataset, depth: int = 0,
) -> None:
    if depth > opts.max_depth:
        raise InputError(f"JSON nesting exceeds --max-depth {opts.max_depth} at {render_path(path)}")
    kind = kind_of(value, opts.strict_integers)
    shape.kinds[kind] += 1
    if kind == "string" and opts.formats:
        shape.string_formats[detect_string_format(value)] += 1
    if kind == "object":
        shape.objects += 1
        stats.object_observations += 1
        mapped = tuple(p for p in opts.maps if selector_matches(path, p))
        if mapped:
            stats.matched_maps.update(mapped)
            if shape.map_values is None:
                shape.map_values = new_shape(opts, stats)
            for key, item in value.items():
                _ = key
                child_path = path + (MAP_VALUE,)
                if not is_ignored(child_path, opts):
                    observe(shape.map_values, item, child_path, opts, stats, depth + 1)
                    shape.map_items += 1
            return
        for key, item in value.items():
            child_path = path + (key,)
            if is_ignored(child_path, opts):
                continue
            current = shape.fields.get(key)
            if current is None:
                current = Field(shape=new_shape(opts, stats))
                shape.fields[key] = current
            current.present += 1
            observe(current.shape, item, child_path, opts, stats, depth + 1)
    elif kind == "array":
        if shape.elements is None:
            shape.elements = new_shape(opts, stats)
        for item in value:
            child_path = path + (ARRAY,)
            if not is_ignored(child_path, opts):
                observe(shape.elements, item, child_path, opts, stats, depth + 1)
                shape.array_items += 1
                stats.array_elements += 1


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if any(0xD800 <= ord(char) <= 0xDFFF for char in key):
            raise InputError("JSON object key contains an invalid Unicode surrogate")
        if key in result:
            raise InputError(f"duplicate JSON object key: {key!r}")
        result[key] = value
    return result


def _reject_constant(name: str) -> None:
    raise InputError(f"non-standard JSON numeric constant: {name}")


def parse_json_document(text: str, label: str) -> Any:
    try:
        return json.loads(text, object_pairs_hook=_reject_duplicate_keys, parse_constant=_reject_constant)
    except json.JSONDecodeError as exc:
        raise InputError(
            f"{label}: invalid JSON at line {exc.lineno}, "
            f"column {exc.colno}: {exc.msg}"
        ) from exc
    except (RecursionError, OverflowError, ValueError) as exc:
        raise InputError(f"{label}: JSON decoder rejected document: {exc}") from exc


def _read_document(stream: Any, label: str, limit: int) -> tuple[Any, int]:
    raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise InputError(f"{label}: exceeds --max-document-mib limit")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise InputError(f"{label}: input must be UTF-8 ({exc})") from exc
    return parse_json_document(text, label), len(raw)


def _jsonl_documents(stream: Any, label: str, limit: int) -> Iterable[tuple[Any, int]]:
    for line_no, raw in enumerate(iter(lambda: stream.readline(limit + 1), b""), 1):
        if len(raw) > limit:
            raise InputError(f"{label}:{line_no}: line exceeds --max-document-mib limit")
        if not raw.strip():
            yield EMPTY_LINE, len(raw)
            continue
        try:
            text = raw.decode("utf-8-sig" if line_no == 1 else "utf-8")
        except UnicodeDecodeError as exc:
            raise InputError(f"{label}:{line_no}: input must be UTF-8 ({exc})") from exc
        yield parse_json_document(text, f"{label}:{line_no}"), len(raw)


def _files_in_directory(directory: Path, recursive: bool) -> list[Path]:
    paths = directory.rglob("*") if recursive else directory.iterdir()
    return sorted(
        (p for p in paths if p.is_file() and not p.is_symlink()
         and p.suffix.lower() in _EXTENSIONS),
        key=lambda p: p.as_posix(),
    )


def load_dataset(argument: str, opts: Options) -> Dataset:
    dataset = Dataset(argument)
    if argument == "-":
        pairs = [("<stdin>", sys.stdin.buffer, opts.stdin_format)]
    else:
        path = Path(argument).expanduser()
        if path.is_symlink():
            raise InputError(f"{argument}: symbolic links are not accepted as input sources")
        if path.is_dir():
            files = _files_in_directory(path, opts.recursive)
            if not files:
                raise InputError(f"{argument}: no .json, .jsonl or .ndjson files found")
        elif path.is_file():
            files = [path]
        else:
            raise InputError(f"{argument}: file or directory does not exist")
        pairs = [
            (str(p), None, "jsonl" if p.suffix.lower() in (".jsonl", ".ndjson") else "json")
            for p in files
        ]

    for label, standard_stream, kind in pairs:
        dataset.files += 1
        try:
            stream = standard_stream if standard_stream is not None else open(label, "rb")
            try:
                if kind == "jsonl":
                    docs = _jsonl_documents(stream, label, opts.max_document_bytes)
                else:
                    docs = [_read_document(stream, label, opts.max_document_bytes)]
                for value, read_size in docs:
                    dataset.bytes_read += read_size
                    if value is EMPTY_LINE:
                        continue
                    if dataset.documents >= opts.max_samples:
                        raise InputError(f"{argument}: exceeds --max-samples {opts.max_samples}")
                    observe(dataset.shape, value, (), opts, dataset)
                    dataset.documents += 1
            finally:
                if standard_stream is None:
                    stream.close()
        except OSError as exc:
            raise InputError(f"{label}: cannot read input: {exc}") from exc
    if dataset.documents == 0:
        raise InputError(f"{argument}: no JSON documents found")
    return dataset


# A profile contains observation counters and keys, never scalar response values.
# The extension is intentional: ordinary JSON must never be auto-detected as a profile.
PROFILE_SUFFIX = ".sdshape"
PROFILE_KIND = "shapediff.observation-profile"
PROFILE_VERSION = 1
_ALLOWED_KINDS = frozenset(("null", "boolean", "integer", "number", "string", "object", "array"))
_ALLOWED_FORMATS = frozenset(("uuid", "date-time", "date", "email", "url", "plain"))


@dataclass(frozen=True)
class Profile:
    dataset: Dataset
    semantics: dict[str, object]


def _pointer_for_selector(selector: tuple[str, ...]) -> str:
    return "/" + "/".join(value.replace("~", "~0").replace("/", "~1") for value in selector) if selector else ""


def _semantic_options(opts: Options) -> dict[str, object]:
    return {
        "ignore": sorted(_pointer_for_selector(selector) for selector in opts.ignore),
        "maps": sorted(_pointer_for_selector(selector) for selector in opts.maps),
        "formats": opts.formats,
        "strict_integers": opts.strict_integers,
    }


def _export_shape(shape: Shape) -> dict[str, object]:
    return {
        "types": dict(sorted(shape.kinds.items())),
        "objects": shape.objects,
        "fields": {
            key: {"present": info.present, "shape": _export_shape(info.shape)}
            for key, info in sorted(shape.fields.items())
        },
        "array_items": shape.array_items,
        "elements": _export_shape(shape.elements) if shape.elements is not None else None,
        "map_items": shape.map_items,
        "map_values": _export_shape(shape.map_values) if shape.map_values is not None else None,
        "string_formats": dict(sorted(shape.string_formats.items())),
    }


def export_profile(dataset: Dataset, opts: Options) -> str:
    content = {
        "kind": PROFILE_KIND,
        "profile_version": PROFILE_VERSION,
        "processing": _semantic_options(opts),
        "observations": {
            "documents": dataset.documents,
            "files": dataset.files,
            "object_observations": dataset.object_observations,
            "array_elements": dataset.array_elements,
            "shape_nodes": dataset.shape_nodes,
        },
        "shape": _export_shape(dataset.shape),
    }
    return json.dumps(content, indent=2, ensure_ascii=False, allow_nan=False) + "\n"


def _int_at(value: object, label: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise InputError(f"invalid profile: {label} must be an integer >= {minimum}")
    return value


def _validate_object(value: object, label: str, keys: set[str]) -> dict:
    if type(value) is not dict or set(value) != keys:
        raise InputError(f"invalid profile: {label} has unexpected or missing members")
    return value


def _validate_counter(value: object, label: str, allowed: frozenset[str]) -> Counter[str]:
    if type(value) is not dict or not set(value).issubset(allowed):
        raise InputError(f"invalid profile: {label} has invalid entries")
    return Counter({key: _int_at(count, f"{label}/{key}", minimum=1) for key, count in value.items()})


def _import_shape(
    raw: object, *, depth: int, path: PathTokens,
    opts: Options, stats: Dataset,
) -> Shape:
    if depth > opts.max_depth:
        raise InputError(f"profile exceeds --max-depth {opts.max_depth}")
    obj = _validate_object(raw, "shape", {
        "types", "objects", "fields", "array_items", "elements", "map_items", "map_values", "string_formats",
    })
    kinds = _validate_counter(obj["types"], "types", _ALLOWED_KINDS)
    objects = _int_at(obj["objects"], "objects")
    array_items = _int_at(obj["array_items"], "array_items")
    map_items = _int_at(obj["map_items"], "map_items")
    formats = _validate_counter(obj["string_formats"], "string_formats", _ALLOWED_FORMATS)
    if objects != kinds["object"] or (formats and "string" not in kinds):
        raise InputError("invalid profile: object/format observation counters are inconsistent")
    if opts.formats is False and formats:
        raise InputError("invalid profile: observed formats disagree with processing settings")
    if opts.formats and sum(formats.values()) != kinds["string"]:
        raise InputError("invalid profile: string format counts do not match string observations")
    if not opts.strict_integers and kinds["integer"]:
        raise InputError("invalid profile: integer observations disagree with processing settings")
    if kinds["array"] == 0 and (array_items or obj["elements"] is not None):
        raise InputError("invalid profile: array observations disagree with element records")
    if kinds["object"] == 0 and (obj["fields"] or map_items or obj["map_values"] is not None):
        raise InputError("invalid profile: object observations disagree with field records")
    if map_items and obj["map_values"] is None:
        raise InputError("invalid profile: missing map value shape")
    if array_items and obj["elements"] is None:
        raise InputError("invalid profile: missing array element shape")
    if obj["map_values"] is not None and obj["fields"]:
        raise InputError("invalid profile: map and named object fields mixed")
    if type(obj["fields"]) is not dict:
        raise InputError("invalid profile: fields must be an object")
    mapped = any(selector_matches(path, spec) for spec in opts.maps)
    if objects and mapped and obj["map_values"] is None:
        raise InputError("invalid profile: mapped object lacks a map value shape")
    if (mapped and obj["fields"]) or (not mapped and obj["map_values"] is not None):
        raise InputError("invalid profile: object layout disagrees with saved map rules")
    result = Shape(kinds=kinds, objects=objects, array_items=array_items, map_items=map_items, string_formats=formats)
    if obj["elements"] is not None:
        stats.shape_nodes += 1
        if stats.shape_nodes > opts.max_shape_nodes:
            raise InputError("profile exceeds --max-shape-nodes")
        result.elements = _import_shape(obj["elements"], depth=depth + 1, path=path + (ARRAY,), opts=opts, stats=stats)
    if obj["map_values"] is not None:
        stats.shape_nodes += 1
        if stats.shape_nodes > opts.max_shape_nodes:
            raise InputError("profile exceeds --max-shape-nodes")
        result.map_values = _import_shape(obj["map_values"], depth=depth + 1, path=path + (MAP_VALUE,), opts=opts, stats=stats)
    for key, field_raw in obj["fields"].items():
        if not isinstance(key, str):
            raise InputError("invalid profile: object keys must be strings")
        if any(0xD800 <= ord(ch) <= 0xDFFF for ch in key):
            raise InputError("invalid profile: object key contains invalid Unicode surrogate")
        if is_ignored(path + (key,), opts):
            raise InputError("invalid profile: stored field disagrees with saved ignore rules")
        entry = _validate_object(field_raw, f"field {key!r}", {"present", "shape"})
        present = _int_at(entry["present"], f"field {key!r} present", minimum=1)
        if present > objects:
            raise InputError("invalid profile: field present more often than its parent object")
        stats.shape_nodes += 1
        if stats.shape_nodes > opts.max_shape_nodes:
            raise InputError("profile exceeds --max-shape-nodes")
        child = _import_shape(entry["shape"], depth=depth + 1, path=path + (key,), opts=opts, stats=stats)
        if sum(child.kinds.values()) != present:
            raise InputError(f"invalid profile: field {key!r} has inconsistent observations")
        result.fields[key] = Field(shape=child, present=present)
    if result.elements is not None and sum(result.elements.kinds.values()) != array_items:
        raise InputError("invalid profile: array item totals do not match their element shape")
    if result.map_values is not None and sum(result.map_values.kinds.values()) != map_items:
        raise InputError("invalid profile: map item totals do not match their value shape")
    return result


def _shape_totals(shape: Shape) -> tuple[int, int]:
    """Recompute aggregate observation totals from a serialized profile tree."""
    objects, elements = shape.objects, shape.array_items
    for child in shape.fields.values():
        a, b = _shape_totals(child.shape)
        objects += a
        elements += b
    if shape.elements is not None:
        a, b = _shape_totals(shape.elements)
        objects += a
        elements += b
    if shape.map_values is not None:
        a, b = _shape_totals(shape.map_values)
        objects += a
        elements += b
    return objects, elements


def _read_profile(path: str, opts: Options) -> Profile:
    source = Path(path).expanduser()
    if source.is_symlink() or not source.is_file():
        raise InputError(f"{path}: profile must be an existing regular file, not a symlink")
    try:
        with source.open("rb") as stream:
            raw, _ = _read_document(stream, path, opts.max_document_bytes)
    except OSError as exc:
        raise InputError(f"{path}: cannot read profile: {exc}") from exc
    root = _validate_object(raw, "root", {"kind", "profile_version", "processing", "observations", "shape"})
    if root["kind"] != PROFILE_KIND or type(root["profile_version"]) is not int or root["profile_version"] != PROFILE_VERSION:
        raise InputError(f"{path}: unsupported ShapeDiff profile kind or version")
    processing = _validate_object(root["processing"], "processing", {"ignore", "maps", "formats", "strict_integers"})
    for name in ("formats", "strict_integers"):
        if type(processing[name]) is not bool:
            raise InputError(f"invalid profile: {name} must be a boolean")
    for name in ("ignore", "maps"):
        if type(processing[name]) is not list or not all(isinstance(s, str) for s in processing[name]):
            raise InputError(f"invalid profile: {name} selectors must be a list of strings")
        selectors = tuple(parse_selector(p) for p in processing[name])
        if name == "ignore" and () in selectors:
            raise InputError("invalid profile: ignored root")
        if len(set(selectors)) != len(selectors):
            raise InputError(f"invalid profile: repeated {name} selectors")
        processing[name] = sorted(_pointer_for_selector(s) for s in selectors)
    stats_raw = _validate_object(root["observations"], "observations", {
        "documents", "files", "object_observations", "array_elements", "shape_nodes",
    })
    counts = {key: _int_at(value, f"observations/{key}", minimum=1 if key in ("documents", "files", "shape_nodes") else 0) for key, value in stats_raw.items()}
    if counts["documents"] > opts.max_samples:
        raise InputError(f"profile exceeds --max-samples {opts.max_samples}")
    semantics_opts = Options(
        ignore=tuple(parse_selector(s) for s in processing["ignore"]),
        maps=tuple(parse_selector(s) for s in processing["maps"]),
        strict_integers=processing["strict_integers"],
        formats=processing["formats"],
        max_depth=opts.max_depth,
        max_shape_nodes=opts.max_shape_nodes,
    )
    imported = Dataset(label=path)
    imported.shape = _import_shape(root["shape"], depth=0, path=(), opts=semantics_opts, stats=imported)
    if counts["documents"] != sum(imported.shape.kinds.values()) or counts["shape_nodes"] != imported.shape_nodes:
        raise InputError("invalid profile: root document or shape node counts do not match")
    observed_objects, observed_elements = _shape_totals(imported.shape)
    if (observed_objects != counts["object_observations"] or observed_elements != counts["array_elements"]):
        raise InputError("invalid profile: aggregate object or array observation counts do not match")
    imported.documents = counts["documents"]
    imported.files = counts["files"]
    # Deliberately discard source byte lengths when producing a reusable profile.
    imported.bytes_read = 0
    imported.object_observations = counts["object_observations"]
    imported.array_elements = counts["array_elements"]
    return Profile(dataset=imported, semantics=processing)


def merge_observations(a: Shape, b: Shape) -> Shape:
    """Merge two independently observed shapes, preserving presence counts."""
    result = Shape(
        kinds=a.kinds + b.kinds,
        objects=a.objects + b.objects,
        array_items=a.array_items + b.array_items,
        map_items=a.map_items + b.map_items,
        string_formats=a.string_formats + b.string_formats,
    )
    for key in a.fields.keys() | b.fields.keys():
        left, right = a.fields.get(key), b.fields.get(key)
        if left is not None and right is not None:
            result.fields[key] = Field(
                shape=merge_observations(left.shape, right.shape),
                present=left.present + right.present,
            )
        elif left is not None:
            result.fields[key] = left
        elif right is not None:
            result.fields[key] = right
    if a.elements is not None and b.elements is not None:
        result.elements = merge_observations(a.elements, b.elements)
    else:
        result.elements = a.elements if a.elements is not None else b.elements
    if a.map_values is not None and b.map_values is not None:
        result.map_values = merge_observations(a.map_values, b.map_values)
    else:
        result.map_values = a.map_values if a.map_values is not None else b.map_values
    return result


def _node_count(shape: Shape) -> int:
    return (1 + sum(_node_count(f.shape) for f in shape.fields.values())
            + (_node_count(shape.elements) if shape.elements is not None else 0)
            + (_node_count(shape.map_values) if shape.map_values is not None else 0))


def merge_datasets(old: Dataset, new: Dataset, opts: Options) -> Dataset:
    if old.documents + new.documents > opts.max_samples:
        raise InputError(f"updated profile exceeds --max-samples {opts.max_samples}")
    result = Dataset(label=old.label)
    result.shape = merge_observations(old.shape, new.shape)
    result.shape_nodes = _node_count(result.shape)
    if result.shape_nodes > opts.max_shape_nodes:
        raise InputError(f"updated profile exceeds --max-shape-nodes {opts.max_shape_nodes}")
    result.documents = old.documents + new.documents
    result.files = old.files + new.files
    result.object_observations = old.object_observations + new.object_observations
    result.array_elements = old.array_elements + new.array_elements
    # Source byte lengths are intentionally not persisted in profile metadata.
    return result


def _identifier_like(text: str) -> bool:
    return bool(_UUID.fullmatch(text) or _EMAIL.fullmatch(text) or (len(text) >= 16 and re.fullmatch(r"[a-fA-F0-9]+", text)))


def _sensitive_selector_count(opts: Options) -> int:
    return sum(1 for selector in (*opts.ignore, *opts.maps) for part in selector if _identifier_like(part))


def _sensitive_key_count(shape: Shape) -> int:
    count = 0
    for key, field_info in shape.fields.items():
        if _identifier_like(key):
            count += 1
        count += _sensitive_key_count(field_info.shape)
    if shape.elements is not None:
        count += _sensitive_key_count(shape.elements)
    if shape.map_values is not None:
        count += _sensitive_key_count(shape.map_values)
    return count


def _profile_input(argument: str) -> bool:
    return argument != "-" and Path(argument).suffix.lower() == PROFILE_SUFFIX


def _select_profile_options(args: argparse.Namespace, profiles: list[Profile]) -> tuple[tuple[tuple[str, ...], ...], tuple[tuple[str, ...], ...], bool, bool]:
    user_ignore = tuple(parse_selector(value) for value in args.ignore)
    user_maps = tuple(parse_selector(value) for value in args.map)
    if not profiles:
        return user_ignore, user_maps, args.strict_integers, args.formats
    shared = profiles[0].semantics
    for entry in profiles[1:]:
        if entry.semantics != shared:
            raise InputError("profile processing settings differ; rebuild them with identical --map, --ignore, --formats and --strict-integers options")
    saved_ignore = tuple(parse_selector(x) for x in shared["ignore"])
    saved_maps = tuple(parse_selector(x) for x in shared["maps"])
    if (args.ignore and set(user_ignore) != set(saved_ignore)) or (args.map and set(user_maps) != set(saved_maps)):
        raise InputError("CLI selectors differ from saved profile; use the original --map and --ignore rules or omit them to inherit")
    if (args.formats and not shared["formats"]) or (args.strict_integers and not shared["strict_integers"]):
        raise InputError("CLI inference flags differ from saved profile; omit them to inherit saved settings")
    return saved_ignore, saved_maps, shared["strict_integers"], shared["formats"]


def _output_safety(destination: str, inputs: Sequence[str]) -> Path:
    target = Path(destination).expanduser()
    if target.is_symlink():
        raise InputError("--output must not replace a symbolic link")
    actual = target.resolve()
    for argument in inputs:
        if argument == "-":
            continue
        source = Path(argument).expanduser().resolve()
        if actual == source or (source.is_dir() and source in actual.parents):
            raise InputError("--output must not overwrite an input or live inside an input directory")
    return target


def profile_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="shapediff profile",
        description="Capture a versioned structural baseline without storing response values.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("source", metavar="SOURCE", help="JSON, JSONL, NDJSON, directory, or - for stdin")
    p.add_argument("-o", "--output", metavar="BASELINE.SDSHAPE", help="profile destination; default stdout")
    p.add_argument("--ignore", action="append", metavar="SELECTOR", default=[], help="omit matching fields from profile")
    p.add_argument("--map", action="append", metavar="SELECTOR", default=[], help="treat matching objects as dynamic-key maps")
    p.add_argument("--formats", action="store_true", help="record heuristic string formats (never raw values)")
    p.add_argument("--strict-integers", action="store_true", help="separate integer from number")
    p.add_argument("--recursive", action="store_true", help="recurse into sample directories")
    p.add_argument("--stdin-format", choices=("json", "jsonl"), default="json")
    p.add_argument("--max-document-mib", type=int, metavar="MiB", default=32)
    p.add_argument("--max-samples", type=int, metavar="N", default=100000)
    p.add_argument("--max-shape-nodes", type=int, metavar="N", default=250000)
    p.add_argument("--max-depth", type=int, metavar="N", default=128)
    p.add_argument("--quiet", action="store_true", help="suppress capture information on stderr")
    p.add_argument("--force", action="store_true", help="replace an existing profile deliberately")
    p.add_argument("--update", metavar="BASELINE.SDSHAPE", help="append observations to an existing profile atomically")
    p.add_argument("--allow-identifier-keys", action="store_true", help="allow storage of UUID/email/hex-like object keys")
    return p


def profile_main(argv: Sequence[str] | None = None) -> int:
    p = profile_parser()
    args = p.parse_args(argv)
    if args.max_document_mib < 1 or args.max_samples < 1 or args.max_shape_nodes < 1 or args.max_depth < 1:
        p.error("resource limits must be positive")
    if _profile_input(args.source):
        p.error("source must contain JSON response samples, not an existing .sdshape profile")
    if args.output and Path(args.output).suffix.lower() != PROFILE_SUFFIX:
        p.error("profile output must end in .sdshape")
    if args.update and (args.output or args.force):
        p.error("--update cannot be combined with --output or --force")
    if args.update and not _profile_input(args.update):
        p.error("--update requires an existing .sdshape file")
    try:
        ignore_rules = tuple(parse_selector(value) for value in args.ignore)
        maps = tuple(parse_selector(value) for value in args.map)
        existing = None
        if args.update:
            existing = _read_profile(args.update, Options(
                max_document_bytes=args.max_document_mib * 1024 * 1024,
                max_samples=args.max_samples,
                max_depth=args.max_depth,
                max_shape_nodes=args.max_shape_nodes,
            ))
            ignore_rules, maps, strict_integers, formats = _select_profile_options(args, [existing])
        else:
            strict_integers, formats = args.strict_integers, args.formats
        if () in ignore_rules:
            p.error("--ignore cannot target the entire response")
        if args.update:
            _output_safety(args.update, (args.source,))
        if args.output:
            target = _output_safety(args.output, (args.source,))
            if target.exists() and not args.force:
                raise InputError("profile already exists; use --force to replace the saved baseline")
        opts = Options(
            ignore=ignore_rules, maps=maps,
            strict_integers=strict_integers, formats=formats,
            recursive=args.recursive, stdin_format=args.stdin_format,
            max_depth=args.max_depth,
            max_document_bytes=args.max_document_mib * 1024 * 1024,
            max_samples=args.max_samples, max_shape_nodes=args.max_shape_nodes,
        )
        dataset = load_dataset(args.source, opts)
        unmatched_maps = set(parse_selector(p) for p in args.map) - dataset.matched_maps
        if unmatched_maps:
            displayed = ", ".join(repr(_pointer_for_selector(p)) for p in sorted(unmatched_maps))
            raise InputError(f"--map selector did not match an observed object: {displayed}")
        if existing is not None:
            dataset = merge_datasets(existing.dataset, dataset, opts)
        risky_keys = _sensitive_key_count(dataset.shape) + _sensitive_selector_count(opts)
        if risky_keys and not args.allow_identifier_keys:
            raise InputError(
                f"profile would retain {risky_keys} identifier-like object keys; "
                "use --map for dynamic-key objects, --ignore, or --allow-identifier-keys"
            )
        content = export_profile(dataset, opts)
        if args.update:
            _write_output(Path(args.update).expanduser(), content)
        elif args.output:
            _write_output(Path(args.output).expanduser(), content)
        else:
            sys.stdout.write(content)
        if not args.quiet:
            print(f"shapediff: profiled {dataset.documents} responses, {dataset.shape_nodes} shape nodes", file=sys.stderr)
            if risky_keys:
                print(
                    f"shapediff: warning: {risky_keys} object keys resemble identifiers; "
                    "profiles retain literal keys; consider --map or --ignore",
                    file=sys.stderr,
                )
        return 0
    except InputError as exc:
        print(f"shapediff: {exc}", file=sys.stderr)
        return 3
    except BrokenPipeError:
        return 0
    except KeyboardInterrupt:
        return 130


def render_path(path: PathTokens) -> str:
    result = ""
    for token in path:
        if token is ARRAY:
            result += "[*]"
        elif token is MAP_VALUE:
            result += "{*}"
        elif isinstance(token, str) and _IDENT.fullmatch(token):
            result += ("." if result else "") + token
        else:
            result += "[" + json.dumps(token, ensure_ascii=False) + "]"
    return result or "$"


def render_pointer(path: PathTokens) -> str:
    if not path:
        return ""
    segments = (
        "*" if part is ARRAY or part is MAP_VALUE
        else str(part).replace("~", "~0").replace("/", "~1")
        for part in path
    )
    return "/" + "/".join(segments)


def _types(shape: Shape) -> set[str]:
    return set(shape.kinds)


def _kind_string(kinds: set[str]) -> str:
    return "|".join(sorted(kinds)) if kinds else "unknown"


def _evidence(shape: Shape) -> dict[str, object]:
    return {"types": dict(sorted(shape.kinds.items()))}


def compare(old: Shape, new: Shape, opts: Options) -> list[Finding]:
    findings: list[Finding] = []

    def add(
        level: str,
        code: str,
        path: PathTokens,
        message: str,
        baseline: dict[str, object] | None = None,
        current: dict[str, object] | None = None,
    ) -> None:
        if not is_ignored(path, opts):
            findings.append(
                Finding(level, code, path, message, baseline or {}, current or {})
            )

    def visit(a: Shape, b: Shape, path: PathTokens, depth: int) -> None:
        if depth > opts.max_depth:
            raise InputError(
                f"comparison depth exceeds --max-depth {opts.max_depth}"
            )

        before, after = _types(a), _types(b)
        gained, lost = after - before, before - after
        # Under strict integer detection, JSON integer is a subset of number.
        # A response narrowing from number to integer adds no unsupported value.
        numeric_narrowing = opts.strict_integers and "number" in before and "integer" in after
        if numeric_narrowing:
            gained.discard("integer")
        overlap = bool(before & after) or numeric_narrowing
        if gained:
            evidence = (_evidence(a), _evidence(b))
            if before == {"null"}:
                add(
                    WARN, "null_only_baseline", path,
                    f"null-only baseline; now observed {_kind_string(after)}",
                    *evidence,
                )
            elif not overlap:
                add(
                    ERROR, "type_changed", path,
                    f"{_kind_string(before)} -> {_kind_string(after)}",
                    *evidence,
                )
            else:
                add(
                    ERROR, "type_added", path,
                    f"new response type: {_kind_string(gained)} "
                    f"(was {_kind_string(before)})",
                    *evidence,
                )
        if lost and (not gained or overlap):
            add(
                INFO, "type_no_longer_observed", path,
                f"type no longer observed: {_kind_string(lost)}",
                _evidence(a), _evidence(b),
            )

        if opts.formats and "string" in before and "string" in after:
            a_formats, b_formats = set(a.string_formats), set(b.string_formats)
            if a_formats != b_formats:
                add(
                    WARN, "format_drift", path,
                    "observed string formats: "
                    f"{_kind_string(a_formats)} -> {_kind_string(b_formats)}",
                    {"formats": dict(a.string_formats)},
                    {"formats": dict(b.string_formats)},
                )

        # Compare only container kinds observed on both sides.
        if "object" in before and "object" in after:
            if any(selector_matches(path, spec) for spec in opts.maps):
                if a.map_items == 0 or b.map_items == 0:
                    if a.map_items != b.map_items:
                        add(
                            WARN, "unverified_map_values", path,
                            "map values not comparable; one side contained no entries",
                            {"entries": a.map_items},
                            {"entries": b.map_items},
                        )
                elif a.map_values is not None and b.map_values is not None:
                    visit(a.map_values, b.map_values, path + (MAP_VALUE,), depth + 1)
            else:
                a_keys, b_keys = set(a.fields), set(b.fields)
                for key in sorted(a_keys - b_keys):
                    count = a.fields[key].present
                    evidence = {"present": count, "objects": a.objects}
                    now = {"present": 0, "objects": b.objects}
                    if count == a.objects:
                        add(
                            ERROR, "field_missing", path + (key,),
                            "missing", evidence, now,
                        )
                    else:
                        add(
                            WARN, "field_unobserved", path + (key,),
                            f"not seen in current samples (baseline {count}/{a.objects})",
                            evidence, now,
                        )
                for key in sorted(b_keys - a_keys):
                    field_info = b.fields[key]
                    add(
                        INFO, "field_added", path + (key,), "added",
                        {"present": 0, "objects": a.objects},
                        {"present": field_info.present, "objects": b.objects},
                    )
                for key in sorted(a_keys & b_keys):
                    fa, fb = a.fields[key], b.fields[key]
                    visit(fa.shape, fb.shape, path + (key,), depth + 1)
                    if (
                        opts.coverage_drop is not None
                        and a.objects >= opts.min_coverage_objects
                        and b.objects >= opts.min_coverage_objects
                    ):
                        earlier = fa.present / a.objects
                        later = fb.present / b.objects
                        if earlier - later >= opts.coverage_drop:
                            add(
                                WARN, "presence_drop", path + (key,),
                                "observed field presence fell "
                                f"{earlier:.0%} -> {later:.0%}",
                                {"present": fa.present, "objects": a.objects},
                                {"present": fb.present, "objects": b.objects},
                            )
        if "array" in before and "array" in after:
            if a.array_items == 0 or b.array_items == 0:
                if a.array_items != b.array_items:
                    add(
                        WARN, "unverified_array_elements", path,
                        "array element types not comparable; "
                        "one side had only empty arrays",
                        {"elements": a.array_items},
                        {"elements": b.array_items},
                    )
            elif a.elements is not None and b.elements is not None:
                visit(a.elements, b.elements, path + (ARRAY,), depth + 1)

    visit(old, new, (), 0)
    order = {ERROR: 0, WARN: 1, INFO: 2}
    return sorted(
        findings,
        key=lambda f: (order[f.level], render_pointer(f.path), f.code, f.message),
    )


def build_report(baseline: Dataset, current: Dataset, opts: Options) -> dict[str, object]:
    findings = compare(baseline.shape, current.shape, opts)
    counts = {level: sum(f.level == level for f in findings) for level in (ERROR, WARN, INFO)}
    return {
        "report_version": 1,
        "tool": "shapediff",
        "version": __version__,
        "contract_direction": "response",
        "evidence_model": "observed-samples-not-schema",
        "baseline": baseline.metadata(),
        "current": current.metadata(),
        "summary": {"errors": counts[ERROR], "warnings": counts[WARN], "infos": counts[INFO], "total": len(findings)},
        "findings": [f.as_dict() for f in findings],
    }


def _color(level: str, enabled: bool) -> str:
    if not enabled:
        return level
    code = {ERROR: "31", WARN: "33", INFO: "36"}[level]
    return f"\x1b[{code}m{level}\x1b[0m"


def format_text(report: dict[str, object], only_errors: bool, colored: bool, evidence: bool = False) -> str:
    findings = report["findings"]
    if only_errors:
        findings = [f for f in findings if f["level"] == ERROR]
    if not findings:
        return ""
    width = max(len(f["path"]) for f in findings)
    lines = []
    for item in findings:
        path = item["path"]
        shown = path
        label = f"{item['level']:<5}"
        if colored:
            label = _color(label, True)
        details = ""
        if evidence:
            before, after = item["baseline"], item["current"]
            if "present" in before and "objects" in before:
                details = f"  [observed {before['present']}/{before['objects']} -> {after.get('present', 0)}/{after.get('objects', 0)}]"
            elif "types" in before:
                details = f"  [counts {before['types']} -> {after['types']}]"
            elif "elements" in before:
                details = f"  [elements {before['elements']} -> {after['elements']}]"
        lines.append(f"{label}  {shown:<{width}}  {item['message']}{details}")
    return "\n".join(lines) + "\n"


def _markdown_escape(text: object) -> str:
    return str(text).replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ").replace("\r", " ")


def format_markdown(report: dict[str, object], only_errors: bool) -> str:
    rows = report["findings"]
    if only_errors:
        rows = [f for f in rows if f["level"] == ERROR]
    summary = report["summary"]
    lines = ["## ShapeDiff report", "", f"{summary['errors']} breaking · {summary['warnings']} warnings · {summary['infos']} informational", "", "| Level | Path | Finding |", "| :--- | :--- | :--- |"]
    for row in rows:
        path = _markdown_escape(row["path"])
        ticks = "`" * (max((len(x) for x in re.findall(r"`+", path)), default=0) + 1)
        lines.append(f"| {row['level']} | {ticks}{path}{ticks} | {_markdown_escape(row['message'])} |")
    if not rows:
        lines.append("| | | No findings at the selected level |")
    lines.extend(("", "Sampled responses provide evidence, not a formal API contract.", ""))
    return "\n".join(lines)


def _write_output(path: Path, contents: str) -> None:
    """Atomic output; unsuccessful writes leave the previous report intact."""
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False) as handle:
            temp = Path(handle.name)
            handle.write(contents)
        os.replace(temp, path)
    except OSError as exc:
        raise InputError(f"cannot write report {path}: {exc}") from exc
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="shapediff",
        description="Compare observed JSON API response shapes without a schema or value noise.",
        epilog="Commands: shapediff profile SOURCE -o baseline.sdshape; shapediff suite before.sdsuite after.sdsuite",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("baseline", metavar="BASELINE", help="JSON, JSONL, NDJSON, .sdshape profile, directory, or - for stdin")
    p.add_argument("current", metavar="CURRENT", help="JSON, JSONL, NDJSON, directory, or - for stdin")
    p.add_argument("--format", choices=("text", "json", "markdown"), default="text", help="report format")
    p.add_argument("--output", metavar="FILE", help="atomically write the report instead of stdout")
    p.add_argument("--breaking-only", action="store_true", help="display only ERROR findings (does not change classification)")
    p.add_argument("--evidence", action="store_true", help="show observation counts alongside text findings")
    p.add_argument("--fail-on", choices=("error", "warning", "any", "never"), default="error", help="exit 1 at or above this finding level")
    p.add_argument("--ignore", action="append", metavar="SELECTOR", default=[], help="exclude a field or subtree; e.g. /items/*/nonce; repeatable")
    p.add_argument("--map", action="append", metavar="SELECTOR", default=[], help="treat matching object paths as dynamic-key maps, e.g. /byId")
    p.add_argument("--formats", action="store_true", help="report heuristic string-format drift as WARN")
    p.add_argument("--strict-integers", action="store_true", help="distinguish JSON integer from fractional number")
    p.add_argument("--coverage-drop", type=float, metavar="FRACTION", help="warn on observed field presence drop, from 0 to 1")
    p.add_argument("--min-coverage-objects", type=int, default=3, metavar="N", help="minimum object observations on each side for coverage warnings")
    p.add_argument("--recursive", action="store_true", help="recurse into sample directory subfolders")
    p.add_argument("--stdin-format", choices=("json", "jsonl"), default="json", help="stdin parser")
    p.add_argument("--max-document-mib", type=int, default=32, metavar="MiB", help="maximum size of one JSON document or JSONL line")
    p.add_argument("--max-samples", type=int, default=100000, metavar="N", help="maximum documents per input side")
    p.add_argument("--max-shape-nodes", type=int, default=250000, metavar="N", help="maximum unique observed shape nodes per side")
    p.add_argument("--max-depth", type=int, default=128, metavar="N", help="maximum JSON nesting depth")
    p.add_argument("--color", choices=("auto", "always", "never"), default="auto", help="ANSI color mode for text")
    p.add_argument("--quiet", action="store_true", help="suppress summary on stderr")
    p.add_argument("-V", "--version", action="version", version=f"%(prog)s {__version__}")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "profile":
        return profile_main(argv[1:])
    if argv and argv[0] == "suite":
        return suite_main(argv[1:])
    p = parser()
    args = p.parse_args(argv)
    if args.baseline == "-" and args.current == "-":
        p.error("both inputs cannot read stdin; save one side as a file")
    if args.max_document_mib < 1 or args.max_depth < 1 or args.max_samples < 1 or args.max_shape_nodes < 1 or args.min_coverage_objects < 1:
        p.error("document size, sample count, depth, and coverage object count must be positive")
    if args.coverage_drop is not None and not 0 < args.coverage_drop <= 1:
        p.error("--coverage-drop must be greater than 0 and at most 1")
    try:
        ignore_rules = tuple(parse_selector(v) for v in args.ignore)
        map_rules = tuple(parse_selector(v) for v in args.map)
    except InputError as exc:
        p.error(str(exc))
    if () in ignore_rules:
        p.error("--ignore cannot target the entire response")
    if args.output is not None:
        try:
            _output_safety(args.output, (args.baseline, args.current))
        except InputError as exc:
            print(f"shapediff: {exc}", file=sys.stderr)
            return 3
    try:
        read_limits = Options(
            max_document_bytes=args.max_document_mib * 1024 * 1024,
            max_depth=args.max_depth,
            max_samples=args.max_samples,
            max_shape_nodes=args.max_shape_nodes,
        )
        saved = {}
        for argument in (args.baseline, args.current):
            if _profile_input(argument):
                saved[argument] = _read_profile(argument, read_limits)
        chosen_ignore, chosen_maps, strict_integers, formats = _select_profile_options(args, list(saved.values()))
        opts = Options(
            ignore=chosen_ignore,
            maps=chosen_maps,
            strict_integers=strict_integers,
            formats=formats,
            coverage_drop=args.coverage_drop,
            min_coverage_objects=args.min_coverage_objects,
            max_depth=args.max_depth,
            max_document_bytes=args.max_document_mib * 1024 * 1024,
            max_samples=args.max_samples,
            max_shape_nodes=args.max_shape_nodes,
            recursive=args.recursive,
            stdin_format=args.stdin_format,
        )
        before = saved[args.baseline].dataset if args.baseline in saved else load_dataset(args.baseline, opts)
        after = saved[args.current].dataset if args.current in saved else load_dataset(args.current, opts)
        report = build_report(before, after, opts)
        if args.format == "json":
            payload = report if not args.breaking_only else {**report, "findings": [f for f in report["findings"] if f["level"] == ERROR]}
            output = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        elif args.format == "markdown":
            output = format_markdown(report, args.breaking_only)
        else:
            colored = args.color == "always" or (args.color == "auto" and sys.stdout.isatty() and "NO_COLOR" not in os.environ and args.output is None)
            output = format_text(report, args.breaking_only, colored, evidence=args.evidence)
        if args.output is not None:
            _write_output(Path(args.output).expanduser(), output)
        else:
            sys.stdout.write(output)
        if not args.quiet and args.format == "text":
            total = report["summary"]
            print(f"shapediff: {total['errors']} breaking, {total['warnings']} warning, {total['infos']} info  |  samples {before.documents} -> {after.documents}", file=sys.stderr)
        levels = {"error": (ERROR,), "warning": (ERROR, WARN), "any": (ERROR, WARN, INFO), "never": ()}[args.fail_on]
        return 1 if any(f["level"] in levels for f in report["findings"]) else 0
    except InputError as exc:
        print(f"shapediff: {exc}", file=sys.stderr)
        return 3
    except BrokenPipeError:
        return 0
    except KeyboardInterrupt:
        return 130


@dataclass(frozen=True)
class SuiteCase:
    identifier: str
    status: int
    body: Path | None
    headers: dict[str, str]


def _read_suite(argument: str, limit: int, max_cases: int) -> dict[str, SuiteCase]:
    source = Path(argument).expanduser()
    if source.suffix.lower() != ".sdsuite":
        raise InputError(f"{argument}: suite file must end in .sdsuite")
    if source.is_symlink() or not source.is_file():
        raise InputError(f"{argument}: suite must be an existing regular file, not a symlink")
    try:
        with source.open("rb") as stream:
            raw, _ = _read_document(stream, argument, limit)
    except OSError as exc:
        raise InputError(f"{argument}: cannot read suite: {exc}") from exc
    if type(raw) is not dict or set(raw) != {"suite_version", "responses"}:
        raise InputError(f"{argument}: suite needs suite_version and responses")
    root = raw
    if type(root["suite_version"]) is not int or root["suite_version"] != 1:
        raise InputError(f"{argument}: unsupported suite version")
    entries = root["responses"]
    if type(entries) is not list or not 1 <= len(entries) <= max_cases:
        raise InputError(f"{argument}: responses must contain 1 to {max_cases} cases")
    base = source.parent.resolve()
    result: dict[str, SuiteCase] = {}
    for index, raw_case in enumerate(entries, 1):
        label = f"{argument}: response {index}"
        if type(raw_case) is not dict or not {"id", "status", "body"}.issubset(raw_case) or not set(raw_case).issubset({"id", "status", "body", "headers"}):
            raise InputError(f"{label}: expected id, status, body and optional headers")
        identifier = raw_case["id"]
        if type(identifier) is not str or not identifier.strip() or len(identifier) > 200 or any(
            ord(ch) < 32 or 127 <= ord(ch) <= 159 or 0xD800 <= ord(ch) <= 0xDFFF
            or ch in "\u2028\u2029" for ch in identifier
        ):
            raise InputError(f"{label}: id must be 1-200 printable characters")
        if identifier in result:
            raise InputError(f"{label}: duplicate response id {identifier!r}")
        status = raw_case["status"]
        if type(status) is not int or not 100 <= status <= 599:
            raise InputError(f"{label}: status must be an HTTP status integer from 100 to 599")
        raw_body = raw_case["body"]
        body = None
        if raw_body is not None:
            if type(raw_body) is not str or not raw_body or any(
                ord(ch) < 32 or 0xD800 <= ord(ch) <= 0xDFFF for ch in raw_body
            ) or Path(raw_body).is_absolute() or Path(raw_body).drive:
                raise InputError(f"{label}: body must be a relative sample path or null")
            candidate = base / raw_body
            try:
                body = candidate.resolve()
            except (OSError, RuntimeError) as exc:
                raise InputError(f"{label}: cannot resolve body path: {exc}") from exc
            if base not in body.parents or candidate.is_symlink():
                raise InputError(f"{label}: body must stay inside the suite directory and cannot be a symlink")
            if not body.is_dir() and (not body.is_file() or body.suffix.lower() not in _EXTENSIONS | {PROFILE_SUFFIX}):
                raise InputError(f"{label}: body must be a JSON sample, sample directory or .sdshape profile")
        raw_headers = raw_case.get("headers", {})
        if type(raw_headers) is not dict:
            raise InputError(f"{label}: headers must be an object")
        headers: dict[str, str] = {}
        for name, value in raw_headers.items():
            if not _HEADER_NAME.fullmatch(name) or type(value) is not str or any(
                ord(ch) < 32 or ord(ch) == 127 for ch in value
            ):
                raise InputError(f"{label}: headers need valid names and single-line string values")
            normalized = name.lower()
            if normalized in headers:
                raise InputError(f"{label}: duplicate header name ignoring case: {name!r}")
            headers[normalized] = value
        result[identifier] = SuiteCase(identifier, status, body, headers)
    return result


def _suite_finding(level: str, code: str, identifier: str, path: str, message: str,
                   baseline: dict[str, object] | None = None,
                   current: dict[str, object] | None = None) -> dict[str, object]:
    if path == "@status":
        pointer = "/status"
    elif path.startswith("@headers."):
        pointer = "/headers/" + path[len("@headers."):].replace("~", "~0").replace("/", "~1")
    else:
        pointer = ""
    return {
        "case": identifier, "level": level, "code": code, "path": path,
        "pointer": pointer, "message": message,
        "baseline": baseline or {}, "current": current or {},
    }


def build_suite_report(baseline: dict[str, SuiteCase], current: dict[str, SuiteCase],
                       args: argparse.Namespace) -> dict[str, object]:
    findings: list[dict[str, object]] = []
    cases: list[dict[str, object]] = []
    read_limits = Options(
        max_document_bytes=args.max_document_mib * 1024 * 1024,
        max_depth=args.max_depth, max_samples=args.max_samples,
        max_shape_nodes=args.max_shape_nodes,
    )
    empty_flags = argparse.Namespace(ignore=[], map=[], strict_integers=False, formats=False)
    def validate_unmatched(case: SuiteCase) -> None:
        if case.body is not None:
            if _profile_input(str(case.body)):
                _read_profile(str(case.body), read_limits)
            else:
                load_dataset(str(case.body), Options(
                    recursive=args.recursive, max_depth=args.max_depth,
                    max_document_bytes=args.max_document_mib * 1024 * 1024,
                    max_samples=args.max_samples, max_shape_nodes=args.max_shape_nodes,
                ))

    for identifier in sorted(baseline.keys() | current.keys()):
        old, new = baseline.get(identifier), current.get(identifier)
        if old is None:
            validate_unmatched(new)
            findings.append(_suite_finding(INFO, "response_added", identifier, "$", "response added to suite"))
            cases.append({"id": identifier, "baseline_status": None, "current_status": new.status, "findings": 1})
            continue
        if new is None:
            validate_unmatched(old)
            findings.append(_suite_finding(ERROR, "response_missing", identifier, "$", "response missing from current suite"))
            cases.append({"id": identifier, "baseline_status": old.status, "current_status": None, "findings": 1})
            continue
        case_findings: list[dict[str, object]] = []
        if old.status != new.status:
            case_findings.append(_suite_finding(
                ERROR, "status_changed", identifier, "@status",
                f"HTTP status {old.status} -> {new.status}",
                {"status": old.status}, {"status": new.status},
            ))
        for name in sorted(old.headers.keys() | new.headers.keys()):
            path = f"@headers.{name}"
            if name not in new.headers:
                case_findings.append(_suite_finding(ERROR, "header_missing", identifier, path, "header missing"))
            elif name not in old.headers:
                case_findings.append(_suite_finding(INFO, "header_added", identifier, path, "header added"))
            elif old.headers[name] != new.headers[name]:
                case_findings.append(_suite_finding(ERROR, "header_changed", identifier, path, "header value changed"))
        if old.body is None and new.body is not None:
            case_findings.append(_suite_finding(INFO, "body_added", identifier, "$", "response body added"))
        elif old.body is not None and new.body is None:
            case_findings.append(_suite_finding(ERROR, "body_missing", identifier, "$", "response body missing"))
        elif old.body is not None and new.body is not None:
            saved = [
                _read_profile(str(path), read_limits)
                for path in (old.body, new.body) if _profile_input(str(path))
            ]
            ignore, maps, strict_integers, formats = _select_profile_options(empty_flags, saved)
            opts = Options(
                ignore=ignore, maps=maps, strict_integers=strict_integers, formats=formats,
                recursive=args.recursive, max_depth=args.max_depth,
                max_document_bytes=args.max_document_mib * 1024 * 1024,
                max_samples=args.max_samples, max_shape_nodes=args.max_shape_nodes,
            )
            old_data = saved[0].dataset if _profile_input(str(old.body)) else load_dataset(str(old.body), opts)
            new_data = saved[-1].dataset if _profile_input(str(new.body)) else load_dataset(str(new.body), opts)
            case_findings.extend({"case": identifier, **finding.as_dict()} for finding in compare(old_data.shape, new_data.shape, opts))
        findings.extend(case_findings)
        cases.append({"id": identifier, "baseline_status": old.status, "current_status": new.status,
                      "findings": len(case_findings)})
    order = {ERROR: 0, WARN: 1, INFO: 2}
    findings.sort(key=lambda f: (order[f["level"]], f["case"], f["path"], f["code"]))
    counts = {level: sum(f["level"] == level for f in findings) for level in (ERROR, WARN, INFO)}
    return {
        "report_version": 1, "tool": "shapediff", "version": __version__,
        "mode": "suite", "contract_direction": "response",
        "evidence_model": "observed-samples-not-schema",
        "baseline_cases": len(baseline), "current_cases": len(current),
        "cases": cases,
        "summary": {"errors": counts[ERROR], "warnings": counts[WARN],
                    "infos": counts[INFO], "total": len(findings)},
        "findings": findings,
    }


def format_suite_text(report: dict[str, object], only_errors: bool) -> str:
    rows = [f for f in report["findings"] if not only_errors or f["level"] == ERROR]
    if not rows:
        return ""
    width = max(len(f["case"]) for f in rows)
    return "".join(f"{f['level']:<5}  {f['case']:<{width}}  {f['path']}  {f['message']}\n" for f in rows)


def _suite_markdown_escape(value: object) -> str:
    return _markdown_escape(html_escape(str(value), quote=False)).replace("`", "\\`")


def format_suite_markdown(report: dict[str, object], only_errors: bool) -> str:
    rows = [f for f in report["findings"] if not only_errors or f["level"] == ERROR]
    summary = report["summary"]
    lines = ["## ShapeDiff suite report", "", f"{summary['errors']} breaking · {summary['warnings']} warnings · {summary['infos']} informational", "", "| Level | Response | Path | Finding |", "| :--- | :--- | :--- | :--- |"]
    for row in rows:
        lines.append(f"| {row['level']} | {_suite_markdown_escape(row['case'])} | {_suite_markdown_escape(row['path'])} | {_suite_markdown_escape(row['message'])} |")
    if not rows:
        lines.append("| | | | No findings at the selected level |")
    lines.extend(("", "Sampled responses provide evidence, not a formal API contract.", ""))
    return "\n".join(lines)


def suite_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="shapediff suite",
        description="Compare named API responses, HTTP statuses and selected headers.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("baseline", metavar="BASELINE.SDSUITE")
    p.add_argument("current", metavar="CURRENT.SDSUITE")
    p.add_argument("--format", choices=("text", "json", "markdown"), default="text")
    p.add_argument("--output", metavar="FILE")
    p.add_argument("--breaking-only", action="store_true")
    p.add_argument("--fail-on", choices=("error", "warning", "any", "never"), default="error")
    p.add_argument("--recursive", action="store_true", help="recurse into case sample directories")
    p.add_argument("--max-document-mib", type=int, default=32, metavar="MiB")
    p.add_argument("--max-samples", type=int, default=100000, metavar="N")
    p.add_argument("--max-shape-nodes", type=int, default=250000, metavar="N")
    p.add_argument("--max-depth", type=int, default=128, metavar="N")
    p.add_argument("--max-cases", type=int, default=1000, metavar="N")
    p.add_argument("--quiet", action="store_true")
    return p


def suite_main(argv: Sequence[str] | None = None) -> int:
    p = suite_parser()
    args = p.parse_args(argv)
    if min(args.max_document_mib, args.max_samples, args.max_shape_nodes, args.max_depth, args.max_cases) < 1:
        p.error("resource limits must be positive")
    try:
        limit = args.max_document_mib * 1024 * 1024
        old = _read_suite(args.baseline, limit, args.max_cases)
        new = _read_suite(args.current, limit, args.max_cases)
        if args.output is not None:
            sources = [args.baseline, args.current] + [str(case.body) for case in (*old.values(), *new.values()) if case.body is not None]
            _output_safety(args.output, sources)
        report = build_suite_report(old, new, args)
        if args.format == "json":
            payload = report if not args.breaking_only else {**report, "findings": [f for f in report["findings"] if f["level"] == ERROR]}
            output = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
        elif args.format == "markdown":
            output = format_suite_markdown(report, args.breaking_only)
        else:
            output = format_suite_text(report, args.breaking_only)
        if args.output is None:
            sys.stdout.write(output)
        else:
            _write_output(Path(args.output).expanduser(), output)
        if not args.quiet and args.format == "text":
            counts = report["summary"]
            print(f"shapediff: {counts['errors']} breaking, {counts['warnings']} warning, {counts['infos']} info  |  responses {len(old)} -> {len(new)}", file=sys.stderr)
        levels = {"error": (ERROR,), "warning": (ERROR, WARN), "any": (ERROR, WARN, INFO), "never": ()}[args.fail_on]
        return 1 if any(f["level"] in levels for f in report["findings"]) else 0
    except InputError as exc:
        print(f"shapediff: {exc}", file=sys.stderr)
        return 3
    except BrokenPipeError:
        return 0
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
