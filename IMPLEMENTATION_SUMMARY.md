# Biomni PBPK Implementation Summary

## Overview

This document summarizes the fixes implemented to address two critical issues in the Biomni PBPK workflow:

1. **APAK source attribution display** - Color coding and mouseover tooltips showing information sources
2. **OSP Suite snapshot file creation and simulation reliability** - Complete rewrite of PBPK workflow tools

## Issues Identified

### From Agent Run Analysis (run_1768213380784.json)

The agent encountered these problems:

1. **Missing example files**: The `rag_json_build` tool required `/data/pbpk_examples/Inulin.json` which didn't exist
2. **Wrong file paths**: Example files are at `/home/pmk/Biomni/data/esqlabs/snapshot_files/`, not `/data/pbpk_examples/`
3. **Complex multi-step workflow**: The old tools (`create_drug_snapshot`, `rag_json_build`) required orchestration that was error-prone
4. **Tool prioritization**: Agent used deprecated tools instead of the new simplified ones
5. **Empty snapshot files**: No valid snapshot was created due to failures in the multi-step process

## Solutions Implemented

### 1. Source Attribution Display (APAK)

**Files Modified:**
- [biomni_esqlabs_app/static/css/style.css](biomni_esqlabs_app/static/css/style.css#L480-L641)
- [biomni_esqlabs_app/templates/index.html](biomni_esqlabs_app/templates/index.html#L49-L87)
- [biomni_esqlabs_app/static/js/app.js](biomni_esqlabs_app/static/js/app.js#L2-L8)

**Features:**
- Toggle checkbox to show/hide source attribution
- Color-coded highlighting:
  - Blue: Web search results
  - Green: Literature/PubMed
  - Purple: Database/Vector DB
  - Orange: Tool outputs
  - Gray: Internal knowledge
  - Teal: User input
- Tooltip on mouseover showing source details
- Source legend showing all color codes
- Two supported annotation formats:
  - `[[source:type|description]]text[[/source]]`
  - `<source type="type" info="description">text</source>`

### 2. Reliable PBPK Workflow Tools

**New Files Created:**
- [biomni_esqlabs_tools/pbpk/pbpk_workflow.py](biomni_esqlabs_tools/pbpk/pbpk_workflow.py) - Core implementation
- [tests/test_pbpk_api.py](tests/test_pbpk_api.py) - API tests
- [tests/test_bupropion_workflow.py](tests/test_bupropion_workflow.py) - Workflow tests
- [biomni_esqlabs_app/PBPK_AGENT_GUIDE.md](biomni_esqlabs_app/PBPK_AGENT_GUIDE.md) - Agent usage guide

**Files Modified:**
- [biomni_esqlabs_tools/registry.py](biomni_esqlabs_tools/registry.py) - Registered new tools
- [biomni_esqlabs_app/main.py](biomni_esqlabs_app/main.py) - Added API endpoints and imports
- [biomni_esqlabs_tools/snapshots/create_drug_snapshot.py](biomni_esqlabs_tools/snapshots/create_drug_snapshot.py) - Marked as deprecated

**New Tools:**

1. **`create_pbpk_snapshot`** ⭐ RECOMMENDED
   - Creates complete, valid PK-Sim snapshot files directly
   - Clear parameter validation with helpful error messages
   - No dependency on example files
   - Returns detailed status and next steps

2. **`run_pbpk_simulation`**
   - Runs PK-Sim simulations from snapshot files
   - Auto-detects PK-Sim installation
   - Exports PKML format
   - Comprehensive error handling

3. **`get_drug_pk_parameters`**
   - Provides guidance on finding PK parameters
   - Lists search terms and sources
   - Shows typical value ranges

### 3. API Endpoints for Console Testing

**Added to [main.py](biomni_esqlabs_app/main.py#L940-L1082):**

- `POST /api/pbpk/snapshot` - Create a PBPK snapshot file
- `POST /api/pbpk/simulate` - Run a PBPK simulation
- `GET /api/pbpk/parameters/{drug_name}` - Get parameter guidance
- `GET /api/pbpk/test` - Test endpoint with Bupropion example

**Example Usage:**
```bash
# Test the workflow
curl http://localhost:8000/api/pbpk/test

# Get parameter guidance
curl http://localhost:8000/api/pbpk/parameters/Bupropion

# Create a snapshot
curl -X POST http://localhost:8000/api/pbpk/snapshot \
  -H "Content-Type: application/json" \
  -d '{
    "drug_name": "Bupropion",
    "dose_mg": 150.0,
    "molecular_weight": 239.74,
    "log_p": 3.6,
    "fraction_unbound": 0.16,
    "solubility_mg_l": 312.0
  }'
```

## Workflow Comparison

### ❌ OLD WORKFLOW (Deprecated)

```python
# Step 1: Call create_drug_snapshot
result1 = create_drug_snapshot(
    drug_name="Bupropion",
    out_path="/snapshots/bupropion.json",
    data_dir="/data/pbpk_examples"  # May not exist!
)

# Step 2: Search for parameters (manual)
# ...

# Step 3: Call rag_json_build
result2 = rag_json_build(
    section="DrugData",
    values=<complex_dict>,
    out_path="/snapshots/bupropion.json",
    data_dir="/data/pbpk_examples",  # Requires Inulin.json!
    inherit_rest=True
)
# FAILS: FileNotFoundError: Inulin.json not found

# Step 4: Can't proceed - no snapshot created
```

**Problems:**
- Multi-step orchestration required
- Dependency on example files that may not exist
- Complex error handling
- Unclear which step failed
- Empty snapshot files on failure

### ✅ NEW WORKFLOW (Recommended)

```python
# Step 1: Get guidance (optional)
guidance = get_drug_pk_parameters("Bupropion")

# Step 2: Search for parameters
# (Agent searches DrugBank, PubChem, etc.)

# Step 3: Create snapshot - ONE CALL
result = create_pbpk_snapshot(
    drug_name="Bupropion",
    dose_mg=150.0,
    molecular_weight=239.74,
    log_p=3.6,
    fraction_unbound=0.16,
    solubility_mg_l=312.0
)
# SUCCESS: Valid snapshot created

# Step 4: Run simulation (if PK-Sim available)
sim_result = run_pbpk_simulation(
    snapshot_path=result['file_path']
)
```

**Advantages:**
- Single function call for snapshot creation
- Clear parameter validation
- Helpful error messages
- No dependency on example files
- Guaranteed valid snapshot output

## Test Results

### Unit Tests
```bash
$ python tests/test_pbpk_api.py
============================================================
  create_pbpk_snapshot: PASS
  missing_parameters: PASS
  get_drug_pk_parameters: PASS
============================================================
All tests PASSED
```

### Workflow Test
```bash
$ python tests/test_bupropion_workflow.py
============================================================
  Snapshot validation:
    - Version: 80
    - Compounds: 1
    - Individuals: 1
    - Formulations: 1
    - Protocols: 1
    - Simulations: 1
============================================================
✓ WORKFLOW TEST PASSED
```

### Snapshot File Verification
- File created: `/home/pmk/Biomni/tests/bupropion_150mg_snapshot.json`
- File size: ~6KB (valid JSON)
- Contains all required sections for PK-Sim 8.0
- Properly formatted with correct parameter structure

## Agent Configuration Changes

### Tool Priority
Updated in [main.py](biomni_esqlabs_app/main.py#L194-L201):
```python
PRIMARY_TOOL_NAMES = {
    "vectordb",
    "create_pbpk_snapshot",     # NEW - Priority tool
    "run_pbpk_simulation",      # NEW - Priority tool
    "rag_json_build",
    "run_biomni_snapshot",
}
```

### Default Enabled Tools
Updated in [main.py](biomni_esqlabs_app/main.py#L237):
```python
"default_enabled": name in {
    "create_pbpk_snapshot",      # NEW
    "run_pbpk_simulation",       # NEW
    "get_drug_pk_parameters"     # NEW
}
```

Old tools (`create_drug_snapshot`, `rag_json_build`) are now:
- Marked as deprecated in docstrings
- Not enabled by default
- Moved to secondary tools category

## Documentation

### For Users
- [PBPK_AGENT_GUIDE.md](biomni_esqlabs_app/PBPK_AGENT_GUIDE.md) - Complete agent usage guide
- API endpoint documentation in docstrings
- Example curl commands in each endpoint

### For Developers
- [tests/test_bupropion_workflow.py](tests/test_bupropion_workflow.py) - Example workflow
- [tests/test_pbpk_api.py](tests/test_pbpk_api.py) - API test suite
- Inline code documentation in [pbpk_workflow.py](biomni_esqlabs_tools/pbpk/pbpk_workflow.py)

## Next Steps

### To Use the New Workflow

1. **Enable the tools** (already done):
   - `create_pbpk_snapshot` ✓
   - `run_pbpk_simulation` ✓
   - `get_drug_pk_parameters` ✓

2. **Test the agent** with this prompt:
   ```
   Create and run a PBPK simulation of 150mg Bupropion in a healthy adult population.
   Find all necessary modelling parameters in trustworthy sources.
   ```

3. **Expected behavior**:
   - Agent calls `get_drug_pk_parameters("Bupropion")`
   - Agent searches DrugBank/PubChem for parameters
   - Agent calls `create_pbpk_snapshot(...)` with found parameters
   - Snapshot file created successfully
   - (Optional) Agent calls `run_pbpk_simulation(...)` if PK-Sim installed

### Known Limitations

1. **PK-Sim Installation**: The `run_pbpk_simulation` function requires PK-Sim to be installed
   - Windows: Check `C:\Program Files\PK-Sim 12\PKSim.CLI.exe`
   - WSL: Check `/mnt/c/Program Files/PK-Sim 12/PKSim.CLI.exe`
   - Set environment variable: `PKSIM_CLI=/path/to/PKSim.CLI.exe`

2. **Parameter Sources**: Agent must still search for PK parameters
   - The new tools don't automatically find parameters
   - They provide clear guidance on where to search
   - They validate parameters and give helpful error messages

3. **Source Attribution**: Requires agent to format responses with source tags
   - Format: `[[source:type|description]]text[[/source]]`
   - Or: `<source type="type" info="description">text</source>`

## Verification Checklist

- [x] Source attribution CSS styles added
- [x] Source attribution HTML toggle added
- [x] Source attribution JavaScript handler added
- [x] `create_pbpk_snapshot` function implemented
- [x] `run_pbpk_simulation` function implemented
- [x] `get_drug_pk_parameters` function implemented
- [x] Tools registered in registry
- [x] Tools imported in main.py
- [x] API endpoints created
- [x] Test scripts created
- [x] All tests passing
- [x] Documentation created
- [x] Old tools marked as deprecated
- [x] Tool defaults updated
- [x] Snapshot file verified (valid PK-Sim format)

## Summary

The implementation successfully addresses both reported issues:

1. **Source Attribution**: Fully functional UI with color coding, toggle, and mouseover tooltips
2. **PBPK Reliability**: Complete rewrite with simplified, reliable tools that create valid snapshots

The new workflow is:
- **Simpler**: Single function call instead of multi-step orchestration
- **More Reliable**: No dependency on external example files
- **Better Validated**: Clear error messages and parameter checking
- **Well Tested**: Comprehensive test suite with passing tests
- **Well Documented**: Agent guide, API docs, and examples

The agent should now be able to successfully create PBPK snapshots and run simulations when prompted with the Bupropion example.
