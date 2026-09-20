#!/usr/bin/env python3
"""A `curl` the forge bootstrap Job's script can be run against (T-2392).

The Job is a shell script that talks to exactly two addresses — the forge and the API server —
and it talks to both with `curl`. Putting a `curl` of our own on PATH therefore runs the real
script, in the real order, with no Gitea and no cluster: the contents endpoints keep their files
in a JSON state file, every other endpoint answers what the script's branches look at, and each
call is appended to a log a test can read.

Only what the script asks for is implemented. An address it never calls answers 404, which is
what an honest stub does with a request it does not understand.

    curl [-sS] [-f] [-o FILE] [-w '%{http_code}'] [-X METHOD] [-u U:P] [-H H] [-d BODY]
         [--cacert FILE] URL

The state file (`JC_FAKE_FORGE_STATE`) holds `{"contents": {path: text}, "calls": [...]}`; the
log is `JC_FAKE_FORGE_CALLS`, one `METHOD URL` per line.
"""

from __future__ import annotations

import base64
import json
import os
import re
import sys
from urllib.parse import unquote

STATE = os.environ["JC_FAKE_FORGE_STATE"]
CALLS = os.environ["JC_FAKE_FORGE_CALLS"]
ORG = os.environ.get("ORG", "joinedcontext")
REPO = os.environ.get("REPO", "configuration")


def load() -> dict:
    with open(STATE, encoding="utf-8") as handle:
        return json.load(handle)


def save(state: dict) -> None:
    with open(STATE, "w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=1, sort_keys=True)


def blob(path: str, text: str) -> dict:
    """What Gitea answers for one file: the content base64-encoded and a 40-hex sha."""
    import hashlib

    return {
        "name": path.rsplit("/", 1)[-1],
        "path": path,
        "sha": hashlib.sha1(text.encode("utf-8")).hexdigest(),
        "content": base64.b64encode(text.encode("utf-8")).decode("ascii"),
    }


def parse(argv: list[str]) -> dict:
    out = {"method": None, "out": None, "code": False, "data": None, "fail": False, "url": None}
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg in ("-s", "-S", "-sS", "-k"):
            pass
        elif arg == "-f":
            out["fail"] = True
        elif arg in ("-o", "-u", "-H", "--cacert"):
            if arg == "-o":
                out["out"] = argv[index + 1]
            index += 1
        elif arg == "-w":
            out["code"] = "%{http_code}" in argv[index + 1]
            index += 1
        elif arg == "-X":
            out["method"] = argv[index + 1]
            index += 1
        elif arg == "-d":
            out["data"] = argv[index + 1]
            index += 1
        elif arg.startswith("-"):
            pass
        else:
            out["url"] = arg
        index += 1
    if out["method"] is None:
        out["method"] = "POST" if out["data"] is not None else "GET"
    return out


def answer(call: dict, state: dict) -> tuple[int, str]:
    url, method = call["url"], call["method"]
    path = url.split("://", 1)[-1].split("/", 1)[-1]
    path = "/" + path

    if path.startswith("/api/healthz"):
        return 200, "{}"
    # The API server: every Secret write is accepted and remembered, every read answers what
    # was written. `read_secret` passes `-f`, so a miss has to be a failure and not an empty
    # body it would read as "there is no token".
    if "/api/v1/namespaces/" in path:
        name = path.rsplit("/", 1)[-1]
        if method == "GET":
            held = state["secrets"].get(name)
            return (200, json.dumps(held)) if held else (404, "{}")
        state["secrets"][name] = json.loads(call["data"])
        return 200, call["data"]
    if re.fullmatch(r"/api/v1/orgs/[^/]+", path):
        return 200, "{}"
    if re.fullmatch(r"/api/v1/repos/[^/]+/[^/]+", path):
        return 200, '{"default_branch":"main"}'
    if "/teams/search" in path:
        team = path.split("q=", 1)[-1]
        return 200, json.dumps({"data": [{"name": team}]})
    if path.endswith("/tokens") and method == "POST":
        return 201, '{"sha1":"%s"}' % ("a" * 40)

    contents = re.fullmatch(
        rf"/api/v1/repos/{re.escape(ORG)}/{re.escape(REPO)}/contents/(.+?)(\?ref=.*)?", path
    )
    if contents:
        file_path = unquote(contents.group(1))
        held = state["contents"].get(file_path)
        if method == "GET":
            return (200, json.dumps(blob(file_path, held))) if held is not None else (404, "{}")
        body = json.loads(call["data"])
        if method == "POST":
            if held is not None:
                return 422, '{"message":"the file already exists"}'
            state["contents"][file_path] = base64.b64decode(body["content"]).decode("utf-8")
            return 201, json.dumps(blob(file_path, state["contents"][file_path]))
        if method == "PUT":
            if held is None or body.get("sha") != blob(file_path, held)["sha"]:
                return 409, '{"message":"sha does not match"}'
            state["contents"][file_path] = base64.b64decode(body["content"]).decode("utf-8")
            return 200, json.dumps(blob(file_path, state["contents"][file_path]))
        if method == "DELETE":
            if held is None or body.get("sha") != blob(file_path, held)["sha"]:
                return 409, '{"message":"sha does not match"}'
            del state["contents"][file_path]
            return 200, '{"commit":{"sha":"%s"}}' % ("b" * 40)
    return 404, "{}"


def main() -> int:
    call = parse(sys.argv[1:])
    state = load()
    code, body = answer(call, state)
    state.setdefault("calls", []).append(f"{call['method']} {call['url']}")
    save(state)
    with open(CALLS, "a", encoding="utf-8") as handle:
        handle.write(f"{call['method']} {call['url']}\n")

    if call["out"]:
        with open(call["out"], "w", encoding="utf-8") as handle:
            handle.write(body)
    else:
        sys.stdout.write(body)
    if call["code"]:
        sys.stdout.write(str(code))
    # `-f` is what `read_secret` uses to turn a 404 into a failure rather than an empty file.
    return 22 if call["fail"] and code >= 400 else 0


if __name__ == "__main__":
    sys.exit(main())
