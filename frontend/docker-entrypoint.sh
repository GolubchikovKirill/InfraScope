#!/bin/sh
set -e

CERT_DIR="/etc/nginx/certs"
CERT_FILE="$CERT_DIR/cert.pem"
KEY_FILE="$CERT_DIR/key.pem"

if [ ! -f "$CERT_FILE" ] || [ ! -f "$KEY_FILE" ]; then
    echo "[InfraScope] SSL certificates not found — generating self-signed..."
    mkdir -p "$CERT_DIR"
    apk add --no-cache openssl > /dev/null 2>&1 || true

    # Collect all container/host IPs for the SAN field
    SAN="DNS:infrascope.local,DNS:localhost,IP:127.0.0.1"
    for ip in $(hostname -i 2>/dev/null); do
        case "$ip" in
            127.*) ;;
            *) SAN="$SAN,IP:$ip" ;;
        esac
    done
    # If HOST_IP is passed via environment, include it too
    if [ -n "$HOST_IP" ]; then
        SAN="$SAN,IP:$HOST_IP"
    fi

    echo "[InfraScope] Certificate SAN: $SAN"

    openssl req -x509 -nodes -days 3650 \
        -newkey rsa:2048 \
        -keyout "$KEY_FILE" \
        -out "$CERT_FILE" \
        -subj "/CN=infrascope.local" \
        -addext "subjectAltName=$SAN" \
        2>/dev/null
    echo "[InfraScope] Self-signed certificate created. For trusted HTTPS use mkcert."
fi

exec nginx -g "daemon off;"
