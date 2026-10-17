"""T-2744 (DS-01, UI-82): the catalogue's dataset pages are written for people.

`ckanext_jc_theme/plugin.py` turns a dataset's CKAN fields and the extras `jcctl` publishes
(crates/jcctl/src/publish/ckan.rs) into labelled rows, the live API box and resources grouped
by format. The helpers are plain functions, so they are tested here against a stand-in for
the two CKAN modules they import; the templates that call them were walked on a CKAN 2.11.6
(the image's base) with axe clean on every page.
"""

import importlib.util
import json
import os
import re
import sys
import types
from pathlib import Path

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
THEME = PROJECT_ROOT / "charts/ckan/files/jc_theme"


@pytest.fixture
def theme(tmp_path, monkeypatch):
    """The plugin module, loaded with a branding block for `dev.example` and the page in `lang`."""
    branding = tmp_path / "branding.json"
    branding.write_text(json.dumps({"domain": "dev.example", "instanceName": "joinedcontext"}))
    monkeypatch.setenv("JC_BRANDING_FILE", str(branding))

    page = types.SimpleNamespace(lang="en")
    toolkit = types.ModuleType("ckan.plugins.toolkit")
    toolkit.h = types.SimpleNamespace(lang=lambda: page.lang)
    # CKAN's actions, answered from `page.actions` by name: a callable or an exception to raise.
    page.actions = {}

    def get_action(name):
        def action(context, data_dict):
            answer = page.actions[name]
            if isinstance(answer, Exception):
                raise answer
            return answer(data_dict)
        return action

    for error in ("ObjectNotFound", "NotAuthorized", "ValidationError"):
        setattr(toolkit, error, type(error, (Exception,), {}))
    toolkit.get_action = get_action
    toolkit.chained_helper = lambda helper: helper
    plugins = types.ModuleType("ckan.plugins")
    plugins.toolkit = toolkit
    plugins.SingletonPlugin = object
    plugins.implements = lambda *args, **kwargs: None
    page.loaded = set()
    plugins.plugin_loaded = lambda name: name in page.loaded
    plugins.IConfigurer = plugins.ITemplateHelpers = plugins.IFacets = plugins.IPackageController = object
    plugins.IBlueprint = object
    ckan = types.ModuleType("ckan")
    ckan.__file__ = str(tmp_path / "ckan/__init__.py")
    ckan.plugins = plugins
    for name, module in (("ckan", ckan), ("ckan.plugins", plugins), ("ckan.plugins.toolkit", toolkit)):
        monkeypatch.setitem(sys.modules, name, module)

    # No __pycache__ beside the theme: the chart ships every file of that directory.
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    spec = importlib.util.spec_from_file_location("jc_theme_plugin", THEME / "plugin.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.page = page
    return module


ENDPOINT = "https://dev.example/api/endpoint/hkiair/"

PUBLISHED = {
    "metadata_modified": "2026-09-25T08:00:00.000000",
    "organization": {"name": "helsinki", "title": "City of Helsinki"},
    "license_id": "cc-by",
    "license_title": "Creative Commons Attribution",
    "license_url": "http://www.opendefinition.org/licenses/cc-by",
    "groups": [{"display_name": "Environment"}],
    "tags": [{"display_name": "air quality"}, {"display_name": "pollution"}],
    "extras": [
        {"key": "frequency", "value": "http://publications.europa.eu/resource/authority/frequency/DAILY"},
        {"key": "publisher_name", "value": "Environment Services"},
        {"key": "publisher_uri", "value": "https://www.hel.fi/"},
        {"key": "contact_email", "value": "data@hel.fi"},
        {"key": "temporal_start", "value": "2024-01-01"},
        {"key": "endpoint", "value": ENDPOINT},
        {"key": "generated_by", "value": "jcctl/ckan-publisher"},
        {"key": "source_note", "value": "Measured by HSY"},
    ],
    "resources": [
        {"format": "CSV"}, {"format": "NGSI-LD"}, {"format": "csv"}, {"format": ""},
    ],
}


def test_the_about_list_names_publisher_licence_and_freshness_in_plain_words(theme):
    rows = {label: (text, link) for label, text, link in theme.jc_about(PUBLISHED)}
    assert rows["Publisher"] == ("Environment Services", "https://www.hel.fi/")
    assert rows["Licence"] == ("Creative Commons Attribution", "http://www.opendefinition.org/licenses/cc-by")
    assert rows["Topic"] == ("Environment", None)
    assert rows["Keywords"] == ("air quality, pollution", None)
    assert rows["Updated"] == ("Every day", None)
    assert rows["Last update"] == ("2026-09-25", None)
    assert rows["Next update expected"] == ("2026-09-26", None)
    assert rows["Contact"] == ("data@hel.fi", "mailto:data@hel.fi")
    assert rows["Time covered"] == ("2024-01-01", None)


def test_an_hourly_dataset_promises_an_hour_and_an_irregular_one_no_date(theme):
    hourly = dict(PUBLISHED, extras=[{"key": "frequency", "value": "HOURLY"}])
    rows = {label: text for label, text, _ in theme.jc_about(hourly)}
    # The hour follows the page's own date, never CKAN's "%B %d, %Y" order (T-4333).
    assert rows["Next update expected"] == "2026-09-25, 09:00 (UTC)"
    irregular = dict(PUBLISHED, extras=[{"key": "frequency", "value": ".../frequency/IRREG"}])
    rows = {label: text for label, text, _ in theme.jc_about(irregular)}
    assert rows["Updated"] == "Irregularly" and "Next update expected" not in rows
    label, next_update = theme.jc_frequency(dict(PUBLISHED, metadata_modified="not a date"))
    assert (label, next_update) == ("Every day", None)


def test_a_bare_dataset_shows_only_what_it_has_and_the_publisher_falls_back_to_the_organization(theme):
    assert theme.jc_about({}) == []
    bare = {"organization": {"name": "helsinki", "title": "City of Helsinki"}}
    assert theme.jc_about(bare) == [("Publisher", "City of Helsinki", None)]
    assert theme.jc_live({}) is None and theme.jc_resource_sections({}) == [] and theme.jc_more({}) == []
    assert theme.jc_previews({}) == [] and theme.jc_formats({}) == []


def test_a_link_that_is_not_http_is_shown_as_text(theme):
    hostile = dict(PUBLISHED, license_url="javascript:alert(1)",
                   extras=[{"key": "publisher_name", "value": "X"}, {"key": "publisher_uri", "value": "javascript:alert(1)"}])
    for _, _, link in theme.jc_about(hostile):
        assert link is None or link.startswith(("https://", "http://", "mailto:")), link


def test_the_live_box_shows_only_an_https_address_of_the_platform_and_a_query_that_answers(theme):
    live = theme.jc_live(PUBLISHED)
    assert live["url"] == ENDPOINT
    assert live["example"].endswith(f"'{ENDPOINT}ngsi-ld/v1/types'")
    for endpoint in ("http://dev.example/api/endpoint/x/", "https://context-gateway.jc.svc:8080/x/",
                     "https://dev.example.evil/x/", "https://evildev.example/x/"):
        foreign = dict(PUBLISHED, extras=[{"key": "endpoint", "value": endpoint}])
        assert theme.jc_live(foreign) is None, endpoint
    sub = dict(PUBLISHED, extras=[{"key": "endpoint", "value": "https://api.dev.example/e/x"}])
    assert theme.jc_live(sub)["url"] == "https://api.dev.example/e/x/"


def test_internal_extras_never_reach_more_details(theme):
    assert theme.jc_more(PUBLISHED) == [("source_note", "Measured by HSY")]
    # T-3025: the DCAT metadata jcctl writes for harvesters is not words for a reader: the EU
    # licence URI beside the licence the About list already links, and the themes as a JSON list.
    dcat = dict(PUBLISHED, extras=PUBLISHED["extras"] + [
        {"key": "license_url", "value": "http://publications.europa.eu/resource/authority/licence/CC_BY_4_0"},
        {"key": "theme", "value": '["http://publications.europa.eu/resource/authority/data-theme/TRAN"]'},
        {"key": "spatial_uri", "value": "http://data.europa.eu/nuts/code/CZ010"},
    ])
    assert theme.jc_more(dcat) == [("source_note", "Measured by HSY")]
    rows = {label: text for label, text, _ in theme.jc_about(dcat)}
    assert rows["Area covered"] == "Prague (NUTS CZ010)"  # linked to its definition (T-4333)


SCHEMA = "https://dev.example/api/endpoint/praha/schema/v1/"

# The resources `jcctl` publishes for an Endpoint, in its order: the DataStore table last.
PUBLISHED_RESOURCES = [
    {"id": "r-ngsi", "name": "NGSI-LD API", "format": "NGSI-LD", "url": ENDPOINT + "ngsi-ld/v1/"},
    {"id": "r-geo", "name": "GeoJSON", "format": "GeoJSON", "url": ENDPOINT + "file.geojson"},
    {"id": "r-csv", "name": "CSV", "format": "CSV", "url": ENDPOINT + "file.csv"},
    {"id": "r-mcp", "name": "Model Context Protocol", "format": "MCP", "url": ENDPOINT + "mcp"},
    {"id": "r-index", "name": "Schema artifacts", "format": "JSON", "url": ENDPOINT + "schema/index.json"},
    {"id": "r-shacl", "name": "model.shacl.ttl", "format": "SHACL", "url": SCHEMA + "model.shacl.ttl"},
    {"id": "r-ctx", "name": "context.jsonld", "format": "JSON-LD", "url": SCHEMA + "context.jsonld?v=1"},
    {"id": "r-odd", "name": "Unlabelled", "format": "", "url": ENDPOINT + "other"},
    {"id": "r-table", "name": "DataStore", "format": "CSV", "url": "https://data.dev.example/datastore/dump/r-table",
     "datastore_active": True},
]


def test_the_datastore_table_leads_the_files_and_the_model_is_a_section_of_its_own(theme):
    """T-3009: the DataStore resource was the last of fourteen links; it leads the data now."""
    sections = theme.jc_resource_sections({"resources": PUBLISHED_RESOURCES})
    ids = {s["key"]: [i["resource"]["id"] for i in s["items"]] for s in sections}
    assert [s["key"] for s in sections] == ["data", "api", "schema"]
    assert ids["data"] == ["r-table", "r-csv", "r-geo", "r-odd"]
    assert ids["api"] == ["r-ngsi", "r-mcp"]
    # Everything under the Endpoint's /schema/ path is the model, whatever format it names.
    assert sorted(ids["schema"]) == ["r-ctx", "r-index", "r-shacl"]
    data = sections[0]["items"]
    assert data[0]["what"] == "The table above, as one file"
    assert data[1]["what"] == "A table for a spreadsheet"
    assert data[-1]["format"] == "—" and data[-1]["what"] == ""
    assert sections[2]["title"] == "Data model" and sections[1]["lead"]


def test_a_dataset_with_only_files_has_one_section_and_a_search_result_names_no_model_format(theme):
    files = [r for r in PUBLISHED_RESOURCES if r["id"] in ("r-csv", "r-geo")]
    assert [s["key"] for s in theme.jc_resource_sections({"resources": files})] == ["data"]
    assert theme.jc_formats({"resources": PUBLISHED_RESOURCES}) == ["CSV", "GeoJSON", "NGSI-LD", "MCP"]


# Since T-3012 the mirror writes one DataStore table per entity type, named by the type and
# with no format of its own.
TYPE_TABLES = [
    {"id": "t-bikes", "name": "BikeHireDockingStation", "format": "", "url": "https://data.dev.example/datastore/dump/t-bikes",
     "datastore_active": True},
    {"id": "t-air", "name": "AirQualityObserved", "format": "", "url": "https://data.dev.example/datastore/dump/t-air",
     "datastore_active": True},
]


def test_the_page_frames_every_type_table_with_its_row_count(theme):
    rows = {"t-air": 300, "t-bikes": 24808, "r-table": 5}
    theme.page.actions = {
        "resource_view_list": lambda d: [{"id": "v-image", "view_type": "image_view"},
                                         {"id": "v-" + d["id"], "view_type": "datatables_view"}],
        "datastore_search": lambda d: {"total": rows[d["resource_id"]]} if d["limit"] == 0 else {},
    }
    previews = theme.jc_previews({"resources": PUBLISHED_RESOURCES[:3] + TYPE_TABLES})
    assert [p["resource"]["id"] for p in previews] == ["t-air", "t-bikes"]
    assert [p["view"]["id"] for p in previews] == ["v-t-air", "v-t-bikes"]
    assert theme.jc_total(previews) == 25108 and theme.jc_number(25108) == "25\u202f108"
    # A table the mirror wrote without a format downloads as CSV and says what it is.
    data = theme.jc_resource_sections({"resources": TYPE_TABLES})[0]["items"]
    assert [(i["format"], i["what"]) for i in data] == [("CSV", "The table above, as one file")] * 2


def test_a_table_without_a_view_or_a_count_still_shows_and_says_so(theme):
    theme.page.actions = {
        "resource_view_list": theme.toolkit.NotAuthorized(),
        "datastore_search": theme.toolkit.ObjectNotFound(),
    }
    previews = theme.jc_previews({"resources": PUBLISHED_RESOURCES})
    assert previews == [{"resource": PUBLISHED_RESOURCES[-1], "view": None, "total": None}]
    assert theme.jc_total(previews) is None and theme.jc_total([]) is None
    assert theme.jc_number(None) == "" and theme.jc_number("x") == ""
    read = (THEME / "templates__package__read.html").read_text()
    assert "h.jc_t('no_view')" in read and "total is not none" in read and "preview.total is not none" in read


def test_only_the_first_table_is_open_so_the_others_load_nothing_until_asked():
    read = (THEME / "templates__package__read.html").read_text()
    assert '<details class="jc-table"{% if loop.first %} open{% endif %}>' in read
    assert 'loading="lazy"' in read


def test_the_table_comes_before_the_about_list_on_the_dataset_page():
    read = (THEME / "templates__package__read.html").read_text()
    assert read.index("h.jc_previews(pkg)") < read.index("h.jc_about(pkg)") < read.index("h.jc_live(pkg)")
    # The framed table carries a title a screen reader announces.
    assert re.search(r"<iframe[^>]*title=\"\{\{ h.jc_t\('table_title'\) \}\}: \{\{ name \}\}", read)


def test_the_mcp_panel_names_the_installation_s_hub_and_nothing_else(theme):
    """T-4114, EP-113: one address for the whole catalogue, a ready line per client."""
    from base64 import b64decode
    from urllib.parse import parse_qs, unquote, urlsplit

    mcp = theme.jc_mcp_install()
    hub = "https://dev.example/api/mcp"
    assert mcp["url"] == hub
    # One argument per line and the address alone on its JSON line, so no line is wider than the
    # address a narrow card has to show anyway (T-4284).
    assert mcp["claude"] == f"claude mcp add --transport http \\\n  joinedcontext \\\n  {hub}"
    assert json.loads(mcp["json"]) == {"mcpServers": {"joinedcontext": {"type": "http", "url": hub}}}
    assert f'  "{hub}"' in mcp["json"].splitlines()
    # The address breaks only before a single slash, never inside a word.
    assert mcp["url_parts"] == ["https://dev.example", "/api", "/mcp"]
    assert mcp["vscode"].startswith("vscode:mcp/install?")
    assert json.loads(unquote(mcp["vscode"].split("?", 1)[1])) == {"name": "joinedcontext", "type": "http", "url": hub}
    cursor = urlsplit(mcp["cursor"])
    assert (cursor.scheme, cursor.netloc, cursor.path) == ("cursor", "anysphere.cursor-deeplink", "/mcp/install")
    query = parse_qs(cursor.query)
    assert query["name"] == ["joinedcontext"]
    assert json.loads(b64decode(query["config"][0])) == {"url": hub}
    # No dataset, no token: every line is the same for every page (EP-110).
    for line in (v for v in mcp.values() if isinstance(v, str)):
        assert "endpoint/" not in unquote(line) and "token" not in line.lower() and "bearer" not in line.lower()


@pytest.mark.parametrize("domain", [None, "", "dev.example\" onmouseover=\"x", "dev.example/evil", "localhost", 7])
def test_the_mcp_panel_is_left_out_without_a_plain_domain(theme, domain):
    theme.BRANDING["domain"] = domain
    assert theme.jc_mcp_install() is None


def test_the_mcp_panel_is_on_the_home_page_and_every_dataset_page_with_its_copy_script():
    panel = (THEME / "templates__snippets__jc_mcp_install.html").read_text()
    for page in ("templates__home__index.html", "templates__package__read.html"):
        text = (THEME / page).read_text()
        assert "{% snippet 'snippets/jc_mcp_install.html'" in text, page
        assert "url_for_static('/jc-copy.js')" in text, page
    # One status line per page: the live box's when the dataset page has one.
    assert '{% if not live %}<p class="visually-hidden" role="status"' in panel
    assert panel.count("{{ copy('") == 3


def test_the_mcp_card_puts_claude_first_and_keeps_its_code_whole():
    """T-4284 (owner screenshot): the address and the code are never cut or broken mid-word, each
    copy button sits in its block's header, and the Claude connector steps come first."""
    panel = (THEME / "templates__snippets__jc_mcp_install.html").read_text()
    order = [panel.index(key) for key in ("mcp_claude_ai_1", "mcp_vscode", "mcp_cursor", "jc-mcp-claude-label", "jc-mcp-json-label")]
    assert order == sorted(order)
    assert panel.count('<div class="jc-code-head">') == 3
    assert "mcp.url_parts | join('<wbr>' | safe)" in panel
    css = (THEME / "public__jc-theme.css").read_text()
    assert ".jc-live .jc-code pre { white-space: pre; overflow-wrap: normal; overflow-x: auto; }" in css
    assert ".jc-code .jc-code-url { overflow-wrap: normal; word-break: normal; }" in css
    # The home page shows the card in the main column, where its code has room, not in the side.
    home = (THEME / "templates__home__index.html").read_text()
    main, side = home.index('<div class="jc-main">'), home.index('<div class="jc-side">')
    assert main < home.index("{% snippet 'snippets/jc_mcp_install.html'") < side


def test_each_resource_has_its_one_action_named_for_a_screen_reader():
    item = (THEME / "templates__package__snippets__resource_item.html").read_text()
    assert "dropdown" not in item and "{{ _('Explore') }}" not in item
    # The publisher's own page opens; only a file downloads (T-4333).
    assert "h.jc_t('open') if jc_section in ('api', 'source') else h.jc_t('download')" in item
    assert item.count('<span class="visually-hidden"> {{ name }}</span>') == 3
    assert "{% if not url_is_edit %}" in item and "jc_format or h.get_translated(res, 'format')" in item


@pytest.mark.parametrize("lang, words", [
    ("sk", ("Vydavateľ", "Denne")), ("cs_CZ", ("Vydavatel", "Denně")), ("de", ("Herausgeber", "Täglich")), ("fi", ("Publisher", "Every day")),
])
def test_the_page_language_picks_the_words_and_an_unknown_one_reads_english(theme, lang, words):
    theme.page.lang = lang
    rows = dict((label, text) for label, text, _ in theme.jc_about(PUBLISHED))
    assert words[0] in rows and rows[words[0]] == "Environment Services"
    assert words[1] in rows.values()


def test_every_word_of_the_theme_is_in_all_four_languages(theme):
    for table in (theme.STRINGS, theme.FORMATS, theme.MODEL_FILES):
        for key, words in table.items():
            assert set(words) == {"en", "sk", "cs", "de"}, key
    for key, (words, _) in theme.FREQUENCIES.items():
        assert set(words) == {"en", "sk", "cs", "de"}, key


def test_the_search_filters_are_named_in_plain_words(theme):
    facets = {"organization": "Organizations", "groups": "Groups", "tags": "Tags", "res_format": "Formats", "license_id": "Licenses"}
    renamed = theme.JcThemePlugin().dataset_facets(dict(facets), "dataset")
    assert renamed == {"organization": "Publisher", "groups": "Topic", "tags": "Keywords", "res_format": "Format", "license_id": "Licence"}


def test_the_portal_link_is_on_the_installation_s_domain(theme):
    assert theme.jc_portal_url() == "https://portal.dev.example/"


def test_every_page_template_and_static_file_is_mounted_at_its_path(rendered):
    (ckan,) = [d for d in rendered("dev") if d.get("kind") == "Deployment" and d["metadata"]["name"].endswith("ckan")
               and any(c["name"] == "ckan" for c in d["spec"]["template"]["spec"]["containers"])]
    (container,) = [c for c in ckan["spec"]["template"]["spec"]["containers"] if c["name"] == "ckan"]
    mounts = {m["subPath"]: m["mountPath"] for m in container["volumeMounts"] if m["name"] == "theme"}
    files = [p.name for p in THEME.iterdir() if p.name.startswith(("templates__", "public__"))]
    assert files, "the theme has page templates"
    for name in files:
        assert mounts[name] == "/srv/theme/ckanext_jc_theme/" + name.replace("__", "/"), name
    assert "__init__.py" in mounts and mounts["__init__.py"].endswith("ckanext_jc_theme/__init__.py")


def test_the_theme_loads_nothing_from_another_origin():
    for path in THEME.iterdir():
        if path.suffix == ".py":
            continue
        text = path.read_text()
        assert not re.search(r"<script>|(src|href)=\"(https?:)?//|(?<!\w)url\(|@import", text), path.name


# --- T-2888: the catalogue wears the installation's look, and a failed sign-in says why ---------


def test_the_brand_colour_reaches_bootstrap_and_its_text_stays_legible(theme, tmp_path):
    assert theme.BRANDING["primaryRgb"] == "29, 78, 216"
    assert theme.BRANDING["primaryForeground"] == "#ffffff"
    light = tmp_path / "light.json"
    light.write_text(json.dumps({"colours": {"primary": "#ffe977"}}))
    theme.BRANDING_FILE = str(light)
    block = theme._load()
    assert block["primaryRgb"] == "255, 233, 119"
    # White on a pale yellow is unreadable; the login theme's YIQ rule gives black.
    assert block["primaryForeground"] == "#000000"
    short = tmp_path / "short.json"
    short.write_text(json.dumps({"colours": {"primary": "#00f"}}))
    theme.BRANDING_FILE = str(short)
    assert theme._load()["primaryRgb"] == "0, 0, 255"


STOCK_TEALS = r"#206b82|#187794|#1a5668|#005d7a|#003647|#00232e|#bfd7de|#d9e7eb|#000f14"


def test_no_stock_ckan_colour_survives_the_theme():
    """CKAN compiles its teal into its own rules; each group of them is restated on the brand."""
    css = (THEME / "public__jc-theme.css").read_text()
    for variable in ("--bs-primary: var(--jc-primary)", "--bs-primary-rgb: var(--jc-primary-rgb)",
                     "--bs-link-color: var(--jc-primary)"):
        assert variable in css, variable
    for rule in (".btn-link, .link-primary", ".btn-primary:hover", ".form-check-input:checked",
                 ".form-control:focus", ".masthead .main-navbar ul li:hover a", ".view-list li a.active .icon",
                 ".account-masthead {", ".dropdown-item.active", ".page-item.active .page-link",
                 "body.dt-view .page-item.active .page-link"):
        assert rule in css, rule
    for path in THEME.iterdir():
        if path.suffix in (".html", ".css"):
            assert not re.search(STOCK_TEALS, path.read_text(), re.I), path.name


def test_the_stylesheet_carries_no_colour_of_its_own():
    """T-3009: every colour is the branding block's or mixed from it, so values restyle it all."""
    css = (THEME / "public__jc-theme.css").read_text()
    assert not re.search(r"#[0-9a-f]{3,8}\b|\brgba?\(|\bhsla?\(", css, re.I)
    named = re.findall(r":\s*(white|black|red|blue|green|gray|grey|navy|teal)\b", css, re.I)
    assert not named, named
    styles = (THEME / "templates__snippets__jc_styles.html").read_text()
    for token in ("--jc-primary:", "--jc-primary-fg:", "--jc-primary-rgb:", "--jc-secondary:", "--jc-accent:",
                  "--jc-background:", "--jc-text:", "--jc-font-heading:", "--jc-font-body:"):
        assert token in styles, token
    assert "h.url_for_static('/jc-theme.css')" in styles


def test_the_table_view_wears_the_theme_and_the_theme_s_templates_win():
    """The table view's own template empties the styles block; the theme restores it there, and
    only the first plugin's templates outrank the table view's."""
    view = (THEME / "templates__datatables__datatables_view.html").read_text()
    assert "{% ckan_extends %}" in view and "snippets/jc_styles.html" in view
    assert "snippets/jc_styles.html" in (THEME / "templates__base.html").read_text()
    values = yaml.safe_load((PROJECT_ROOT / "charts/ckan/values.yaml").read_text())
    assert values["ckan"]["plugins"].split()[0] == "jc_theme"


def test_the_home_page_replaces_ckan_s_sample_page():
    home = (THEME / "templates__home__index.html").read_text()
    assert "{% block primary_content %}" in home
    for part in ("brand.tagline or h.jc_t('tagline')", "h.get_site_statistics()", "h.jc_recent(6)",
                 "get_facet_items_dict('organization'", 'role="search"', '<label for="jc-hero-q">'):
        assert part in home, part
    assert "home/snippets/" not in home


def test_tagline_and_footer_lines_are_read_as_words_and_nothing_else(theme, tmp_path):
    assert theme.BRANDING["tagline"] == "" and theme.BRANDING["footerLines"] == []
    block = tmp_path / "words.json"
    block.write_text(json.dumps({"tagline": "Open data of the city",
                                 "footerLines": ["Demo instance, not affiliated.", "", "  ", 7, None]}))
    theme.BRANDING_FILE = str(block)
    loaded = theme._load()
    assert loaded["tagline"] == "Open data of the city"
    assert loaded["footerLines"] == ["Demo instance, not affiliated."]
    block.write_text(json.dumps({"tagline": {"x": 1}, "footerLines": "not a list"}))
    loaded = theme._load()
    assert loaded["tagline"] == "" and loaded["footerLines"] == []


def test_the_footer_carries_the_installations_links_and_none_of_ckans():
    footer = (THEME / "footer.html").read_text()
    assert "{% block footer_links_ckan %}{% endblock %}" in footer
    for stock in ("docs.ckan.org", "ckan.org", "opendefinition", "od_80x15"):
        assert stock not in footer, stock
    assert "h.jc_t('about_site')" in footer and "h.jc_portal_url()" in footer
    # The demo disclaimer stays: the organisation line, and the footer lines of the block.
    assert "brand.organisation" in footer and "brand.footerLines" in footer


def test_the_footers_api_link_opens_the_page_that_explains_the_api_not_raw_json():
    """T-4234 (photo audit T-4161 #12): "Catalogue API" opened package_list's raw JSON with no
    word on what the API offers. It opens the About page's developer section, which names the
    address, says what it returns and links the JSON one step further."""
    footer = (THEME / "footer.html").read_text()
    assert "<a href=\"{{ h.url_for('home.about') }}#api\">{{ h.jc_t('catalogue_api') }}</a>" in footer
    assert "logic_function='package_list'" not in footer
    about = (THEME / "templates__home__about.html").read_text()
    assert '<h2 id="api">{{ h.jc_t(\'about_machines\') }}</h2>' in about
    assert "logic_function='package_list'" in about and "h.jc_t('about_api')" in about


def test_a_second_deployment_restyles_the_catalogue_from_values_alone(rendered, rendered_variant):
    """T-3009: a new palette, logo, tagline and footer reach the theme with no file of it edited."""
    logo = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><rect width="1" height="1" fill="#8a1538"/></svg>'

    def rebrand(tree):
        env = tree / "deployment/environments/dev/global.yaml.gotmpl"
        text = env.read_text()
        assert "primary: '#0000bf'" in text
        text = text.replace("primary: '#0000bf'", "primary: '#8a1538'")
        text = text.replace("    logo: logo.svg\n", "    logo: logo.svg\n    tagline: Otvorené dáta mesta\n"
                            "    footerLines:\n      - Demo, not affiliated.\n", 1)
        env.write_text(text)
        (tree / "deployment/environments/dev/branding/logo.svg").write_text(logo + "\n")

    def theme_of(docs):
        (cm,) = [d for d in docs if d.get("kind") == "ConfigMap" and d["metadata"]["name"] == "ckan-theme"]
        (ckan,) = [d for d in docs if d.get("kind") == "Deployment" and d["metadata"]["name"] == "ckan"]
        return cm["data"], ckan["spec"]["template"]["metadata"]["annotations"]["checksum/theme"]

    before, before_sum = theme_of(rendered("dev"))
    after, after_sum = theme_of(rendered_variant("dev", rebrand))
    branding = json.loads(after["branding.json"])
    assert branding["colours"]["primary"] == "#8a1538"
    assert branding["tagline"] == "Otvorené dáta mesta" and branding["footerLines"] == ["Demo, not affiliated."]
    assert after["logo.svg"].strip() == logo
    # The theme's own files are byte for byte the same: only the values changed.
    assert {k: v for k, v in after.items() if k not in ("branding.json", "logo.svg")} == \
        {k: v for k, v in before.items() if k not in ("branding.json", "logo.svg")}
    # And the pod restarts to show it.
    assert after_sum != before_sum


@pytest.mark.parametrize("reason, key", [
    ("Login process was not started properly", "sso_cookie"),
    ("The app state does not match", "sso_state"),
    ("Unsupported token type. Should be 'Bearer'.", "sso_refused"),
    ("No access token returned from the token endpoint.", "sso_refused"),
    ("Unique user not found", "sso_account"),
    ("access_denied", "sso_other"),
])
def test_a_failed_sign_in_says_why_once_in_words_a_person_acts_on(theme, reason, key):
    session = {theme.SSO_ERROR: reason}
    assert theme.jc_sso_error(session) == theme.STRINGS[key]["en"]
    # Said once: a reload of the login page does not repeat an old failure.
    assert theme.jc_sso_error(session) is None
    theme.page.lang = "sk"
    session[theme.SSO_ERROR] = reason
    assert theme.jc_sso_error(session) == theme.STRINGS[key]["sk"]


def test_a_sign_in_that_did_not_fail_says_nothing(theme):
    assert theme.jc_sso_error({}) is None


def test_the_login_page_shows_the_reason_as_an_alert():
    login = (THEME / "templates__user__login.html").read_text()
    assert "h.jc_sso_error()" in login and 'role="alert"' in login


# --- T-3028: the About page, the publisher and topic pages speak for this catalogue ------------


def test_the_about_page_says_whose_catalogue_this_is_and_how_to_reach_the_data(theme, tmp_path):
    block = tmp_path / "about.json"
    block.write_text(json.dumps({"instanceName": "Praha Context", "organisation": "Hlavní město Praha",
                                 "contactEmail": "opendata@praha.eu"}))
    theme.BRANDING_FILE = str(block)
    theme.BRANDING = theme._load()
    theme.page.loaded = {"dcat"}
    about = theme.jc_about_site()
    assert about == {"intro": "Praha Context is the open data catalogue of Hlavní město Praha.",
                     "dcat": True, "email": "opendata@praha.eu"}
    theme.page.lang = "de"
    assert theme.jc_about_site()["intro"] == "Praha Context ist der Katalog offener Daten von Hlavní město Praha."


def test_an_about_page_without_organisation_contact_or_dcat_leaves_those_out(theme, tmp_path):
    block = tmp_path / "bare.json"
    block.write_text(json.dumps({"instanceName": "City Context", "contactEmail": "not an address"}))
    theme.BRANDING_FILE = str(block)
    theme.BRANDING = theme._load()
    assert theme.jc_about_site() == {"intro": "City Context is an open data catalogue.", "dcat": False, "email": ""}
    about = (THEME / "templates__home__about.html").read_text()
    assert "{% if about.dcat %}" in about and "{% if about.email %}" in about


def test_a_sysadmin_s_own_about_text_still_wins_and_no_ckan_advert_is_left():
    about = (THEME / "templates__home__about.html").read_text()
    assert "{% if g.site_about %}\n    {{ super() }}" in about
    assert "about_text.html" not in about and "ckan.org" not in about
    for name in ("templates__organization__snippets__helper.html", "templates__group__snippets__helper.html"):
        helper = (THEME / name).read_text()
        assert "CKAN" not in helper.split("#}", 1)[1] and "h.jc_t(" in helper, name


def test_the_header_names_the_sections_as_the_search_filters_do():
    header = (THEME / "header.html").read_text()
    for key in ("nav_datasets", "nav_publishers", "nav_topics", "nav_about"):
        assert f"h.jc_t('{key}')" in header, key
    assert "_('Organizations')" not in header and "_('Groups')" not in header


def test_publisher_and_topic_cards_are_a_grid_that_wraps_at_words():
    css = (THEME / "public__jc-theme.css").read_text()
    assert re.search(r"\.media-grid \{ clear: both; display: grid;", css)
    assert ".media-grid > .clearfix { display: none; }" in css
    assert "word-break: normal" in css and "float: none; width: auto" in css
    for name in ("templates__organization__snippets__organization_list.html", "templates__group__snippets__group_list.html"):
        listing = (THEME / name).read_text()
        # CKAN's media-grid module places each card absolutely (masonry) over the grid.
        assert 'data-module="media-grid"' not in listing and '<ul class="media-grid">' in listing, name


def test_a_short_page_keeps_its_footer_at_the_bottom():
    css = (THEME / "public__jc-theme.css").read_text()
    assert "body:not(.dt-view) { min-height: 100vh; display: flex; flex-direction: column; }" in css
    assert "body:not(.dt-view) > .site-footer { margin-top: auto; }" in css


# T-3048: what a reader meets on the resource page, the search filters and a narrow table.

REGISTRE = {"name": "bbsk-registre", "title": "Registre kraja"}


@pytest.mark.parametrize("lang, shacl, owl", [
    ("en", "Validation rules", "OWL"),
    ("sk", "Pravidlá kontroly", "OWL"),
    ("fi", "Validation rules", "OWL"),
])
def test_a_data_model_file_is_named_in_words_without_the_dataset_s_name(theme, lang, shacl, owl):
    theme.page.lang = lang
    label = theme.jc_resource_label
    assert label({"name": "bbsk-registre model.shacl.ttl"}, REGISTRE) == shacl
    assert label({"name": "bbsk-registre model.owl.ttl"}, REGISTRE) == owl
    # Every file jcctl publishes for a model reads as words, none as a file name.
    names = {label({"name": f"bbsk-registre {file}"}, REGISTRE) for file in theme.MODEL_FILES}
    assert len(names) == len(theme.MODEL_FILES) and not any("bbsk-registre" in n for n in names)


def test_another_resource_keeps_its_name_and_an_empty_one_falls_back(theme):
    label = theme.jc_resource_label
    assert label({"name": "Bridge"}, REGISTRE) == "Bridge"
    assert label({"name": "bbsk-registre context.jsonld"}, None) == "bbsk-registre context.jsonld"
    assert label({"name": "bbsk-registre"}, REGISTRE) == "bbsk-registre"  # nothing after the prefix
    assert label({"name": "", "format": "CSV"}, REGISTRE) == "CSV"
    assert label({"id": "r1"}, REGISTRE) == "r1"
    assert label(None, None) == ""


def test_the_resource_list_and_page_name_resources_in_words_and_never_cut_them():
    sidebar = (THEME / "templates__package__snippets__resources.html").read_text()
    page = (THEME / "templates__package__resource_read.html").read_text()
    row = (THEME / "templates__package__snippets__resource_item.html").read_text()
    for template in (sidebar, page, row):
        assert "h.jc_resource_label(" in template
        assert "|truncate" not in template and "| truncate" not in template
    assert 'aria-current="page"' in sidebar
    crumb = page[page.index("{% block breadcrumb_content %}"):page.index("{% endblock %}", page.index("{% block breadcrumb_content %}"))]
    assert "h.jc_resource_label(res, pkg)" in crumb and "super()" not in crumb
    # One line back to the dataset, never its whole description again.
    assert "Dataset description" not in page and "h.jc_t('part_of')" in page


def test_a_file_without_a_view_says_what_it_is_and_offers_its_one_action():
    page = (THEME / "templates__package__resource_read.html").read_text()
    block = page[page.index("{% block resource_view_content %}"):]
    assert "_(\"There are no views" not in block
    # A file says what it is and offers Download; an API offers no download (T-4333).
    files = block[block.index("{% else %}", block.index("{% elif api %}")):]
    assert "h.jc_t('file_lead')" in files and "h.jc_t('download')" in files
    # Whoever may create views still gets CKAN's own page.
    assert "{{ super() }}" in block and "resource_view_create" in block


def test_a_search_filter_with_nothing_to_choose_is_left_out_and_labels_are_whole():
    facets = (THEME / "templates__snippets__facet_list.html").read_text()
    assert "_('There are no" not in facets
    assert "{% if items %}" in facets and "|truncate" not in facets
    css = (THEME / "public__jc-theme.css").read_text()
    assert ".nav-facet .nav-item > a .item-label { overflow-wrap: anywhere; }" in css
    assert "text-overflow: ellipsis; white-space: nowrap; }\n" not in css.split(".nav-facet .nav-item > a .item-label", 1)[1][:80]
    # Owner, 2026-10-12: an empty footer drew a bordered strip under a short list (Licence), so the
    # footer is printed only inside the condition that gives it a link.
    guard = facets.index("{% if not limited or h.has_more_facets(name, search_facets) %}")
    assert guard < facets.index('<p class="module-footer">') < facets.index("{% endif %}\n      </section>")


def test_the_table_view_stacks_its_controls_below_desktop_width():
    """The view's own rules name `#dtprv_wrapper`; a rule on the class alone loses to them, which is
    how the first try left "Search:" under the toolbar."""
    css = (THEME / "public__jc-theme.css").read_text()
    block = css[css.index("@media (max-width: 991.98px) {\n  body.dt-view"):]
    block = block[:block.index("\n}\n") + 3]
    assert "body.dt-view #dtprv_wrapper { display: flex; flex-wrap: wrap;" in block
    assert "float: none; width: 100%; margin: 0;" in block
    for selector in (".dataTables_filter", ".dataTables_info", ".dataTables_paginate"):
        assert all("#dtprv_wrapper" in line for line in block.splitlines() if selector in line), selector



# --- T-3058, AG-114: the catalogue offers its knowledge assistant ----------------------------


@pytest.mark.parametrize("address, offered", [
    ("https://assistant.dev.example/d/helsinki-catalogue/widget", True),
    ("", False),
    ("https://assistant.evil.example/d/helsinki-catalogue/widget", False),
    ("https://assistant.dev.example.evil.example/d/helsinki-catalogue/widget", False),
    ("http://assistant.dev.example/d/helsinki-catalogue/widget", False),
    ("https://assistant.dev.example/d/Helsinki/widget", False),
    ("https://assistant.dev.example/d/x/widget?next=//evil.example", False),
    ('https://assistant.dev.example/d/x/widget"><script>', False),
])
def test_the_widget_is_offered_only_from_the_installation_s_assistant_host(theme, address, offered):
    theme.ASSISTANT_WIDGET = address
    assert theme.jc_assistant_widget() == (address if offered else None)
    # A publisher's own address is held to the same rule (T-4281).
    theme.ASSISTANT_WIDGET = ""
    theme.ASSISTANT_WIDGETS = {"bbsk": address}
    assert theme.jc_assistant_widget("bbsk") == (address if offered else None)
    theme.ASSISTANT_WIDGETS = {}


def test_a_dataset_page_opens_its_publishers_assistant_and_any_other_page_the_catalogue_s(theme):
    """T-4281: the publisher's widget by CKAN organization, the catalogue's for every page with no
    publisher or a publisher with none of its own; an unreadable map is no map."""
    theme.ASSISTANT_WIDGET = "https://assistant.dev.example/d/bbsk/widget"
    theme.ASSISTANT_WIDGETS = {"praha": "https://assistant.dev.example/d/praha/widget"}
    assert theme.jc_assistant_widget("praha") == "https://assistant.dev.example/d/praha/widget"
    for organization in (None, "", "zilina"):
        assert theme.jc_assistant_widget(organization) == "https://assistant.dev.example/d/bbsk/widget"
    for raw in ("not json", "[1, 2]", '{"praha": 3}'):
        os.environ["JC_ASSISTANT_WIDGET_URLS"] = raw
        try:
            assert theme._widgets() == {}
        finally:
            del os.environ["JC_ASSISTANT_WIDGET_URLS"]
    theme.ASSISTANT_WIDGETS = {}


def test_the_footer_offers_the_assistant_as_a_disclosure_a_keyboard_opens():
    footer = (THEME / "footer.html").read_text()
    assert "{% set widget = h.jc_assistant_widget(publisher) %}" in footer
    assert "{% set publisher = pkg_dict.organization.name if pkg_dict is defined" in footer
    assert '<details class="jc-assistant">' in footer and "<summary><span>{{ h.jc_t('assistant') }}</span></summary>" in footer
    assert 'title="{{ h.jc_t(\'assistant\') }}"' in footer and 'loading="lazy"' in footer
    assert 'referrerpolicy="no-referrer"' in footer
    # T-4280: the chat opens in Slovak or the visitor's own choice in it; the page's language
    # (T-4253) no longer reaches it.
    assert '<iframe src="{{ widget }}"' in footer
    assert "lang=" not in footer.split("<iframe", 1)[1].split(">", 1)[0]


def test_the_assistant_leaves_the_page_room_and_takes_a_phone_s_whole_screen():
    """T-4204: the button never covers the page's last line; open on a phone, the frame is the
    screen, the page behind neither shows nor takes focus, and Escape closes it."""
    css = (THEME / "public__jc-theme.css").read_text()
    assert "body:has(.jc-assistant) { padding-block-end: 5rem; }" in css
    phone = css.split("@media (max-width: 40rem) {", 1)[1].split("\n}\n", 1)[0]
    assert ".jc-assistant[open] { inset: 0;" in phone
    assert "body:has(.jc-assistant[open]) { overflow: hidden; }" in phone
    # The frame takes its size from the screen, below the 3.25rem bar (T-4248).
    assert "block-size: 3.25rem;" in phone
    assert "inset: 3.25rem 0 auto 0; width: 100%; height: calc(100vh - 3.25rem); height: calc(100dvh - 3.25rem);" in phone
    footer = (THEME / "footer.html").read_text()
    assert "<script src=\"{{ h.url_for_static('/jc-assistant.js') }}\" defer></script>" in footer
    script = (THEME / "public__jc-assistant.js").read_text()
    assert 'matchMedia("(max-width: 40rem)")' in script and "el.inert = true" in script
    assert 'event.key === "Escape"' in script and 'querySelector("summary").focus()' in script


def test_the_open_assistant_shows_one_close_control_and_a_frame_that_fits_the_window():
    """T-4283: open, the launcher turns into the panel's round close control (never the label
    beside the panel); the frame takes the height the chat reports, inside 40rem and the window;
    the button keeps clear of a phone's home bar."""
    css = (THEME / "public__jc-theme.css").read_text()
    desktop = css.split("@media (max-width: 40rem) {", 1)[0]
    assert "inset-block-end: max(1rem, env(safe-area-inset-bottom));" in desktop
    assert ".jc-assistant[open] > summary { inline-size: 2.75rem; block-size: 2.75rem; padding: 0; }" in desktop
    assert ".jc-assistant[open] > summary > span { position: absolute;" in desktop and "clip-path: inset(50%)" in desktop
    assert '.jc-assistant[open] > summary::after { content: "\\2715";' in desktop
    assert "height: min(var(--jc-h, 40rem), 40rem, calc(100dvh - 6.25rem));" in desktop
    phone = css.split("@media (max-width: 40rem) {", 1)[1].split("\n}\n", 1)[0]
    assert ".jc-assistant[open] > summary > span { position: static;" in phone, "a phone's bar keeps its words"
    script = (THEME / "public__jc-assistant.js").read_text()
    # The height is heard from the frame's own window and origin alone, and only as a number.
    assert "event.source !== frame.contentWindow || event.origin !== origin" in script
    assert 'data.type !== "jc-assistant-height"' in script and "isFinite(height) && height > 0" in script
    assert 'frame.style.setProperty("--jc-h"' in script


def test_the_catalogue_pod_is_told_its_assistant_only_when_the_assistant_is_deployed(rendered, rendered_variant):
    def widget(docs):
        (ckan,) = [d for d in docs if d.get("kind") == "Deployment" and d["metadata"]["name"].endswith("ckan")
                   and any(c["name"] == "ckan" for c in d["spec"]["template"]["spec"]["containers"])]
        (container,) = [c for c in ckan["spec"]["template"]["spec"]["containers"] if c["name"] == "ckan"]
        env = {e["name"]: e.get("value") for e in container["env"]}
        return env["JC_ASSISTANT_WIDGET_URL"], json.loads(env["JC_ASSISTANT_WIDGET_URLS"])

    # dev lists the assistant since T-3181, so its catalogue carries the widget: the one general
    # assistant on every page, the home page, every organization's dataset and resource pages
    # included, and no city's (T-4342); without the component it is told nothing.
    default, by_organization = widget(rendered("dev"))
    assert default == "https://assistant.dev.joinedcontext.com/d/data/widget"
    assert by_organization == {}

    def without_assistant(tree):
        path = tree / "deployment/environments/dev/global.yaml.gotmpl"
        text = path.read_text()
        assert "\n  - assistant\n" in text
        path.write_text(text.replace("\n  - assistant\n", "\n", 1))

    assert widget(rendered_variant("dev", without_assistant)) == ("", {})


# The usage texts `jcctl publish ckan` writes on the API resources (T-3886), for a restricted
# Endpoint on dev.example: a paragraph, an indented command, a paragraph.
WS_USAGE = (
    "Live updates: open one WebSocket, subscribe to the entities you want.\n\n"
    "    websocat -H \"Authorization: Bearer $TOKEN\" 'wss://dev.example/api/endpoint/hkiair/ws'\n"
    "    {\"metadata\":{\"x-op\":\"x-subscribe\",\"x-id\":\"s1\"},\"body\":{\"type\":\"Subscription\"}}\n\n"
    "Always live: the catalogue holds this link, never a copy. Answers what the endpoint's policy lets "
    "the caller read: send a bearer token for the endpoint; without one it answers 401."
)

EVERY_SURFACE = PUBLISHED_RESOURCES + [
    {"id": "r-ws", "name": "Live updates over WebSocket", "format": "WebSocket", "url": ENDPOINT + "ws",
     "description": WS_USAGE},
    {"id": "r-ogc", "name": "OGC API - Features", "format": "OGCFEAT", "url": ENDPOINT + "ogc/features/"},
    {"id": "r-odata", "name": "OData v4", "format": "OData", "url": ENDPOINT + "odata/v4/"},
    {"id": "r-xlsx", "name": "Excel spreadsheet", "format": "XLSX", "url": ENDPOINT + "file.xlsx"},
]


def test_every_live_surface_is_in_the_api_and_live_access_section(theme):
    """T-3887, EP-108: WebSocket, OGC API - Features and OData are APIs a program calls, beside
    NGSI-LD and MCP; the spreadsheet is a download."""
    sections = {s["key"]: s for s in theme.jc_resource_sections({"resources": EVERY_SURFACE})}
    assert [i["resource"]["id"] for i in sections["api"]["items"]] == ["r-ngsi", "r-ws", "r-mcp", "r-ogc", "r-odata"]
    assert sections["api"]["title"] == "API and live access"
    assert "r-xlsx" in [i["resource"]["id"] for i in sections["data"]["items"]]
    words = {i["resource"]["id"]: i["what"] for i in sections["api"]["items"]}
    assert "WebSocket" in words["r-ws"] and "Power BI" in words["r-odata"]
    # A dataset without the WebSocket surface shows no WebSocket row.
    without = [r for r in EVERY_SURFACE if r["format"] != "WebSocket"]
    api = [s for s in theme.jc_resource_sections({"resources": without}) if s["key"] == "api"][0]
    assert all(i["format"] != "WebSocket" for i in api["items"])


def test_an_api_resource_shows_its_usage_with_its_commands_to_copy(theme):
    (ws,) = [r for r in EVERY_SURFACE if r["id"] == "r-ws"]
    blocks = theme.jc_usage(ws)
    assert [b["code"] for b in blocks] == [False, True, False]
    command = blocks[1]
    assert command["text"].startswith("websocat -H \"Authorization: Bearer $TOKEN\" 'wss://dev.example/")
    assert command["id"] == "jc-use-r-ws-1"
    # A file has no usage blocks; its description is CKAN's one-line extract.
    assert theme.jc_usage({"id": "r-csv", "format": "CSV", "url": ENDPOINT + "file.csv", "description": WS_USAGE}) == []
    assert theme.jc_usage({"format": "MCP"}) == []


@pytest.mark.parametrize("leak", [
    "    curl -H \"Authorization: Bearer eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJ4In0.c2ln\" 'https://dev.example/x'",
    "    curl -H \"Authorization: Bearer 0123456789abcdef0123\" 'https://dev.example/x'",
    "    websocat 'wss://context-gateway.jc.svc.cluster.local:8080/api/endpoint/hkiair/ws'",
    "Open https://dev.example.evil/x to start.",
])
def test_a_usage_block_with_a_token_or_an_internal_address_never_reaches_the_page(theme, leak):
    """EP-110: the page shows `$TOKEN` and the platform's own addresses, nothing else."""
    resource = {"id": "r", "format": "NGSI-LD", "url": ENDPOINT, "description": "Query it.\n\n" + leak}
    assert [b["text"] for b in theme.jc_usage(resource)] == ["Query it."]


def test_the_websocket_guide_is_linked_only_from_the_installation_s_documentation(theme, monkeypatch):
    ws = {"format": "WebSocket"}
    assert theme.jc_guide(ws) is None
    monkeypatch.setitem(theme.BRANDING, "documentationBaseUrl", "https://docs.dev.example/")
    assert theme.jc_guide(ws) == "https://docs.dev.example/API/07-websocket"
    assert theme.jc_guide({"format": "NGSI-LD"}) is None
    # A usage text may link the guide's host.
    linked = {"id": "r", "format": "WebSocket", "description": "Guide: https://docs.dev.example/API/07-websocket"}
    assert len(theme.jc_usage(linked)) == 1
    for unsafe in ("javascript:alert(1)", "http://docs.dev.example", "https://docs.dev.example/\"onload=x"):
        monkeypatch.setitem(theme.BRANDING, "documentationBaseUrl", unsafe)
        assert theme.jc_guide(ws) is None, unsafe


def test_an_api_resource_page_shows_its_usage_where_ckan_said_no_view():
    page = (THEME / "templates__package__resource_read.html").read_text()
    assert "(not api and h.check_access('resource_view_create'" in page
    assert "package/snippets/jc_usage.html" in page and "/jc-copy.js" in page
    item = (THEME / "templates__package__snippets__resource_item.html").read_text()
    assert "h.jc_usage(res) if jc_section == 'api' and not url_is_edit" in item
    snippet = (THEME / "templates__package__snippets__jc_usage.html").read_text()
    assert 'data-jc-copy="{{ block.id }}"' in snippet and '<pre id="{{ block.id }}"' in snippet
    assert "|safe" not in snippet
    # The copy button reads a block's text as well as a field's value.
    assert "field.value !== undefined ? field.value : field.textContent" in (THEME / "public__jc-copy.js").read_text()


@pytest.mark.parametrize("lang, counts", [
    ("en", {1: "1 row", 2: "2 rows", 5: "5 rows", 0: "0 rows", 1234: "1 234 rows"}),
    ("sk", {1: "1 riadok", 3: "3 riadky", 5: "5 riadkov"}),
    ("cs_CZ", {1: "1 řádek", 4: "4 řádky", 12: "12 řádků"}),
    ("de", {1: "1 Zeile", 2: "2 Zeilen"}),
    ("fi", {1: "1 row", 7: "7 rows"}),
])
def test_a_row_count_takes_its_language_s_plural(theme, lang, counts):
    """T-4066: the owner's photo read "GtfsAgency 1 rows"."""
    theme.page.lang = lang
    for count, words in counts.items():
        assert theme.jc_rows(count) == words
    assert theme.jc_rows(None) == ""
    read = (THEME / "templates__package__read.html").read_text()
    assert "h.jc_t('rows')" not in read and read.count("h.jc_rows(") == 2


def test_usage_reads_as_markdown_and_its_commands_wrap(theme):
    """T-4066: `query_entities` showed its backticks, and a long command was a one-line box
    clipped mid-word behind a horizontal scrollbar."""
    snippet = (THEME / "templates__package__snippets__jc_usage.html").read_text()
    # CKAN's render_markdown runs the sanitiser; the text never reaches the page as raw HTML.
    assert "h.render_markdown(block.text)" in snippet and "<p>{{ block.text }}</p>" not in snippet
    assert "|safe" not in snippet
    css = (THEME / "public__jc-theme.css").read_text()
    # Owner, 2026-10-12: a textarea sized to its text only in Chromium; a block wraps everywhere.
    box = re.search(r"^\.jc-copy-code pre \{([^}]*)\}", css, re.M).group(1)
    assert "white-space: pre-wrap" in box and "overflow-wrap: anywhere" in box and "white-space: pre;" not in box
    assert "<textarea" not in snippet
    config = '    {"mcpServers":{"helsinki-transport":{"type":"http","url":"https://dev.example/api/endpoint/ajaezssvx3bwqgejgepmq4ig3frgan4e/mcp"}}}'
    resource = {"id": "r", "format": "MCP", "url": ENDPOINT + "mcp", "description": "Tools: `get_entity`.\n\n" + config}
    text, code = theme.jc_usage(resource)
    assert text["text"] == "Tools: `get_entity`." and not text["code"]
    assert code["code"] and code["text"] == config[4:]


def test_the_format_badge_sits_beside_the_resource_name():
    """T-4066: the badge stood alone in a wide left column beside a long usage text."""
    item = (THEME / "templates__package__snippets__resource_item.html").read_text()
    head = item[item.index('<div class="jc-resource-head">'):item.index("</div>", item.index('<div class="jc-resource-head">'))]
    assert "jc-chip" in head and 'class="heading"' in head
    css = (THEME / "public__jc-theme.css").read_text()
    assert "grid-template-columns: 6.5rem" not in css


def test_a_publisher_without_a_picture_gets_its_badge_and_words_in_the_page_language(theme, tmp_path):
    import base64
    block = tmp_path / "organizations.json"
    block.write_text(json.dumps({
        "hel-fi": {"initials": "HEL", "colour": "#0000bf", "description": {"en": "Helsinki data", "sk": "Údaje Helsínk"}},
        "bad": {"initials": "<b>", "colour": "red"},
        "evil": {"initials": "<script>", "colour": "#ffffff"},
    }))
    theme.ORGANIZATIONS_FILE = str(block)
    theme.ORGANIZATIONS = theme._organizations()
    card = theme.jc_org({"name": "hel-fi", "description": "", "image_display_url": ""})
    assert card["description"] == "Helsinki data"
    svg = base64.b64decode(card["image"].removeprefix("data:image/svg+xml;base64,")).decode()
    assert ">HEL</text>" in svg and 'fill="#0000bf"' in svg and 'fill="#ffffff"' in svg
    theme.page.lang = "sk"
    assert theme.jc_org({"name": "hel-fi"})["description"] == "Údaje Helsínk"
    # CKAN's own picture and words win; an unknown publisher keeps CKAN's placeholder.
    assert theme.jc_org({"name": "hel-fi", "description": "own", "image_display_url": "/x.png"}) == \
        {"image": "/x.png", "description": "own"}
    assert theme.jc_org({"name": "nobody"}) == {"image": None, "description": None}
    assert theme.jc_org(None) == {"image": None, "description": None}
    # A colour that is not #rgb/#rrggbb draws nothing; initials are text, never markup.
    assert theme.jc_org({"name": "bad"})["image"] is None
    evil = base64.b64decode(theme.jc_org({"name": "evil"})["image"].split(",", 1)[1]).decode()
    assert "<script>" not in evil and "&lt;scr" in evil and 'fill="#000000"' in evil


def test_a_missing_or_broken_organizations_file_leaves_ckan_s_placeholder(theme, tmp_path):
    theme.ORGANIZATIONS_FILE = str(tmp_path / "absent.json")
    assert theme._organizations() == {}
    broken = tmp_path / "broken.json"
    broken.write_text("[1, 2")
    theme.ORGANIZATIONS_FILE = str(broken)
    assert theme._organizations() == {}
    broken.write_text("[1, 2]")
    assert theme._organizations() == {}


def test_every_demo_publisher_has_a_badge_and_the_file_reaches_the_pod(rendered):
    docs = rendered("dev")
    (config,) = [d for d in docs if d.get("kind") == "ConfigMap" and d["metadata"]["name"].endswith("ckan-theme")]
    organizations = json.loads(config["data"]["organizations.json"])
    assert {"hel-fi", "praha", "zilina", "banskabystrica", "bbsk"} <= set(organizations)
    for name, entry in organizations.items():
        assert re.fullmatch(r"#[0-9a-fA-F]{6}", entry["colour"]) and entry["initials"], name
    for name in ("hel-fi", "praha", "zilina"):
        assert organizations[name]["description"]["en"] and organizations[name]["description"]["sk"], name
    (ckan,) = [d for d in docs if d.get("kind") == "Deployment" and d["metadata"]["name"].endswith("ckan")
               and any(c["name"] == "ckan" for c in d["spec"]["template"]["spec"]["containers"])]
    (branding,) = [v for v in ckan["spec"]["template"]["spec"]["volumes"] if v["name"] == "branding"]
    assert {"key": "organizations.json", "path": "organizations.json"} in branding["configMap"]["items"]


def test_a_dataset_page_puts_its_publisher_above_and_gives_the_data_the_whole_width():
    """Owner, 2026-10-12: the publisher sidebar took a quarter of the page from the tables."""
    base = (THEME / "templates__package__read_base.html").read_text()
    assert "{% block secondary %}{% endblock %}" in base
    assert '<div class="primary col-12" role="main">' in base and "self.primary_content()" in base
    assert "package/snippets/jc_publisher.html" in base.split("{% block pre_primary %}", 1)[1]
    bar = (THEME / "templates__package__snippets__jc_publisher.html").read_text()
    assert "h.jc_org(organization)" in bar and "placeholder-organization.png" in bar
    assert ".jc-publisher {" in (THEME / "public__jc-theme.css").read_text()


# T-4217 (photo audit T-4161): "Topics" in the main navigation opened "There are currently no
# groups for this site." and every dataset carried an empty Groups tab. Both are offered only
# once a topic exists.
def test_topics_are_offered_only_when_one_exists(theme):
    theme.page.actions["group_list"] = lambda data: []
    assert theme.jc_has_topics() is False
    theme.page.actions["group_list"] = lambda data: ["environment"]
    assert theme.jc_has_topics() is True


def test_a_topic_list_the_visitor_may_not_read_offers_no_topics(theme):
    theme.page.actions["group_list"] = theme.toolkit.NotAuthorized()
    assert theme.jc_has_topics() is False


def test_the_navigation_and_the_dataset_tabs_ask_before_offering_topics():
    header = (THEME / "header.html").read_text()
    assert "h.jc_has_topics()" in header
    tabs = (THEME / "templates__package__read_base.html").read_text()
    assert "block content_primary_nav" in tabs and "h.jc_has_topics()" in tabs


# T-4218 (photo audit T-4161): Solr split a hyphenated word into parts it OR'ed, so "bike-sharing"
# found every dataset about bikes or about sharing, and a word nobody wrote found them all
# (measured on dev: 6 against 1 as a phrase, 132 of 132 against 0). Each such word is searched
# as the phrase it is; a query with its own quotes or fields is the visitor's syntax and stays.
@pytest.mark.parametrize("asked, searched", [
    ("bike-sharing", '"bike-sharing"'),
    ("kvalita-ovzdušia Žilina", '"kvalita-ovzdušia" (Žilina OR Žilin*)'),
    ("qzxwv-nothing-is-called-this", '"qzxwv-nothing-is-called-this"'),
    ("air quality", "air (quality OR qualit*)"),
    ("-draft", "-draft"),
    ('"bike-sharing" x-y', '"bike-sharing" x-y'),
    ("tags:air-quality", "tags:air-quality"),
    ("", ""),
])
def test_a_hyphenated_word_is_searched_as_written(theme, asked, searched):
    assert theme.jc_search_words(asked) == searched


def test_the_dataset_search_takes_the_hyphenated_word_as_a_phrase(theme):
    plugin = theme.JcThemePlugin()
    assert plugin.before_dataset_search({"q": "bike-sharing", "rows": 20}) == {"q": '"bike-sharing"', "rows": 20}
    assert plugin.before_dataset_search({"fq": "x"}) == {"fq": "x"}


# T-4239 (photo audit T-4161 #3): Solr stems with the English Porter stemmer, so "ovzdušie" (air)
# found only Praha's "ovzduší" and missed the three Slovak "ovzdušia" datasets. A word with a
# Slovak or Czech letter is searched as itself or its stem with any ending, through edismax (the
# only parser of CKAN's two that takes a prefix); measured on the ckan-solr 2.11 image: dismax
# "ovzdušie" finds praha-air only, edismax "(ovzdušie OR ovzduš*)" finds praha-air and bb-air.
@pytest.mark.parametrize("asked, searched", [
    ("ovzdušie", "(ovzdušie OR ovzduš*)"),
    ("kvalita ovzdušia", "(kvalita OR kvalit*) (ovzdušia OR ovzduš*)"),
    ("Kvalita ovzduší", "(Kvalita OR Kvalit*) (ovzduší OR ovzduš*)"),
    ("školy", "(školy OR škol*)"),
    ("ľad", "ľad"),
    ("ovzduš", "(ovzduš OR ovzduš*)"),
    ('"ovzdušie"', '"ovzdušie"'),
])
def test_a_slovak_or_czech_word_finds_its_other_endings(theme, asked, searched):
    assert theme.jc_search_words(asked) == searched


# T-4387: a visitor types Slovak without its letters and in the singular; Solr folds the letters
# on both sides (CKAN's `text` field ends in ASCIIFoldingFilter), so the folded word and its stem
# reach the same Datasets. Each pair below asks for one stem: dev counted ovzdušie 4, ovzdusie 3,
# mosty 1, most 0, cesty 1, cesta 0 before.
@pytest.mark.parametrize("one, other, stem", [
    ("ovzdušie", "ovzdusie", None),
    ("most", "mosty", "most*"),
    ("cesta", "cesty", "cest*"),
    ("ovzdušie", "ovzdušia", "ovzduš*"),
])
def test_the_folded_word_and_the_singular_ask_for_the_plurals_stem(theme, one, other, stem):
    def asked(word):
        searched = theme.jc_search_words(word)
        assert searched.startswith("(%s OR " % word), searched
        return searched.split(" OR ")[1].rstrip(")")
    if stem is None:
        assert asked(one).replace("š", "s") == asked(other)
    else:
        assert asked(one) == asked(other) == stem


@pytest.mark.parametrize("word", ["air", "bus", "ľad", "x2", "2024", "-draft", "co2"])
def test_a_short_or_not_alphabetic_word_is_searched_as_written(theme, word):
    assert theme.jc_search_words(word) == word


def test_a_stemmed_search_asks_for_the_parser_that_takes_a_prefix(theme):
    plugin = theme.JcThemePlugin()
    assert plugin.before_dataset_search({"q": "ovzdušie"}) == {"q": "(ovzdušie OR ovzduš*)", "defType": "edismax"}
    assert plugin.before_dataset_search({"q": "air"}) == {"q": "air"}
    assert plugin.before_dataset_search({"q": "ovzdušie", "defType": "lucene"})["defType"] == "lucene"


# T-4220 (photo audit T-4161): one concept, three names. The navigation said Publishers, the
# breadcrumb, title and search box Organizations, and each card counted its CKAN members.
@pytest.mark.parametrize("entity, purpose, en, sk", [
    ("organization", "breadcrumb", "Publishers", "Vydavatelia"),
    ("organization", "page title", "Publishers", "Vydavatelia"),
    ("organization", "main nav", "Publishers", "Vydavatelia"),
    ("organization", "search placeholder", "Search publishers…", "Hľadať vydavateľov…"),
    ("group", "breadcrumb", "Topics", "Témy"),
    ("group", "search placeholder", "Search topics…", "Hľadať témy…"),
])
def test_publishers_and_topics_have_one_name(theme, entity, purpose, en, sk):
    stock = lambda *args: None
    assert theme.humanize_entity_type(stock, entity, entity, purpose) == en
    theme.page.lang = "sk"
    assert theme.humanize_entity_type(stock, entity, entity, purpose) == sk


def test_other_words_stay_ckans(theme):
    stock = lambda entity, object_type, purpose: "stock %s" % purpose
    assert theme.humanize_entity_type(stock, "organization", "organization", "save label") == "stock save label"
    assert theme.humanize_entity_type(stock, "package", "dataset", "breadcrumb") == "stock breadcrumb"


def test_a_public_publisher_card_counts_no_members():
    card = (THEME / "templates__organization__snippets__organization_item.html").read_text()
    assert "{% block members %}{% endblock %}" in card


def test_symbol_font_bullets_become_real_ones_on_the_page_and_the_api(theme):
    """T-4283: " Druh " drew as "□ Druh □" on data.dev's dataset list."""
    plugin = theme.JcThemePlugin()
    pkg = {
        "title": "Dotácie",
        "notes": "atribúty:  Rok  Typ Druh",
        "resources": [{"name": " XML", "description": None}, {"url": "x"}],
    }
    plugin.after_dataset_show({}, pkg)
    assert pkg["notes"] == "atribúty: • Rok ▪ Typ Druh"
    assert pkg["resources"][0] == {"name": "✓ XML", "description": None}
    found = plugin.after_dataset_search({"results": [{"notes": " a"}], "count": 1}, {})
    assert found == {"results": [{"notes": "• a"}], "count": 1}
    assert plugin.after_dataset_search({"count": 0}, {}) == {"count": 0}


def test_no_private_use_glyph_survives_any_text(theme):
    text = "".join(chr(c) for c in range(0xE000, 0xF900, 7))
    assert not re.search("[-�]", theme.jc_plain_glyphs(text) or "")
    assert theme.jc_plain_glyphs("Žilina ľ ô") == "Žilina ľ ô"


@pytest.mark.parametrize("lang", ["en", "sk"])
def test_the_connector_privacy_terms_and_support_pages_read_in_slovak_and_english(theme, tmp_path, lang):
    """T-4315: the pages a directory reviewer reads, from the branding block alone, no secret."""
    branding = tmp_path / "branding.json"
    branding.write_text(json.dumps({"domain": "dev.example", "contactEmail": "hello@dev.example"}))
    theme.BRANDING = theme._load()
    theme.page.lang = lang
    for name in ("connector", "privacy", "terms", "support"):
        page = theme.jc_page(name)
        assert page["title"] == theme.PAGES[name][lang]["title"] and page["sections"], name
        assert page["email"] == "hello@dev.example" and page["pages"] == ["connector", "privacy", "terms", "support"]
        text = " ".join(p for s in page["sections"] for p in s["paragraphs"])
        assert "{" not in text and not re.search(r"(?i)bearer|token|api[_-]?key|password", text), name
    assert "https://dev.example/api/mcp" in " ".join(theme.jc_page("connector")["sections"][0]["paragraphs"])
    assert theme.jc_page("privacy")["title"] != theme.PAGES["privacy"]["sk" if lang == "en" else "en"]["title"]
    assert theme.jc_page("imprint") is None


def test_a_page_in_another_language_reads_english_and_no_domain_drops_the_address(theme, tmp_path):
    theme.page.lang = "de"
    assert theme.jc_page("terms")["title"] == "Terms of use"
    branding = tmp_path / "branding.json"
    branding.write_text(json.dumps({"instanceName": "x", "contactEmail": "not-an-address"}))
    theme.BRANDING = theme._load()
    page = theme.jc_page("privacy")
    text = " ".join(p for s in page["sections"] for p in s["paragraphs"])
    assert page["mcp"] is None and page["email"] == "" and "{url}" not in text and "None" not in text
    assert [s["heading"] for s in theme.jc_page("terms")["sections"]] == ["Licences", "Read only", "Fair use"]


def test_the_four_pages_are_routes_of_one_template_and_every_page_links_them(theme, monkeypatch):
    rules = {}

    class Blueprint:
        def __init__(self, name, module):
            self.name = name

        def add_url_rule(self, path, endpoint, view):
            rules[path] = (endpoint, view)

    monkeypatch.setitem(sys.modules, "flask", types.SimpleNamespace(Blueprint=Blueprint))
    theme.toolkit.render = lambda template, extra: (template, extra)
    blueprint = theme.JcThemePlugin().get_blueprint()
    assert blueprint.name == "jc_pages" and sorted(rules) == ["/connector", "/privacy", "/support", "/terms"]
    endpoint, view = rules["/privacy"]
    assert endpoint == "privacy" and view() == ("jc/page.html", {"jc_name": "privacy"})
    template = (THEME / "templates__jc__page.html").read_text()
    assert "h.jc_page(jc_name)" in template and 'snippet "snippets/jc_mcp_install.html"' in template
    footer = (THEME / "footer.html").read_text()
    assert "('connector', 'privacy', 'terms', 'support')" in footer and "h.url_for('jc_pages.' ~ name)" in footer

# T-4333: a resource page reads what an Endpoint's address is from its path, says it in the page's
# language, shows an API's live rows and how to use it, and offers a file its one Download.
OD = "https://dev.example/api/endpoint/4ysiqy53qik5qyvawwaj7wgylpt4uoxa/"
OD_QUERY = "?type=StatisticalObservation&q=isPartOf%3D%3D%22https%3A%2F%2Fdata.dev.example%2Fdataset%2Fbb%22"
OD_PKG = {"name": "bb", "title": "Prírastky a úbytky občanov", "resources": [
    {"id": "n", "name": "NGSI-LD API (StatisticalObservation)", "format": "JSON-LD", "resource_type": "api",
     "url": OD + "ngsi-ld/v1/entities" + OD_QUERY, "conforms_to": "https://www.etsi.org/deliver/etsi_gs/CIM/001_099/009/",
     "description": "These rows, through the platform's NGSI-LD API (NGSI-LD data, read-only)."},
    {"id": "c", "name": "CSV (StatisticalObservation)", "format": "CSV", "resource_type": "api", "url": OD + "file.csv" + OD_QUERY},
    {"id": "m", "name": "Model Context Protocol (StatisticalObservation)", "format": "JSON", "resource_type": "api", "url": OD + "mcp"},
    {"id": "w", "name": "WebSocket (StatisticalObservation)", "format": "JSON", "resource_type": "api",
     "url": "wss://dev.example/api/endpoint/4ysiqy53qik5qyvawwaj7wgylpt4uoxa/ws"},
    {"id": "o", "name": "OData v4 (StatisticalObservation)", "format": "JSON", "resource_type": "api",
     "url": OD + "odata/v4/StatisticalObservation"},
    {"id": "t", "name": "Prírastky a úbytky občanov (tabuľka)", "format": "CSV", "datastore_active": True,
     "url": "https://data.dev.example/datastore/dump/t"},
    {"id": "p", "name": "Prírastky a úbytky občanov", "format": "JSON",
     "url": "https://egov.banskabystrica.sk/Default.aspx?NavigationState=890"},
]}


def _od(theme, rid):
    return next(r for r in OD_PKG["resources"] if r["id"] == rid)


def test_an_endpoint_address_is_read_by_its_path_not_its_format_label(theme):
    kinds = {r["id"]: theme.jc_kind(r) for r in OD_PKG["resources"]}
    assert kinds == {"n": "NGSI-LD", "c": "CSV", "m": "MCP", "w": "WEBSOCKET", "o": "ODATA", "t": None, "p": None}
    assert theme.jc_is_api(_od(theme, "n")) and theme.jc_is_api(_od(theme, "m"))
    # A file the Endpoint renders is a file, whatever resource_type the harvest wrote.
    assert not theme.jc_is_api(_od(theme, "c"))
    assert theme.jc_format(_od(theme, "n")) == "NGSI-LD" and theme.jc_format(_od(theme, "w")) == "WebSocket"
    assert theme.jc_kind({"url": "https://dev.example/api/endpoint/x/schema/v1/model.schema.json"}) == "MODEL"
    assert theme.jc_kind({"url": "javascript:alert(1)"}) is None and theme.jc_kind(None) is None


def test_the_resource_list_groups_and_names_the_type_once(theme):
    sections = {s["key"]: s for s in theme.jc_resource_sections(OD_PKG)}
    assert [i["resource"]["id"] for i in sections["api"]["items"]] == ["n", "w", "m", "o"]
    assert {i["resource"]["id"] for i in sections["data"]["items"]} == {"c", "t"}
    # The harvest's link to the publisher's page is opened at the publisher, not a twin download.
    assert [i["resource"]["id"] for i in sections["source"]["items"]] == ["p"]
    labels = {r["id"]: theme.jc_resource_label(r, OD_PKG) for r in OD_PKG["resources"]}
    assert not any("(StatisticalObservation)" in label for label in labels.values()), labels
    assert labels["n"] == "NGSI-LD API" and labels["m"] == "Model Context Protocol"
    # The publisher's own page, named after the dataset, no longer reads as a twin of the table.
    assert labels["p"] == "On the publisher's site" and labels["t"] == "The publisher's original table"
    # A file or a socket is named by what is in it; its chip already names the format.
    assert labels["c"] == "All records as a table" and labels["w"] == "Live changes"
    # Each of the platform's files says what it is for, so none reads as a twin of another.
    files = [dict(_od(theme, "c"), url=OD + "file.%s" % f, format=f) for f in ("csv", "geojson", "json", "xlsx")]
    named = [theme.jc_resource_label(r, OD_PKG) for r in files]
    assert [theme.jc_kind(r) for r in files] == ["CSV", "GEOJSON", "JSON", "XLSX"]
    assert len(set(named)) == len(named)
    assert theme.jc_entity_type(_od(theme, "m")) == theme.jc_entity_type(_od(theme, "o")) == "StatisticalObservation"
    theme.page.lang = "sk"
    model = {"name": "Data model: LinkML", "format": "LinkML", "url": OD + "schema/v1/model.linkml.yaml"}
    assert theme.jc_resource_label(model, OD_PKG) == "LinkML"  # the group already says "Dátový model"
    sidebar = (THEME / "templates__package__snippets__resources.html").read_text()
    assert "h.jc_resource_sections(pkg)" in sidebar and "section.title" in sidebar


def test_the_slovak_page_carries_no_english_description(theme):
    theme.page.lang = "sk"
    what = theme.jc_what(_od(theme, "n"))
    assert what == "Živé entity cez API. Iba záznamy tohto datasetu."
    assert "Všetky záznamy typu StatisticalObservation" in theme.jc_what(_od(theme, "o"))
    # OGC API Features and OData keep the dataset's rows in their own syntax (T-4289).
    mine = "https%3A%2F%2Fdata.dev.example%2Fdataset%2Fbb"
    for url in (OD + "odata/v4/StatisticalObservation?%24filter=isPartOf%20eq%20%27" + mine + "%27",
                OD + "ogc/features/collections/StatisticalObservation/items?isPartOf=" + mine):
        assert theme.jc_what(dict(_od(theme, "o"), url=url)).endswith(". Iba záznamy tohto datasetu."), url
    page = (THEME / "templates__package__resource_read.html").read_text()
    # The harvest's description reaches the page only for a resource that is not an Endpoint's.
    assert "{% if res.description and not kind and not api %}" in page
    row = (THEME / "templates__package__snippets__resource_item.html").read_text()
    assert "{% elif res.description and not kind %}" in row
    for key, words in theme.STRINGS.items():
        assert words.get("sk"), key


def test_an_address_reads_short_and_copies_whole(theme):
    address = theme.jc_address(_od(theme, "n"))
    assert address["short"] == "dev.example/api/endpoint/4ysiqy\u2026/ngsi-ld/v1/entities"
    assert address["full"] == _od(theme, "n")["url"]
    assert theme.jc_address({"url": "https://elsewhere.example/x?y=1"})["short"] == "https://elsewhere.example/x?y=1"
    # It breaks only after a slash: each segment is kept whole, "ngsi-ld" included (T-4333).
    assert address["segments"] == ["dev.example", "api", "endpoint", "4ysiqy\u2026", "ngsi-ld", "v1", "entities"]
    css = (THEME / "public__jc-theme.css").read_text()
    assert ".jc-address-short > span { white-space: nowrap; }" in css
    page = (THEME / "templates__package__resource_read.html").read_text()
    assert 'data-jc-copy="jc-address-full"' in page and '<pre id="jc-address-full"' in page


def test_an_api_offers_no_download_and_ckan_s_top_button_is_gone():
    page = (THEME / "templates__package__resource_read.html").read_text()
    actions = page[page.index("{% block resource_actions %}"):page.index("{% endblock %}", page.index("{% block resource_actions %}"))]
    assert "res.url" not in actions and "_resource.edit" in actions
    block = page[page.index("{% block resource_view_content %}"):]
    api = block[block.index("{% elif api %}"):block.index("{% else %}", block.index("{% elif api %}"))]
    assert "jc_t('download')" not in api and "h.jc_examples(res)" in api and "data-jc-preview" in api


def test_the_live_preview_reads_five_rows_anonymously_from_the_platform_only(theme):
    preview = theme.jc_preview(_od(theme, "n"))
    assert preview["kind"] == "NGSI-LD" and "limit=5" in preview["url"] and "options=keyValues" in preview["url"]
    assert "q=isPartOf%3D%3D" in preview["url"]
    assert "%24top=5" in theme.jc_preview(_od(theme, "o"))["url"] or "$top=5" in theme.jc_preview(_od(theme, "o"))["url"]
    assert theme.jc_preview(_od(theme, "m")) is None and theme.jc_preview(_od(theme, "c")) is None
    assert theme.jc_preview({"url": "https://evil.example/api/endpoint/x/ngsi-ld/v1/entities"}) is None
    assert theme.jc_preview({"url": "http://dev.example/api/endpoint/x/ngsi-ld/v1/entities"}) is None
    script = (THEME / "public__jc-preview.js").read_text()
    assert 'credentials: "omit"' in script and "innerHTML" not in script


def test_each_kind_shows_how_to_use_it_and_a_private_one_sends_the_token(theme):
    ngsi = theme.jc_examples(_od(theme, "n"))
    assert ngsi[0]["code"].startswith("curl -H 'Accept: application/ld+json' 'https://dev.example/") and "limit=5" in ngsi[0]["code"]
    mcp = theme.jc_examples(_od(theme, "m"))
    assert [e["title"] for e in mcp] == ["Claude (claude.ai and Claude Desktop)", "ChatGPT", "Claude Code"]
    assert all(OD + "mcp" in e["code"] for e in mcp)
    ws = theme.jc_examples(_od(theme, "w"))[0]["code"]
    assert ws.startswith("websocat --protocol ngsi-ld-ws 'wss://") and '"entities":[{"type":"StatisticalObservation"}]' in ws
    private = dict(_od(theme, "n"), description="Send `Authorization: Bearer $TOKEN`.")
    assert '-H "Authorization: Bearer $TOKEN"' in theme.jc_examples(private)[0]["code"]
    assert theme.jc_examples(_od(theme, "t")) == [] and theme.jc_examples({}) == []
    ids = [e["id"] for e in mcp]
    assert len(set(ids)) == len(ids)


def test_the_facts_name_the_standard_and_one_date_unless_another_day(theme):
    theme.toolkit.h.render_datetime = lambda value: str(value)[:10]
    assert theme.jc_standard(_od(theme, "n")) == {"url": _od(theme, "n")["conforms_to"], "name": "ETSI NGSI-LD (GS CIM 009)"}
    assert theme.jc_standard({"conforms_to": "not a url"}) is None
    same = {"created": "2026-10-16T10:20:46", "metadata_modified": "2026-10-16T10:20:47"}
    assert theme.jc_dates(same) == [("Updated", "2026-10-16")]
    other = {"created": "2026-10-01T10:00:00", "last_modified": "2026-10-16T10:00:00"}
    assert theme.jc_dates(other) == [("Updated", "2026-10-16"), ("Created", "2026-10-01")]
    assert theme.jc_dates({}) == []
    page = (THEME / "templates__package__resource_read.html").read_text()
    info = page[page.index("{% block resource_additional_information_inner %}"):]
    for english in ("Data last updated", "Metadata last updated", "format_resource_items"):
        assert english not in info


def test_a_hidden_package_leaves_search_and_its_page_for_all_but_a_sysadmin(theme, tmp_path):
    hidden = tmp_path / "hidden.json"
    hidden.write_text(json.dumps({"bb-adresy": "accurate: 16304 entities for 16902 rows", "Bad Name;": "x"}))
    theme.HIDDEN_FILE = str(hidden)
    theme.HIDDEN = theme._hidden()
    assert theme.HIDDEN == {"bb-adresy"}, "a name CKAN would not mint is never put into a Solr query"
    toolkit = sys.modules["ckan.plugins.toolkit"]
    plugin = theme.JcThemePlugin()

    toolkit.g = types.SimpleNamespace(userobj=None)
    params = plugin.before_dataset_search({"q": "", "fq": "+dataset_type:dataset"})
    assert params["fq"] == '+dataset_type:dataset -name:("bb-adresy")'
    with pytest.raises(toolkit.ObjectNotFound):
        plugin.after_dataset_show({}, {"name": "bb-adresy", "resources": []})
    plugin.after_dataset_show({}, {"name": "bb-dotacie", "resources": []})

    toolkit.g = types.SimpleNamespace(userobj=types.SimpleNamespace(sysadmin=True))
    assert "fq" not in plugin.before_dataset_search({"q": ""}), "the harvests still see what they wrote"
    plugin.after_dataset_show({}, {"name": "bb-adresy", "resources": []})


def test_without_a_hidden_list_nothing_is_filtered(theme, tmp_path):
    theme.HIDDEN_FILE = str(tmp_path / "missing.json")
    theme.HIDDEN = theme._hidden()
    assert theme.HIDDEN == frozenset()
    assert "fq" not in theme.JcThemePlugin().before_dataset_search({"q": ""})


def test_the_chart_mounts_the_hidden_list_beside_the_organizations():
    chart = PROJECT_ROOT / "charts/ckan/templates"
    assert "hidden.json: |\n    {{ .Values.hidden | default dict | toJson }}" in (chart / "theme.yaml").read_text()
    assert "- key: hidden.json\n                path: hidden.json" in (chart / "ckan.yaml").read_text()


def test_more_details_name_the_publisher_s_dates_and_record_in_words(theme):
    theme.page.lang = "sk"
    theme.toolkit.h.render_datetime = lambda value: "30. novembra 2023" if value.startswith("2023-11-30") else value
    assert theme.jc_extra("issued", "2023-11-30T07:59:41Z") == ("Zverejnené vydavateľom", "30. novembra 2023", None)
    assert theme.jc_extra("source_uri", "https://data.gov.sk/set/057d") == ("Pôvodný záznam", "https://data.gov.sk/set/057d", "https://data.gov.sk/set/057d")
    assert theme.jc_extra("source_note", "Measured by HSY") == ("Source note", "Measured by HSY", None)
    assert "harvest_source" not in dict(theme.jc_more({"extras": [{"key": "harvest_source", "value": "nkod-bb"}]}))


def test_a_file_follows_its_format_s_rfc_and_an_api_base_lists_its_types(theme):
    assert theme.jc_standard(_od(theme, "c"))["name"] == "CSV (RFC 4180)"
    assert theme.jc_standard({"url": "https://elsewhere.example/a.csv", "format": "CSV"}) is None
    base = {"url": OD + "ngsi-ld/v1/", "format": "NGSI-LD"}
    assert theme.jc_preview(base) == {"url": OD + "ngsi-ld/v1/types", "kind": "NGSI-LD-TYPES"}
    assert theme.jc_examples(base)[0]["code"].endswith("ngsi-ld/v1/types'")
    # OData and OGC API without an entity set or items have no rows to preview.
    assert theme.jc_preview({"url": OD + "odata/v4/"}) is None and theme.jc_preview({"url": OD + "ogc/features/"}) is None


def test_a_short_table_gets_a_short_frame_and_the_live_address_wraps():
    css = (THEME / "public__jc-theme.css").read_text()
    # `.jc-live pre` paints commands dark; the address box stays light, its text readable (T-4333).
    assert ".jc-live .jc-live-url { padding: .5rem .75rem; background: var(--jc-surface); color: var(--jc-ink);" in css
    page = (THEME / "templates__package__read.html").read_text()
    assert 'style="--jc-rows: {{ [preview.total or 20, 20]|min }}"' in page
    assert '<pre id="jc-live-url"' in page and 'readonly value="{{ live.url }}"' not in page
    css = (THEME / "public__jc-theme.css").read_text()
    assert "calc(15rem + var(--jc-rows, 20) * 2.6rem)" in css


def test_the_dataset_facts_name_the_standard_and_the_region(theme):
    rows = {label: (text, link) for label, text, link in theme.jc_about({"extras": [
        {"key": "conforms_to", "value": "https://www.w3.org/TR/json-ld11/"},
        {"key": "spatial_uri", "value": "http://data.europa.eu/nuts/code/SK031"}]})}
    assert rows["Follows the standard"] == ("JSON-LD 1.1", "https://www.w3.org/TR/json-ld11/")
    assert rows["Area covered"] == ("Žilina Region (NUTS SK031)", "http://data.europa.eu/nuts/code/SK031")
    assert theme.jc_about({"extras": [{"key": "spatial_uri", "value": "http://data.europa.eu/nuts/code/FI1B1"}]})[0][1] == "NUTS FI1B1"
    assert theme.jc_extra("quality_pass_rate", "1.0")[1] == "100 %"


def test_a_command_breaks_only_between_its_pieces(theme):
    # The owner's rule: a URL never breaks inside a word, a host, an id or "ngsi-ld" (T-4333).
    pieces = theme.jc_pieces("curl -H 'Accept: x' 'https://dev.example/api/endpoint/4ysiqy/ngsi-ld/v1/entities?type=A&limit=5'")
    assert "".join(p["text"] for p in pieces).startswith("curl -H 'Accept: x' 'https://")
    words = [p["text"] for p in pieces if not p["space"]]
    assert words[4] == "'https://" and "ngsi-ld/" in words and "4ysiqy/" in words and "entities?" in words and "type=A&" in words
    assert all(not p["text"].isspace() or p["space"] for p in pieces)
    assert theme.jc_pieces("") == [] and theme.jc_pieces(None) == []
    snippet = (THEME / "templates__snippets__jc_breakable.html").read_text()
    assert not snippet.endswith("\n")  # inside <pre> a trailing newline is a blank line
    for name in ("templates__package__read.html", "templates__package__resource_read.html",
                 "templates__package__snippets__jc_usage.html", "templates__snippets__jc_mcp_install.html"):
        page = (THEME / name).read_text()
        assert "snippets/jc_breakable.html" in page and not re.search(r"<pre[^>]*><code>\{\{", page), name
    css = (THEME / "public__jc-theme.css").read_text()
    assert "pre .jc-nb { white-space: pre; }" in css and "pre:has(.jc-nb) { overflow-x: auto; }" in css


def test_the_framed_table_has_no_developer_lines_and_room_below_desktop():
    css = (THEME / "public__jc-theme.css").read_text()
    assert "body.dt-view .resourceinfo, body.dt-view .sortinfo { display: none; }" in css
    assert "body.dt-view .dataTables_filter label::after { content: none; }" in css
    assert "clamp(27rem, calc(24rem + var(--jc-rows, 20) * 2.6rem), 34rem)" in css
