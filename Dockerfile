# syntax=docker/dockerfile:1.7
ARG MAMBA_VERSION=1.5.8
FROM mambaorg/micromamba:${MAMBA_VERSION}

ARG ENV_NAME=biomni_e1
ARG USERNAME=appuser
ARG UID=1000
ARG GID=1000
ENV ENV_NAME=${ENV_NAME}

USER root
RUN groupadd -g ${GID} ${USERNAME} && \
    useradd -m -u ${UID} -g ${GID} -s /bin/bash ${USERNAME} && \
    mkdir -p /workspace && chown -R ${USERNAME}:${USERNAME} /workspace

WORKDIR /workspace
USER ${USERNAME}

ENV TMPDIR=/workspace/.tmp
RUN mkdir -p "${TMPDIR}"

# Cache-friendly: copy env spec first
COPY --chown=${USERNAME}:${USERNAME} environment.yml /workspace/

# Single-shot env solve (must include Web UI deps)
RUN micromamba create -y -n ${ENV_NAME} -f /workspace/environment.yml && \
    micromamba clean --all --yes

COPY --chown=${USERNAME}:${USERNAME} pyproject.toml /workspace/

SHELL ["bash", "-lc"]
ENV MAMBA_DOCKERFILE_ACTIVATE=1
RUN echo "micromamba activate ${ENV_NAME}" >> ~/.bashrc

# Copy source (exclude data via .dockerignore)
COPY --chown=${USERNAME}:${USERNAME} . /workspace

# Optional local install if present
RUN if [[ -f biomni_esqlabs_app/requirements.txt ]]; then \
      micromamba run -n ${ENV_NAME} pip install -r biomni_esqlabs_app/requirements.txt ; \
    fi && \
    if [[ -f pyproject.toml ]]; then \
      micromamba run -n ${ENV_NAME} pip install -e . ; \
    elif [[ -f requirements.txt ]]; then \
      micromamba run -n ${ENV_NAME} pip install -r requirements.txt ; \
    fi

ENV BIOMNI_DATA_DIR=/workspace/data/biomni_data
ENV BIOMNI_APP_MODULE=biomni_esqlabs_app.main:app
RUN mkdir -p "$BIOMNI_DATA_DIR"

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
  CMD micromamba run -n ${ENV_NAME} python -c "import importlib; importlib.import_module('biomni')" || exit 1

# Use existing scripts folder for entrypoint
RUN chmod +x /workspace/scripts/entrypoint.sh || true
EXPOSE 8001
ENTRYPOINT ["/workspace/scripts/entrypoint.sh"]
