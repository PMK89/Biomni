# ===== Stage 1: Base Environment =====
# This stage builds the heavy conda environment and is cached
FROM ubuntu:22.04 AS base

# Set Shell
SHELL ["/bin/bash", "-c"]

# Avoid prompts from apt
ENV DEBIAN_FRONTEND=noninteractive

# Install basic utilities and build tools
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    bzip2 \
    unzip \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install Miniconda
RUN curl -sSL https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -o /tmp/miniconda.sh && \
    bash /tmp/miniconda.sh -b -p /opt/conda && \
    rm /tmp/miniconda.sh

# Set PATH to include conda
ENV PATH="/opt/conda/bin:$PATH"

# Accept conda ToS
RUN conda config --set auto_activate_base false && \
    conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main && \
    conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r

# Copy only the environment setup files
COPY biomni_env/ /tmp/biomni_env/

# Run the long setup script to create the 'biomni' environment
WORKDIR /tmp/biomni_env
RUN source /opt/conda/etc/profile.d/conda.sh && bash setup.sh


# ===== Stage 2: Final Application Image =====
# This stage starts from the base, copies app code, and is rebuilt quickly
FROM base

# Set the working directory
WORKDIR /app

# Copy the application code from the host machine
COPY app/ /app/

# Install Python dependencies from requirements.txt into the 'biomni' conda environment
# The conda environment already exists from the base stage
RUN source /opt/conda/etc/profile.d/conda.sh && \
    conda activate biomni_e1 && \
    pip install -r /app/requirements.txt

# Expose the port the app runs on
EXPOSE 8001

# Set the entrypoint to run the application using the python from the 'biomni' env
CMD ["/opt/conda/envs/biomni_e1/bin/python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
