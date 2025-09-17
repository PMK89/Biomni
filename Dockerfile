# ===== Stage 1: Base Environment =====
# Build the heavy conda environment once and reuse it in the final image
FROM ubuntu:22.04 AS base

SHELL ["/bin/bash", "-c"]
ENV DEBIAN_FRONTEND=noninteractive

# Core build tools and utilities
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    bzip2 \
    unzip \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install Miniconda under /opt/conda
RUN curl -sSL https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -o /tmp/miniconda.sh && \
    bash /tmp/miniconda.sh -b -p /opt/conda && \
    rm /tmp/miniconda.sh

ENV PATH="/opt/conda/bin:$PATH"

# Accept conda Terms of Service to avoid interactive prompts
RUN conda config --set auto_activate_base false && \
    conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main && \
    conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r

# Copy environment setup resources and create the biomni_e1 environment
COPY biomni_env/ /tmp/biomni_env/
WORKDIR /tmp/biomni_env
RUN NON_INTERACTIVE=1 bash setup.sh

# ===== Stage 2: Final Application Image =====
FROM base

WORKDIR /app

# Copy project files
COPY pyproject.toml README.md LICENSE /app/
COPY biomni /app/biomni
COPY app /app/app

# Install local biomni package into the prepared environment
RUN source /opt/conda/etc/profile.d/conda.sh && \
    conda activate biomni_e1 && \
    pip install --no-cache-dir .

EXPOSE 8000

# Start the FastAPI app with uvicorn (proxy headers retained for reverse proxy setups)
CMD ["/opt/conda/envs/biomni_e1/bin/python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
