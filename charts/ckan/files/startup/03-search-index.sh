# Re-index the catalogue once when Solr's schema has gained the stemmed `text_sk` field that the
# indexed datasets do not carry yet (T-4233, files/solr/managed-schema).
#
# A schema change reaches only what is indexed after it: the datasets indexed before keep
# answering the exact word form alone until CKAN writes them again. This counts the datasets that
# have a title and the ones that have stemmed words; fewer of the second means the index predates
# the field, and `ckan search-index rebuild` writes every dataset again. Without `--clear` it
# replaces each document in place, so search keeps answering while it runs, in the background,
# beside uWSGI. Once every dataset carries the field, a restart finds nothing to do.
#
# Solr down, or a Solr without the field: nothing to do now, the next start looks again. The
# catalogue starts either way; a stale index is a worse search, not an outage.
#
# Sourced by `start_ckan.sh`, not executed: no `exit` on any path.
jc_index=$(python3 - <<'PY' 2>&1 || true
import json
import os
import time
import urllib.request

base = os.environ.get("CKAN_SOLR_URL", "").rstrip("/")
wait = int(os.environ.get("JC_SOLR_WAIT_SECONDS", "120"))


def get(path):
    with urllib.request.urlopen(base + path, timeout=10) as answer:
        return json.load(answer)


def found(query):
    return get("/select?rows=0&wt=json&q=" + query)["response"]["numFound"]


if not base:
    print("no CKAN_SOLR_URL")
    raise SystemExit
deadline = time.monotonic() + wait
while True:
    try:
        get("/admin/ping?wt=json")
        break
    except Exception:
        if time.monotonic() >= deadline:
            print("Solr did not answer")
            raise SystemExit
        time.sleep(5)
try:
    get("/schema/fields/text_sk?wt=json")
    titled, stemmed = found("title:*"), found("text_sk:*")
except Exception as error:
    print(f"not checked: {error}")
    raise SystemExit
print("rebuild" if stemmed < titled else f"current, {titled} datasets")
PY
)
case "$jc_index" in
  rebuild)
    echo "[jc] search index predates the stemmed field: rebuilding it in the background"
    ckan -c "$CKAN_INI" search-index rebuild -q &
    ;;
  *)
    echo "[jc] search index: $jc_index"
    ;;
esac
unset jc_index
