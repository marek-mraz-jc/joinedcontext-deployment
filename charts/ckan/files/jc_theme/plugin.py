"""Renders any branding block (OPS-47).

The block is read once at start-up from the file the chart mounts. A missing or broken
file is not an error: CKAN then looks like a plain CKAN, which is what an installation
without branding should look like.
"""

import datetime
import json
import os

import ckan
import ckan.plugins as plugins
import ckan.plugins.toolkit as toolkit

BRANDING_FILE = os.environ.get("JC_BRANDING_FILE", "/etc/jc/branding/branding.json")

NEUTRAL = {
    "instanceName": "joinedcontext",
    "shortName": "joinedcontext",
    "organisation": "",
    "contactEmail": "",
    "logo": "",
    "colours": {
        "primary": "#1d4ed8",
        "secondary": "#0f766e",
        "accent": "#f59e0b",
        "background": "#ffffff",
        "text": "#0f172a",
    },
    "fonts": {"heading": "system-ui, sans-serif", "body": "system-ui, sans-serif"},
    "languages": {"default": "en", "offered": ["en"]},
    "primaryForeground": "#ffffff",
    # The line under the name on the home page and the lines at the foot of every page (a
    # demo disclaimer, an imprint): words only a deployment knows, so they are values too.
    "tagline": "",
    "footerLines": [],
}

HEX = set("0123456789abcdefABCDEF")


def _is_colour(value):
    """`#rgb` or `#rrggbb`. A custom property is a value the browser evaluates, so
    nothing else may reach a stylesheet."""
    return (
        isinstance(value, str)
        and value.startswith("#")
        and len(value) in (4, 7)
        and all(character in HEX for character in value[1:])
    )


def _load():
    try:
        with open(BRANDING_FILE, encoding="utf-8") as handle:
            block = json.load(handle)
    except (OSError, ValueError):
        return dict(NEUTRAL)
    if not isinstance(block, dict):
        return dict(NEUTRAL)
    branding = dict(NEUTRAL)
    branding.update(block)
    colours = dict(NEUTRAL["colours"])
    for name, value in (branding.get("colours") or {}).items():
        if _is_colour(value):
            colours[name] = value
    branding["colours"] = colours
    if not isinstance(branding.get("tagline"), str):
        branding["tagline"] = ""
    lines = branding.get("footerLines")
    branding["footerLines"] = [line for line in lines if isinstance(line, str) and line.strip()] \
        if isinstance(lines, list) else []
    red, green, blue = _rgb(colours["primary"])
    branding["primaryRgb"] = "%d, %d, %d" % (red, green, blue)
    # The text on the primary colour, by the YIQ rule the login theme uses too
    # (components/keycloak/charts/theme), so a light brand colour gets dark text.
    branding["primaryForeground"] = "#000000" if (red * 299 + green * 587 + blue * 114) // 1000 >= 128 else "#ffffff"
    return branding


def _rgb(colour):
    """`#rgb` or `#rrggbb` as three integers, for Bootstrap's `--bs-primary-rgb`."""
    digits = colour[1:]
    if len(digits) == 3:
        digits = "".join(character * 2 for character in digits)
    return tuple(int(digits[index:index + 2], 16) for index in (0, 2, 4))


def _available(codes):
    """The subset of `codes` CKAN can actually serve, in the order given.

    A locale CKAN does not ship makes it exit at start-up with "Locale(s) not available".
    The branding block is written by whoever deploys, not by whoever wrote CKAN, so an
    unsupported code narrows the language switcher instead of taking the catalogue down.
    """
    directory = os.path.join(os.path.dirname(ckan.__file__), "i18n")
    try:
        installed = set(os.listdir(directory))
    except OSError:
        installed = set()
    # English is the source language and has no catalogue of its own.
    installed.add("en")
    seen, out = set(), []
    for code in codes:
        if isinstance(code, str) and code in installed and code not in seen:
            seen.add(code)
            out.append(code)
    return out


BRANDING = _load()

# The words the theme adds to CKAN's own, in the four languages of the Portal (UI-82). CKAN's
# catalogues translate everything else; a language CKAN names `cs_CZ` reads the `cs` column.
STRINGS = {
    "about": {"en": "About this dataset", "sk": "O tomto datasete", "cs": "O této datové sadě", "de": "Über diesen Datensatz"},
    "publisher": {"en": "Publisher", "sk": "Vydavateľ", "cs": "Vydavatel", "de": "Herausgeber"},
    "licence": {"en": "Licence", "sk": "Licencia", "cs": "Licence", "de": "Lizenz"},
    "topic": {"en": "Topic", "sk": "Téma", "cs": "Téma", "de": "Thema"},
    "keywords": {"en": "Keywords", "sk": "Kľúčové slová", "cs": "Klíčová slova", "de": "Schlagwörter"},
    "format": {"en": "Format", "sk": "Formát", "cs": "Formát", "de": "Format"},
    "frequency": {"en": "Updated", "sk": "Aktualizácia", "cs": "Aktualizace", "de": "Aktualisierung"},
    "last_update": {"en": "Last update", "sk": "Posledná aktualizácia", "cs": "Poslední aktualizace", "de": "Letzte Aktualisierung"},
    "next_update": {"en": "Next update expected", "sk": "Ďalšia aktualizácia", "cs": "Další aktualizace", "de": "Nächste Aktualisierung"},
    "coverage": {"en": "Area covered", "sk": "Pokryté územie", "cs": "Pokryté území", "de": "Abgedecktes Gebiet"},
    "period": {"en": "Time covered", "sk": "Obdobie", "cs": "Období", "de": "Zeitraum"},
    "contact": {"en": "Contact", "sk": "Kontakt", "cs": "Kontakt", "de": "Kontakt"},
    "identifier": {"en": "Identifier", "sk": "Identifikátor", "cs": "Identifikátor", "de": "Kennung"},
    "language": {"en": "Language", "sk": "Jazyk", "cs": "Jazyk", "de": "Sprache"},
    "conforms_to": {"en": "Follows the standard", "sk": "Zodpovedá štandardu", "cs": "Odpovídá standardu", "de": "Folgt dem Standard"},
    "status": {"en": "Status", "sk": "Stav", "cs": "Stav", "de": "Status"},
    "live": {"en": "Live data (API)", "sk": "Živé dáta (API)", "cs": "Živá data (API)", "de": "Live-Daten (API)"},
    "live_lead": {
        "en": "The current state of this data, answered by the platform on every request (NGSI-LD).",
        "sk": "Aktuálny stav týchto dát, ktorý platforma vracia pri každej požiadavke (NGSI-LD).",
        "cs": "Aktuální stav těchto dat, který platforma vrací při každém požadavku (NGSI-LD).",
        "de": "Der aktuelle Stand dieser Daten, von der Plattform bei jeder Anfrage beantwortet (NGSI-LD).",
    },
    "example": {"en": "Start here: the kinds of entities it holds", "sk": "Začnite tu: aké druhy entít obsahuje", "cs": "Začněte zde: jaké druhy entit obsahuje", "de": "Hier beginnen: welche Arten von Entitäten es enthält"},
    "copy": {"en": "Copy", "sk": "Kopírovať", "cs": "Kopírovat", "de": "Kopieren"},
    "copied": {"en": "Copied", "sk": "Skopírované", "cs": "Zkopírováno", "de": "Kopiert"},
    "resources": {"en": "Data and downloads", "sk": "Dáta na stiahnutie", "cs": "Data ke stažení", "de": "Daten und Downloads"},
    "no_resources": {"en": "This dataset has no downloads yet.", "sk": "Tento dataset zatiaľ nemá nič na stiahnutie.", "cs": "Tato datová sada zatím nemá nic ke stažení.", "de": "Dieser Datensatz hat noch keine Downloads."},
    "empty": {
        "en": "Nothing matches. Try fewer or other words, or remove a filter on the left.",
        "sk": "Nič nezodpovedá. Skúste menej alebo iné slová, alebo zrušte filter vľavo.",
        "cs": "Nic neodpovídá. Zkuste méně nebo jiná slova, nebo zrušte filtr vlevo.",
        "de": "Nichts gefunden. Versuchen Sie weniger oder andere Wörter, oder entfernen Sie links einen Filter.",
    },
    "portal": {"en": "Portal", "sk": "Portál", "cs": "Portál", "de": "Portal"},
    "about_site": {"en": "About this catalogue", "sk": "O tomto katalógu", "cs": "O tomto katalogu", "de": "Über diesen Katalog"},
    "catalogue_api": {"en": "Catalogue API", "sk": "API katalógu", "cs": "API katalogu", "de": "Katalog-API"},
    # What a failed single sign-on says (T-2888). The extension keeps its reason in the session
    # and shows it nowhere, so the person was sent back to the login page without a word.
    "sso_cookie": {
        "en": "The sign-in could not finish: this browser did not keep the catalogue's cookie from the start of the sign-in. Allow cookies for this site and sign in again.",
        "sk": "Prihlásenie sa nedokončilo: prehliadač si neponechal súbor cookie katalógu zo začiatku prihlásenia. Povoľte súbory cookie pre túto stránku a prihláste sa znova.",
        "cs": "Přihlášení se nedokončilo: prohlížeč si neponechal soubor cookie katalogu ze začátku přihlášení. Povolte soubory cookie pro tento web a přihlaste se znovu.",
        "de": "Die Anmeldung wurde nicht abgeschlossen: Der Browser hat das Cookie des Katalogs vom Beginn der Anmeldung nicht behalten. Erlauben Sie Cookies für diese Seite und melden Sie sich erneut an.",
    },
    "sso_state": {
        "en": "The sign-in expired or was started in another tab. Sign in again.",
        "sk": "Prihlásenie vypršalo alebo sa začalo na inej karte. Prihláste sa znova.",
        "cs": "Přihlášení vypršelo nebo bylo zahájeno na jiné kartě. Přihlaste se znovu.",
        "de": "Die Anmeldung ist abgelaufen oder wurde in einem anderen Tab begonnen. Melden Sie sich erneut an.",
    },
    "sso_refused": {
        "en": "The identity service refused the catalogue's sign-in request. Tell the administrator: the catalogue's log names the reason.",
        "sk": "Služba identity odmietla žiadosť katalógu o prihlásenie. Povedzte to správcovi: dôvod je v logu katalógu.",
        "cs": "Služba identity odmítla žádost katalogu o přihlášení. Řekněte to správci: důvod je v logu katalogu.",
        "de": "Der Identitätsdienst hat die Anmeldeanfrage des Katalogs abgelehnt. Melden Sie es der Administration: Das Protokoll des Katalogs nennt den Grund.",
    },
    "sso_account": {
        "en": "More than one catalogue account uses your e-mail address, so the catalogue cannot tell which one is yours. Ask the administrator to merge them.",
        "sk": "Vašu e-mailovú adresu používa viac účtov katalógu, takže katalóg nevie, ktorý je váš. Požiadajte správcu, aby ich zlúčil.",
        "cs": "Vaši e-mailovou adresu používá více účtů katalogu, takže katalog neví, který je váš. Požádejte správce, aby je sloučil.",
        "de": "Mehrere Katalogkonten verwenden Ihre E-Mail-Adresse, daher weiß der Katalog nicht, welches Ihres ist. Bitten Sie die Administration, sie zusammenzuführen.",
    },
    "sso_other": {
        "en": "The sign-in did not finish. Sign in again; if it fails again, tell the administrator when it happened.",
        "sk": "Prihlásenie sa nedokončilo. Prihláste sa znova; ak zlyhá opäť, povedzte správcovi, kedy sa to stalo.",
        "cs": "Přihlášení se nedokončilo. Přihlaste se znovu; pokud selže znovu, řekněte správci, kdy se to stalo.",
        "de": "Die Anmeldung wurde nicht abgeschlossen. Melden Sie sich erneut an; schlägt es wieder fehl, nennen Sie der Administration den Zeitpunkt.",
    },
    # The dataset page leads with its rows, then the downloads in three sections (T-3009).
    "preview": {"en": "The data", "sk": "Dáta", "cs": "Data", "de": "Die Daten"},
    "preview_lead": {
        "en": "Browse, search and sort the rows here, or download the whole table.",
        "sk": "Prezerajte, vyhľadávajte a triedte riadky priamo tu, alebo si stiahnite celú tabuľku.",
        "cs": "Procházejte, vyhledávejte a řaďte řádky přímo zde, nebo si stáhněte celou tabulku.",
        "de": "Zeilen hier durchsuchen, filtern und sortieren oder die ganze Tabelle herunterladen.",
    },
    "rows": {"en": "rows", "sk": "riadkov", "cs": "řádků", "de": "Zeilen"},
    "table_title": {"en": "Table of the data", "sk": "Tabuľka dát", "cs": "Tabulka dat", "de": "Tabelle der Daten"},
    "tables": {"en": "tables", "sk": "tabuľky", "cs": "tabulky", "de": "Tabellen"},
    "table_what": {"en": "The table above, as one file", "sk": "Tabuľka vyššie ako jeden súbor", "cs": "Tabulka výše jako jeden soubor", "de": "Die Tabelle oben als eine Datei"},
    "open_table": {"en": "Open the table on its own page", "sk": "Otvoriť tabuľku na samostatnej stránke", "cs": "Otevřít tabulku na samostatné stránce", "de": "Tabelle auf eigener Seite öffnen"},
    "no_view": {
        "en": "The table has no view yet; download it below.",
        "sk": "Tabuľka zatiaľ nemá zobrazenie; stiahnite si ju nižšie.",
        "cs": "Tabulka zatím nemá zobrazení; stáhněte si ji níže.",
        "de": "Die Tabelle hat noch keine Ansicht; laden Sie sie unten herunter.",
    },
    "download": {"en": "Download", "sk": "Stiahnuť", "cs": "Stáhnout", "de": "Herunterladen"},
    "open": {"en": "Open", "sk": "Otvoriť", "cs": "Otevřít", "de": "Öffnen"},
    "details": {"en": "Details", "sk": "Podrobnosti", "cs": "Podrobnosti", "de": "Details"},
    "section_data": {"en": "Downloads", "sk": "Na stiahnutie", "cs": "Ke stažení", "de": "Downloads"},
    "section_data_lead": {"en": "The data as files, updated with the dataset.", "sk": "Dáta ako súbory, aktualizované spolu s datasetom.", "cs": "Data jako soubory, aktualizovaná spolu s datovou sadou.", "de": "Die Daten als Dateien, mit dem Datensatz aktualisiert."},
    "section_api": {"en": "APIs", "sk": "API", "cs": "API", "de": "Schnittstellen"},
    "section_api_lead": {"en": "For applications and AI assistants that query the data live.", "sk": "Pre aplikácie a AI asistentov, ktorí sa na dáta pýtajú naživo.", "cs": "Pro aplikace a AI asistenty, kteří se na data ptají živě.", "de": "Für Anwendungen und KI-Assistenten, die die Daten live abfragen."},
    "section_schema": {"en": "Data model", "sk": "Dátový model", "cs": "Datový model", "de": "Datenmodell"},
    "section_schema_lead": {"en": "What each field means, in the formats validators and developers read.", "sk": "Čo znamená každé pole, vo formátoch pre validátory a vývojárov.", "cs": "Co znamená každé pole, ve formátech pro validátory a vývojáře.", "de": "Was jedes Feld bedeutet, in den Formaten für Validatoren und Entwickler."},
    # The home page (T-3009).
    "tagline": {
        "en": "Open data you can browse, download and query live.",
        "sk": "Otvorené dáta, ktoré si prezriete, stiahnete a dopytujete naživo.",
        "cs": "Otevřená data, která si prohlédnete, stáhnete a dotazujete živě.",
        "de": "Offene Daten zum Durchsuchen, Herunterladen und Live-Abfragen.",
    },
    "no_datasets": {"en": "No dataset is published yet.", "sk": "Zatiaľ nie je zverejnený žiadny dataset.", "cs": "Zatím není zveřejněna žádná datová sada.", "de": "Noch ist kein Datensatz veröffentlicht."},
    "hero_search": {"en": "Search the open data", "sk": "Hľadať v otvorených dátach", "cs": "Hledat v otevřených datech", "de": "Offene Daten durchsuchen"},
    "hero_placeholder": {"en": "e.g. air quality, bikes, budget", "sk": "napr. kvalita ovzdušia, bicykle, rozpočet", "cs": "např. kvalita ovzduší, kola, rozpočet", "de": "z. B. Luftqualität, Fahrräder, Haushalt"},
    "search": {"en": "Search", "sk": "Hľadať", "cs": "Hledat", "de": "Suchen"},
    "datasets": {"en": "datasets", "sk": "datasetov", "cs": "datových sad", "de": "Datensätze"},
    "publishers": {"en": "publishers", "sk": "vydavateľov", "cs": "vydavatelů", "de": "Herausgeber"},
    "recent": {"en": "Recently updated", "sk": "Nedávno aktualizované", "cs": "Nedávno aktualizované", "de": "Kürzlich aktualisiert"},
    "all_datasets": {"en": "All datasets", "sk": "Všetky datasety", "cs": "Všechny datové sady", "de": "Alle Datensätze"},
    "by_publisher": {"en": "By publisher", "sk": "Podľa vydavateľa", "cs": "Podle vydavatele", "de": "Nach Herausgeber"},
    "by_keyword": {"en": "Popular keywords", "sk": "Časté kľúčové slová", "cs": "Častá klíčová slova", "de": "Häufige Schlagwörter"},
    "updated": {"en": "Updated", "sk": "Aktualizované", "cs": "Aktualizováno", "de": "Aktualisiert"},
    # The About page, the publisher and topic helpers and the header's words (T-3028).
    "nav_datasets": {"en": "Datasets", "sk": "Datasety", "cs": "Datové sady", "de": "Datensätze"},
    "nav_publishers": {"en": "Publishers", "sk": "Vydavatelia", "cs": "Vydavatelé", "de": "Herausgeber"},
    "nav_topics": {"en": "Topics", "sk": "Témy", "cs": "Témata", "de": "Themen"},
    "nav_about": {"en": "About", "sk": "O katalógu", "cs": "O katalogu", "de": "Über den Katalog"},
    "publishers_help": {
        "en": "The cities, regions and offices whose data this catalogue carries. Open one to see all of its datasets.",
        "sk": "Mestá, kraje a úrady, ktorých dáta tento katalóg obsahuje. Otvorte jedného a uvidíte všetky jeho datasety.",
        "cs": "Města, kraje a úřady, jejichž data tento katalog obsahuje. Otevřete jednoho a uvidíte všechny jeho datové sady.",
        "de": "Die Städte, Regionen und Ämter, deren Daten dieser Katalog enthält. Öffnen Sie einen, um alle seine Datensätze zu sehen.",
    },
    "topics_help": {
        "en": "A topic gathers the datasets on one subject from every publisher.",
        "sk": "Téma spája datasety o jednej veci od všetkých vydavateľov.",
        "cs": "Téma spojuje datové sady o jedné věci od všech vydavatelů.",
        "de": "Ein Thema bündelt die Datensätze zu einem Gegenstand von allen Herausgebern.",
    },
    "about_intro_org": {
        "en": "{name} is the open data catalogue of {org}.",
        "sk": "{name} je katalóg otvorených dát: {org}.",
        "cs": "{name} je katalog otevřených dat: {org}.",
        "de": "{name} ist der Katalog offener Daten von {org}.",
    },
    "about_intro": {
        "en": "{name} is an open data catalogue.",
        "sk": "{name} je katalóg otvorených dát.",
        "cs": "{name} je katalog otevřených dat.",
        "de": "{name} ist ein Katalog offener Daten.",
    },
    "about_data": {
        "en": "Every dataset comes straight from the platform's live data. Open one to browse and search its rows, download it as files, or query it live through its API.",
        "sk": "Každý dataset pochádza priamo zo živých dát platformy. Otvorte ho a prezerajte či vyhľadávajte v jeho riadkoch, stiahnite si ho ako súbory alebo sa naň pýtajte naživo cez jeho API.",
        "cs": "Každá datová sada pochází přímo z živých dat platformy. Otevřete ji a procházejte či vyhledávejte v jejích řádcích, stáhněte si ji jako soubory nebo se na ni ptejte živě přes její API.",
        "de": "Jeder Datensatz stammt direkt aus den Live-Daten der Plattform. Öffnen Sie ihn, um seine Zeilen zu durchsuchen, ihn als Dateien herunterzuladen oder ihn live über seine API abzufragen.",
    },
    "about_machines": {"en": "For developers and other catalogues", "sk": "Pre vývojárov a iné katalógy", "cs": "Pro vývojáře a jiné katalogy", "de": "Für Entwickler und andere Kataloge"},
    "about_api": {
        "en": "Every dataset and its description as JSON, through CKAN's Action API.",
        "sk": "Všetky datasety a ich opis ako JSON, cez Action API CKAN.",
        "cs": "Všechny datové sady a jejich popis jako JSON, přes Action API CKAN.",
        "de": "Alle Datensätze und ihre Beschreibung als JSON, über die Action-API von CKAN.",
    },
    "about_dcat": {"en": "DCAT-AP catalogue", "sk": "Katalóg DCAT-AP", "cs": "Katalog DCAT-AP", "de": "DCAT-AP-Katalog"},
    "about_dcat_what": {
        "en": "The whole catalogue as DCAT-AP, for harvesting by national and European data portals.",
        "sk": "Celý katalóg vo formáte DCAT-AP, na zber národnými a európskymi dátovými portálmi.",
        "cs": "Celý katalog ve formátu DCAT-AP, pro sklízení národními a evropskými datovými portály.",
        "de": "Der ganze Katalog als DCAT-AP, zum Einsammeln durch nationale und europäische Datenportale.",
    },
    "about_contact": {"en": "Questions about the data", "sk": "Otázky k dátam", "cs": "Dotazy k datům", "de": "Fragen zu den Daten"},
    "more": {"en": "More details", "sk": "Ďalšie údaje", "cs": "Další údaje", "de": "Weitere Angaben"},
}

# What a reader gets from each format, in one line (T-2744). A format not listed gets none.
FORMATS = {
    "NGSI-LD": {"en": "Live entities through the API", "sk": "Živé entity cez API", "cs": "Živé entity přes API", "de": "Live-Entitäten über die API"},
    "JSON-LD": {"en": "Linked data with its context", "sk": "Prepojené dáta s kontextom", "cs": "Propojená data s kontextem", "de": "Verknüpfte Daten mit Kontext"},
    "GEOJSON": {"en": "Points and shapes for a map", "sk": "Body a tvary pre mapu", "cs": "Body a tvary pro mapu", "de": "Punkte und Formen für eine Karte"},
    "CSV": {"en": "A table for a spreadsheet", "sk": "Tabuľka pre tabuľkový procesor", "cs": "Tabulka pro tabulkový procesor", "de": "Eine Tabelle für die Tabellenkalkulation"},
    "JSON": {"en": "Machine-readable JSON", "sk": "Strojovo čitateľný JSON", "cs": "Strojově čitelný JSON", "de": "Maschinenlesbares JSON"},
    "XLSX": {"en": "A spreadsheet", "sk": "Tabuľkový súbor", "cs": "Tabulkový soubor", "de": "Eine Tabellendatei"},
    "ZIP": {"en": "Everything in one download", "sk": "Všetko v jednom súbore", "cs": "Vše v jednom souboru", "de": "Alles in einem Download"},
    "MCP": {"en": "For AI assistants (Model Context Protocol)", "sk": "Pre AI asistentov (Model Context Protocol)", "cs": "Pro AI asistenty (Model Context Protocol)", "de": "Für KI-Assistenten (Model Context Protocol)"},
    "LINKML": {"en": "The data model", "sk": "Dátový model", "cs": "Datový model", "de": "Das Datenmodell"},
    "SHACL": {"en": "Validation rules of the data model", "sk": "Pravidlá kontroly dátového modelu", "cs": "Pravidla kontroly datového modelu", "de": "Prüfregeln des Datenmodells"},
}

# The EU frequency vocabulary, publications.europa.eu/resource/authority/frequency, as a label
# and the days to the next update. Irregular and unknown frequencies promise no date.
FREQUENCIES = {
    "CONT": ({"en": "Continuously", "sk": "Priebežne", "cs": "Průběžně", "de": "Laufend"}, None),
    "UPDATE_CONT": ({"en": "Continuously", "sk": "Priebežne", "cs": "Průběžně", "de": "Laufend"}, None),
    "HOURLY": ({"en": "Every hour", "sk": "Každú hodinu", "cs": "Každou hodinu", "de": "Stündlich"}, 1 / 24),
    "DAILY": ({"en": "Every day", "sk": "Denne", "cs": "Denně", "de": "Täglich"}, 1),
    "WEEKLY": ({"en": "Every week", "sk": "Týždenne", "cs": "Týdně", "de": "Wöchentlich"}, 7),
    "MONTHLY": ({"en": "Every month", "sk": "Mesačne", "cs": "Měsíčně", "de": "Monatlich"}, 30),
    "QUARTERLY": ({"en": "Every quarter", "sk": "Štvrťročne", "cs": "Čtvrtletně", "de": "Vierteljährlich"}, 91),
    "ANNUAL": ({"en": "Every year", "sk": "Ročne", "cs": "Ročně", "de": "Jährlich"}, 365),
    "IRREG": ({"en": "Irregularly", "sk": "Nepravidelne", "cs": "Nepravidelně", "de": "Unregelmäßig"}, None),
}

# The extras the About list reads by name, in the order a reader sees them. Everything else
# the publisher wrote stays under "More details"; the internal ones are never shown.
ABOUT_EXTRAS = ("identifier", "language", "contact", "conforms_to", "status")
# `license_url` and `theme` are DCAT metadata for harvesters (T-3025): the EU licence URI beside
# the licence the About list already links, and the themes as a JSON list of vocabulary URIs.
INTERNAL_EXTRAS = {"generated_by", "endpoint", "publisher_name", "publisher_uri", "contact_name",
                   "contact_email", "frequency", "spatial", "spatial_uri", "temporal_start",
                   "temporal_end", "theme", "license_url"}


def _language():
    try:
        code = toolkit.h.lang() or "en"
    except (AttributeError, RuntimeError):
        code = "en"
    return code.split("_")[0].split("-")[0]


def jc_t(key):
    """One of the theme's words in the page's language, English when there is none."""
    words = STRINGS.get(key) or {}
    return words.get(_language()) or words.get("en") or key


def _extras(pkg):
    return {e.get("key"): e.get("value") for e in (pkg or {}).get("extras") or [] if e.get("key")}


def _is_url(value):
    return isinstance(value, str) and value.startswith(("https://", "http://"))


_DAY = datetime.timedelta(days=1)


def _parse(stamp):
    """CKAN's `metadata_modified`, naive UTC without a zone, as an aware datetime."""
    parsed = datetime.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=datetime.timezone.utc)


def jc_frequency(pkg):
    """(label, next update as a datetime or None) of the dataset's frequency; None when unset."""
    value = _extras(pkg).get("frequency")
    if not value:
        return None
    code = str(value).rstrip("/").rsplit("/", 1)[-1].upper()
    known = FREQUENCIES.get(code)
    if not known:
        return (str(value), None)
    words, days = known
    label = words.get(_language()) or words["en"]
    modified = (pkg or {}).get("metadata_modified")
    if days is None or not modified:
        return (label, None)
    try:
        last = _parse(modified)
    except ValueError:
        return (label, None)
    return (label, last + datetime.timedelta(days=days))


def jc_about(pkg):
    """The rows of "About this dataset" as (label, text, link or None), empty ones left out."""
    pkg = pkg or {}
    extras = _extras(pkg)
    rows = []
    organization = pkg.get("organization") or {}
    publisher = extras.get("publisher_name") or organization.get("title") or organization.get("name")
    if publisher:
        link = extras.get("publisher_uri")
        rows.append((jc_t("publisher"), publisher, link if _is_url(link) else None))
    if pkg.get("license_title") or pkg.get("license_id"):
        link = pkg.get("license_url")
        rows.append((jc_t("licence"), pkg.get("license_title") or pkg.get("license_id"),
                     link if _is_url(link) else None))
    groups = [g.get("display_name") or g.get("title") or g.get("name") for g in pkg.get("groups") or []]
    if groups:
        rows.append((jc_t("topic"), ", ".join(g for g in groups if g), None))
    tags = [t.get("display_name") or t.get("name") for t in pkg.get("tags") or []]
    if tags:
        rows.append((jc_t("keywords"), ", ".join(t for t in tags if t), None))
    frequency = jc_frequency(pkg)
    if frequency:
        rows.append((jc_t("frequency"), frequency[0], None))
    if pkg.get("metadata_modified"):
        rows.append((jc_t("last_update"), str(pkg["metadata_modified"])[:10], None))
    if frequency and frequency[1]:
        # A dataset updated more than once a day promises an hour, not only a date.
        pattern = "%Y-%m-%d %H:%M UTC" if frequency[1] - _parse(pkg["metadata_modified"]) < _DAY else "%Y-%m-%d"
        rows.append((jc_t("next_update"), frequency[1].strftime(pattern), None))
    coverage = extras.get("spatial_uri")
    if coverage:
        rows.append((jc_t("coverage"), coverage, coverage if _is_url(coverage) else None))
    start, end = extras.get("temporal_start"), extras.get("temporal_end")
    if start or end:
        rows.append((jc_t("period"), " – ".join(v for v in (start, end) if v), None))
    contact = extras.get("contact_name") or extras.get("contact_email")
    if contact:
        email = extras.get("contact_email")
        rows.append((jc_t("contact"), contact, "mailto:" + email if email and "@" in email else None))
    for key in ("identifier", "language", "conforms_to", "status"):
        value = extras.get(key)
        if value:
            rows.append((jc_t(key), value, value if _is_url(value) else None))
    return rows


def jc_more(pkg):
    """The extras the About list does not show, as (key, value), for "More details"."""
    shown = set(ABOUT_EXTRAS) | INTERNAL_EXTRAS | {"identifier", "language", "conforms_to", "status"}
    return sorted((k, v) for k, v in _extras(pkg).items() if k not in shown and v)


def jc_live(pkg):
    """The dataset's live NGSI-LD address and an example query, or None.

    Only an https address under the platform's own domain is shown: the extra is written by
    the publisher, and a page must never point a reader at an internal service address.
    """
    endpoint = _extras(pkg).get("endpoint")
    domain = BRANDING.get("domain") or ""
    if not (isinstance(endpoint, str) and endpoint.startswith("https://") and domain):
        return None
    host = endpoint[len("https://"):].split("/", 1)[0]
    if host != domain and not host.endswith("." + domain):
        return None
    base = endpoint if endpoint.endswith("/") else endpoint + "/"
    # `types` answers without a filter; a query for entities needs a type the reader learns here.
    example = "curl -H 'Accept: application/ld+json' '%sngsi-ld/v1/types'" % base
    return {"url": base, "example": example}


# Where a resource belongs on the dataset page (T-3009). The model artifacts are published under
# the endpoint's `/schema/` path; the API formats answer queries rather than being files.
API_FORMATS = ("NGSI-LD", "MCP")
DATA_ORDER = ("CSV", "GEOJSON", "JSON", "XLSX", "ZIP")


def _section(resource):
    url = resource.get("url") or ""
    path = url.split("?", 1)[0]
    if "/schema/" in path:
        return "schema"
    if (resource.get("format") or "").strip().upper() in API_FORMATS:
        return "api"
    return "data"


def _order(resource):
    """The DataStore table first (it is the data a reader came for), then files by format."""
    name = (resource.get("format") or "").strip().upper()
    known = DATA_ORDER.index(name) if name in DATA_ORDER else len(DATA_ORDER)
    api = API_FORMATS.index(name) if name in API_FORMATS else len(API_FORMATS)
    return (not resource.get("datastore_active"), known, api, name, resource.get("name") or "")


def jc_resource_sections(pkg):
    """The resources in three sections, data, APIs and the data model, each in reading order
    and each resource with its one-line "what is this". Empty sections are left out."""
    sections = {"data": [], "api": [], "schema": []}
    for resource in sorted((pkg or {}).get("resources") or [], key=_order):
        name = (resource.get("format") or "").strip()
        words = FORMATS.get(name.upper()) or {}
        if resource.get("datastore_active"):
            # A DataStore table downloads as CSV, whatever format its resource names (T-3012
            # writes its tables with none).
            name = name or "CSV"
            words = STRINGS["table_what"]
        sections[_section(resource)].append({
            "resource": resource,
            "format": name or "—",
            "what": words.get(_language()) or words.get("en") or "",
        })
    return [{"key": key, "title": jc_t("section_" + key), "lead": jc_t("section_" + key + "_lead"),
             "items": items} for key, items in sections.items() if items]


def jc_previews(pkg):
    """The dataset's DataStore tables for the page itself, one per entity type since T-3012, in
    the order `_order` gives them: each resource with its table view (None when nobody created
    one) and its number of rows (None when the DataStore does not say)."""
    out = []
    for resource in sorted((pkg or {}).get("resources") or [], key=_order):
        if not resource.get("datastore_active"):
            continue
        try:
            views = toolkit.get_action("resource_view_list")({}, {"id": resource["id"]})
        except (toolkit.ObjectNotFound, toolkit.NotAuthorized):
            views = []
        view = next((v for v in views or [] if v.get("view_type") == "datatables_view"), None)
        try:
            total = toolkit.get_action("datastore_search")({}, {"resource_id": resource["id"], "limit": 0}).get("total")
        except (toolkit.ObjectNotFound, toolkit.NotAuthorized, toolkit.ValidationError):
            total = None
        out.append({"resource": resource, "view": view, "total": total})
    return out


def jc_total(previews):
    """All rows of the tables, or None when any table's count is unknown."""
    totals = [p["total"] for p in previews or []]
    return sum(totals) if totals and all(isinstance(t, int) for t in totals) else None


def jc_formats(pkg):
    """The formats a reader gets, data before APIs, without the data model's artifacts."""
    seen, out = set(), []
    for section in jc_resource_sections(pkg):
        if section["key"] == "schema":
            continue
        for item in section["items"]:
            name = item["format"]
            if name != "—" and name.upper() not in seen:
                seen.add(name.upper())
                out.append(name)
    return out


def jc_number(value):
    """A count with thin-space thousands, the way every language of the Portal reads it."""
    try:
        return "{:,}".format(int(value)).replace(",", "\u202f")
    except (TypeError, ValueError):
        return ""


def jc_recent(limit=6):
    """The public datasets changed last, for the home page."""
    from ckan.lib.search import SearchError

    try:
        found = toolkit.get_action("package_search")(
            {}, {"rows": limit, "sort": "metadata_modified desc", "fq": 'capacity:"public"'})
    except SearchError:
        return []
    return found.get("results") or []


def jc_about_site():
    """What the About page says when no sysadmin wrote `ckan.site_about` (T-3028): whose
    catalogue this is, how to get at the data, and the machine entrances, all from the branding
    block and the plugins that are loaded. The words are escaped by the template like any text."""
    name = BRANDING.get("instanceName") or "joinedcontext"
    organisation = BRANDING.get("organisation") or ""
    if organisation:
        intro = jc_t("about_intro_org").format(name=name, org=organisation)
    else:
        intro = jc_t("about_intro").format(name=name)
    email = BRANDING.get("contactEmail") or ""
    return {
        "intro": intro,
        "dcat": plugins.plugin_loaded("dcat"),
        "email": email if "@" in email else "",
    }


def jc_portal_url():
    """The Portal of this installation, for staff who signed in; None without a domain."""
    domain = BRANDING.get("domain")
    return "https://portal.%s/" % domain if domain else None


def jc_branding():
    """The block, for the templates."""
    return BRANDING


# The session key `ckanext-oidc-pkce` writes its reason under, and each reason it writes
# (views.py of 0.4.1, pinned in images/ckan/Dockerfile) mapped to words a person can act on.
SSO_ERROR = "ckanext:oidc-pkce:error"
SSO_REASONS = {
    "Login process was not started properly": "sso_cookie",
    "The app state does not match": "sso_state",
    "Unsupported token type. Should be 'Bearer'.": "sso_refused",
    "No access token returned from the token endpoint.": "sso_refused",
    "Unique user not found": "sso_account",
}


def jc_sso_error(session=None):
    """Why the last single sign-on failed, once, in the page's language; None when it did not.

    The raw reason stays in the extension's log line: it can name the identity service's own
    error, which is for the administrator and not for the page.
    """
    if session is None:
        from ckan.common import session
    reason = session.pop(SSO_ERROR, None)
    if not reason:
        return None
    return jc_t(SSO_REASONS.get(reason, "sso_other"))


class JcThemePlugin(plugins.SingletonPlugin):
    plugins.implements(plugins.IConfigurer)
    plugins.implements(plugins.ITemplateHelpers)
    plugins.implements(plugins.IFacets, inherit=True)

    def update_config(self, config):
        toolkit.add_template_directory(config, "templates")
        # The logo is a file beside this package, so CKAN serves it from its own origin and
        # no page reaches a third party for an asset.
        toolkit.add_public_directory(config, "public")
        title = BRANDING.get("instanceName")
        if title:
            config["ckan.site_title"] = title
            config["ckan.site_description"] = BRANDING.get("organisation", "")
        public = os.path.join(os.path.dirname(__file__), "public")
        logo = BRANDING.get("logo")
        if logo and os.path.exists(os.path.join(public, logo)):
            config["ckan.site_logo"] = "/" + logo
        favicon = BRANDING.get("favicon")
        if favicon and os.path.exists(os.path.join(public, favicon)):
            config["ckan.favicon"] = "/" + favicon
        languages = BRANDING.get("languages") or {}
        offered = _available(languages.get("offered") or [])
        default = languages.get("default")
        if default in offered:
            config["ckan.locale_default"] = default
        if offered:
            config["ckan.locales_offered"] = " ".join(offered)

    def get_helpers(self):
        return {
            "jc_branding": jc_branding,
            "jc_t": jc_t,
            "jc_about": jc_about,
            "jc_more": jc_more,
            "jc_live": jc_live,
            "jc_resource_sections": jc_resource_sections,
            "jc_previews": jc_previews,
            "jc_total": jc_total,
            "jc_number": jc_number,
            "jc_formats": jc_formats,
            "jc_recent": jc_recent,
            "jc_portal_url": jc_portal_url,
            "jc_about_site": jc_about_site,
            "jc_sso_error": jc_sso_error,
        }

    def dataset_facets(self, facets_dict, package_type):
        """The search filters in plain words: Publisher, Topic, Keywords, Format, Licence."""
        names = {"organization": "publisher", "groups": "topic", "tags": "keywords",
                 "res_format": "format", "license_id": "licence"}
        for field, key in names.items():
            if field in facets_dict:
                facets_dict[field] = jc_t(key)
        return facets_dict
