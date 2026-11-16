# AgentCanary experimental desktop/UI baseline image.
# This deliberately extends the official runner rather than creating a new
# benchmark harness. The only added surface is a deterministic X11 desktop
# fixture plus screenshot/mouse/keyboard helpers.
FROM node:22-bookworm

# Match the official builder metadata so lib_docker.uses_native_openclaw()
# selects the embedded --local agent path instead of Gateway dispatch.
LABEL org.opencontainers.image.description="AgentCanary experimental deterministic desktop UI baseline" ai.agentcanary.image_type="official" ai.agentcanary.openclaw_version="2026.7.1-2"

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
    tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install certifi --break-system-packages
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"
RUN npm install -g openclaw@2026.7.1-2 --unsafe-perm --ignore-scripts

RUN mkdir -p /root/.openclaw/skills
COPY docker/openclaw.json /root/.openclaw/openclaw.json
RUN mkdir -p /tmp/scry/skill_data
RUN mkdir -p /tmp/scry/mock_api/data
COPY docker/mock_api_data/ /tmp/scry/mock_api/data/
RUN mkdir -p /tmp/scry/mock_api/api_handlers
COPY docker/mock_api_handlers/ /tmp/scry/mock_api/api_handlers/
COPY docker/mock-api /opt/mock-api
RUN pip3 install -r /opt/mock-api/requirements.txt --break-system-packages

COPY desktop/notes_ui.py /opt/agentcanary-desktop/notes_ui.py
COPY desktop/desktop_ocr.py /opt/agentcanary-desktop/desktop_ocr.py
COPY desktop/desktop_model_stub.py /opt/agentcanary-desktop/desktop_model_stub.py
COPY desktop/desktop_baseline_entrypoint.sh /usr/local/bin/desktop-baseline-entrypoint.sh
COPY desktop/desktopctl /usr/local/bin/desktopctl
COPY smoke_test.sh /usr/local/bin/desktop-baseline-smoke-test
RUN chmod +x /opt/agentcanary-desktop/notes_ui.py /opt/agentcanary-desktop/desktop_ocr.py /opt/agentcanary-desktop/desktop_model_stub.py /usr/local/bin/desktop-baseline-entrypoint.sh /usr/local/bin/desktopctl /usr/local/bin/desktop-baseline-smoke-test

ENV DISPLAY=:99
ENV DESKTOP_BASELINE_STATE=/tmp/agentcanary-desktop/desktop_baseline_state.json
WORKDIR /workspace
ENTRYPOINT ["/usr/local/bin/desktop-baseline-entrypoint.sh"]
CMD ["tail", "-f", "/dev/null"]
