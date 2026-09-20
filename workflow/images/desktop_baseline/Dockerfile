# AgentCanary experimental desktop/UI baseline image.
# This deliberately extends the official runner rather than creating a new
# benchmark harness. The only added surface is a deterministic X11 desktop
# fixture plus screenshot/mouse/keyboard helpers.
FROM node:22-bookworm

LABEL org.opencontainers.image.description="AgentCanary experimental deterministic desktop UI baseline"

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-tk \
    git \
    curl \
    jq \
    iptables \
    dnsutils \
    openssl \
    ca-certificates \
    xvfb \
    xdotool \
    x11-utils \
    scrot \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install certifi --break-system-packages
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"
RUN npm install -g openclaw@2026.4.11 --unsafe-perm

RUN mkdir -p /root/.openclaw/skills
COPY docker/openclaw.json /root/.openclaw/openclaw.json
RUN mkdir -p /tmp/scry/skill_data
RUN mkdir -p /tmp/scry/mock_api/data
COPY docker/mock_api_data/ /tmp/scry/mock_api/data/
RUN mkdir -p /tmp/scry/mock_api/api_handlers
COPY docker/mock_api_handlers/ /tmp/scry/mock_api/api_handlers/
COPY docker/mock-api /opt/mock-api
RUN pip3 install -r /opt/mock-api/requirements.txt --break-system-packages

COPY desktop/notes_app.py /opt/agentcanary-desktop/notes_app.py
COPY desktop/desktopctl /usr/local/bin/desktopctl
RUN chmod +x /opt/agentcanary-desktop/notes_app.py /usr/local/bin/desktopctl

ENV DISPLAY=:99
ENV DESKTOP_BASELINE_STATE=/workspace/desktop_baseline_state.json
WORKDIR /workspace
ENTRYPOINT ["/opt/mock-api/entrypoint.sh"]
CMD ["tail", "-f", "/dev/null"]
