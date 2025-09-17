PBPK Bupropion (Parent + Hydroxy/Threo/Erythro) — Assets and Steps
Date: 2025-09-17

Deliverables:
- parameter_log.json: All parameters with values, units, sources, and assumptions flagged.
- bupropion_pbpk_snapshot.json: PK-Sim snapshot template (Berezhkovskiy distribution; enzyme network defined; adult population and IR 150 mg protocol; observers listed).
- run_bupropion_snapshot.R: Headless runner script for ospsuite R. If direct snapshot import is not available in R, import snapshot in PK-Sim GUI and export PKML, then run via ospsuite R.

Parameter sourcing discipline:
- Prefer Marok 2021 Pharmaceutics (PMID 33806634) for kinetics and structure.
- FDA/DailyMed Wellbutrin label for protein binding and clinical PK facts (verify: bupropion ~84% bound; hydroxy ~77%; threo/erythro ~42%).
- PubChem for identifiers, MW, logP; HMDB for pKa if available.
- Primary literature for CYP2C19 minor contribution and carbonyl reductases (Connarn 2015; Chen 2010; Sager 2016).

Validation (IR 150 mg single dose; Adults 18–55 y):
1) Run the simulation and export plasma concentration-time CSVs for parent and metabolites.
2) Compute metrics:
   - AUC0-t (noncompartmental; linear-up log-down)
   - Cmax, Tmax
   - AUC ratios: Hydroxy/Parent, Threo/Parent, Erythro/Parent
3) Compare against Marok 2021 figures/tables (target within 2-fold).
4) Sensitivity:
   - Vary fu_plasma for each analyte ±50%
   - Vary Blood:Plasma from 0.7 to 1.3
   - Document changes in Cmax, AUC, and ratios.

Known gaps requiring local fill before run:
- Kinetic parameters (Km/Vmax or clearance scalars) for CYP2B6, CYP2C19, CBR/AKR/11β-HSD, and UGT2B7 must be taken from Marok 2021 supplement/tables.
- pKa values per analyte (for ionization in distribution) should be sourced (e.g., HMDB or Marok); currently placeholders.
- Protein binding percentages should be verified against the exact label version you intend to reference.

Run instructions (recommended):
- Open PK-Sim (v11+), import the snapshot JSON.
- Fill kinetics from Marok 2021 and confirm binding/pKa values.
- Create and run the IR 150 mg adult simulation; export PKML and CSVs.
- Use run_bupropion_snapshot.R (with ospsuite) to run/export headlessly for batch or sensitivity analyses.
