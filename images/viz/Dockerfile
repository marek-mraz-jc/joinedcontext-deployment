# The chart renderer's server on viz.{domain} (T-4641, T-4657): the pinned nginx the chart ran,
# with the vendored Vega, MapLibre and PMTiles builds inside the image. In the chart they made the
# Helm release Secret 2.2 MB, over its 1 MiB, and the upgrade failed on dev. The site pages and
# nginx.conf stay in the chart's ConfigMaps, so a page change is still a values edit.
FROM docker.io/nginxinc/nginx-unprivileged:1.30.4-alpine-slim@sha256:7bbe8940bc478e5618e6d4cfbeda406e5b4217cacc06faacd665aca5e468595e

COPY vendor/ /srv/vendor/

# Every file is the release byte for byte (vendor/SHA256SUMS), or the image does not build.
# pcre2 from the base's repository: 10.48-r0 in the pinned base is CVE-2026-103111 (HIGH), fixed
# in 10.49-r0 (trivy on image-viz, 2026-10-18).
USER root
RUN apk upgrade --no-cache pcre2 \
    && cd /srv/vendor && grep -v '^#' SHA256SUMS | sha256sum -c - && chmod -R a+rX,go-w /srv/vendor
USER 101
