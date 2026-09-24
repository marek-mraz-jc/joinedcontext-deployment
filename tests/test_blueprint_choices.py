"""A seeded blueprint's choices read as words (UI-16; T-2756).

The flow wizard renders a blueprint's parameter schema as a form. A plain `enum` shows the value
itself ("static", "30m"), so every choice is `oneOf` consts, each with a title.
"""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent / "components"


def blueprints():
    for path in sorted(ROOT.glob("**/seed/**/*.yaml")):
        for doc in yaml.safe_load_all(path.read_text()):
            if isinstance(doc, dict) and doc.get("kind") == "Blueprint":
                yield path, doc


def choices(node, at, found):
    if isinstance(node, dict):
        if isinstance(node.get("enum"), list) and all(isinstance(v, str) for v in node["enum"]):
            found.append(f"{at}: plain enum {node['enum']}")
        for option in node.get("oneOf") or []:
            if isinstance(option, dict) and "const" in option and not str(option.get("title", "")).strip():
                found.append(f"{at}: option {option['const']!r} has no title")
        for key, value in node.items():
            choices(value, f"{at}.{key}", found)
    elif isinstance(node, list):
        for item in node:
            choices(item, at, found)
    return found


def test_there_are_seeded_blueprints_to_check():
    assert len(list(blueprints())) >= 3


def test_every_choice_of_a_seeded_blueprint_is_titled():
    found = []
    for path, doc in blueprints():
        choices(doc["spec"].get("parameterSchema", {}), f"{path.relative_to(ROOT)}", found)
    assert found == []
