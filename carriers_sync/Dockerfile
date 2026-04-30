# Official Python image: Debian bookworm + glibc, multi-arch manifest (amd64+arm64).
# Required because Microsoft's prebuilt Playwright Chromium binaries are glibc-only
# and break on Alpine/musl. HA's own base-python is Alpine-only at the time of
# writing, so we use the upstream Python image instead. Pinned tag for
# reproducible builds.
FROM python:3.12-bookworm

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Playwright + Chromium + stealth (used by some providers — e.g. Ogero — to
# get past Google reCAPTCHA v3 invisible scoring during login)
RUN pip3 install --no-cache-dir \
      playwright \
      "playwright-stealth>=1.0" \
      "aiomqtt>=2.0" \
      "pyyaml>=6.0" \
 && playwright install-deps \
 && playwright install chromium

WORKDIR /app
COPY src/ ./src/
COPY run.sh ./
RUN chmod +x run.sh

CMD ["./run.sh"]
