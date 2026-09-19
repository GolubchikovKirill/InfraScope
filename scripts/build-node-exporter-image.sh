#!/usr/bin/env bash
set -euo pipefail

# Builds the local image `infrascope/node-exporter:v1.9.1` from the official
# node_exporter release tarball, with no container registry involved.
#
# Why this exists: from the production host both Docker Hub and Quay drop the
# layer download of prom/node-exporter on every attempt, and the host's own
# internet is only a few kB/s (a corporate gateway sits in the path), so
# `docker pull` cannot be relied on there. The release binary is a single
# static executable, so the image is just `FROM scratch` + that file.
#
# Usage:
#   ./scripts/build-node-exporter-image.sh                 # download, verify, build
#   ./scripts/build-node-exporter-image.sh /path/to.tar.gz # use a tarball you fetched elsewhere
#
# The tarball is verified against the SHA-256 published by the project
# (sha256sums.txt of the v1.9.1 release); a mismatch aborts the build.

VERSION="1.9.1"
TARBALL_NAME="node_exporter-${VERSION}.linux-amd64.tar.gz"
EXPECTED_SHA256="becb950ee80daa8ae7331d77966d94a611af79ad0d3307380907e0ec08f5b4e8"
IMAGE="${NODE_EXPORTER_IMAGE:-infrascope/node-exporter:v${VERSION}}"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

if [ "${1:-}" != "" ]; then
  cp "$1" "$work/ne.tar.gz"
else
  curl -fsSL --retry 3 -o "$work/ne.tar.gz" \
    "https://github.com/prometheus/node_exporter/releases/download/v${VERSION}/${TARBALL_NAME}"
fi

actual="$(sha256sum "$work/ne.tar.gz" | cut -d' ' -f1)"
if [ "$actual" != "$EXPECTED_SHA256" ]; then
  echo "SHA-256 mismatch for node_exporter tarball" >&2
  echo "  expected: $EXPECTED_SHA256" >&2
  echo "  actual:   $actual" >&2
  exit 1
fi

tar -xzf "$work/ne.tar.gz" -C "$work" --strip-components=1 "node_exporter-${VERSION}.linux-amd64/node_exporter"

cat > "$work/Dockerfile" <<'EOF'
FROM scratch
COPY node_exporter /node_exporter
USER 65534:65534
EXPOSE 9100
ENTRYPOINT ["/node_exporter"]
EOF

docker build -t "$IMAGE" "$work"
echo "Built $IMAGE"
