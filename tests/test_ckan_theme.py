"""T-2744 (DS-01, UI-82): the catalogue's dataset pages are written for people.

`ckanext_jc_theme/plugin.py` turns a dataset's CKAN fields and the extras `jcctl` publishes
(crates/jcctl/src/publish/ckan.rs) into labelled rows, the live API box and resources grouped
by format. The helpers are plain functions, so they are tested here against a stand-in for
the two CKAN modules they import; the templates that call them were walked on a CKAN 2.11.6
(the image's base) with axe clean on every page.
"""

import importlib.util
import json
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
    assert rows["Next update expected"] == "2026-09-25 09:00 UTC"
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
    assert rows["Area covered"] == "http://data.europa.eu/nuts/code/CZ010"


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
    assert mcp["claude"] == f"claude mcp add --transport http joinedcontext {hub}"
    assert json.loads(mcp["json"]) == {"mcpServers": {"joinedcontext": {"type": "http", "url": hub}}}
    assert mcp["vscode"].startswith("vscode:mcp/install?")
    assert json.loads(unquote(mcp["vscode"].split("?", 1)[1])) == {"name": "joinedcontext", "type": "http", "url": hub}
    cursor = urlsplit(mcp["cursor"])
    assert (cursor.scheme, cursor.netloc, cursor.path) == ("cursor", "anysphere.cursor-deeplink", "/mcp/install")
    query = parse_qs(cursor.query)
    assert query["name"] == ["joinedcontext"]
    assert json.loads(b64decode(query["config"][0])) == {"url": hub}
    # No dataset, no token: every line is the same for every page (EP-110).
    for line in mcp.values():
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
    assert panel.count("data-jc-copy=") == 3


def test_each_resource_has_its_one_action_named_for_a_screen_reader():
    item = (THEME / "templates__package__snippets__resource_item.html").read_text()
    assert "dropdown" not in item and "{{ _('Explore') }}" not in item
    assert "h.jc_t('open') if jc_section == 'api' else h.jc_t('download')" in item
    assert item.count('<span class="visually-hidden"> {{ name }}</span>') == 2
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
    ("en", "Validation rules (SHACL)", "Data model (OWL)"),
    ("sk", "Pravidlá kontroly (SHACL)", "Dátový model (OWL)"),
    ("fi", "Validation rules (SHACL)", "Data model (OWL)"),
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
    assert "h.jc_t('api_lead') if api else h.jc_t('file_lead')" in block
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


def test_the_footer_offers_the_assistant_as_a_disclosure_a_keyboard_opens():
    footer = (THEME / "footer.html").read_text()
    assert "{% set widget = h.jc_assistant_widget() %}" in footer
    assert '<details class="jc-assistant">' in footer and "<summary>{{ h.jc_t('assistant') }}</summary>" in footer
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


def test_the_catalogue_pod_is_told_its_assistant_only_when_the_assistant_is_deployed(rendered, rendered_variant):
    def widget(docs):
        (ckan,) = [d for d in docs if d.get("kind") == "Deployment" and d["metadata"]["name"].endswith("ckan")
                   and any(c["name"] == "ckan" for c in d["spec"]["template"]["spec"]["containers"])]
        (container,) = [c for c in ckan["spec"]["template"]["spec"]["containers"] if c["name"] == "ckan"]
        return {e["name"]: e.get("value") for e in container["env"]}["JC_ASSISTANT_WIDGET_URL"]

    # dev lists the assistant since T-3181, so its catalogue carries the widget; without the
    # component the catalogue is told nothing.
    assert widget(rendered("dev")) == "https://assistant.dev.joinedcontext.com/d/banskabystrica/widget"

    def without_assistant(tree):
        path = tree / "deployment/environments/dev/global.yaml.gotmpl"
        text = path.read_text()
        assert "\n  - assistant\n" in text
        path.write_text(text.replace("\n  - assistant\n", "\n", 1))

    assert widget(rendered_variant("dev", without_assistant)) == ""


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
    ("air quality", "air quality"),
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
    ("kvalita ovzdušia", "kvalita (ovzdušia OR ovzduš*)"),
    ("Kvalita ovzduší", "Kvalita (ovzduší OR ovzduš*)"),
    ("školy", "(školy OR škol*)"),
    ("ľad", "ľad"),
    ("ovzduš", "ovzduš"),
    ("air quality", "air quality"),
    ('"ovzdušie"', '"ovzdušie"'),
])
def test_a_slovak_or_czech_word_finds_its_other_endings(theme, asked, searched):
    assert theme.jc_search_words(asked) == searched


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
