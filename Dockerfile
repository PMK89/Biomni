# syntax=docker/dockerfile:1.7
ARG MAMBA_VERSION=1.5.8
FROM mambaorg/micromamba:${MAMBA_VERSION}

ARG ENV_NAME=biomni_e1
ARG USERNAME=appuser
ARG UID=1000
ARG GID=1000
ENV ENV_NAME=${ENV_NAME}

USER root
# Install system dependencies for R packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpng-dev \
    libxml2-dev \
    libfreetype6-dev \
    libfontconfig1-dev \
    libcurl4-openssl-dev \
    libssl-dev \
    zlib1g-dev \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd -g ${GID} ${USERNAME} && \
    useradd -m -u ${UID} -g ${GID} -s /bin/bash ${USERNAME} && \
    mkdir -p /workspace && chown -R ${USERNAME}:${USERNAME} /workspace

WORKDIR /workspace
USER ${USERNAME}

ENV TMPDIR=/workspace/.tmp
RUN mkdir -p "${TMPDIR}"

# Ensure R installs packages into a writable user library path
ENV R_LIBS_USER=/home/${USERNAME}/.R/library
RUN mkdir -p "${R_LIBS_USER}"

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
RUN chmod -R 755 /workspace/biomni_esqlabs_app

# Optional local install if present
RUN if [[ -f biomni_esqlabs_app/requirements.txt ]]; then \
      micromamba run -n ${ENV_NAME} pip install -r biomni_esqlabs_app/requirements.txt ; \
    fi && \
    if [[ -f pyproject.toml ]]; then \
      micromamba run -n ${ENV_NAME} pip install -e . ; \
    elif [[ -f requirements.txt ]]; then \
      micromamba run -n ${ENV_NAME} pip install -r requirements.txt ; \
    fi

RUN micromamba run -n ${ENV_NAME} python -c "import biomni_esqlabs_app.main" && \
    micromamba run -n ${ENV_NAME} python -c "from biomni_esqlabs_app.main import app; assert app is not None" && \
    micromamba run -n ${ENV_NAME} dotnet --info >/dev/null

RUN micromamba run -n ${ENV_NAME} Rscript -e "options(repos=c(CRAN='https://cloud.r-project.org')); dir.create(Sys.getenv('R_LIBS_USER'), recursive=TRUE, showWarnings=FALSE); .libPaths(c(Sys.getenv('R_LIBS_USER'), .libPaths())); \
    core_deps <- c('cli', 'crayon', 'dplyr', 'ggplot2', 'glue', 'lifecycle', 'logger', 'openxlsx', 'patchwork', 'purrr', 'R6', 'readr', 'rlang', 'stringi', 'stringr', 'tidyr', 'xml2'); \
    optional_deps <- c('ggtext', 'showtext', 'sysfonts', 'showtextdb', 'gridtext', 'png'); \
    install.packages(core_deps, lib=Sys.getenv('R_LIBS_USER'), Ncpus=4); \
    install.packages(optional_deps, lib=Sys.getenv('R_LIBS_USER'), Ncpus=4); \
    download.file('https://github.com/Open-Systems-Pharmacology/rSharp/releases/download/v1.1.2/rSharp_1.1.2_R_x86_64-pc-linux-gnu.tar.gz', destfile='/tmp/rSharp.tar.gz'); \
    download.file('https://github.com/Open-Systems-Pharmacology/OSPSuite.RUtils/releases/download/v1.9.0/ospsuite.utils_1.9.0_R_x86_64-pc-linux-gnu.tar.gz', destfile='/tmp/ospsuite.utils.tar.gz'); \
    download.file('https://github.com/Open-Systems-Pharmacology/TLF-Library/releases/download/v1.6.2/tlf_1.6.2_R_x86_64-pc-linux-gnu.tar.gz', destfile='/tmp/tlf.tar.gz'); \
    download.file('https://github.com/Open-Systems-Pharmacology/OSPSuite-R/releases/download/v12.4.0/ospsuite_12.4.0_R_x86_64-pc-linux-gnu.tar.gz', destfile='/tmp/ospsuite.tar.gz'); \
    install.packages('/tmp/rSharp.tar.gz', repos=NULL, lib=Sys.getenv('R_LIBS_USER')); \
    install.packages('/tmp/ospsuite.utils.tar.gz', repos=NULL, lib=Sys.getenv('R_LIBS_USER')); \
    install.packages('/tmp/tlf.tar.gz', repos=NULL, lib=Sys.getenv('R_LIBS_USER')); \
    install.packages('/tmp/ospsuite.tar.gz', repos=NULL, lib=Sys.getenv('R_LIBS_USER')); \
    if (!requireNamespace('data.table', quietly=TRUE)) stop('data.table is required but not installed'); \
    library(ospsuite); \
    cat('ospsuite version:', as.character(packageVersion('ospsuite')), '\\\\n')"

RUN micromamba run -n ${ENV_NAME} Rscript -e "suppressPackageStartupMessages(library(ospsuite)); cat(as.character(packageVersion('ospsuite')))" >/dev/null

ENV BIOMNI_DATA_DIR=/workspace/data/biomni_data
ENV BIOMNI_APP_MODULE=biomni_esqlabs_app.main:app
RUN mkdir -p "$BIOMNI_DATA_DIR"

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
  CMD micromamba run -n ${ENV_NAME} python -c "import importlib; importlib.import_module('biomni')" || exit 1

# Use existing scripts folder for entrypoint
RUN chmod +x /workspace/scripts/entrypoint.sh || true
EXPOSE 8001
ENTRYPOINT ["/workspace/scripts/entrypoint.sh"]
