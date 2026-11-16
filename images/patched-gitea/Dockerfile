# Gitea as pinned, with its Alpine packages upgraded (T-7124): 1.27.3-rootless, the newest 1.27
# patch, ships openssh-keygen 10.3_p1-r0 (CVE-2026-123158 CRITICAL, fixed in 10.3_p1-r2) and no
# newer 1.27 tag rebuilds the base; 28.x carries the fix but is a major line with forward-only
# database migrations. The image keeps upstream's user, entrypoint and Gitea binary. Drop this
# image when an upstream 1.27 tag scans clean (trivy image --pkg-types os) or the forge moves to 28.
FROM docker.gitea.com/gitea:1.27.3-rootless@sha256:1c17ecaead42eb3b5391553d8708103a4beb0e86edf5b9ebc1eb269c318845f2
USER root
RUN apk upgrade --no-cache
USER 1000:1000
