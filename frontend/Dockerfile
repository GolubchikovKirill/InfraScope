FROM node:20-bookworm-slim AS builder

WORKDIR /app

COPY package.json package-lock.json* ./
ARG NPM_REGISTRY=https://registry.npmjs.org/
ARG NPM_REGISTRY_FALLBACK=https://registry.npmmirror.com/
ARG NPM_STRICT_SSL=false
ENV npm_config_registry=${NPM_REGISTRY}
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN --mount=type=cache,target=/root/.npm npm --version \
    && npm config set strict-ssl "${NPM_STRICT_SSL}" \
    && npm config set fund false \
    && npm config set audit false \
    && npm config set progress false \
    && npm config set fetch-retries 5 \
    && npm config set fetch-retry-mintimeout 20000 \
    && npm config set fetch-retry-maxtimeout 120000 \
    && npm config set fetch-timeout 300000 \
    && npm config set maxsockets 1 \
    && run_npm_ci() { \
        timeout 10m npm ci --no-audit --no-fund --prefer-offline \
        && [ -x node_modules/.bin/vite ]; \
      } \
    && install_with_retries() { \
        reg="$1"; \
        npm config set registry "$reg"; \
        success=0; \
        for i in 1 2 3 4 5; do \
          if run_npm_ci; then success=1; break; fi; \
          echo "npm ci failed on $reg, retry $i/5"; \
          npm cache clean --force; \
          sleep $((i * 5)); \
        done; \
        [ "$success" -eq 1 ]; \
      } \
    && (install_with_retries "$NPM_REGISTRY" || install_with_retries "$NPM_REGISTRY_FALLBACK")

COPY . .

ARG VITE_API_URL=/api/v1
ENV VITE_API_URL=${VITE_API_URL}

RUN npm run build


FROM nginx:1.27-alpine

RUN apk add --no-cache openssl

COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN sed -i 's/\r$//' /docker-entrypoint.sh && chmod +x /docker-entrypoint.sh

EXPOSE 80 443

ENTRYPOINT ["/docker-entrypoint.sh"]
