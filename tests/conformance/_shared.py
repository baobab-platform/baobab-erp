"""Access to the baobab-platform/shared checkout that contracts.lock.yaml pins (ERP-COMPAT-06).

Every conformance test reads contracts from this checkout, never from a copy, so the proof is about the real
files at the real pin. The suite refuses to run against any other revision and never skips silently: a missing
BAOBAB_SHARED_PATH or a checkout at a different commit is an error."""

import json
import os
import subprocess
from pathlib import Path
from urllib.parse import urldefrag

import jsonschema
import yaml
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

REPO = Path(__file__).resolve().parents[2]
LOCK = yaml.safe_load((REPO / "contracts.lock.yaml").read_text())
PIN = LOCK["source"]["commit"]
HOST = "https://contracts.baobab-platform.com/"

_configured = os.environ.get("BAOBAB_SHARED_PATH")
if not _configured:
    raise RuntimeError(
        "BAOBAB_SHARED_PATH is not set. Point it at a checkout of baobab-platform/shared at "
        f"{PIN} (contracts.lock.yaml). The conformance suite never skips silently."
    )
ROOT = Path(_configured).resolve()
CONTRACTS = ROOT / "contracts"


def head() -> str:
    return subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip()


def read_text(path: str) -> str:
    return (CONTRACTS / path).read_text()


def read_json(path: str):
    return json.loads(read_text(path))


def read_yaml(path: str):
    return yaml.safe_load(read_text(path))


# Every Shared schema, by $id, so relative references between contracts resolve as for any other consumer.
UNLOADED: list[tuple[str, str]] = []
_ID_BY_PATH: dict[str, str] = {}
REGISTRY = Registry()
for _file in sorted(CONTRACTS.rglob("*.schema.json")):
    try:
        _doc = json.loads(_file.read_text())
        _id = _doc["$id"]
        REGISTRY = REGISTRY.with_resource(_id, Resource.from_contents(_doc, default_specification=DRAFT202012))
        _ID_BY_PATH[str(_file.relative_to(CONTRACTS))] = _id
    except Exception as exc:  # noqa: BLE001 - reported by the pin test, not swallowed
        UNLOADED.append((str(_file.relative_to(CONTRACTS)), repr(exc)))

# jsonschema only enforces the formats it can check; the suite asserts the ones it relies on are active.
FORMATS = jsonschema.Draft202012Validator.FORMAT_CHECKER


def validator_for(uri: str) -> jsonschema.Draft202012Validator:
    """A validator for the schema (or $defs fragment) named by an absolute Shared URI."""
    return jsonschema.Draft202012Validator({"$ref": uri}, registry=REGISTRY, format_checker=FORMATS)


def schema_uri(path: str, fragment: str = "") -> str:
    return _ID_BY_PATH[path] + (f"#{fragment}" if fragment else "")


def validate(uri: str, instance) -> None:
    validator_for(uri).validate(instance)


def errors(uri: str, instance) -> list[str]:
    return [e.message for e in validator_for(uri).iter_errors(instance)]


# ---- OpenAPI response contracts ---------------------------------------------------------------------------
OPENAPI_PATH = "erp/v1/openapi.yaml"
_OPENAPI = read_yaml(OPENAPI_PATH)


def _absolutise(node, base: Path):
    """Rewrite relative file $refs inside an OpenAPI schema node to absolute Shared $id URIs."""
    if isinstance(node, dict):
        out = {}
        for key, value in node.items():
            if key == "$ref" and isinstance(value, str) and not value.startswith("#"):
                target, fragment = urldefrag(value)
                relative = str((base / target).resolve().relative_to(CONTRACTS))
                out[key] = _ID_BY_PATH[relative] + (f"#{fragment}" if fragment else "")
            else:
                out[key] = _absolutise(value, base)
        return out
    if isinstance(node, list):
        return [_absolutise(item, base) for item in node]
    return node


def _follow(ref: str):
    node = _OPENAPI
    for part in ref.removeprefix("#/").split("/"):
        node = node[part]
    return node


def declared_statuses(path_template: str, method: str) -> set[int]:
    return {int(code) for code in _OPENAPI["paths"][path_template][method.lower()]["responses"]}


def response_validator(path_template: str, method: str, status: int, media: str) -> jsonschema.Draft202012Validator:
    response = _OPENAPI["paths"][path_template][method.lower()]["responses"][str(status)]
    if "$ref" in response:
        response = _follow(response["$ref"])
    schema = response["content"][media]["schema"]
    base = (CONTRACTS / OPENAPI_PATH).parent
    while "$ref" in schema and schema["$ref"].startswith("#"):
        schema = _follow(schema["$ref"])
    return jsonschema.Draft202012Validator(
        _absolutise(schema, base), registry=REGISTRY, format_checker=FORMATS)


def declared_media(path_template: str, method: str, status: int) -> set[str]:
    response = _OPENAPI["paths"][path_template][method.lower()]["responses"][str(status)]
    if "$ref" in response:
        response = _follow(response["$ref"])
    return set(response["content"])


def errors_for(path_template: str, method: str, status: int, media: str, instance) -> list[str]:
    return [e.message for e in response_validator(path_template, method, status, media).iter_errors(instance)]
