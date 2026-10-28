# KeepSift in a browser tab: the desktop app served over noVNC on port 5800 (for Unraid and other Docker hosts).
FROM jlesage/baseimage-gui:debian-12-v4

ARG KEEPSIFT_VERSION=dev

RUN add-pkg python3 python3-tk python3-pip fonts-noto-core fonts-noto-color-emoji \
 && pip3 install --no-cache-dir --break-system-packages sv-ttk==2.6.1

RUN install_app_icon.sh "https://raw.githubusercontent.com/vonhex/keepsift/main/assets/icon-256.png"

COPY keepsift /app/keepsift
COPY assets /app/assets
COPY samples /app/samples
COPY --chmod=755 docker/startapp.sh /startapp.sh

RUN set-cont-env APP_NAME "KeepSift" \
 && set-cont-env APP_VERSION "$KEEPSIFT_VERSION"

# Settings, Gmail login, history and logs all live in /config (map it to appdata).
ENV KEEPSIFT_HOME=/config PYTHONPATH=/app PYTHONDONTWRITEBYTECODE=1

LABEL org.opencontainers.image.title="KeepSift" \
      org.opencontainers.image.description="Clean out a huge Gmail inbox with your own local AI, without losing product keys, activation links or receipts." \
      org.opencontainers.image.source="https://github.com/vonhex/keepsift" \
      org.opencontainers.image.licenses="PolyForm-Noncommercial-1.0.0"
