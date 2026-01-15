# Archived Legacy Code

This directory contains legacy code that has been deprecated but preserved for reference.

**Created:** 2025-01-14

## Contents

### legacy_code/

- **old_version.py** - Previous version of the RAG-based snapshot builder. Replaced by `pbpk_workflow.py` with more reliable, deterministic implementation.

- **patch_main.py** - One-time patch script for HTML static paths. Already applied, no longer needed.

- **main_legacy.py** - Old Gradio-only interface. Replaced by the FastAPI + Gradio hybrid in `main.py`.

- **config_patch.py** - Incomplete stub file that was never completed.

### legacy_auth/ (in ESQai repo)

- **saml_authenticator.py**, **manual_auth.py**, **scrape_with_auth.py** - Legacy authentication code from Azure VM era. Authentication is now handled server-side.

- **auth_cookies.json**, **auth_storage_state.json** - Stale browser auth state (should not be used).

- **dashboard_scraper.py** - Legacy scraper that depended on old auth.

- **debug_attempt_1.html** - Debug output from authentication testing.

## Recovery

If any of this code is needed, it can be recovered from git history or this archive:

```bash
# From git history
git log --all -- old_version.py

# From archive
cp _archive/legacy_code/old_version.py ./
```

## Deprecation Notes

- **Snapshot Tools**: The `create_drug_snapshot` function is deprecated. Use `create_pbpk_snapshot` from `biomni_esqlabs_tools.pbpk.pbpk_workflow` instead.

- **RAG Builder**: The `json_rag_builder.py` tools are still available for backward compatibility but are deprecated in favor of the direct snapshot creation approach.

- **Authentication**: All authentication is now handled by the FastAPI SessionMiddleware and server-side auth proxy. No client-side auth code is needed.
