# Comprehensive Agent Test Prompts

These prompts are designed to test the full spectrum of the Biomni agent's capabilities, including literature research, database queries, PBPK model creation, simulation, analysis, and scientific reporting.

---

## Test Prompt 1: Novel Drug Candidate - Pharmacokinetic Profile Assessment

**Prompt:**
```
Deliver a full PK research + PBPK simulation dossier for Venetoclax (BCL-2 inhibitor).

1) Literature research (save all papers):
- Search PubMed and web sources for physicochemical properties (MW, logP, pKa, solubility), ADME, clinical PK (Cmax, Tmax, AUC, t1/2, CL, Vd), DDIs, and protein binding.
- Extract key numeric values into a structured table with citations and record URLs/PMIDs/DOIs.
- Save all available open-access PDFs and include a download report.

2) PBPK model + simulation:
- Build an adult PBPK model for Venetoclax, 400 mg oral dose, CYP3A4 metabolism.
- Simulate 48 hours with appropriate time step and output concentrations.
- Compute Cmax, Tmax, AUC0-24h and save metrics as CSV.
- Plot the concentration–time profile (linear + semi-log if possible).

3) Reporting:
- Compare predicted PK parameters with clinical literature values (cite each source).
- Produce a comprehensive report with methods, parameters, results tables, plots, and a discussion of discrepancies/assumptions.
- Include a file index listing all generated outputs.
```

---

## Test Prompt 2: Pediatric Dose Optimization Study

**Prompt:**
```
Perform a pediatric dose optimization study for Oseltamivir (Tamiflu) across age groups 2–5 years (15 kg), 6–8 years (25 kg), 9–12 years (40 kg), and adults (70 kg).

1) Literature research (save all papers):
- Collect oseltamivir PK/PD data, MW (312.4 g/mol), logP (1.1), bioavailability (80%), protein binding (3%), half-life (6–10 h), and metabolite (oseltamivir carboxylate) parameters.
- Extract pediatric and adult PK datasets, dosing regimens, and exposure targets (AUC/Cmax) with citations.

2) PBPK modeling + simulation:
- Create PBPK models for each age group with age-appropriate physiology.
- Simulate weight-based dosing (30–75 mg BID) over 5 days; include steady-state assessment.
- Calculate Cmax, AUC, and Tmax for each group and save results as a table.
- Plot all age-group concentration–time profiles on a single figure (legend by age).

3) Analysis + reporting:
- Evaluate dose proportionality and pediatric exposure vs adult targets.
- Provide dosing recommendations and rationale with citations.
- Produce a regulatory-style report including methods, assumptions, sensitivity notes, tables, plots, and a references section.
```

---

## Test Prompt 3: Drug-Drug Interaction Assessment

**Prompt:**
```
Assess the drug–drug interaction between Rifampicin (CYP3A4 inducer) and Midazolam (CYP3A4 substrate).

1) Literature research (save all papers):
- Find clinical DDI studies and induction kinetics data.
- Extract properties: Midazolam (MW 325.8, logP 3.9, high first-pass, t½ 2–4 h), Rifampicin (MW 822.9, CYP3A4 inducer), and exposure changes (AUC/Cmax ratios) from clinical data.

2) PBPK modeling + simulation:
- Build PBPK models for both drugs (midazolam oral, rifampicin oral with enzyme induction).
- Simulate four scenarios: (1) midazolam 5 mg alone, (2) midazolam after 7 days rifampicin 600 mg daily, (3) midazolam after 14 days rifampicin, (4) midazolam 7 days post-rifampicin (recovery).
- Compute AUC and Cmax ratios and save as CSV.
- Plot all concentration–time profiles overlaid and an induction time-course plot.

3) Reporting:
- Compare predictions with published clinical DDI ratios.
- Write a comprehensive report (executive summary, methods, assumptions, results tables, validation plots, DDI comparison, dose adjustment recommendations, and full references).
```

---

## Test Prompt 4: Bupropion Adult PBPK Simulation & Reporting

**Prompt:**
```
Build a full PBPK simulation and report for Bupropion (adult, 70 kg).

1) Literature research (save all papers):
- Collect physicochemical properties (MW, logP, pKa, solubility), protein binding, clearance, and clinical PK metrics (Cmax, Tmax, AUC, t1/2).
- Identify metabolite considerations (hydroxybupropion) and CYP2B6 metabolism references.
- Save all available open-access PDFs and list key citations with PMIDs/DOIs.

2) PBPK modeling + simulation:
- Create an adult PBPK model for Bupropion with a 150 mg oral dose.
- Simulate 72 hours with appropriate resolution.
- Compute Cmax, Tmax, AUC0–24h, AUC0–72h and save results as CSV.
- Plot concentration–time profiles for parent (and metabolite if supported).

3) Reporting:
- Compare simulated PK to literature values and discuss discrepancies.
- Produce a publication-ready report with methods, parameters table, results, plots, sensitivity notes, and a references section.
```

---

## Expected Agent Workflow for Each Prompt

For successful completion, the agent should:

1. **Research Phase:**
   - Use web search and PubMed tools to find relevant papers
   - Save papers using the paper saving tool
   - Extract and organize key data points
   - Document sources with proper citations

2. **Model Building Phase:**
   - Use PBPK snapshot creation tool with gathered parameters
   - Validate parameter choices against literature
   - Document model structure and assumptions

3. **Simulation Phase:**
   - Run PBPK simulations with appropriate settings
   - Handle any simulation errors and retry if needed
   - Verify simulation outputs are generated

4. **Analysis Phase:**
   - Use analysis tools to calculate PK metrics
   - Generate plots with proper formatting
   - Compare predictions with literature data

5. **Reporting Phase:**
   - Synthesize all findings into coherent report
   - Include all required sections (methods, results, discussion)
   - Reference saved papers appropriately
   - Ensure figures and tables are publication-ready

6. **Quality Checks:**
   - Verify all files are saved in chat directory
   - Confirm simulation outputs exist and are readable
   - Check that plots are generated successfully
   - Ensure report is comprehensive and scientifically sound
