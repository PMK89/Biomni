# Comprehensive Agent Test Prompts

These prompts are designed to test the full spectrum of the Biomni agent's capabilities, including literature research, database queries, PBPK model creation, simulation, analysis, and scientific reporting.

---

## Test Prompt 1: Novel Drug Candidate - Pharmacokinetic Profile Assessment

**Prompt:**
```
Perform a complete pharmacokinetic analysis for Venetoclax (BCL-2 inhibitor). Search PubMed and databases for physicochemical properties (MW, logP, pKa, solubility), ADME data, clinical PK parameters (Cmax, Tmax, AUC, half-life, clearance, Vd), DDIs, and protein binding. Save all papers you find.

Create a PBPK model for Venetoclax with adult physiology, 400 mg oral dose, and CYP3A4 metabolism. Run the simulation for 48 hours. Analyze the results to calculate Cmax, Tmax, and AUC0-24h. Plot the concentration-time profile.

Compare your predicted PK parameters with the clinical data from literature. Write a comprehensive report summarizing the literature findings, model structure, simulation results, and comparison with clinical data. Include all plots and data tables.
```

---

## Test Prompt 2: Pediatric Dose Optimization Study

**Prompt:**
```
Perform a pediatric dose optimization study for Oseltamivir (Tamiflu) across age groups 2-5 years (15 kg), 6-8 years (25 kg), 9-12 years (40 kg), and adults (70 kg). Search literature for oseltamivir PK data including MW (312.4 g/mol), logP (1.1), bioavailability (80%), protein binding (3%), half-life (6-10 h), and the active metabolite oseltamivir carboxylate. Save all papers.

Create PBPK models for each age group with age-appropriate physiology. Simulate current weight-based dosing (30-75 mg BID) over 5 days. Calculate Cmax, AUC, and Tmax for each group. Plot concentration-time profiles for all age groups on the same graph for comparison.

Analyze dose proportionality across ages and compare pediatric exposure to adult targets. Generate a report with literature review, model methodology, comparative plots, PK parameter tables by age, and dosing recommendations for regulatory submission.
```

---

## Test Prompt 3: Drug-Drug Interaction Assessment

**Prompt:**
```
Assess the drug-drug interaction between Rifampicin (CYP3A4 inducer) and Midazolam (CYP3A4 substrate). Search for clinical DDI studies and extract properties: Midazolam (MW 325.8, logP 3.9, high first-pass, t½ 2-4h) and Rifampicin (MW 822.9, CYP3A4 inducer). Find CYP3A4 induction kinetics data and clinical PK for both drugs alone and combined. Save all papers.

Build PBPK models for both drugs. For midazolam: oral administration with extensive hepatic metabolism. For rifampicin: oral with enzyme induction properties. Simulate four scenarios: (1) midazolam 5 mg alone, (2) midazolam after 7 days rifampicin 600 mg daily, (3) midazolam after 14 days rifampicin, (4) midazolam 7 days post-rifampicin (recovery).

Calculate AUC and Cmax ratios for each scenario. Plot all concentration-time profiles overlaid. Create plots showing enzyme induction time course. Compare predictions with published clinical DDI data. Write a comprehensive report with executive summary, methods, validation plots, DDI comparison plots, statistical tables, dose adjustment recommendations, and full references.
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
