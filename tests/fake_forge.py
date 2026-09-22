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


def git_blob(text: str) -> str:
    """The id `git hash-object` gives the file: sha1 over `blob <size>\\0` and the bytes."""
    import hashlib

    data = text.encode("utf-8")
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def head_of(files: dict[str, str]) -> str:
    import hashlib

    return hashlib.sha1(json.dumps(files, sort_keys=True).encode("utf-8")).hexdigest()


def app_repository(path: str, method: str, call: dict, state: dict) -> tuple[int, str] | None:
    """An application's own repository (T-2599): created in the organization, read as a tree,
    written as one commit of file operations, and its main branch's head."""
    repos = state.setdefault("repos", {})
    if re.fullmatch(rf"/api/v1/orgs/{re.escape(ORG)}/repos", path) and method == "POST":
        body = json.loads(call["data"])
        if body["name"] in repos:
            return 409, '{"message":"the repository already exists"}'
        files = {"README.md": f"# {body['name']}\n"} if body.get("auto_init") else {}
        repos[body["name"]] = {"files": files, "private": body.get("private"), "head": head_of(files)}
        return 201, json.dumps({"name": body["name"]})
    match = re.fullmatch(rf"/api/v1/repos/{re.escape(ORG)}/([^/?]+)/(git/trees/main|contents|branches/main)(\?.*)?", path)
    if not match or match.group(1) == REPO or match.group(1) not in repos:
        return None
    repo = repos[match.group(1)]
    what = match.group(2)
    if what == "git/trees/main" and method == "GET":
        tree = [
            {"path": p, "mode": "100644", "type": "blob", "size": len(t.encode("utf-8")), "sha": git_blob(t), "url": f"http://forge.test/{p}"}
            for p, t in sorted(repo["files"].items())
        ]
        return 200, json.dumps({"sha": "c" * 40, "url": "http://forge.test/tree", "tree": tree, "truncated": False, "page": 1, "total_count": len(tree)}, separators=(",", ":"))
    if what == "branches/main" and method == "GET":
        return 200, json.dumps({"name": "main", "commit": {"id": repo["head"], "message": "seed"}}, separators=(",", ":"))
    if what == "contents" and method == "POST":
        body = json.loads(call["data"])
        files = dict(repo["files"])
        for change in body["files"]:
            held = files.get(change["path"])
            if change["operation"] == "create":
                if held is not None:
                    return 422, '{"message":"the file already exists"}'
            elif held is None or change.get("sha") != git_blob(held):
                return 409, '{"message":"sha does not match"}'
            if change["operation"] == "delete":
                del files[change["path"]]
            else:
                files[change["path"]] = base64.b64decode(change["content"]).decode("utf-8")
        repo["files"] = files
        repo["head"] = head_of(files)
        repo.setdefault("commits", []).append(body["message"])
        return 201, json.dumps({"commit": {"sha": repo["head"]}})
    return None


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
            data = argv[index + 1]
            # `-d @file` sends the file, which is how the Job posts a tree too big for argv.
            if data.startswith("@"):
                with open(data[1:], encoding="utf-8") as handle:
                    data = handle.read()
            out["data"] = data
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
    # The organization's packages: what a read:package token may read (AP-108).
    if re.fullmatch(r"/api/v1/packages/[^/?]+", path):
        return 200, "[]"
    if re.fullmatch(r"/api/v1/repos/[^/]+/[^/]+", path):
        name = path.rsplit("/", 1)[-1]
        known = name == REPO or name in state.setdefault("repos", {})
        return (200, '{"default_branch":"main"}') if known else (404, "{}")
    app = app_repository(path, method, call, state)
    if app is not None:
        return app
    if "/teams/search" in path:
        team = path.split("q=", 1)[-1]
        return 200, json.dumps({"data": [{"name": team}]})
    if path.endswith("/actions/runners/registration-token") and method == "POST":
        return 200, '{"token":"%s"}' % ("R" * 40)
    if path.endswith("/tokens") and method == "POST":
        return 201, '{"sha1":"%s"}' % ("a" * 40)

    contents = re.fullmatch(
        rf"/api/v1/repos/{re.escape(ORG)}/([^/?]+)/contents/(.+?)(\?ref=.*)?", path
    )
    # The configuration repository keeps its files in `contents`, any other one (a project
    # repository of layout 2) in `repos[name].files`.
    if contents and contents.group(1) != REPO and contents.group(1) not in state.setdefault("repos", {}):
        return 404, "{}"
    if contents:
        files = state["contents"] if contents.group(1) == REPO else state["repos"][contents.group(1)]["files"]
        file_path = unquote(contents.group(2))
        held = files.get(file_path)
        if method == "GET":
            return (200, json.dumps(blob(file_path, held))) if held is not None else (404, "{}")
        body = json.loads(call["data"])
        if method == "POST":
            if held is not None:
                return 422, '{"message":"the file already exists"}'
            files[file_path] = base64.b64decode(body["content"]).decode("utf-8")
            return 201, json.dumps(blob(file_path, files[file_path]))
        if method == "PUT":
            if held is None or body.get("sha") != blob(file_path, held)["sha"]:
                return 409, '{"message":"sha does not match"}'
            files[file_path] = base64.b64decode(body["content"]).decode("utf-8")
            return 200, json.dumps(blob(file_path, files[file_path]))
        if method == "DELETE":
            if held is None or body.get("sha") != blob(file_path, held)["sha"]:
                return 409, '{"message":"sha does not match"}'
            del files[file_path]
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
