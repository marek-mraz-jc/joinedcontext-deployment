"""T-4740: the BBSK demo's host serves a landing page with the demo assistant docked, not a CKAN.

The page is static: files from demos/bbsk/chart/files/landing/ and the catalogue theme's dock
scripts, on the platform's pinned nginx. It says DEMO in its ribbon, title and footer, keeps search
engines out, carries no coat of arms or third-party file, and frames only the demo assistant.
"""

import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

import pytest
import yaml
from test_demo_bbsk import HOSTS, one, render

pytestmark = pytest.mark.xdist_group("docker-demo-bbsk-landing")

ROOT = Path(__file__).resolve().parent.parent
THEME = ROOT / "charts/ckan/files/jc_theme"
RIBBON = {"index.html": "DEMO · ukážka od joinedcontext, nie oficiálna stránka BBSK",
          "en.html": "DEMO · a demo by joinedcontext, not BBSK's official site"}


@pytest.fixture(scope="module", params=sorted(HOSTS))
def landing(request):
    env = request.param
    docs = render(env)
    site = one(docs, "ConfigMap", "demo-bbsk-landing-site")["data"]
    conf = one(docs, "ConfigMap", "demo-bbsk-landing")["data"]["default.conf"]
    domain = HOSTS[env].split(".", 1)[1].removeprefix("apps.")
    return env, domain, docs, site, conf


class Page(HTMLParser):
    """What a page loads (scripts, styles, frames, images) and the text it shows."""

    def __init__(self):
        super().__init__()
        self.loads, self.frames, self.meta, self.text = [], [], {}, []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "script":
            self.loads.append(a.get("src"))
        elif tag == "link" and a.get("rel") == "stylesheet":
            self.loads.append(a["href"])
        elif tag in ("img", "source", "video", "audio", "object", "embed"):
            self.loads.append(a.get("src") or a.get("data") or "")
        elif tag == "iframe":
            self.frames.append(a["src"])
        elif tag == "meta" and "name" in a:
            self.meta[a["name"]] = a["content"]

    def handle_data(self, data):
        self.text.append(data)


def parse(html: str) -> Page:
    page = Page()
    page.feed(html)
    return page


def test_the_page_is_static_on_the_pinned_nginx_and_closed_but_for_the_edge(landing):
    _, _, docs, _, _ = landing
    pod = one(docs, "Deployment", "demo-bbsk-landing")["spec"]["template"]["spec"]
    nginx = pod["containers"][0]
    assert nginx["image"].startswith("docker.io/nginxinc/nginx-unprivileged:") and "@sha256:" in nginx["image"]
    assert nginx["securityContext"]["readOnlyRootFilesystem"] is True
    assert pod["securityContext"]["runAsNonRoot"] is True and pod["automountServiceAccountToken"] is False
    policy = one(docs, "NetworkPolicy", "demo-bbsk-landing")["spec"]
    assert policy["podSelector"] == {"matchLabels": {"app.kubernetes.io/name": "demo-bbsk-landing"}}
    assert policy["ingress"][0]["ports"] == [{"protocol": "TCP", "port": 8080}]


def test_both_pages_say_demo_keep_search_engines_out_and_load_nothing_third_party(landing):
    _, domain, _, site, _ = landing
    for name, ribbon in RIBBON.items():
        page = parse(site[name])
        text = " ".join(page.text)
        assert text.count(ribbon) == 2, name  # the ribbon and the footer
        assert ribbon.split(" · ")[0] in site[name].split("<title>")[1].split("</title>")[0], name
        assert page.meta["robots"] == "noindex, nofollow", name
        # Every script and style is this host's own; the one frame is the demo assistant.
        assert page.loads and all(src and src.startswith("/") for src in page.loads), (name, page.loads)
        assert page.frames == [f"https://assistant.{domain}/d/bbsk-demo/widget?embed=1&dock=1"], name
        assert f"https://api.{domain}/api/mcp/d/bbsk-demo" in text, name
        assert "<form" not in site[name] and "__DOMAIN__" not in site[name], name
        # No coat of arms, no logo and no file of bbsk.sk: their site is only linked.
        assert "<img" not in site[name] and "<picture" not in site[name], name
        assert "bbsk.sk/themes" not in site[name] and "bbsk.sk/storage" not in site[name], name


def test_the_six_cards_are_the_demo_assistants_own_questions(landing):
    _, _, _, site, _ = landing
    seed = yaml.safe_load((ROOT / "components/context-gateway/seed/bbsk/bbsk-assistant-demo.yaml").read_text())
    for name, lang in (("index.html", "sk"), ("en.html", "en")):
        cards = [part.split("</strong>")[0] for part in site[name].split('<button type="button" data-ask><span class="head">')[1:]]
        cards = [card.split("<strong>")[1] for card in cards]
        assert cards == seed["spec"]["suggestions"][lang], name


def test_the_dock_is_the_catalogues_own_and_the_policy_frames_only_the_assistant(landing):
    _, domain, _, site, conf = landing
    for script in ("jc-dock.js", "jc-assistant.js"):
        assert site[script] == (THEME / f"public__{script}").read_text(), script
    csp = next(line for line in conf.splitlines() if "Content-Security-Policy" in line)
    assert "script-src 'self';" in csp and "style-src 'self';" in csp and "default-src 'none';" in csp
    assert f"frame-src https://assistant.{domain};" in csp and "frame-ancestors 'none'" in csp
    assert 'X-Robots-Tag "noindex, nofollow"' in conf


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture(scope="module")
def served(tmp_path_factory):
    """The smartcity render, served by its own pinned image as the cluster runs it."""
    if not shutil.which("docker"):
        pytest.skip("docker not installed")
    docs = render("smartcity")
    tmp = tmp_path_factory.mktemp("landing")
    (tmp / "site").mkdir()
    for name, body in one(docs, "ConfigMap", "demo-bbsk-landing-site")["data"].items():
        (tmp / "site" / name).write_text(body)
    (tmp / "default.conf").write_text(one(docs, "ConfigMap", "demo-bbsk-landing")["data"]["default.conf"])
    for path in [tmp, tmp / "site", *tmp.rglob("*")]:
        path.chmod(0o755 if path.is_dir() else 0o644)
    image = one(docs, "Deployment", "demo-bbsk-landing")["spec"]["template"]["spec"]["containers"][0]["image"]
    port = free_port()
    name = f"demo-bbsk-landing-{port}"
    started = subprocess.run(
        ["docker", "run", "-d", "--name", name, "--read-only", "--tmpfs", "/tmp", "--tmpfs", "/var/cache/nginx",
         "-u", "101:101", "-p", f"127.0.0.1:{port}:8080",
         "-v", f"{tmp / 'default.conf'}:/etc/nginx/conf.d/default.conf:ro", "-v", f"{tmp / 'site'}:/srv/site:ro", image],
        capture_output=True, text=True, check=False)
    if started.returncode != 0:
        pytest.skip(f"the pinned image does not run here: {started.stderr.strip()}")
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                urllib.request.urlopen(base + "/healthz", timeout=2)
                break
            except OSError:
                time.sleep(0.3)
        else:
            pytest.skip("nginx did not answer within 30 s")
        yield base
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, check=False)


class Stay(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


def fetch(url: str, method: str = "GET"):
    opener = urllib.request.build_opener(Stay)
    try:
        with opener.open(urllib.request.Request(url, method=method), timeout=10) as answer:
            return answer.status, answer.headers, answer.read().decode()
    except urllib.error.HTTPError as error:
        return error.code, error.headers, ""


def test_the_served_page_answers_with_noindex_and_nothing_else_is_served(served):
    status, headers, body = fetch(served + "/")
    assert status == 200 and "text/html" in headers["Content-Type"] and RIBBON["index.html"] in body
    assert headers["X-Robots-Tag"] == "noindex, nofollow" and "frame-ancestors 'none'" in headers["Content-Security-Policy"]
    assert "Set-Cookie" not in headers
    status, _, body = fetch(served + "/en/")
    assert status == 200 and RIBBON["en.html"] in body
    # A relative redirect, so the edge's https host stays in the address.
    status, headers, _ = fetch(served + "/en")
    assert status == 301 and headers["Location"] == "/en/"
    for path in ("/landing.css", "/landing.js", "/jc-dock.js", "/jc-assistant.js"):
        assert fetch(served + path)[0] == 200, path
    for path in ("/index.html", "/en.html", "/default.conf", "/.git", "/admin", "/api/3/action/package_list"):
        assert fetch(served + path)[0] == 404, path
    assert fetch(served + "/", "POST")[0] == 403
