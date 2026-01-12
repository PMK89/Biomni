# PBPK Agent Usage Guide

## Quick Reference for Creating PBPK Snapshots and Running Simulations

When a user asks to create a PBPK simulation, follow this simple workflow:

### Step 1: Find PK Parameters

Use web search or database queries to find these required parameters for the drug:

1. **Molecular weight** (g/mol) - from PubChem, DrugBank
2. **LogP** (lipophilicity) - from PubChem, DrugBank
3. **Fraction unbound** (0-1) - search for "plasma protein binding"
4. **Solubility** (mg/L) - search for "aqueous solubility at pH 7.4"

You can use the helper tool first:
```python
get_drug_pk_parameters("DrugName")
```

### Step 2: Create the Snapshot

Use `create_pbpk_snapshot` - this is the RECOMMENDED tool (NOT `create_drug_snapshot` or `rag_json_build`):

```python
result = create_pbpk_snapshot(
    drug_name="Bupropion",
    dose_mg=150.0,
    molecular_weight=239.74,
    log_p=3.6,
    fraction_unbound=0.16,
    solubility_mg_l=312.0,
    # Optional parameters with defaults:
    # reference_ph=7.4,
    # individual_name="HealthyAdult",
    # population="European_ICRP_2002",
    # age_years=30.0,
    # weight_kg=70.0,
    # height_cm=175.0,
    # formulation_type="Formulation_Tablet_Weibull",
    # simulation_duration_h=24.0,
    # out_path=None  # auto-generated if not specified
)
```

The function returns a dict with:
- `status`: "success" or "error"
- `file_path`: path to the created snapshot file
- `message`: status message
- `next_step`: guidance on what to do next

### Step 3: Run the Simulation (Optional)

If PK-Sim is installed on the system:

```python
result = run_pbpk_simulation(
    snapshot_path="/path/to/snapshot.json",
    # Optional:
    # output_dir=None,  # uses snapshot directory if not specified
    # export_pkml=True,
    # timeout_seconds=300
)
```

## Common Mistakes to Avoid

### ❌ DON'T DO THIS:
```python
# These old tools have issues:
create_drug_snapshot(...)  # Complex, requires multiple steps
rag_json_build(...)  # Requires example files that may not exist
```

### ✅ DO THIS INSTEAD:
```python
# Use the new simplified tool:
create_pbpk_snapshot(...)  # All-in-one, creates valid snapshot directly
```

## Example: Complete Bupropion Workflow

```python
# 1. Get parameter guidance
guidance = get_drug_pk_parameters("Bupropion")
print(guidance)

# 2. Search for parameters (example using web search)
# Search for: "Bupropion molecular weight"
# Search for: "Bupropion LogP"
# Search for: "Bupropion plasma protein binding"
# Search for: "Bupropion solubility"

# 3. Create snapshot with found parameters
result = create_pbpk_snapshot(
    drug_name="Bupropion",
    dose_mg=150.0,
    molecular_weight=239.74,  # from PubChem
    log_p=3.6,                # from DrugBank
    fraction_unbound=0.16,     # 84% protein bound = 16% unbound
    solubility_mg_l=312.0,     # from literature
)

if result["status"] == "success":
    print(f"Snapshot created: {result['file_path']}")

    # 4. Optionally run simulation if PK-Sim is available
    sim_result = run_pbpk_simulation(
        snapshot_path=result['file_path']
    )

    if sim_result["status"] == "success":
        print(f"Simulation complete!")
        print(f"Project: {sim_result['outputs']['project_file']}")
        if 'pkml_file' in sim_result['outputs']:
            print(f"PKML: {sim_result['outputs']['pkml_file']}")
else:
    print(f"Error: {result['error']}")
    if 'missing_parameters' in result:
        print(f"Missing: {result['missing_parameters']}")
    if 'hint' in result:
        print(f"Hint: {result['hint']}")
```

## Parameter Sources

| Parameter | Best Sources |
|-----------|--------------|
| Molecular Weight | PubChem, DrugBank, ChemSpider |
| LogP | DrugBank, PubChem, literature |
| Fraction Unbound | DrugBank "plasma protein binding" section, clinical literature |
| Solubility | PubChem, DrugBank, scientific papers |

## File Locations

Example snapshot files are located at:
```
/home/pmk/Biomni/data/esqlabs/snapshot_files/
```

These include:
- Inulin.json
- Atazanavir.json
- Digoxin.json

## Tool Priority

When creating PBPK snapshots, prefer tools in this order:

1. **create_pbpk_snapshot** ⭐ RECOMMENDED - Simple, reliable, creates valid snapshots
2. **run_pbpk_simulation** - Runs simulations from snapshots
3. **get_drug_pk_parameters** - Helper for finding parameters
4. ~~create_drug_snapshot~~ - Legacy, complex workflow
5. ~~rag_json_build~~ - Legacy, requires example files
