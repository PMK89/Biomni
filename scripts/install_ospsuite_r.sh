#!/usr/bin/env bash
set -euo pipefail

if ! command -v Rscript >/dev/null 2>&1; then
  echo "ERROR: Rscript not found in PATH. Activate your env (e.g., micromamba/conda) and retry." >&2
  exit 1
fi

Rscript -e "cat('R version: ', getRversion(), '\n', sep='')"

Rscript -e "options(repos=c(CRAN='https://cloud.r-project.org')); if (!requireNamespace('remotes', quietly=TRUE)) install.packages('remotes')"

Rscript -e "options(repos=c(CRAN='https://cloud.r-project.org')); remotes::install_github('Open-Systems-Pharmacology/OSPSuite-R@*release', upgrade='never')"

Rscript -e "suppressPackageStartupMessages({ library(ospsuite) }); cat('ospsuite loaded successfully\n')"
