"""Renders any branding block (OPS-47).

The block is read once at start-up from the file the chart mounts. A missing or broken
file is not an error: CKAN then looks like a plain CKAN, which is what an installation
without branding should look like.
"""

import base64
import datetime
import html
import json
import os
import re
from urllib.parse import parse_qs, quote, urlencode, urlsplit, urlunsplit

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

# A badge and a description per CKAN organization name, from the chart's `organizations` value,
# for a publisher that set neither in CKAN. Same rule as the branding: a missing or broken file
# leaves CKAN's own placeholder.
ORGANIZATIONS_FILE = os.environ.get(
    "JC_ORGANIZATIONS_FILE", os.path.join(os.path.dirname(BRANDING_FILE), "organizations.json"))


def _organizations():
    try:
        with open(ORGANIZATIONS_FILE, encoding="utf-8") as handle:
            block = json.load(handle)
    except (OSError, ValueError):
        return {}
    return {name: entry for name, entry in block.items() if isinstance(entry, dict)} \
        if isinstance(block, dict) else {}


ORGANIZATIONS = _organizations()

# The packages the publish gate hides (T-4318): `{name: reason}` from the chart's `hidden` value.
# Hidden is not deleted: a sysadmin (the harvests' token) still finds, reads and updates them, so
# the next harvest keeps them current and a package comes back by leaving the list.
HIDDEN_FILE = os.environ.get("JC_HIDDEN_FILE", os.path.join(os.path.dirname(BRANDING_FILE), "hidden.json"))
PACKAGE_NAME = re.compile(r"^[a-z0-9_-]{2,100}$")


def _hidden():
    try:
        with open(HIDDEN_FILE, encoding="utf-8") as handle:
            block = json.load(handle)
    except (OSError, ValueError):
        return frozenset()
    return frozenset(n for n in block if isinstance(n, str) and PACKAGE_NAME.match(n)) \
        if isinstance(block, dict) else frozenset()


HIDDEN = _hidden()


def jc_sees_hidden():
    """Whether the caller is a sysadmin; outside a request nobody is."""
    try:
        return bool(getattr(toolkit.g.userobj, "sysadmin", False))
    except (AttributeError, RuntimeError, TypeError):
        return False


def jc_hide(search_params):
    """The search without the hidden packages, on the page, the API and the DCAT feed alike."""
    if HIDDEN and not jc_sees_hidden():
        clause = "-name:(" + " OR ".join(f'"{name}"' for name in sorted(HIDDEN)) + ")"
        search_params["fq"] = f"{search_params.get('fq') or ''} {clause}".strip()
    return search_params


def _badge(entry):
    """The publisher's initials on its colour, as an SVG data URI: on this origin, no file to mount."""
    initials = entry.get("initials")
    colour = entry.get("colour")
    if not isinstance(initials, str) or not initials.strip() or not _is_colour(colour):
        return None
    red, green, blue = _rgb(colour)
    ink = "#000000" if (red * 299 + green * 587 + blue * 114) // 1000 >= 128 else "#ffffff"
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="200" viewBox="0 0 400 200">'
        '<rect width="400" height="200" fill="%s"/>'
        '<text x="200" y="100" dy="0.35em" text-anchor="middle" fill="%s" '
        'font-family="system-ui, sans-serif" font-size="72" font-weight="700">%s</text></svg>'
    ) % (colour, ink, html.escape(initials.strip()[:4]))
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("ascii")


def jc_org(organization):
    """The organization's image and description: CKAN's own first, then the chart's, in the page's
    language when the chart gives several; None where neither has one."""
    organization = organization or {}
    entry = ORGANIZATIONS.get(organization.get("name") or "", {})
    description = organization.get("description")
    if not description:
        words = entry.get("description")
        if isinstance(words, dict):
            lang = toolkit.h.lang() or "en"
            words = words.get(lang) or words.get("en")
        description = words if isinstance(words, str) and words.strip() else None
    return {"image": organization.get("image_display_url") or _badge(entry), "description": description}

# The words the theme adds to CKAN's own, in the four languages of the Portal (UI-82). CKAN's
# catalogues translate everything else; a language CKAN names `cs_CZ` reads the `cs` column.
STRINGS = {
    "about": {"en": "About this dataset", "sk": "O tomto datasete", "cs": "O této datové sadě", "de": "Über diesen Datensatz"},
    "publisher": {"en": "Publisher", "sk": "Vydavateľ", "cs": "Vydavatel", "de": "Herausgeber"},
    "licence": {"en": "Licence", "sk": "Licencia", "cs": "Licence", "de": "Lizenz"},
    "attribution": {"en": "Attribution", "sk": "Uvedenie zdroja", "cs": "Uvedení zdroje", "de": "Quellenangabe"},
    "source": {"en": "Original data", "sk": "Pôvodné dáta", "cs": "Původní data", "de": "Ursprüngliche Daten"},
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
    "assistant": {"en": "Ask the assistant", "sk": "Opýtajte sa asistenta", "cs": "Zeptejte se asistenta", "de": "Fragen Sie den Assistenten"},
    # The dataset page leads with its rows, then the downloads in three sections (T-3009).
    "preview": {"en": "The data", "sk": "Dáta", "cs": "Data", "de": "Die Daten"},
    "preview_lead": {
        "en": "Browse, search and sort the rows here, or download the whole table.",
        "sk": "Prezerajte, vyhľadávajte a triedte riadky priamo tu, alebo si stiahnite celú tabuľku.",
        "cs": "Procházejte, vyhledávejte a řaďte řádky přímo zde, nebo si stáhněte celou tabulku.",
        "de": "Zeilen hier durchsuchen, filtern und sortieren oder die ganze Tabelle herunterladen.",
    },
    # A count's word in each language's plural forms, one, two to four, five and more (T-4066).
    "rows": {"en": ("row", "rows", "rows"), "sk": ("riadok", "riadky", "riadkov"),
             "cs": ("řádek", "řádky", "řádků"), "de": ("Zeile", "Zeilen", "Zeilen")},
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
    "part_of": {"en": "Part of the dataset", "sk": "Súčasť datasetu", "cs": "Součást datové sady", "de": "Teil des Datensatzes"},
    "address": {"en": "Address", "sk": "Adresa", "cs": "Adresa", "de": "Adresse"},
    "file_lead": {
        "en": "This is a file to download; it opens in the program that reads its format.",
        "sk": "Toto je súbor na stiahnutie; otvorí sa v programe, ktorý číta jeho formát.",
        "cs": "Toto je soubor ke stažení; otevře se v programu, který čte jeho formát.",
        "de": "Dies ist eine Datei zum Herunterladen; sie öffnet sich im Programm, das ihr Format liest.",
    },
    "api_lead": {
        "en": "This is an address a program calls; open it to see what it answers.",
        "sk": "Toto je adresa, ktorú volá program; otvorte ju a uvidíte, čo odpovedá.",
        "cs": "Toto je adresa, kterou volá program; otevřete ji a uvidíte, co odpovídá.",
        "de": "Dies ist eine Adresse, die ein Programm aufruft; öffnen Sie sie, um die Antwort zu sehen.",
    },
    "open": {"en": "Open", "sk": "Otvoriť", "cs": "Otevřít", "de": "Öffnen"},
    "details": {"en": "Details", "sk": "Podrobnosti", "cs": "Podrobnosti", "de": "Details"},
    "section_data": {"en": "Downloads", "sk": "Na stiahnutie", "cs": "Ke stažení", "de": "Downloads"},
    "section_data_lead": {"en": "The data as files, updated with the dataset.", "sk": "Dáta ako súbory, aktualizované spolu s datasetom.", "cs": "Data jako soubory, aktualizovaná spolu s datovou sadou.", "de": "Die Daten als Dateien, mit dem Datensatz aktualisiert."},
    "section_api": {"en": "API and live access", "sk": "API a živý prístup", "cs": "API a živý přístup", "de": "API und Live-Zugriff"},
    "usage": {"en": "How to use it", "sk": "Ako to použiť", "cs": "Jak to použít", "de": "So verwenden Sie es"},
    "guide": {"en": "The WebSocket guide: messages, limits and examples", "sk": "Príručka k WebSocketu: správy, limity a príklady", "cs": "Průvodce WebSocketem: zprávy, limity a příklady", "de": "Die WebSocket-Anleitung: Nachrichten, Grenzen und Beispiele"},
    "snippet": {"en": "Command to copy", "sk": "Príkaz na skopírovanie", "cs": "Příkaz ke zkopírování", "de": "Befehl zum Kopieren"},
    "mcp": {"en": "Connect an AI assistant", "sk": "Pripojte AI asistenta", "cs": "Připojte AI asistenta", "de": "KI-Assistenten verbinden"},
    "mcp_lead": {
        "en": "One address for the whole catalogue (MCP). Add it once and your assistant finds every dataset, its attributes, data model and access rules by itself. Open data needs no login; signing in adds the data you may read.",
        "sk": "Jedna adresa pre celý katalóg (MCP). Pridajte ju raz a asistent sám nájde každý dataset, jeho atribúty, dátový model a pravidlá prístupu. Otvorené dáta nepotrebujú prihlásenie; po prihlásení pribudnú dáta, ktoré smiete čítať.",
        "cs": "Jedna adresa pro celý katalog (MCP). Přidejte ji jednou a asistent sám najde každou datovou sadu, její atributy, datový model a pravidla přístupu. Otevřená data nepotřebují přihlášení; po přihlášení přibudou data, která smíte číst.",
        "de": "Eine Adresse für den ganzen Katalog (MCP). Einmal hinzugefügt, findet Ihr Assistent jeden Datensatz, seine Attribute, sein Datenmodell und seine Zugriffsregeln selbst. Offene Daten brauchen keine Anmeldung; nach der Anmeldung kommen die Daten hinzu, die Sie lesen dürfen.",
    },
    "mcp_url": {"en": "MCP server address", "sk": "Adresa MCP servera", "cs": "Adresa MCP serveru", "de": "Adresse des MCP-Servers"},
    "mcp_claude_ai": {"en": "Claude (claude.ai and Claude Desktop)", "sk": "Claude (claude.ai a Claude Desktop)", "cs": "Claude (claude.ai a Claude Desktop)", "de": "Claude (claude.ai und Claude Desktop)"},
    "mcp_claude_ai_1": {"en": "Open Customize, then Connectors, choose + Add and Add custom connector.", "sk": "Otvorte Prispôsobiť, potom Konektory, zvoľte + Pridať a Pridať vlastný konektor.", "cs": "Otevřete Přizpůsobit, pak Konektory, zvolte + Přidat a Přidat vlastní konektor.", "de": "Öffnen Sie Anpassen, dann Konnektoren, wählen Sie + Hinzufügen und Benutzerdefinierten Konnektor hinzufügen."},
    "mcp_claude_ai_2": {"en": "Name it joinedcontext and paste this address:", "sk": "Pomenujte ho joinedcontext a vložte túto adresu:", "cs": "Pojmenujte ho joinedcontext a vložte tuto adresu:", "de": "Nennen Sie ihn joinedcontext und fügen Sie diese Adresse ein:"},
    "mcp_claude_ai_3": {"en": "Leave the advanced settings empty and choose Add. Open data needs no login.", "sk": "Rozšírené nastavenia nechajte prázdne a zvoľte Pridať. Otvorené dáta nepotrebujú prihlásenie.", "cs": "Rozšířená nastavení nechte prázdná a zvolte Přidat. Otevřená data nepotřebují přihlášení.", "de": "Lassen Sie die erweiterten Einstellungen leer und wählen Sie Hinzufügen. Offene Daten brauchen keine Anmeldung."},
    "mcp_editors": {"en": "Code editors and other assistants", "sk": "Editory kódu a iní asistenti", "cs": "Editory kódu a jiní asistenti", "de": "Code-Editoren und andere Assistenten"},
    "mcp_claude": {"en": "Claude Code", "sk": "Claude Code", "cs": "Claude Code", "de": "Claude Code"},
    "mcp_json": {"en": "Any other MCP client (JSON)", "sk": "Iný MCP klient (JSON)", "cs": "Jiný MCP klient (JSON)", "de": "Jeder andere MCP-Client (JSON)"},
    "mcp_vscode": {"en": "Add to VS Code", "sk": "Pridať do VS Code", "cs": "Přidat do VS Code", "de": "Zu VS Code hinzufügen"},
    "mcp_cursor": {"en": "Add to Cursor", "sk": "Pridať do Cursoru", "cs": "Přidat do Cursoru", "de": "Zu Cursor hinzufügen"},
    # The "Use it in your AI assistant" page and its button (T-4585). The stores are the ones each
    # maker documents, read 2026-10-18: ChatGPT at chatgpt.com/plugins
    # (developers.openai.com/apps-sdk/deploy/connect-chatgpt), Claude at Customize > Connectors
    # (support.claude.com article 11175166), Gemini CLI's `gemini mcp add --transport http`
    # (geminicli.com/docs/tools/mcp-server). The Gemini and Grok apps take no connectors (Grok
    # remote MCP only through the xAI API, docs.x.ai), so their cards link nowhere.
    "assistants": {"en": "Use it in your AI assistant", "sk": "Použite v AI asistentovi", "cs": "Použijte v AI asistentovi", "de": "In Ihrem KI-Assistenten nutzen"},
    "assistants_label": {"en": "Use the data in ChatGPT, Claude, Gemini or any MCP client", "sk": "Použite dáta v ChatGPT, Claude, Gemini alebo v akomkoľvek klientovi MCP", "cs": "Použijte data v ChatGPT, Claude, Gemini nebo v libovolném klientovi MCP", "de": "Die Daten in ChatGPT, Claude, Gemini oder jedem MCP-Client nutzen"},
    "assistants_lead": {
        "en": "Add {name} to the assistant you already use, and ask it about this catalogue's open data. One address covers every dataset; no account is needed.",
        "sk": "Pridajte {name} do asistenta, ktorého už používate, a pýtajte sa ho na otvorené dáta tohto katalógu. Jedna adresa pokrýva všetky datasety; účet netreba.",
        "cs": "Přidejte {name} do asistenta, kterého už používáte, a ptejte se ho na otevřená data tohoto katalogu. Jedna adresa pokrývá všechny datové sady; účet není potřeba.",
        "de": "Fügen Sie {name} dem Assistenten hinzu, den Sie schon nutzen, und fragen Sie ihn nach den offenen Daten dieses Katalogs. Eine Adresse deckt alle Datensätze ab; kein Konto nötig.",
    },
    "coming_soon": {"en": "Coming soon", "sk": "Čoskoro", "cs": "Brzy", "de": "Demnächst"},
    # T-4628: a card is the logo, the name and one link to that assistant's connector store.
    "add_to": {"en": "Add to {name}", "sk": "Pridať do {name}", "cs": "Přidat do {name}", "de": "Zu {name} hinzufügen"},
    "store_address": {"en": "In the store, choose Add custom connector and paste this address:",
                      "sk": "V obchode zvoľte Pridať vlastný konektor a vložte túto adresu:",
                      "cs": "V obchodě zvolte Přidat vlastní konektor a vložte tuto adresu:",
                      "de": "Wählen Sie im Store Benutzerdefinierten Konnektor hinzufügen und fügen Sie diese Adresse ein:"},
    "for_developers": {"en": "For developers", "sk": "Pre vývojárov", "cs": "Pro vývojáře", "de": "Für Entwickler"},
    "gemini_1": {"en": "In Gemini CLI: run this command in a terminal, then start gemini.", "sk": "V Gemini CLI: spustite tento príkaz v termináli a potom gemini.", "cs": "V Gemini CLI: spusťte tento příkaz v terminálu a pak gemini.", "de": "In der Gemini CLI: Führen Sie diesen Befehl im Terminal aus und starten Sie dann gemini."},
    "any_client": {"en": "Any MCP client", "sk": "Akýkoľvek MCP klient", "cs": "Jakýkoli MCP klient", "de": "Jeder MCP-Client"},
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
    "search_publishers": {"en": "Search publishers…", "sk": "Hľadať vydavateľov…",
                          "cs": "Hledat vydavatele…", "de": "Herausgeber suchen…"},
    "search_topics": {"en": "Search topics…", "sk": "Hľadať témy…", "cs": "Hledat témata…",
                      "de": "Themen suchen…"},
    "nav_about": {"en": "About", "sk": "O katalógu", "cs": "O katalogu", "de": "Über den Katalog"},
    "try_it": {"en": "Try it", "sk": "Vyskúšajte", "cs": "Vyzkoušejte", "de": "Probieren Sie es aus"},
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
    # A resource page (T-4333): what it is, its address, its live rows and how to use it.
    "copy_address": {"en": "Copy address", "sk": "Kopírovať adresu", "cs": "Kopírovat adresu", "de": "Adresse kopieren"},
    "full_address": {"en": "The whole address", "sk": "Celá adresa", "cs": "Celá adresa", "de": "Die ganze Adresse"},
    "entity_type": {"en": "Data type", "sk": "Typ dát", "cs": "Typ dat", "de": "Datentyp"},
    "scope_dataset": {"en": "Only this dataset's records.", "sk": "Iba záznamy tohto datasetu.", "cs": "Pouze záznamy této datové sady.", "de": "Nur die Einträge dieses Datensatzes."},
    "scope_type": {
        "en": "Every {type} record of the publisher's open data, this dataset's among them.",
        "sk": "Všetky záznamy typu {type} v otvorených dátach vydavateľa, vrátane tohto datasetu.",
        "cs": "Všechny záznamy typu {type} v otevřených datech vydavatele, včetně této datové sady.",
        "de": "Alle {type}-Einträge der offenen Daten des Herausgebers, auch die dieses Datensatzes.",
    },
    "preview_types": {"en": "The kinds of entities it holds, live", "sk": "Druhy entít, ktoré obsahuje, naživo", "cs": "Druhy entit, které obsahuje, živě", "de": "Die Arten von Entitäten, live"},
    "preview_api": {"en": "The first records, live", "sk": "Prvé záznamy naživo", "cs": "První záznamy živě", "de": "Die ersten Einträge, live"},
    "preview_loading": {"en": "Loading the first records…", "sk": "Načítavajú sa prvé záznamy…", "cs": "Načítají se první záznamy…", "de": "Die ersten Einträge werden geladen…"},
    "preview_failed": {
        "en": "The records did not load here; the address still answers a program.",
        "sk": "Záznamy sa tu nenačítali; adresa programu odpovedá aj tak.",
        "cs": "Záznamy se zde nenačetly; adresa programu odpovídá i tak.",
        "de": "Die Einträge wurden hier nicht geladen; die Adresse antwortet einem Programm trotzdem.",
    },
    "preview_empty": {"en": "No records yet.", "sk": "Zatiaľ žiadne záznamy.", "cs": "Zatím žádné záznamy.", "de": "Noch keine Einträge."},
    "preview_shown": {"en": "{shown} of {total} records", "sk": "{shown} z {total} záznamov", "cs": "{shown} z {total} záznamů", "de": "{shown} von {total} Einträgen"},
    "records": {"en": "Records", "sk": "Počet záznamov", "cs": "Počet záznamů", "de": "Einträge"},
    "ex_first": {"en": "The first 5 records, with curl", "sk": "Prvých 5 záznamov cez curl", "cs": "Prvních 5 záznamů přes curl", "de": "Die ersten 5 Einträge mit curl"},
    "ex_file": {"en": "Download it with curl", "sk": "Stiahnutie cez curl", "cs": "Stažení přes curl", "de": "Mit curl herunterladen"},
    "ex_excel": {
        "en": "In Excel or Power BI: Data, Get Data, From OData Feed, with this address",
        "sk": "V Exceli alebo Power BI: Údaje, Získať údaje, Z informačného kanála OData, s touto adresou",
        "cs": "V Excelu nebo Power BI: Data, Načíst data, Z informačního kanálu OData, s touto adresou",
        "de": "In Excel oder Power BI: Daten, Daten abrufen, Aus OData-Feed, mit dieser Adresse",
    },
    "ex_qgis": {
        "en": "In QGIS: Layer, Add Layer, Add WFS / OGC API - Features Layer, a new connection with this address",
        "sk": "V QGIS: Vrstva, Pridať vrstvu, Pridať vrstvu WFS / OGC API - Features, nové pripojenie s touto adresou",
        "cs": "V QGIS: Vrstva, Přidat vrstvu, Přidat vrstvu WFS / OGC API - Features, nové připojení s touto adresou",
        "de": "In QGIS: Layer, Layer hinzufügen, WFS / OGC API - Features-Layer hinzufügen, eine neue Verbindung mit dieser Adresse",
    },
    "ex_ws": {
        "en": "Changes as they happen, with websocat: open the socket, then send the subscription as the first line",
        "sk": "Zmeny naživo cez websocat: otvorte spojenie a ako prvý riadok pošlite odber",
        "cs": "Změny živě přes websocat: otevřete spojení a jako první řádek pošlete odběr",
        "de": "Änderungen live mit websocat: Verbindung öffnen, dann das Abonnement als erste Zeile senden",
    },
    "ex_chatgpt_title": {"en": "ChatGPT", "sk": "ChatGPT", "cs": "ChatGPT", "de": "ChatGPT"},
    "ex_chatgpt": {
        "en": "Open Settings, then Apps and Connectors, and choose Create. Paste this address as the MCP server URL, with no authentication.",
        "sk": "Otvorte Nastavenia, potom Aplikácie a konektory, a zvoľte Vytvoriť. Vložte túto adresu ako URL MCP servera, bez overenia.",
        "cs": "Otevřete Nastavení, pak Aplikace a konektory, a zvolte Vytvořit. Vložte tuto adresu jako URL MCP serveru, bez ověření.",
        "de": "Öffnen Sie Einstellungen, dann Apps und Konnektoren, und wählen Sie Erstellen. Fügen Sie diese Adresse als URL des MCP-Servers ein, ohne Authentifizierung.",
    },
    "created": {"en": "Created", "sk": "Vytvorené", "cs": "Vytvořeno", "de": "Erstellt"},
    "info": {"en": "About this resource", "sk": "O tomto zdroji", "cs": "O tomto zdroji", "de": "Über diese Ressource"},
    "original_table": {"en": "The publisher's original table", "sk": "Pôvodná tabuľka vydavateľa", "cs": "Původní tabulka vydavatele", "de": "Die Originaltabelle des Herausgebers"},
    "records_csv": {"en": "All records as a table", "sk": "Všetky záznamy ako tabuľka", "cs": "Všechny záznamy jako tabulka", "de": "Alle Einträge als Tabelle"},
    "records_geojson": {"en": "All records for a map", "sk": "Všetky záznamy na mapu", "cs": "Všechny záznamy na mapu", "de": "Alle Einträge für eine Karte"},
    "records_json": {"en": "All records for programs", "sk": "Všetky záznamy pre programy", "cs": "Všechny záznamy pro programy", "de": "Alle Einträge für Programme"},
    "records_xlsx": {"en": "All records for Excel", "sk": "Všetky záznamy pre Excel", "cs": "Všechny záznamy pro Excel", "de": "Alle Einträge für Excel"},
    "records_parquet": {"en": "All records for pandas, Polars or DuckDB", "sk": "Všetky záznamy pre pandas, Polars alebo DuckDB", "cs": "Všechny záznamy pro pandas, Polars nebo DuckDB", "de": "Alle Einträge für pandas, Polars oder DuckDB"},
    "live_changes": {"en": "Live changes", "sk": "Zmeny naživo", "cs": "Změny živě", "de": "Änderungen live"},
    "ex_types": {"en": "The kinds of entities it holds, with curl", "sk": "Druhy entít, ktoré obsahuje, cez curl", "cs": "Druhy entit, které obsahuje, přes curl", "de": "Die Arten von Entitäten, die sie enthält, mit curl"},
    "section_source": {"en": "At the publisher", "sk": "U vydavateľa", "cs": "U vydavatele", "de": "Beim Herausgeber"},
    "source_lead": {
        "en": "This is the publisher's own page for the data; it opens on their site.",
        "sk": "Toto je stránka vydavateľa s týmito dátami; otvorí sa na jeho webe.",
        "cs": "Toto je stránka vydavatele s těmito daty; otevře se na jeho webu.",
        "de": "Dies ist die Seite des Herausgebers zu diesen Daten; sie öffnet sich auf seiner Website.",
    },
    "section_source_lead": {"en": "Where the publisher keeps the original.", "sk": "Kde má vydavateľ originál.", "cs": "Kde má vydavatel originál.", "de": "Wo der Herausgeber das Original hat."},
    "at_publisher": {"en": "On the publisher's site", "sk": "Na stránke vydavateľa", "cs": "Na stránce vydavatele", "de": "Auf der Seite des Herausgebers"},
}

# What a reader gets from each format, in one line (T-2744). A format not listed gets none.
FORMATS = {
    "NGSI-LD": {"en": "Live entities through the API", "sk": "Živé entity cez API", "cs": "Živé entity přes API", "de": "Live-Entitäten über die API"},
    "JSON-LD": {"en": "Linked data with its context", "sk": "Prepojené dáta s kontextom", "cs": "Propojená data s kontextem", "de": "Verknüpfte Daten mit Kontext"},
    "GEOJSON": {"en": "Points and shapes for a map", "sk": "Body a tvary pre mapu", "cs": "Body a tvary pro mapu", "de": "Punkte und Formen für eine Karte"},
    "CSV": {"en": "A table for a spreadsheet", "sk": "Tabuľka pre tabuľkový procesor", "cs": "Tabulka pro tabulkový procesor", "de": "Eine Tabelle für die Tabellenkalkulation"},
    "JSON": {"en": "Machine-readable JSON", "sk": "Strojovo čitateľný JSON", "cs": "Strojově čitelný JSON", "de": "Maschinenlesbares JSON"},
    "XLSX": {"en": "A spreadsheet", "sk": "Tabuľkový súbor", "cs": "Tabulkový soubor", "de": "Eine Tabellendatei"},
    "PARQUET": {"en": "Typed columns for data analysis (Apache Parquet)", "sk": "Typované stĺpce pre analýzu dát (Apache Parquet)", "cs": "Typované sloupce pro analýzu dat (Apache Parquet)", "de": "Typisierte Spalten für die Datenanalyse (Apache Parquet)"},
    "ZIP": {"en": "Everything in one download", "sk": "Všetko v jednom súbore", "cs": "Vše v jednom souboru", "de": "Alles in einem Download"},
    "WEBSOCKET": {"en": "Live updates as they happen (WebSocket)", "sk": "Zmeny naživo, hneď ako nastanú (WebSocket)", "cs": "Změny živě, hned jak nastanou (WebSocket)", "de": "Änderungen live, sobald sie geschehen (WebSocket)"},
    "OGCFEAT": {"en": "Map layers for GIS (OGC API - Features)", "sk": "Mapové vrstvy pre GIS (OGC API - Features)", "cs": "Mapové vrstvy pro GIS (OGC API - Features)", "de": "Kartenebenen für GIS (OGC API - Features)"},
    "ODATA": {"en": "For Excel and Power BI (OData)", "sk": "Pre Excel a Power BI (OData)", "cs": "Pro Excel a Power BI (OData)", "de": "Für Excel und Power BI (OData)"},
    "STA": {"en": "Sensors and observations (SensorThings API)", "sk": "Senzory a merania (SensorThings API)", "cs": "Senzory a měření (SensorThings API)", "de": "Sensoren und Messungen (SensorThings API)"},
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
                   "temporal_end", "theme", "license_url", "harvest_source", "rights", "source"}
# What a harvested record says about itself, in words (T-4333): the dates the publisher gave and
# where the record came from. Any other extra keeps its own key.
EXTRA_LABELS = {
    "issued": {"en": "Published by the publisher", "sk": "Zverejnené vydavateľom", "cs": "Zveřejněno vydavatelem", "de": "Vom Herausgeber veröffentlicht"},
    "modified": {"en": "Changed by the publisher", "sk": "Zmenené vydavateľom", "cs": "Změněno vydavatelem", "de": "Vom Herausgeber geändert"},
    "quality_pass_rate": {"en": "Passed the quality checks", "sk": "Prešlo kontrolami kvality", "cs": "Prošlo kontrolami kvality", "de": "Qualitätsprüfungen bestanden"},
    "source_uri": {"en": "Original record", "sk": "Pôvodný záznam", "cs": "Původní záznam", "de": "Ursprünglicher Eintrag"},
    "was_generated_by": {"en": "Produced by", "sk": "Vytvoril", "cs": "Vytvořil", "de": "Erzeugt von"},
}


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


def _localized(values, language):
    """`values[language]`, else the catalogue's default language's, else the first; a plain value
    is the same in every language. None when nothing usable is there."""
    if not isinstance(values, dict):
        return values or None
    default = (BRANDING.get("languages") or {}).get("default")
    for code in (language, default):
        if values.get(code):
            return values[code]
    return next((value for value in values.values() if value), None)


def jc_site_title(language=None):
    """The catalogue's name in the page's language (T-4636): its instance's `site.title`, else the
    installation's name."""
    title = _localized(BRANDING.get("siteTitle"), language or _language())
    return title if isinstance(title, str) else BRANDING.get("instanceName") or "joinedcontext"


def jc_site_logo():
    """The header's image on this origin (T-4636): the instance's `site.logo`, a file in the
    theme's public directory, else the joinedcontext.com lockup (T-4627)."""
    logo = BRANDING.get("siteLogo")
    if isinstance(logo, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*\.(svg|png|webp)", logo):
        return "/" + logo
    return "/jc-logo.svg"


def _samples(language):
    """The instance's sample questions for the page's language (T-4636): strings only."""
    found = _localized(BRANDING.get("samples"), language)
    return [q for q in found if isinstance(q, str) and q.strip()] if isinstance(found, list) else []


def _extras(pkg):
    return {e.get("key"): e.get("value") for e in (pkg or {}).get("extras") or [] if e.get("key")}


def _is_url(value):
    return isinstance(value, str) and value.startswith(("https://", "http://"))


def _sources(value):
    """(address, title) of each http source in a `source` extra: a JSON list of `{url, title}`
    (T-4436) or of addresses, or one address; a source without a title shows its address."""
    try:
        items = json.loads(value) if isinstance(value, str) and value.startswith("[") else [value]
    except ValueError:
        return []
    out = []
    for item in items if isinstance(items, list) else []:
        url = item.get("url") if isinstance(item, dict) else item
        if _is_url(url):
            title = item.get("title") if isinstance(item, dict) else None
            out.append((url, title if isinstance(title, str) and title else url))
    return out


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


# The NUTS 3 regions of the bodies on the platform, by code and language (T-4333); any other code
# reads as its code. A data file beside this one, so no country's names sit in the code (T-4636).
# ponytail: a handful of names, the Eurostat NUTS list when more countries publish.
def _nuts_names():
    try:
        with open(os.path.join(os.path.dirname(__file__), "nuts.json"), encoding="utf-8") as handle:
            names = json.load(handle)
    except (OSError, ValueError):
        return {}
    return names if isinstance(names, dict) else {}


NUTS_NAMES = _nuts_names()


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
    # The credit the licence asks for and the data it came from, as the Endpoint names them
    # (T-4417): `source` is the JSON list of IRIs ckanext-dcat reads as dct:source.
    if extras.get("rights"):
        rows.append((jc_t("attribution"), extras["rights"], None))
    for url, title in _sources(extras.get("source")):
        rows.append((jc_t("source"), title, url))
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
        rows.append((jc_t("last_update"), _date(str(pkg["metadata_modified"])[:10]), None))
    if frequency and frequency[1]:
        # A dataset updated more than once a day promises an hour, not only a date.
        hourly = frequency[1] - _parse(pkg["metadata_modified"]) < _DAY
        # CKAN writes a date with hours as "%B %d, %Y", English order with the page's month name;
        # the hour goes after the page's own date instead (T-4333).
        text = _date(frequency[1])
        rows.append((jc_t("next_update"), text + frequency[1].strftime(", %H:%M (UTC)") if hourly else text, None))
    coverage = extras.get("spatial_uri")
    if coverage:
        # An EU NUTS region reads by its name where the theme knows it and by its code, linked to
        # its definition (T-4333).
        nuts = re.search(r"/nuts/code/([A-Z]{2}[0-9A-Z]{0,3})$", coverage)
        text = coverage
        if nuts:
            names = NUTS_NAMES.get(nuts.group(1))
            text = "NUTS " + nuts.group(1)
            if names:
                text = "%s (%s)" % (names.get(_language()) or names["en"], text)
        rows.append((jc_t("coverage"), text, coverage if _is_url(coverage) else None))
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
            standard = jc_standard({"conforms_to": value}) if key == "conforms_to" else None
            rows.append((jc_t(key), standard["name"] if standard else value, value if _is_url(value) else None))
    return rows


def _date(value, hours=False):
    """A date (or a datetime) as CKAN writes dates in the page's language (T-4333); the ISO form
    where CKAN's helper is not there to ask."""
    try:
        return toolkit.h.render_datetime(value, with_hours=hours)
    except (AttributeError, TypeError, ValueError):
        if isinstance(value, datetime.datetime):
            return value.strftime("%Y-%m-%d %H:%M UTC" if hours else "%Y-%m-%d")
        return str(value)


def jc_more(pkg):
    """The extras the About list does not show, as (key, value), for "More details"."""
    shown = set(ABOUT_EXTRAS) | INTERNAL_EXTRAS | {"identifier", "language", "conforms_to", "status"}
    return sorted((k, v) for k, v in _extras(pkg).items() if k not in shown and v)


def jc_extra(key, value):
    """One "More details" row as (label, text, link): a known key in words, an ISO date as the
    page writes dates, an http address as a link; anything else as it is."""
    words = EXTRA_LABELS.get(key)
    label = (words.get(_language()) or words["en"]) if words else str(key).replace("_", " ").capitalize()
    text = str(value)
    if key == "quality_pass_rate" and re.match(r"^(0(\.\d+)?|1(\.0+)?)$", text):
        text = "%d %%" % round(float(text) * 100)
    if re.match(r"^\d{4}-\d{2}-\d{2}(T[\d:.]+Z?)?$", text):
        try:
            text = toolkit.h.render_datetime(text.rstrip("Z"))
        except (AttributeError, TypeError, ValueError):
            pass
    return label, text, text if _is_url(text) else None


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
API_FORMATS = ("NGSI-LD", "WEBSOCKET", "MCP", "OGCFEAT", "ODATA", "STA")
DATA_ORDER = ("CSV", "GEOJSON", "JSON", "XLSX", "PARQUET", "ZIP")


# What an address of the platform is, read from its path under `/api/endpoint/{slug}/` (T-4333):
# the format a harvest wrote has been wrong (JSON-LD for NGSI-LD, JSON for MCP and WebSocket),
# the path never is. A file the Endpoint renders is `file.{ext}`; the model is under `schema/`.
_ENDPOINT_PATH = re.compile(r"^/api/endpoint/[^/]+/(.*)$")
_KIND_PREFIXES = (("ngsi-ld/", "NGSI-LD"), ("odata/", "ODATA"), ("ogc/", "OGCFEAT"), ("sta/", "STA"),
                  ("schema/", "MODEL"))
# An Endpoint's door by its kind: product names, the same on a page in any language (T-4333).
DOOR_NAMES = {"NGSI-LD": "NGSI-LD API", "WEBSOCKET": "WebSocket", "MCP": "Model Context Protocol",
              "OGCFEAT": "OGC API - Features", "ODATA": "OData v4", "STA": "SensorThings API",
              "CSV": "CSV", "JSON": "JSON", "GEOJSON": "GeoJSON", "XLSX": "Excel", "PARQUET": "Apache Parquet"}
# The format as a reader reads it, on a chip and in the facts list.
KIND_LABELS = {"NGSI-LD": "NGSI-LD", "WEBSOCKET": "WebSocket", "MCP": "MCP", "OGCFEAT": "OGC API",
               "ODATA": "OData", "STA": "SensorThings", "CSV": "CSV", "JSON": "JSON",
               "GEOJSON": "GeoJSON", "XLSX": "Excel", "PARQUET": "Parquet"}


def _split(resource):
    """The resource's address in parts and its path below the Endpoint, or None off the platform."""
    url = (resource or {}).get("url") or ""
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    match = _ENDPOINT_PATH.match(parts.path or "")
    if parts.scheme not in ("http", "https", "ws", "wss") or not parts.netloc or not match:
        return None
    return parts, match.group(1)


def jc_kind(resource):
    """NGSI-LD, MCP, WEBSOCKET, ODATA, OGCFEAT, STA, MODEL, or a file's CSV, JSON, GEOJSON, XLSX or PARQUET
    for an Endpoint's address; None for anything else."""
    split = _split(resource)
    if not split:
        return None
    rest = split[1].rstrip("/")
    for prefix, kind in _KIND_PREFIXES:
        if rest.startswith(prefix) or rest == prefix.rstrip("/"):
            return kind
    if rest in ("mcp", "ws"):
        return "MCP" if rest == "mcp" else "WEBSOCKET"
    match = re.fullmatch(r"file\.(csv|json|geojson|xlsx|parquet)", rest)
    return match.group(1).upper() if match else None


def jc_is_source(resource, pkg):
    """Whether a resource is the harvest's link to the publisher's own page, named after the
    dataset (T-4333): it is opened there, never downloaded."""
    title = ((pkg or {}).get("title") or "").strip()
    return bool(title) and _off_platform(resource) and ((resource or {}).get("name") or "").strip() == title


def _section(resource):
    url = resource.get("url") or ""
    path = url.split("?", 1)[0]
    kind = jc_kind(resource)
    if kind == "MODEL" or "/schema/" in path:
        return "schema"
    if kind:
        return "api" if kind in API_FORMATS else "data"
    if (resource.get("format") or "").strip().upper() in API_FORMATS:
        return "api"
    return "data"


def _order(resource):
    """The DataStore table first (it is the data a reader came for), then files by format."""
    kind = jc_kind(resource)
    name = kind if kind and kind != "MODEL" else (resource.get("format") or "").strip().upper()
    known = DATA_ORDER.index(name) if name in DATA_ORDER else len(DATA_ORDER)
    api = API_FORMATS.index(name) if name in API_FORMATS else len(API_FORMATS)
    return (not resource.get("datastore_active"), known, api, name, resource.get("name") or "")


def jc_is_api(resource):
    """Whether a resource is an address a program calls rather than a file (T-3887)."""
    return _section(resource or {}) == "api"


# An address in a usage text, and a credential where `$TOKEN` belongs: a bearer value or a JWT.
_ADDRESS = re.compile(r"\b(?:https?|wss?)://([^/\s'\"<>`]+)")
_CREDENTIAL = re.compile(
    r"(?i)(?:bearer[ .]+(?!\$TOKEN\b)[A-Za-z0-9._~+/=-]{16,}|\beyJ[A-Za-z0-9_-]{8,}\.)")


def _docs_base():
    """The installation's documentation, from branding `documentationBaseUrl`: https only."""
    base = BRANDING.get("documentationBaseUrl")
    if not (isinstance(base, str) and base.startswith("https://") and _is_url(base)) \
            or re.search(r"[\s\"'<>]", base):
        return None
    return base.rstrip("/")


def _shown(text):
    """Whether a usage block may reach the page: every address it names is on the platform's
    domain or the documentation's host, and it carries no credential (T-3887, EP-110). The text is
    the publisher's, and a page must never show an internal service address or a token."""
    if _CREDENTIAL.search(text):
        return False
    domain = BRANDING.get("domain") or ""
    docs = _docs_base()
    docs_host = docs[len("https://"):].split("/", 1)[0] if docs else None
    for host in _ADDRESS.findall(text):
        on_platform = domain and (host == domain or host.endswith("." + domain))
        if not (on_platform or host == docs_host):
            return False
    return True


def jc_usage(resource):
    """An API resource's usage description as blocks for the page (T-3887, EP-108): paragraphs,
    and the indented code `jcctl` writes as fields with a copy button. A block that names a
    foreign address or holds a credential is left out; anything but an API resource has none."""
    resource = resource or {}
    text = resource.get("description")
    if not jc_is_api(resource) or not isinstance(text, str):
        return []
    key = re.sub(r"[^A-Za-z0-9_-]", "", str(resource.get("id") or "")) or "resource"
    blocks = []
    for number, chunk in enumerate(re.split(r"\n[ \t]*\n", text.strip("\n"))):
        lines = chunk.split("\n")
        code = all(line.startswith("    ") for line in lines if line.strip())
        body = "\n".join(line[4:] for line in lines) if code else " ".join(line.strip() for line in lines)
        if body.strip() and _shown(body):
            blocks.append({"code": code, "text": body, "id": "jc-use-%s-%d" % (key, number)})
    return blocks


def jc_guide(resource):
    """The WebSocket guide (API/07) for a WebSocket resource, when the installation names its
    documentation; None otherwise (T-3887)."""
    base = _docs_base()
    if base and ((resource or {}).get("format") or "").strip().upper() == "WEBSOCKET":
        return base + "/API/07-websocket"
    return None


def jc_resource_sections(pkg):
    """The resources in three sections, data, APIs and the data model, each in reading order
    and each resource with its one-line "what is this". Empty sections are left out."""
    sections = {"data": [], "api": [], "schema": [], "source": []}
    for resource in sorted((pkg or {}).get("resources") or [], key=_order):
        kind = jc_kind(resource)
        name = KIND_LABELS.get(kind) or (resource.get("format") or "").strip()
        words = FORMATS.get(kind or name.upper()) or {}
        if resource.get("datastore_active"):
            # A DataStore table downloads as CSV, whatever format its resource names (T-3012
            # writes its tables with none).
            name = name or "CSV"
            words = STRINGS["table_what"]
        sections["source" if jc_is_source(resource, pkg) else _section(resource)].append({
            "resource": resource,
            "format": name or "—",
            "what": words.get(_language()) or words.get("en") or "",
        })
    return [{"key": key, "title": jc_t("section_" + key), "lead": jc_t("section_" + key + "_lead"),
             "items": items} for key, items in sections.items() if items]


# The data model's files as `jcctl` publishes them (crates/jcctl/src/publish/ckan.rs): the
# dataset's name, a space and the file. A reader sees what each one is instead (T-3048), named
# once the "Data model" group around them has said what they belong to (T-4333).
MODEL_FILES = {
    "context.jsonld": {"en": "JSON-LD context", "sk": "Kontext JSON-LD", "cs": "Kontext JSON-LD", "de": "JSON-LD-Kontext"},
    "model.linkml.yaml": {"en": "LinkML", "sk": "LinkML", "cs": "LinkML", "de": "LinkML"},
    "model.md": {"en": "Described in words", "sk": "Popis slovami", "cs": "Popis slovy", "de": "In Worten beschrieben"},
    "model.owl.ttl": {"en": "OWL", "sk": "OWL", "cs": "OWL", "de": "OWL"},
    "model.rdf.ttl": {"en": "RDF", "sk": "RDF", "cs": "RDF", "de": "RDF"},
    "model.schema.json": {"en": "JSON Schema", "sk": "JSON Schema", "cs": "JSON Schema", "de": "JSON Schema"},
    "index.json": {"en": "List of its files", "sk": "Zoznam súborov", "cs": "Seznam souborů", "de": "Liste der Dateien"},
    "model.shacl.ttl": {"en": "Validation rules", "sk": "Pravidlá kontroly", "cs": "Pravidla kontroly", "de": "Prüfregeln"},
}


def jc_resource_label(resource, pkg=None):
    """A resource's name as a reader reads it: a data model file in words, any other name
    without the dataset's own name in front of it, and the name as it is when that leaves nothing."""
    name = ((resource or {}).get("name") or "").strip()
    prefix = ((pkg or {}).get("name") or "").strip()
    rest = name[len(prefix):].strip() if prefix and name.startswith(prefix + " ") else name
    words = MODEL_FILES.get(rest)
    if jc_kind(resource) == "MODEL":
        # The harvest names a model file in English ("Data model: LinkML"); its file name says
        # which one it is in any language (T-4333).
        words = MODEL_FILES.get(((resource or {}).get("url") or "").split("?", 1)[0].rsplit("/", 1)[-1]) or words
    if words:
        return words.get(_language()) or words["en"]
    kind = jc_kind(resource)
    if kind in ("CSV", "JSON", "GEOJSON", "XLSX", "PARQUET") or kind == "WEBSOCKET":
        # The chip already says the format: the name says what is inside and what for, so the
        # platform's files never read as twins of each other (T-4333).
        return jc_t("records_" + kind.lower() if kind != "WEBSOCKET" else "live_changes")
    if kind in DOOR_NAMES:
        # An Endpoint's door is named by what it is, in words every language shares, with its
        # entity type once in the page header instead of on every entry: the harvest wrote
        # "NGSI-LD API (StatisticalObservation)", jcctl "Live updates over WebSocket" (T-4333).
        return DOOR_NAMES[kind]
    elif (resource or {}).get("datastore_active") and pkg and rest.startswith((pkg.get("title") or "\0").strip() + " ("):
        # A harvested table is named "{dataset} (tabuľka)", in Slovak on every page (T-4333).
        return jc_t("original_table")
    elif jc_is_source(resource, pkg):
        # The harvest names the publisher's own page after the dataset, so it read as a twin of
        # the table (T-4333).
        return jc_t("at_publisher")
    return rest or name or (resource or {}).get("format") or (resource or {}).get("id") or ""


def _off_platform(resource):
    """Whether a resource is a link to somewhere other than the platform and this catalogue."""
    resource = resource or {}
    if resource.get("datastore_active") or resource.get("url_type") == "upload":
        return False
    try:
        host = urlsplit(resource.get("url") or "").hostname or ""
    except ValueError:
        return False
    domain = BRANDING.get("domain") or ""
    return bool(host) and not (domain and (host == domain or host.endswith("." + domain)))


def jc_entity_type(resource):
    """The entity type an Endpoint's address reads: its `type` query, or the type in an OData
    or OGC API path. None when it names none."""
    split = _split(resource)
    if not split:
        return None
    parts, rest = split
    found = parse_qs(parts.query).get("type")
    if found and found[0]:
        return found[0]
    match = re.match(r"^(?:odata/v4|ogc/features/collections|sta/v1\.1)/([^/?]+)", rest)
    if match:
        return match.group(1)
    # MCP and WebSocket read every type of the Endpoint; the harvest names the dataset's in
    # parentheses after the door ("WebSocket (StatisticalObservation)").
    named = re.search(r"\(([A-Za-z][A-Za-z0-9_]*)\)$", ((resource or {}).get("name") or "").strip())
    return named.group(1) if named else None


def _filtered(resource):
    """Whether the address keeps only this dataset's rows: the harvest's `q=isPartOf==...`, OGC API
    Features' `isPartOf=...` or OData's `$filter=isPartOf eq ...` (T-4289)."""
    split = _split(resource)
    if not split:
        return False
    query = parse_qs(split[0].query)
    return ("isPartOf" in query or any("isPartOf==" in q for q in query.get("q", []))
            or any(f.startswith("isPartOf eq ") for f in query.get("$filter", [])))


def jc_what(resource):
    """One line, in the page's language, of what this resource is, and for an Endpoint's address
    whose rows it holds (T-4333): the harvest's English sentence never reaches the page."""
    kind = jc_kind(resource)
    words = FORMATS.get(kind or ((resource or {}).get("format") or "").strip().upper()) or {}
    line = words.get(_language()) or words.get("en") or ""
    kind_type = jc_entity_type(resource)
    if kind and kind != "MODEL" and kind_type:
        scope = jc_t("scope_dataset") if _filtered(resource) else jc_t("scope_type").replace("{type}", kind_type)
        line = (line + ". " if line else "") + scope
    return line if not line or line.endswith((".", "…")) else line + "."


def jc_format(resource):
    """The format a reader is shown: the kind of an Endpoint's address, CSV for a DataStore
    table, the format the resource names otherwise."""
    resource = resource or {}
    kind = jc_kind(resource)
    if kind in KIND_LABELS:
        return KIND_LABELS[kind]
    name = (resource.get("format") or "").strip()
    return name or ("CSV" if resource.get("datastore_active") else "")


def jc_address(resource):
    """The address as a person reads it (T-4333): host and path, the Endpoint's 32-character
    slug shortened, without the query a program needs; the whole address stays beside it."""
    split = _split(resource)
    url = (resource or {}).get("url") or ""
    if not split:
        return {"short": url, "full": url}
    parts, rest = split
    slug = parts.path[len("/api/endpoint/"):].split("/", 1)[0]
    short_slug = slug if len(slug) <= 10 else slug[:6] + "\u2026"
    short = "%s/api/endpoint/%s/%s" % (parts.netloc, short_slug, rest)
    # The page breaks it only after a slash, never inside a segment such as "ngsi-ld" (T-4333).
    return {"short": short, "segments": short.split("/"), "full": url}


def jc_pieces(text):
    """A command or address in the pieces a line may break between (T-4333): the spaces as they
    are, every other run cut after a slash, "?" or "&", so a line never breaks inside a word, a
    host, an id or "ngsi-ld". The page keeps each piece whole and scrolls one longer than a line."""
    pieces = []
    for token in re.split(r"(\s+)", str(text or "")):
        if not token:
            continue
        if token.isspace():
            pieces.append({"text": token, "space": True})
        else:
            pieces.extend({"text": part, "space": False} for part in re.findall(r"[^/?&]*(?:/+|[?&])|[^/?&]+", token))
    return pieces


def _with(url, **params):
    """The address with these query parameters set, the others kept in order."""
    parts = urlsplit(url)
    query = [(k, v) for k, values in parse_qs(parts.query, keep_blank_values=True).items()
             if k not in params for v in values]
    query += list(params.items())
    return urlunsplit(parts._replace(query=urlencode(query, quote_via=quote, safe="$")))


def jc_preview(resource):
    """The address the page's script fetches for its live preview (T-4333): five rows, read
    anonymously by the reader's browser from an https address of the platform. None for a kind
    without rows to show (MCP, WebSocket, a file) or an address elsewhere."""
    kind = jc_kind(resource)
    url = (resource or {}).get("url") or ""
    domain = BRANDING.get("domain") or ""
    host = urlsplit(url).hostname or "" if url else ""
    if not (url.startswith("https://") and domain and (host == domain or host.endswith("." + domain))):
        return None
    path = urlsplit(url).path
    if kind == "NGSI-LD" and "/entities" in path:
        return {"url": _with(url, limit="5", options="keyValues", count="true"), "kind": kind}
    if kind == "NGSI-LD":
        # The API itself, without a type: what it holds is its list of types.
        return {"url": url.split("?", 1)[0].rstrip("/") + "/types", "kind": "NGSI-LD-TYPES"}
    if kind in ("ODATA", "STA") and jc_entity_type(resource):
        return {"url": _with(url, **{"$top": "5"}), "kind": kind}
    if kind == "OGCFEAT" and path.rstrip("/").endswith("/items"):
        return {"url": _with(url, limit="5"), "kind": kind}
    return None


def jc_examples(resource):
    """How to use an Endpoint's address, in the page's language (T-4333): each a title, the
    steps in words and the command to copy. A non-public address carries `$TOKEN` in its
    description, so its commands send the header with it."""
    resource = resource or {}
    kind = jc_kind(resource)
    url = resource.get("url") or ""
    if not kind or kind == "MODEL" or not url:
        return []
    token = "$TOKEN" in (resource.get("description") or "")
    auth = ' -H "Authorization: Bearer $TOKEN"' if token else ""
    key = re.sub(r"[^A-Za-z0-9_-]", "", str(resource.get("id") or "")) or "resource"
    kind_type = jc_entity_type(resource) or ""
    out = []

    def add(title, code=None, steps=()):
        out.append({"title": title, "steps": list(steps), "code": code,
                    "id": "jc-ex-%s-%d" % (key, len(out))})

    if kind == "NGSI-LD" and "/entities" not in urlsplit(url).path:
        add(jc_t("ex_types"), "curl%s -H 'Accept: application/ld+json' '%s'" % (auth, url.split("?", 1)[0].rstrip("/") + "/types"))
    elif kind == "NGSI-LD":
        add(jc_t("ex_first"), "curl%s -H 'Accept: application/ld+json' '%s'" % (auth, _with(url, limit="5")))
    elif kind in ("ODATA", "STA"):
        add(jc_t("ex_first"), "curl%s '%s'" % (auth, _with(url, **{"$top": "5"})))
        if kind == "ODATA":
            add(jc_t("ex_excel"), url)
    elif kind == "OGCFEAT":
        add(jc_t("ex_first"), "curl%s '%s'" % (auth, _with(url, limit="5")))
        add(jc_t("ex_qgis"), url.split("/collections/", 1)[0] + "/")
    elif kind == "MCP":
        add(jc_t("mcp_claude_ai"), url, [jc_t("mcp_claude_ai_1"), jc_t("mcp_claude_ai_2")])
        add(jc_t("ex_chatgpt_title"), url, [jc_t("ex_chatgpt")])
        add(jc_t("mcp_claude"), "claude mcp add --transport http joinedcontext %s" % url)
    elif kind == "WEBSOCKET":
        body = {"type": "Subscription"}
        body["entities" if kind_type else "watchedAttributes"] = [{"type": kind_type}] if kind_type else ["location"]
        message = json.dumps({"metadata": {"x-op": "x-subscribe", "x-id": "s1"}, "body": body},
                             separators=(",", ":"), ensure_ascii=False)
        add(jc_t("ex_ws"), "websocat --protocol ngsi-ld-ws%s '%s'\n%s" % (auth, url, message))
    elif kind in ("CSV", "JSON", "GEOJSON", "XLSX", "PARQUET"):
        name = "data." + kind.lower()
        add(jc_t("ex_file"), "curl%s -L -o %s '%s'" % (auth, name, url))
    return out


# The standards a distribution names in `conforms_to`, as a reader knows them.
STANDARDS = (
    ("etsi.org/deliver/etsi_gs/cim", "ETSI NGSI-LD (GS CIM 009)"),
    ("ogcapi-features", "OGC API - Features"),
    ("odata", "OData v4"),
    ("modelcontextprotocol", "Model Context Protocol"),
    ("rfc7946", "GeoJSON (RFC 7946)"),
    ("rfc4180", "CSV (RFC 4180)"),
    ("rfc8259", "JSON (RFC 8259)"),
    ("smart-data-models", "Smart Data Models"),
    ("w3.org/tr/json-ld11", "JSON-LD 1.1"),
    ("w3.org/tr/vocab-dcat", "DCAT"),
    ("smartdatamodels", "Smart Data Models"),
)


# The standard each kind of door follows, when the resource names none (jcctl's do not).
KIND_STANDARDS = {"CSV": "https://www.rfc-editor.org/rfc/rfc4180", "GEOJSON": "https://www.rfc-editor.org/rfc/rfc7946",
                  "JSON": "https://www.rfc-editor.org/rfc/rfc8259",
                  "NGSI-LD": "https://www.etsi.org/deliver/etsi_gs/CIM/001_099/009/",
                  "OGCFEAT": "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/core",
                  "ODATA": "https://docs.oasis-open.org/odata/odata/v4.01/",
                  "MCP": "https://modelcontextprotocol.io/specification"}


def jc_standard(resource):
    """The standard a distribution follows, named, with its address; a file the platform renders
    follows its format's RFC. None when it names none or a value that is not an http address."""
    url = ((resource or {}).get("conforms_to") or "").strip() or KIND_STANDARDS.get(jc_kind(resource), "")
    if not _is_url(url):
        return None
    name = next((label for needle, label in STANDARDS if needle in url.lower()), url)
    return {"url": url, "name": name}


def jc_model(pkg):
    """The dataset's data model for a resource page (T-4333): the Smart Data Model a resource
    names, else the published JSON Schema, else None."""
    resources = (pkg or {}).get("resources") or []
    for resource in resources:
        standard = jc_standard(resource)
        if standard and standard["name"] == "Smart Data Models":
            return {"url": standard["url"], "name": "Smart Data Model"}
    for resource in resources:
        url = (resource.get("url") or "").split("?", 1)[0]
        if _section(resource) == "schema" and url.endswith("schema.json"):
            return {"url": resource["url"], "name": jc_resource_label(resource, pkg)}
    return None


def jc_dates(resource):
    """When the resource was updated, and when it was created only on another day (T-4333):
    three rows of one date said nothing three times."""
    resource = resource or {}
    updated = resource.get("last_modified") or resource.get("metadata_modified") or resource.get("created")
    rows = []
    if updated:
        rows.append((jc_t("updated"), toolkit.h.render_datetime(updated)))
    created = resource.get("created")
    if created and (not updated or str(created)[:10] != str(updated)[:10]):
        rows.append((jc_t("created"), toolkit.h.render_datetime(created)))
    return rows


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


def jc_rows(value):
    """A row count with its word in the page's language: "1 row", "3 riadky", "5 řádků"."""
    number = jc_number(value)
    if not number:
        return ""
    count = abs(int(value))
    words = STRINGS["rows"].get(_language()) or STRINGS["rows"]["en"]
    form = 0 if count == 1 else 1 if 2 <= count <= 4 else 2
    return "%s %s" % (number, words[form])


def jc_recent(limit=6):
    """The public datasets changed last, for the home page."""
    from ckan.lib.search import SearchError

    try:
        found = toolkit.get_action("package_search")(
            {}, {"rows": limit, "sort": "metadata_modified desc", "fq": 'capacity:"public"'})
    except SearchError:
        return []
    return found.get("results") or []


def jc_has_topics():
    """Whether the catalogue has a topic at all (T-4217): the navigation's Topics and a
    dataset's Topics tab led to "There are currently no groups for this site." until one did."""
    try:
        return bool(toolkit.get_action("group_list")({}, {"limit": 1}))
    except (toolkit.NotAuthorized, toolkit.ObjectNotFound):
        return False


HYPHENATED = re.compile(r"^\w+(?:-\w+)+$")


# The endings Slovak and Czech nouns and adjectives decline through, longest first (T-4239).
SLAVIC_ENDINGS = ("iach", "ách", "ami", "ých", "ými", "ého", "ému", "ia", "ie", "ii", "iu", "ej",
                  "om", "ov", "ou", "ím", "ým", "a", "á", "e", "é", "ě", "i", "í", "o", "u", "ú", "y", "ý")


def jc_stem(word):
    """`(word OR stem*)` for a word of four letters or more, else the word (T-4239, T-4387). The
    catalogue's Solr stems in English, so "ovzdušie" missed every "ovzdušia". Any word, since a
    visitor types Slovak without its letters ("ovzdusie") and Solr folds them on both sides; a word
    with no ending is its own stem, so the singular finds the plural ("most", "mosty"). The stem
    keeps four letters at least."""
    if not word.isalpha() or len(word) < 4:
        return word
    for ending in SLAVIC_ENDINGS:
        if word.lower().endswith(ending) and len(word) - len(ending) >= 4:
            return "(%s OR %s*)" % (word, word[: -len(ending)])
    return "(%s OR %s*)" % (word, word)


def jc_search_words(q):
    """The visitor's search with each hyphenated word as a phrase (T-4218) and each Slovak or
    Czech word open to its other endings (T-4239). Solr split `bike-sharing` into parts it OR'ed,
    so the word found everything about either part. A query with its own quotes or a field
    (`tags:x`) is the visitor's syntax and goes as typed."""
    if not q or '"' in q or ":" in q:
        return q
    return " ".join('"%s"' % word if HYPHENATED.match(word) else jc_stem(word) for word in q.split())


# CKAN's words for its organizations and groups, where a visitor reads them (T-4220): the
# navigation said Publishers and Topics, the breadcrumb, the title and the search box
# Organizations and Groups. Every other purpose is a staff form and keeps CKAN's word.
HUMANIZE = {
    "breadcrumb": "nav_%s", "page title": "nav_%s", "main nav": "nav_%s",
    "facet label": "nav_%s", "search placeholder": "search_%s",
}
HUMANIZED = {"organization": "publishers", "group": "topics"}


@toolkit.chained_helper
def humanize_entity_type(next_helper, entity_type, object_type, purpose):
    if entity_type == object_type and entity_type in HUMANIZED and purpose in HUMANIZE:
        return jc_t(HUMANIZE[purpose] % HUMANIZED[entity_type])
    return next_helper(entity_type, object_type, purpose)


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


_HOST = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")
MCP_NAME = "joinedcontext"


def jc_mcp_install():
    """The "Connect an AI assistant" panel (T-4114, EP-113): the installation's MCP hub and one
    ready line per client, or None without a valid domain. Every line names the hub alone, never a
    dataset, a token or a key, so one installation serves the whole catalogue (EP-110)."""
    domain = BRANDING.get("domain")
    if not (isinstance(domain, str) and _HOST.match(domain)):
        return None
    url = "https://%s/api/mcp" % domain
    server = {"type": "http", "url": url}
    vscode = json.dumps(dict(name=MCP_NAME, **server), separators=(",", ":"))
    cursor = base64.b64encode(json.dumps({"url": url}, separators=(",", ":")).encode()).decode()
    return {
        "url": url,
        # Where the address may break in a narrow card: before each single slash, never inside
        # a word (T-4284). The template joins the parts with <wbr>; a copy reads them as one.
        "url_parts": re.split(r"(?<=[^/])(?=/(?!/))", url),
        # One argument per line, so a narrow card never breaks the command mid-flag (T-4284).
        "claude": "claude mcp add --transport http \\\n  %s \\\n  %s" % (MCP_NAME, url),
        # Valid JSON laid out for a phone's card: the address alone on its line, so no line is
        # wider than the address itself (T-4284).
        "json": '{"mcpServers": {%s: {\n  "type": "http",\n  "url":\n  %s\n}}}' % (json.dumps(MCP_NAME), json.dumps(url)),
        "vscode": "vscode:mcp/install?" + quote(vscode, safe=""),
        "cursor": "cursor://anysphere.cursor-deeplink/mcp/install?name=%s&config=%s" % (MCP_NAME, quote(cursor, safe="")),
    }


CHATGPT_PLUGINS = "https://chatgpt.com/plugins"
CLAUDE_CONNECTORS = "https://claude.ai/customize/connectors"


def jc_assistants():
    """The "Use it in your AI assistant" page (T-4585, T-4628): a card per assistant, ChatGPT,
    Claude, Gemini, Grok, in that order, each its logo, its name and at most one link, to its
    connector store; None without the hub. An assistant whose app takes no connectors today has
    no link (`soon`), never a dead one. The hub's address stands once under the cards, because our
    connector is not listed in either store yet; the Gemini CLI command goes to the developers'
    fold with the editors.

    `logo` is the card's mark in its brand colours, a template beside this file."""
    mcp = jc_mcp_install()
    if not mcp:
        return None
    name = BRANDING.get("instanceName") or MCP_NAME

    def card(id, title, store=None):
        found = {"id": id, "name": title, "logo": "jc/card-%s.svg" % id}
        if store:
            found.update(open=store, open_label=jc_t("add_to").replace("{name}", title))
        else:
            found["soon"] = True
        return found

    return {
        "lead": jc_t("assistants_lead").replace("{name}", name),
        "mcp": mcp,
        "cards": [card("chatgpt", "ChatGPT", CHATGPT_PLUGINS), card("claude", "Claude", CLAUDE_CONNECTORS),
                  card("gemini", "Gemini"), card("grok", "Grok")],
        "gemini": "gemini mcp add --transport http %s %s" % (MCP_NAME, mcp["url"]),
    }


# The connector's public pages (T-4315): what a directory reviewer and a visitor read before
# adding the MCP hub to Claude or ChatGPT. Every fact is the deployment's own: no account or
# cookie on the hub, the edge's per-IP limit held in memory, logs on container stdout only and no
# retention period configured, so none is promised. `{url}` is the hub, `{domain}` the
# installation's; a paragraph naming `{url}` is left out on an installation without a domain.
PAGES = {
    "connector": {
        "en": {"title": "MCP connector", "sections": [
            ("", ["Ask an AI assistant about this catalogue's open data: air quality now, hospitals in the "
                  "region, a city's contracts. The connector is an MCP server at {url}. It needs no account "
                  "and only reads."]),
            ("What it can do", ["list_endpoints finds the datasets; list_types, get_type and describe_schema "
                                "read their data models; query_entities and get_entity read the current rows; "
                                "query_temporal and retrieve_temporal read their history; describe_access says "
                                "what a call may read.",
                                "Every tool reads. A tool that would write is refused without a sign-in."])
        ]},
        "sk": {"title": "MCP konektor", "sections": [
            ("", ["Pýtajte sa AI asistenta na otvorené dáta tohto katalógu: aktuálnu kvalitu ovzdušia, "
                  "nemocnice v kraji, zmluvy mesta. Konektor je MCP server na adrese {url}. Netreba účet "
                  "a iba číta."]),
            ("Čo dokáže", ["list_endpoints nájde datasety; list_types, get_type a describe_schema prečítajú "
                           "ich dátové modely; query_entities a get_entity čítajú aktuálne záznamy; "
                           "query_temporal a retrieve_temporal ich históriu; describe_access povie, čo smie "
                           "volanie čítať.",
                           "Každý nástroj iba číta. Nástroj, ktorý by zapisoval, bez prihlásenia odmietne."])
        ]},
    },
    "privacy": {
        "en": {"title": "Privacy", "sections": [
            ("", ["This page covers the MCP connector at {url}."]),
            ("No account, no cookie", ["The connector answers without an account. It sets no cookie and "
                                       "keeps no profile of you."]),
            ("What reaches us", ["Each call's address, the tool, its arguments and your IP address. The edge "
                                 "counts anonymous calls per IP address to limit their rate; the counter lives "
                                 "in memory for one time window and is not stored.",
                                 "The services write each request to their container log on the server, which "
                                 "the server rotates. We do not archive these logs and send them to no "
                                 "analytics or advertising service."]),
            ("Your assistant", ["What you type stays with the assistant you use, such as Claude or ChatGPT; "
                                "the connector receives only the tool calls it makes. That provider's privacy "
                                "policy covers what you type."]),
            ("The data", ["The connector serves only datasets their publishers released as open data."]),
        ]},
        "sk": {"title": "Ochrana súkromia", "sections": [
            ("", ["Táto stránka sa týka MCP konektora na adrese {url}."]),
            ("Bez účtu, bez cookies", ["Konektor odpovedá bez účtu. Nenastavuje žiadne cookie a nevedie "
                                       "o vás žiadny profil."]),
            ("Čo k nám príde", ["Adresa každého volania, nástroj, jeho argumenty a vaša IP adresa. Brána "
                                "počíta anonymné volania podľa IP adresy, aby obmedzila ich frekvenciu; "
                                "počítadlo žije v pamäti počas jedného časového okna a neukladá sa.",
                                "Služby zapisujú každú požiadavku do logu svojho kontajnera na serveri, "
                                "ktorý server rotuje. Tieto logy nearchivujeme a neposielame ich žiadnej "
                                "analytickej ani reklamnej službe."]),
            ("Váš asistent", ["Čo napíšete, zostáva u asistenta, ktorého používate, napríklad Claude alebo "
                              "ChatGPT; konektor dostane iba volania nástrojov, ktoré asistent urobí. Na to, "
                              "čo napíšete, sa vzťahujú zásady ochrany súkromia toho poskytovateľa."]),
            ("Dáta", ["Konektor poskytuje iba datasety, ktoré ich vydavatelia zverejnili ako otvorené dáta."]),
        ]},
    },
    "terms": {
        "en": {"title": "Terms of use", "sections": [
            ("Licences", ["Each dataset names its licence on its catalogue page, and that licence governs its "
                          "reuse. Under Creative Commons Attribution (CC BY) you may copy and reuse the data "
                          "when you name the publisher."]),
            ("Read only", ["The connector never changes data. Tools that would write are refused without a "
                           "sign-in."]),
            ("As is", ["{domain} runs as a development service. It can be slow, change or pause without "
                       "notice, and we give no warranty that the data is complete or current. Check the "
                       "publisher's source before you rely on a number."]),
            ("Fair use", ["Calls are limited per IP address. Do not try to get around the limit or to reach "
                          "data that is not public."]),
        ]},
        "sk": {"title": "Podmienky používania", "sections": [
            ("Licencie", ["Každý dataset uvádza svoju licenciu na svojej stránke v katalógu a tá určuje, ako "
                          "ho smiete použiť. Pri Creative Commons Attribution (CC BY) smiete dáta kopírovať "
                          "a ďalej používať, ak uvediete vydavateľa."]),
            ("Iba čítanie", ["Konektor dáta nikdy nemení. Nástroje, ktoré by zapisovali, bez prihlásenia "
                             "odmietne."]),
            ("Bez záruky", ["{domain} beží ako vývojová služba. Môže byť pomalá, zmeniť sa alebo prerušiť bez "
                            "ohlásenia a neručíme za úplnosť ani aktuálnosť dát. Skôr než sa spoľahnete na "
                            "číslo, overte ho u vydavateľa."]),
            ("Férové používanie", ["Počet volaní je obmedzený podľa IP adresy. Neobchádzajte limit a "
                                   "nesnažte sa dostať k dátam, ktoré nie sú verejné."]),
        ]},
    },
    "support": {
        "en": {"title": "Support", "sections": [
            ("", ["Write to us when the connector fails or a number looks wrong. Name the dataset or the "
                  "tool, the question you asked and the time.",
                  "A wrong number in a dataset: tell its publisher too, named on the dataset page."]),
        ]},
        "sk": {"title": "Podpora", "sections": [
            ("", ["Napíšte nám, keď konektor zlyhá alebo číslo nesedí. Uveďte dataset alebo nástroj, otázku, "
                  "ktorú ste položili, a čas.",
                  "Chybné číslo v datasete: oznámte ho aj jeho vydavateľovi, uvedenému na stránke datasetu."]),
        ]},
    },
}


def jc_page(name):
    """One of the connector's pages in the page's language, English when there is none; None for
    a name that is not one. The hub, the domain and the contact come from the branding block."""
    words = PAGES.get(name)
    if not words:
        return None
    words = words.get(_language()) or words["en"]
    mcp = jc_mcp_install()
    domain = BRANDING.get("domain") if mcp else None
    email = BRANDING.get("contactEmail") or ""
    sections = []
    for heading, paragraphs in words["sections"]:
        kept = [p.format(url=mcp["url"], domain=domain) if mcp else p
                for p in paragraphs if mcp or ("{url}" not in p and "{domain}" not in p)]
        if kept:
            sections.append({"heading": heading, "paragraphs": kept})
    # The connector's questions are the instance's own, about its own publishers (T-4636).
    samples = _samples(_language()) if name == "connector" else []
    if samples:
        sections.append({"heading": jc_t("try_it"), "paragraphs": samples})
    return {"name": name, "title": words["title"], "sections": sections,
            "email": email if "@" in email else "", "mcp": mcp, "pages": list(PAGES)}


def jc_portal_url():
    """The Portal of this installation, for staff who signed in; None without a domain."""
    domain = BRANDING.get("domain")
    return "https://portal.%s/" % domain if domain else None


ASSISTANT_WIDGET = os.environ.get("JC_ASSISTANT_WIDGET_URL", "")
PUBLIC_ID = r"[a-z0-9](?:[-a-z0-9]{0,61}[a-z0-9])?"


def _widgets():
    """Each CKAN organization's own widget address (T-4281); empty when unset or unreadable."""
    try:
        found = json.loads(os.environ.get("JC_ASSISTANT_WIDGET_URLS") or "{}")
    except ValueError:
        return {}
    return {k: v for k, v in found.items() if isinstance(k, str) and isinstance(v, str)} if isinstance(found, dict) else {}


ASSISTANT_WIDGETS = _widgets()


def jc_assistant_widget(organization=None):
    """The knowledge assistant's widget page on this installation's assistant host (AG-114): the
    publisher's own when `organization` has one (T-4281), else the catalogue's; None when there
    is none, or when the address names any other host or path."""
    domain = BRANDING.get("domain")
    widget = ASSISTANT_WIDGETS.get(organization or "") or ASSISTANT_WIDGET
    if not domain or not widget:
        return None
    pattern = r"https://assistant\.%s/d/%s/widget" % (re.escape(domain), PUBLIC_ID)
    return widget if re.fullmatch(pattern, widget) else None


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


# Word's Symbol font writes bullets as private-use code points (U+F0B7 and kin); a page without
# that font draws a box ("□ Druh □" on data.dev, T-4283). Publishers' descriptions arrive with
# them, so the catalogue maps the common ones and drops any other private-use character.
SYMBOL_GLYPHS = {"\uf0b7": "•", "\uf0a7": "▪", "\uf0a8": "◦", "\uf0d8": "›", "\uf0fc": "✓", "\uf076": "❖"}
PRIVATE_USE = re.compile("[\ue000-\uf8ff]")


def jc_plain_glyphs(text):
    """The text with Symbol-font bullets as real ones and no other private-use character."""
    if not isinstance(text, str):
        return text
    return PRIVATE_USE.sub(lambda m: SYMBOL_GLYPHS.get(m.group(), ""), text)


def jc_clean_dataset(pkg):
    """A dataset's words, and its resources', without glyphs no font draws."""
    for key in ("title", "notes"):
        if key in pkg:
            pkg[key] = jc_plain_glyphs(pkg[key])
    for resource in pkg.get("resources") or []:
        for key in ("name", "description"):
            if key in resource:
                resource[key] = jc_plain_glyphs(resource[key])
    return pkg


class JcThemePlugin(plugins.SingletonPlugin):
    plugins.implements(plugins.IConfigurer)
    plugins.implements(plugins.ITemplateHelpers)
    plugins.implements(plugins.IFacets, inherit=True)
    plugins.implements(plugins.IPackageController, inherit=True)
    plugins.implements(plugins.IBlueprint)

    def update_config(self, config):
        toolkit.add_template_directory(config, "templates")
        # The logo is a file beside this package, so CKAN serves it from its own origin and
        # no page reaches a third party for an asset.
        toolkit.add_public_directory(config, "public")
        # CKAN keeps one title; the pages ask jc_site_title for the reader's language (T-4636).
        title = jc_site_title((BRANDING.get("languages") or {}).get("default"))
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
            "jc_org": jc_org,
            "jc_t": jc_t,
            "jc_about": jc_about,
            "jc_more": jc_more,
            "jc_live": jc_live,
            "jc_resource_sections": jc_resource_sections,
            "jc_resource_label": jc_resource_label,
            "jc_is_api": jc_is_api,
            "jc_extra": jc_extra,
            "jc_is_source": jc_is_source,
            "jc_kind": jc_kind,
            "jc_entity_type": jc_entity_type,
            "jc_what": jc_what,
            "jc_format": jc_format,
            "jc_address": jc_address,
            "jc_pieces": jc_pieces,
            "jc_preview": jc_preview,
            "jc_examples": jc_examples,
            "jc_standard": jc_standard,
            "jc_model": jc_model,
            "jc_dates": jc_dates,
            "jc_usage": jc_usage,
            "jc_guide": jc_guide,
            "jc_previews": jc_previews,
            "jc_total": jc_total,
            "jc_number": jc_number,
            "jc_rows": jc_rows,
            "jc_formats": jc_formats,
            "jc_recent": jc_recent,
            "jc_portal_url": jc_portal_url,
            "jc_mcp_install": jc_mcp_install,
            "jc_assistants": jc_assistants,
            "jc_page": jc_page,
            "jc_site_title": jc_site_title,
            "jc_site_logo": jc_site_logo,
            "jc_assistant_widget": jc_assistant_widget,
            "jc_about_site": jc_about_site,
            "humanize_entity_type": humanize_entity_type,
            "jc_has_topics": jc_has_topics,
            "jc_sso_error": jc_sso_error,
        }

    def get_blueprint(self):
        """/connector, /privacy, /terms and /support (T-4315), one template for all four, and
        /assistants (T-4585)."""
        from flask import Blueprint

        blueprint = Blueprint("jc_pages", self.__module__)
        for name in PAGES:
            blueprint.add_url_rule("/" + name, name, lambda name=name: toolkit.render("jc/page.html", {"jc_name": name}))
        blueprint.add_url_rule("/assistants", "assistants", lambda: toolkit.render("jc/assistants.html", {}))
        return blueprint

    def before_dataset_search(self, search_params):
        """The hidden packages left out (T-4318), and a hyphenated word searched as the phrase it is and a Slovak or Czech word with its other
        endings, on the page and the API alike. A stem is a prefix query, which CKAN's default
        dismax parser does not take; edismax does, with the same fields and minimum match."""
        jc_hide(search_params)
        q = search_params.get("q")
        if q:
            search_params["q"] = jc_search_words(q)
            if "*)" in search_params["q"] and "*)" not in q:
                search_params.setdefault("defType", "edismax")
        return search_params

    def after_dataset_show(self, context, pkg_dict):
        if pkg_dict.get("name") in HIDDEN and not jc_sees_hidden():
            raise toolkit.ObjectNotFound("Dataset not found")
        jc_clean_dataset(pkg_dict)

    def after_dataset_search(self, search_results, search_params):
        for pkg in search_results.get("results") or []:
            jc_clean_dataset(pkg)
        return search_results

    def dataset_facets(self, facets_dict, package_type):
        """The search filters in plain words: Publisher, Topic, Keywords, Format, Licence."""
        names = {"organization": "publisher", "groups": "topic", "tags": "keywords",
                 "res_format": "format", "license_id": "licence"}
        for field, key in names.items():
            if field in facets_dict:
                facets_dict[field] = jc_t(key)
        return facets_dict
