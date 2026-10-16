"""What the open-data mapping tests share (T-2787, T-2785): run a committed mapping by Bento over a
recorded answer, reduce an entity to `keyValues`, and check it against its space's generated JSON
Schema, which is what the gateway enforces."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

# The digest the pipeline runner pins (test_bystrica_pipelines.py, test_demo_feeds.py).
BENTO = "ghcr.io/warpstreamlabs/bento:1.22.0@sha256:ef674bebae45793c982c350d8f37c2c7661133c1dc65a5517fb977b36dc09841"

requires_docker = pytest.mark.skipif(
    shutil.which("docker") is None, reason="no container runtime, so Bento cannot run the mapping"
)

# The runner's shared caches, which a mapping may name (T-4052).
RESOURCES = Path(__file__).resolve().parent.parent / "components/pipeline-runner/streams/resources.yaml"


def _bento(mapping: Path, document: bytes, space: str, domain: str, codec: str, metadata: dict | None = None) -> bytes:
    pipeline = yaml.safe_load(mapping.read_text())["pipeline"]
    if metadata:
        # What a connection's own steps leave on the message, such as the member name an archive
        # read sets (PL-72), set the way those steps set it.
        pipeline["processors"].insert(0, {"mapping": "\n".join(f"meta {k} = {json.dumps(v)}" for k, v in metadata.items())})
    config = {
        "input": {"stdin": {"scanner": {"to_the_end": {}}}},
        "pipeline": pipeline,
        "cache_resources": yaml.safe_load(RESOURCES.read_text())["cache_resources"],
        # The runner's shared egress limit, which a mapping that fetches further pages names.
        "rate_limit_resources": yaml.safe_load(RESOURCES.read_text())["rate_limit_resources"],
        "output": {"stdout": {"codec": codec}},
        "logger": {"level": "error"},
    }
    result = subprocess.run(
        ["docker", "run", "--rm", "-i", "-e", f"JC_ORG_DOMAIN={domain}", "-e", f"JC_SPACE={space}",
         "-e", f"CONFIG={json.dumps(config)}", "--entrypoint", "sh", BENTO, "-c",
         'printf "%s" "$CONFIG" > /tmp/c.json && exec /bento -c /tmp/c.json'],
        input=document, capture_output=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr.decode() or result.stdout.decode()
    return result.stdout


def run(mapping: Path, document: bytes, space: str, domain: str = "hel.fi") -> list[dict]:
    """The mapping's processors over one fetched document, as the runner feeds it."""
    return json.loads(_bento(mapping, document, space, domain, "all-bytes"))


def run_all(mapping: Path, document: bytes, space: str, domain: str = "hel.fi", metadata: dict | None = None) -> list[dict]:
    """Like `run`, for a mapping that answers many messages (one entity each, or arrays), as one
    that splits and regroups its rows does: the runner batches whichever it gets (T-3356)."""
    entities: list[dict] = []
    for line in _bento(mapping, document, space, domain, "lines", metadata).decode().splitlines():
        if line.strip():
            message = json.loads(line)
            entities.extend(message if isinstance(message, list) else [message])
    return entities


def key_values(entity: dict) -> dict:
    """The entity as `keyValues`, the shape the generated JSON Schema describes."""
    out = {}
    for name, attribute in entity.items():
        if not isinstance(attribute, dict) or "type" not in attribute:
            out[name] = attribute
        elif attribute["type"] == "Relationship":
            out[name] = attribute["object"]
        elif attribute["type"] == "LanguageProperty":
            out[name] = attribute["languageMap"]
        elif attribute["type"] == "JsonProperty":
            out[name] = attribute["json"]
        else:
            out[name] = attribute["value"]
    return out


def schema_errors(schema_file: Path, entity: dict) -> list[str]:
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(schema_file.read_text())
    # The class definition refers to the enums beside it, so it is checked inside the document.
    validator = jsonschema.Draft7Validator(
        {**schema["definitions"][entity["type"]], "definitions": schema["definitions"]},
        format_checker=jsonschema.Draft7Validator.FORMAT_CHECKER,
    )
    return [e.message for e in validator.iter_errors(key_values(entity))]
