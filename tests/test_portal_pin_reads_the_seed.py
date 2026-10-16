"""The pinned Portal reads every field the seed's spaces carry (T-4054).

The Portal drops a manifest whole when its jc-core does not know a field: on 2026-10-12 the
Helsinki space gained `quality` and `retention` (T-3904) while dev still ran a Portal built on a
jc-core without them (T-3899), and the Portal removed every Helsinki view; all its Endpoints
answered 404. The portal pin names the platform commit its jc-core is built from (`platform` in
components/portal/images.yaml); a space field the seed carries needs that commit to contain the
one that taught jc-core the field.

Whether one commit contains another is asked of a platform clone (`JC_PLATFORM_DIR`, or the
sibling joinedcontext-platform folder) or else of GitHub's compare API; without either the
ancestry case skips, and the format case still holds.
"""

import json
import os
import re
import subprocess
import urllib.request
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
PLATFORM_REPO = "marek-mraz-jc/joinedcontext-platform"

# A ContextSpace spec field, and the platform commit whose jc-core first reads it.
SINCE = {
    "quality": "2883bd06a17ebe8568f37579d0578025fc9eb963",  # T-3899
    "retention": "2883bd06a17ebe8568f37579d0578025fc9eb963",  # T-3899
}

# A retention `history` word, and the platform commit whose jc-core first accepts it: an older
# one refuses the value and drops the space as it drops an unknown field (T-4275).
HISTORY_SINCE = {
    "off": "1e5b0ec9938bd530c6e810e86d872d4dae1442fb",  # T-4275
    "forever": "1e5b0ec9938bd530c6e810e86d872d4dae1442fb",  # T-4275
}


def pinned_platform() -> str:
    return yaml.safe_load((ROOT / "components/portal/images.yaml").read_text())["portal"]["portal"].get("platform", "")


def space_fields() -> dict[str, list[str]]:
    """Each field of SINCE a seed space carries, with the files that carry it."""
    found: dict[str, list[str]] = {}
    for path in sorted(ROOT.glob("components/*/seed/**/*.yaml")):
        for document in yaml.safe_load_all(path.read_text()):
            if isinstance(document, dict) and document.get("kind") == "ContextSpace":
                for field in SINCE.keys() & (document.get("spec") or {}).keys():
                    found.setdefault(field, []).append(str(path.relative_to(ROOT)))
    return found


def contains(pin: str, since: str) -> bool | None:
    """Whether platform commit `pin` contains `since`; None when nothing can answer."""
    clone = Path(os.environ.get("JC_PLATFORM_DIR", ROOT.parent / "joinedcontext-platform"))
    if (clone / ".git").exists():
        result = subprocess.run(["git", "-C", str(clone), "merge-base", "--is-ancestor", since, pin],
                                capture_output=True, text=True)
        if result.returncode in (0, 1):
            return result.returncode == 0
    request = urllib.request.Request(f"https://api.github.com/repos/{PLATFORM_REPO}/compare/{since}...{pin}")
    if os.environ.get("GITHUB_TOKEN"):
        request.add_header("Authorization", f"Bearer {os.environ['GITHUB_TOKEN']}")
    try:
        with urllib.request.urlopen(request, timeout=20) as answer:
            return json.load(answer)["status"] in ("ahead", "identical")
    except (OSError, KeyError, ValueError):
        return None


def test_the_portal_pin_names_its_platform_commit():
    assert re.fullmatch(r"[0-9a-f]{40}", pinned_platform()), "portal images.yaml: platform is the full commit"


def test_a_space_field_in_the_seed_is_one_the_pinned_portal_reads():
    fields = space_fields()
    assert set(fields) <= set(SINCE)
    pin = pinned_platform()
    for field, files in fields.items():
        known = contains(pin, SINCE[field])
        if known is None:
            pytest.skip("no platform clone and no answer from GitHub")
        assert known, (
            f"{files} carry `{field}`, which jc-core reads from platform {SINCE[field][:7]} on; "
            f"the pinned Portal is built on {pin[:7]}: pin a Portal that has it in the same commit"
        )


# An AssistantDeployment spec field, and the platform commit whose jc-core first reads it: an older
# Portal or assistant refuses it and drops the deployment whole (T-4343, the T-4296 lesson).
ASSISTANT_SINCE = {
    "widget": "9fdbd9bddd8e1ee677963614df3d25daf8c0c40a",  # T-4343
}


def assistant_fields() -> dict[str, list[str]]:
    """Each field of ASSISTANT_SINCE a seed AssistantDeployment carries, with the files that carry it."""
    found: dict[str, list[str]] = {}
    for path in sorted(ROOT.glob("components/*/seed/**/*.yaml")):
        for document in yaml.safe_load_all(path.read_text()):
            if isinstance(document, dict) and document.get("kind") == "AssistantDeployment":
                for field in ASSISTANT_SINCE.keys() & (document.get("spec") or {}).keys():
                    found.setdefault(field, []).append(str(path.relative_to(ROOT)))
    return found


def test_an_assistant_field_in_the_seed_is_one_the_pinned_portal_reads():
    pin = pinned_platform()
    for field, files in assistant_fields().items():
        known = contains(pin, ASSISTANT_SINCE[field])
        if known is None:
            pytest.skip("no platform clone and no answer from GitHub")
        assert known, (
            f"{files} carry `{field}`, which jc-core reads from platform {ASSISTANT_SINCE[field][:7]} on; "
            f"the pinned Portal is built on {pin[:7]}: pin a Portal (and an assistant) that has it first"
        )


def test_the_widget_field_is_caught_on_todays_pin():
    """platform 77d9a82, the Portal pin before T-4343, has no `widget`."""
    known = contains("77d9a825a46beb3cbf45bf512d922b2a1c6e7b75", ASSISTANT_SINCE["widget"])
    if known is None:
        pytest.skip("no platform clone and no answer from GitHub")
    assert known is False


def history_words() -> dict[str, list[str]]:
    """Each word of HISTORY_SINCE a seed space's retention says, with the files that say it."""
    found: dict[str, list[str]] = {}
    for path in sorted(ROOT.glob("components/*/seed/**/*.yaml")):
        for document in yaml.safe_load_all(path.read_text()):
            if isinstance(document, dict) and document.get("kind") == "ContextSpace":
                for rule in (document.get("spec") or {}).get("retention") or []:
                    if rule.get("history") in HISTORY_SINCE:
                        found.setdefault(rule["history"], []).append(str(path.relative_to(ROOT)))
    return found


def test_a_history_word_in_the_seed_is_one_the_pinned_portal_accepts():
    pin = pinned_platform()
    for word, files in history_words().items():
        known = contains(pin, HISTORY_SINCE[word])
        if known is None:
            pytest.skip("no platform clone and no answer from GitHub")
        assert known, (
            f"{sorted(set(files))} say `history: {word}`, which jc-core accepts from platform "
            f"{HISTORY_SINCE[word][:7]} on; the pinned Portal is built on {pin[:7]}: pin a Portal that has it"
        )


def test_an_older_pin_is_caught():
    """The pin dev ran when the Helsinki views went (portal 2c47e68, platform 5a2c609)."""
    known = contains("5a2c6091c1ccb05da2708d3d7f6f78194c92722d", SINCE["quality"])
    if known is None:
        pytest.skip("no platform clone and no answer from GitHub")
    assert known is False
