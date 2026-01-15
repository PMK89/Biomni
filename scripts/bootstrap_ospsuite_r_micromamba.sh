#!/usr/bin/env bash
set -euo pipefail

ENV_NAME=${ENV_NAME:-${CONDA_DEFAULT_ENV:-biomni_e1}}

PM=""
if command -v micromamba >/dev/null 2>&1; then
  PM="micromamba"
elif command -v conda >/dev/null 2>&1; then
  PM="conda"
elif command -v mamba >/dev/null 2>&1; then
  PM="mamba"
fi

if [[ -z "$PM" ]]; then
  echo "ERROR: No conda/mamba/micromamba executable found in PATH. Activate your environment and retry." >&2
  exit 1
fi

echo "[bootstrap] Using package manager: ${PM}" >&2
echo "[bootstrap] Target env: ${ENV_NAME}" >&2

TMP_R_SCRIPT="$(mktemp -t install_ospsuite_XXXXXX.R)"
cat >"$TMP_R_SCRIPT" <<'RSCRIPT'
options(repos = c(CRAN = "https://cloud.r-project.org"))

Sys.unsetenv("GITHUB_TOKEN")
Sys.unsetenv("GITHUB_PAT")

install_if_missing <- function(pkg) {
  if (!requireNamespace(pkg, quietly = TRUE)) {
    install.packages(pkg)
  }
}

install_if_missing("remotes")

try_install_ospsuite <- function() {
  ok <- requireNamespace("ospsuite", quietly = TRUE)
  if (ok) return(TRUE)

  # Try Open Systems Pharmacology r-universe (may fail behind some networks)
  try({
    options(repos = c(CRAN = "https://cloud.r-project.org", OSP = "https://open-systems-pharmacology.r-universe.dev"))
    install.packages("ospsuite")
  }, silent = TRUE)
  if (requireNamespace("ospsuite", quietly = TRUE)) return(TRUE)

  # Tarball fallback (avoids GitHub API auth; still requires GitHub reachability)
  try({
    tmp <- tempfile(fileext = ".tar.gz")
    url <- "https://github.com/Open-Systems-Pharmacology/OSPSuite-R/archive/refs/heads/develop.tar.gz"
    download.file(url, destfile = tmp, mode = "wb", quiet = TRUE)
    install.packages(tmp, repos = NULL, type = "source")
  }, silent = TRUE)
  if (requireNamespace("ospsuite", quietly = TRUE)) return(TRUE)

  # Final fallback: direct GitHub install, explicitly without auth
  try({
    Sys.setenv(GITHUB_PAT = "")
    remotes::install_github("Open-Systems-Pharmacology/OSPSuite-R", upgrade = "never", auth_token = NULL)
  }, silent = TRUE)

  requireNamespace("ospsuite", quietly = TRUE)
}

if (!try_install_ospsuite()) {
  stop("Failed to install ospsuite")
}

suppressPackageStartupMessages(library(ospsuite))
cat("ospsuite loaded successfully\n")
RSCRIPT

if [[ "$PM" == "micromamba" ]]; then
  micromamba install -y -n "${ENV_NAME}" -c conda-forge \
    r-base r-jsonlite r-pak \
    dotnet-runtime=8.0 \
    libcurl openssl libxml2 fontconfig harfbuzz fribidi freetype libpng libtiff jpeg

  if ! env -u GITHUB_TOKEN -u GITHUB_PAT micromamba run -n "${ENV_NAME}" Rscript "$TMP_R_SCRIPT"; then
    echo "ERROR: Failed to install ospsuite. If you're behind a proxy/firewall, ensure GitHub and r-universe are reachable." >&2
    exit 1
  fi
  exit 0
fi

if [[ "$PM" == "mamba" ]]; then
  mamba install -y -n "${ENV_NAME}" -c conda-forge \
    r-base r-jsonlite r-pak \
    dotnet-runtime=8.0 \
    libcurl openssl libxml2 fontconfig harfbuzz fribidi freetype libpng libtiff jpeg
  conda run -n "${ENV_NAME}" Rscript -e "options(repos=c(CRAN='https://cloud.r-project.org')); if (!requireNamespace('remotes', quietly=TRUE)) install.packages('remotes')"
  if ! env -u GITHUB_TOKEN -u GITHUB_PAT conda run -n "${ENV_NAME}" Rscript "$TMP_R_SCRIPT"; then
    echo "ERROR: Failed to install ospsuite. If you're behind a proxy/firewall, ensure GitHub and r-universe are reachable." >&2
    exit 1
  fi
  exit 0
fi

conda install -y -n "${ENV_NAME}" -c conda-forge \
  r-base r-jsonlite r-pak \
  dotnet-runtime=8.0 \
  libcurl openssl libxml2 fontconfig harfbuzz fribidi freetype libpng libtiff jpeg

echo "[bootstrap] Installing compilers/build tools for source installs" >&2
conda install -y -n "${ENV_NAME}" -c conda-forge compilers make cmake pkg-config

conda run -n "${ENV_NAME}" Rscript -e "options(repos=c(CRAN='https://cloud.r-project.org')); if (!requireNamespace('remotes', quietly=TRUE)) install.packages('remotes')"
if ! env -u GITHUB_TOKEN -u GITHUB_PAT conda run -n "${ENV_NAME}" Rscript "$TMP_R_SCRIPT"; then
  echo "ERROR: Failed to install ospsuite. If you're behind a proxy/firewall, ensure GitHub and r-universe are reachable." >&2
  exit 1
fi
