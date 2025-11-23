6988o# ESQlabs Integration Plan

This document tracks the differences between `upstream/main` and `origin/osp_rag_docker`, categorizes ESQlabs contributions, and captures how each artifact will be merged or isolated.

**Type legend**
- **A** – New ESQlabs-only modules, tools, or datasets that do not exist upstream.
- **B** – Files shared with upstream (code, configs, infra) that must stay close to Stanford's implementation.
- **C** – Internal GUI / app assets that should remain outside of an upstream PR.

## File integration matrix

| File | Type (A/B/C) | Main purpose | Integration strategy (copy, refactor, isolate, etc.) |
| --- | --- | --- | --- |
| `.dockerignore` | B | Docker build context exclusions | Copy upstream ignore style; ensure only ESQ-specific paths are added |
| `.env.example` | B | Sample environment variables including ESQ secrets | Merge new keys with upstream sample via comments/feature flags |
| `.gitignore` | B | Ignore list for local data/results | Keep new folders ignored while matching upstream defaults |
| `Dockerfile` | B | Container image for Biomni + ESQ tooling | Refactor into optional image that layers ESQ tools without replacing upstream base |
| `README.md` | B | Project overview with ESQ instructions | Split upstream-ready instructions from ESQ-only notes; minimize diff |
| `app/auth.py` | C | Azure AD helper logic for the GUI | Move under `biomni_esqlabs_app.auth` and decouple from core |
| `app/config.py` | C | Pydantic config for the GUI/app | Relocate to GUI package and load settings from ESQ config file |
| `app/main.py` | C | FastAPI + Gradio UI used internally | Keep inside `biomni_esqlabs_app`; ensure it consumes the plugin APIs |
| `app/main_bkp.py` | C | Legacy Gradio UI implementation | Archive within the GUI package or drop once parity is confirmed |
| `app/requirements.txt` | C | GUI-specific dependency pinning | Convert into optional extras (e.g., `pip install biomni[esqlabs-app]`) |
| `app/upload.py` | C | File upload router for the app | Keep bundled with the GUI module calling into shared services |
| `biomni/agent/a1.py` | B | Core agent class customized by ESQlabs | Rebase on upstream agent and expose extension hooks for ESQ features |
| `biomni/agent/apak.py` | A | APKA hallucination audit agent | Move into `biomni_esqlabs_tools.apak` and register as optional tool |
| `biomni/env_desc.py` | B | Prompt/environment description helpers | Reconcile diffs; gate ESQ prompts via config flags |
| `biomni/llm.py` | B | LLM factory tweaked for Azure endpoints | Add config-driven provider selection; keep upstream defaults |
| `biomni/model/retriever.py` | B | Retriever tuned for ESQ embeddings | Parameterize ESQ settings via config; retain upstream interface |
| `biomni/tool/biomni_snapshot_tool.py` | A | Tool to inspect/manipulate OSP snapshots | Relocate to `biomni_esqlabs_tools.snapshot` and expose plugin registration |
| `biomni/tool/biomni_tool_json_rag_V2.py` | A | JSON RAG builder used for PBPK inputs | House under ESQ tools package with tight tests |
| `biomni/tool/create_drug_snapshot.py` | A | Workflow helper instructing snapshot creation | Move into ESQ tools and document usage |
| `biomni/tool/pksim_runner.py` | A | PK-Sim CLI integration helpers | Package as optional ESQ tool with dependency guards |
| `biomni_env/setup_path.sh` | B | Shell helper to adjust PATH for biomni_env | Keep as optional script referencing new package layout |
| `create_env.sh` | B | Convenience script to create micromamba env | Parameterize to install ESQ extras without overriding upstream setup |
| `data/generated_snapshot_files/aspirin_snapshot.json` | A | Sample generated snapshot output | Relocate under `data/esqlabs/generated` and load optionally |
| `data/generated_snapshot_files/aspirin_snapshot_erster_test.json` | A | Sample snapshot variant | Store as optional fixture data outside upstream release |
| `data/generated_snapshot_files/fix_2.py` | A | Helper script to clean snapshot JSON | Refactor into tooling tests or remove after port |
| `data/generated_snapshot_files/fix_snapshot.py` | A | Snapshot patching helper | Same as above—consider moving into tests/scripts |
| `data/generated_snapshot_files/ibuprofen_snapshot.json` | A | Sample generated snapshot | Treat as optional fixture |
| `data/generated_snapshot_files/ibuprofen_snapshot_erster_run.json` | A | Another snapshot variant | Same handling as other generated files |
| `data/generated_snapshot_files/metoprolol_snapshot_alt.json` | A | Sample alternative snapshot | Keep as optional dataset |
| `data/snapshot_files/Atazanavir.json` | A | Base snapshot input example | Ship as optional dataset under ESQ data folder |
| `data/snapshot_files/Digoxin.json` | A | Base snapshot input example | Same treatment |
| `data/snapshot_files/Inulin.json` | A | Base snapshot input example | Same treatment |
| `docker-compose.yml` | B | Compose stack for Biomni + GUI | Keep optional compose profile referencing new packages |
| `environment.yml` | B | Conda env description with ESQ deps | Add as `environment.esqlabs.yml` or extras to avoid upstream drift |
| `example.py` | A | Script showing agent workflow with ESQ tools | Move under `examples/esqlabs_snapshot.py` feeding plugin registry |
| `scripts/entrypoint.sh` | B | Container entrypoint launching web UI or agent | Update to use plugin-based detection and keep optional |
| `test_auth.py` | C | Diagnostic script for Azure AD login | Keep alongside ESQ GUI documentation |
| `tutorials/biomni_pmk.ipynb` | C | Internal tutorial notebook | Move to `docs/esqlabs/` and exclude from upstream PR |
| `tutorials/biomni_pmk1.ipynb` | C | Additional internal tutorial | Same handling as above |
| `tutorials/examples/cloning.ipynb` | B | Upstream cloning tutorial with ESQ edits | Reapply upstream version and minimize ESQ-specific content |
| `tutorials/physicochemical_properties.csv` | A | Dataset used by snapshot builder | Keep under ESQ data directory with optional download |

## Target module structure

To keep the Stanford codebase authoritative, upstream directories (e.g., `biomni/agent`, `biomni/model`, `deploy/`) stay in place, while ESQlabs layers its tooling through optional namespaces and registries. The structure below highlights the new modules and where Type A/B/C artifacts land.

### Package layout

```
biomni/
    agent/
        __init__.py
        a1.py                # upstream agent with documented hooks
        extension_hooks.py   # small shim exporting plugin events (if needed)
    env_desc.py             # authoritative environment description
    llm.py                  # upstream provider factory
    model/
        __init__.py
        retriever.py        # exported interface used by plugins
    tool/
        __init__.py
        registry.py         # shared tool registry exposed to plugins
        base.py             # upstream tool contracts
biomni_esqlabs_tools/
    __init__.py
    registry.py             # registers ESQ tool sets with biomni.tool.registry
    apak.py                 # APKA hallucination mitigation agent
    data_lake/
        __init__.py
        descriptors.py      # consolidated env_desc additions (data lake prompts, etc.)
    snapshots/
        __init__.py
        create_drug_snapshot.py
        biomni_snapshot_tool.py
        json_rag_builder.py
    pbpk/
        __init__.py
        pksim_runner.py
    datasets/
        __init__.py
        snapshot_examples/  # JSON fixtures, optionally packaged as data files
biomni_esqlabs_app/
    __init__.py
    config.py               # pydantic/Settings for GUI
    auth.py
    upload.py
    main.py                 # FastAPI/Gradio entrypoint
    main_legacy.py          # previous UI kept for reference
    static/
    templates/
config/
    __init__.py (optional)
    esqlabs_agent_config.yaml
    esqlabs_app.env
examples/
    esqlabs_snapshot.py
    esqlabs_apak_audit.py
```

* Type A modules migrate to `biomni_esqlabs_tools` so they can ship as an installable extra (`pip install biomni[esqlabs-tools]`).
* Type B files such as `biomni/agent/a1.py`, `biomni/env_desc.py` (with its data-lake descriptors), `biomni/llm.py`, and `biomni/model/retriever.py` remain in their upstream paths. ESQlabs-specific logic is wired through hooks/config rather than diverging file copies.
* Type C GUI assets relocate to `biomni_esqlabs_app`, allowing the upstream PR to omit that entire directory.

### Extension mechanism

1. Introduce a lightweight `biomni.tool.registry.ToolRegistry` (or reuse upstream hooks) that exposes `register_toolset(namespace: str, tools: list[Tool])`.
2. `biomni_esqlabs_tools.registry` imports ESQ tool factories (APKA, snapshot helpers, PBPK runners) and registers them under namespaces such as `esqlabs.audit` or `esqlabs.pbpk`.
3. `biomni.agent.a1.A1` (Type B) loads the upstream tools first, then conditionally loads ESQ namespaces based on configuration flags (e.g., `BIOMNI_ENABLE_ESQLABS_TOOLS` or entries inside `config/esqlabs_agent_config.yaml`).
4. The GUI package depends on `biomni_esqlabs_tools` for tool access but the tools never import GUI frameworks, ensuring headless usage.

### Configuration assets

- Add `config/esqlabs_agent_config.yaml` describing:
  - Tool namespaces to enable.
  - Paths to ESQ data lakes/snapshot folders (e.g., the additional files referenced in `biomni/env_desc.py`).
  - Azure/OpenAI endpoints for ESQ usage.
- Expose `BIOMNI_AGENT_CONFIG` env var for overriding the config path.
- Provide `.env.esqlabs` sample aligned with `app/.env` so staff can source the same values locally or in Docker.

### Required __init__.py files

To keep the packages importable, ensure `__init__.py` exists (even if empty) in:

- `biomni_esqlabs_tools/`
- `biomni_esqlabs_tools/data_lake/`
- `biomni_esqlabs_tools/snapshots/`
- `biomni_esqlabs_tools/pbpk/`
- `biomni_esqlabs_tools/datasets/`
- `biomni_esqlabs_app/`
- `biomni_esqlabs_app/static/` (if Python needs to discover templates/assets)

Upstream packages already contain `__init__.py`; only the new directories require additions. Where namespace packages are preferred, we can use implicit namespace packages, but explicit files keep compatibility with existing tooling.

## Implementation notes

- **Type A** modules (APKA, snapshot builders, PK-Sim runner) now live inside `biomni_esqlabs_tools/` with a registry helper so the upstream agent can register them without direct imports. Snapshot fixture data was moved to `data/esqlabs/` to keep optional datasets isolated from the release tarball.
- **Type B** files (`biomni/agent/a1.py`, `biomni/env_desc.py`, `biomni/llm.py`, `biomni/model/retriever.py`) were rebased onto upstream `main` with explicit extension hooks. The hooks keep the Stanford behavior as defaults while allowing ESQlabs-specific descriptors, retry logic, and tool registration to be toggled via `config/esqlabs_agent_config.yaml` or environment variables.
- **Type C** GUI assets were moved to `biomni_esqlabs_app/` with unchanged FastAPI/Gradio behavior. The Docker entrypoint searches for the new module first, and the GUI consumes the shared registry instead of importing core files directly.
- **Infrastructure** restored: Dockerfile/docker-compose now point at `biomni_esqlabs_app.main:app`, using a refreshed `scripts/entrypoint.sh` and the ESQ environment spec (`environment.yml`).
- Configuration assets under `config/` let ESQlabs employees opt into the extensions without touching source files. Setting `BIOMNI_ENABLE_ESQLABS_TOOLS=1` (or editing the YAML file) enables the registry, optional data descriptors, and rate-limit retry wrapper.

## Next steps

1. Backfill unit tests for the registry (`tests/test_esqlabs_registry.py`) to ensure tool discovery works even when optional dependencies (PK-Sim) are missing.
2. Wire CI jobs to lint the new packages and run a minimal `A1` smoke test with `BIOMNI_ENABLE_ESQLABS_TOOLS=1`.
3. When preparing the upstream PR, include only `biomni_esqlabs_tools` + hook changes; keep `biomni_esqlabs_app` and config defaults on the fork.
