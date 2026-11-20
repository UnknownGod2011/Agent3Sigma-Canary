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
    x11-xserver-utils \
    util-linux \
    scrot \
    tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install certifi --break-system-packages
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"
RUN npm install -g openclaw@2026.7.1-2 --unsafe-perm --ignore-scripts

RUN mkdir -p /home/node/.openclaw/skills /tmp/agentcanary-desktop-agent \
    && chown -R node:node /home/node/.openclaw /tmp/agentcanary-desktop-agent \
    && chmod 0700 /home/node/.openclaw /tmp/agentcanary-desktop-agent
COPY docker/openclaw.json /home/node/.openclaw/openclaw.json
RUN chown node:node /home/node/.openclaw/openclaw.json \
    && chmod 0600 /home/node/.openclaw/openclaw.json \
    && rm -rf /root/.openclaw \
    && ln -s /home/node/.openclaw /root/.openclaw \
    && mv /usr/local/bin/openclaw /usr/local/bin/openclaw-real
COPY desktop/openclaw_nonroot /usr/local/bin/openclaw
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
COPY nonroot_gui_boundary_smoke.sh /usr/local/bin/desktop-baseline-nonroot-smoke-test
RUN chmod 600 /opt/agentcanary-desktop/notes_ui.py \
    && chmod +x /opt/agentcanary-desktop/desktop_ocr.py /opt/agentcanary-desktop/desktop_model_stub.py \
        /usr/local/bin/desktop-baseline-entrypoint.sh /usr/local/bin/desktopctl \
        /usr/local/bin/desktop-baseline-smoke-test /usr/local/bin/desktop-baseline-nonroot-smoke-test \
        /usr/local/bin/openclaw

ENV DISPLAY=:99
ENV DESKTOP_BASELINE_STATE=/tmp/agentcanary-desktop/desktop_baseline_state.json
WORKDIR /workspace
ENTRYPOINT ["/usr/local/bin/desktop-baseline-entrypoint.sh"]
CMD ["tail", "-f", "/dev/null"]
