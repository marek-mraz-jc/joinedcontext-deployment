"""pin-images.py's tiers (T-4721): a production tier pins only digests that passed the full tests."""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts/pin-images.py"
DIGEST = "sha256:" + "a" * 64


@pytest.fixture
def pin(monkeypatch):
    spec = importlib.util.spec_from_file_location("pin_images", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    written = []
    monkeypatch.setattr(module, "head", lambda repository: "c" * 40)
    monkeypatch.setattr(module, "green", lambda repository, workflow, commit: True)
    monkeypatch.setattr(module, "published", lambda image, commit: DIGEST)
    monkeypatch.setattr(module, "signed", lambda repository, image, digest: True)
    monkeypatch.setattr(module, "pin_files", lambda pins: written.append(pins) or [Path("x")])
    module.written = written
    return module


def test_dev_pins_a_signed_digest_without_the_full_tests(pin, monkeypatch):
    monkeypatch.setattr(pin, "attested", lambda *a: pytest.fail("dev must not ask for the full tests"))
    pin.main("platform")
    assert pin.written and set(pin.written[0].values()) == {DIGEST}


def test_production_refuses_a_digest_without_the_full_tests_attestation(pin, monkeypatch):
    monkeypatch.setattr(pin, "attested", lambda repository, image, digest: False)
    with pytest.raises(SystemExit, match="has not passed the full tests"):
        pin.main("platform", "production")
    assert pin.written == []


def test_production_pins_a_promoted_digest(pin, monkeypatch):
    asked = []
    monkeypatch.setattr(pin, "attested", lambda repository, image, digest: asked.append(image) or True)
    pin.main("platform", "production")
    assert asked == pin.SOURCES["platform"][1]
    assert pin.written


def test_the_attestation_is_checked_against_promote_yml_on_main(pin, monkeypatch):
    calls = []
    monkeypatch.setattr(pin, "run", lambda *args, check=True: calls.append(args) or type("R", (), {"returncode": 1})())
    assert not pin.attested("joinedcontext-platform", "joinedcontext-platform", DIGEST)
    [args] = calls
    assert args[:4] == ("cosign", "verify-attestation", "--type", pin.FULL_TESTS)
    assert "https://github.com/marek-mraz-jc/joinedcontext-platform/.github/workflows/promote.yml@refs/heads/main" in args
