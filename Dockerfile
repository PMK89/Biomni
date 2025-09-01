FROM ghcr.io/mamba-org/micromamba:1.5.8

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    MAMBA_ROOT_PREFIX=/opt/conda

WORKDIR /app

USER root

# Copy environment first for better layer caching (with correct ownership)
COPY --chown=mambauser:mambauser biomni_env/environment.yml /tmp/environment.yml

# Create the Biomni conda environment (biomni_e1)
RUN micromamba create -y -n biomni_e1 -f /tmp/environment.yml && \
    micromamba clean -a -y

# Copy project files
COPY --chown=mambauser:mambauser pyproject.toml README.md LICENSE ./
COPY --chown=mambauser:mambauser biomni ./biomni
COPY --chown=mambauser:mambauser app ./app

# Install the local biomni package into the conda env
USER mambauser
RUN micromamba run -n biomni_e1 pip install --no-cache-dir .

EXPOSE 8000

# Use proxy headers so auth redirects build correct external https URLs behind nginx
CMD ["micromamba", "run", "-n", "biomni_e1", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]

