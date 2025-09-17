import json, argparse, copy

"""
Takes a template snapshot (JSON) and sets:
- Compound building block (name, type, pKa, MW, lipophilicity, fu, clearance, solubility, permeability, processes)
- Minimal simulation (dose, infusion time; route is chosen by the template)

Note: Exact JSON paths depend on your template.
This mapper shows a robust pattern:
- Find the dummy compound in the template (e.g., first compound block)
- Replace fields via name synonyms
- Adjust the protocol (dose) in the simulation
"""

def main():
    ap = argparse.ArgumentParser(description="Map payload values into a snapshot JSON template.")
    ap.add_argument("--template", required=True, help="Path to the snapshot template JSON.")
    ap.add_argument("--out", required=True, help="Output path for the modified snapshot JSON.")
    ap.add_argument("--payload", required=True, help="Payload as a JSON string.")
    args = ap.parse_args()

    with open(args.template, "r", encoding="utf-8") as f:
        snap = json.load(f)
    payload = json.loads(args.payload)

    # ---- 1) Find compound
    compounds = [bb for bb in snap.get("BuildingBlocks", []) if bb.get("Type", "").lower() == "compound"]
    if not compounds:
        raise RuntimeError("Template contains no compound building block.")
    comp = copy.deepcopy(compounds[0])

    # ---- 2) Set fields (simplified mapper)
    comp["Name"] = payload["name"]
    physchem = comp.setdefault("PhysChem", {})
    physchem["Type"] = payload["type"]  # neutral|acid|base
    physchem["MolecularWeight_g_per_mol"] = payload["MW_g_per_mol"]
    if "pKa" in payload:
        physchem["pKa"] = payload["pKa"]

    lip = payload.get("lipophilicity", {})
    physchem["Lipophilicity"] = {"kind": lip.get("kind", "logMA"), "value": lip.get("value")}

    # Binding
    binding = comp.setdefault("Binding", {})
    if "fu" in payload:
        binding["FractionUnbound"] = payload["fu"]  # [{species, value}]

    # Clearance
    if payload.get("clearance"):
        comp["Clearance"] = payload["clearance"]

    # Solubility / Permeability
    if payload.get("solubility"):
        comp.setdefault("Solubility", {})["profiles"] = payload["solubility"]
    if payload.get("permeability"):
        comp.setdefault("Permeability", {})["intestinal"] = payload["permeability"]

    # Metabolism / Transport
    processes = payload.get("processes", {})
    if processes:
        comp["Processes"] = processes

    # Replace the compound in the snapshot (all occurrences of the dummy compound with 'comp')
    for i, bb in enumerate(snap.get("BuildingBlocks", [])):
        if bb.get("Type", "").lower() == "compound":
            snap["BuildingBlocks"][i] = comp
            break

    # ---- 3) Adjust minimal simulation (dose)
    sims = snap.get("Simulations", [])
    if sims:
        sim = sims[0]
        protocol = sim.setdefault("Protocol", {})
        if payload.get("dose"):
            d = payload["dose"]
            protocol["Amount"] = d.get("amount", 500)
            protocol["Unit"] = d.get("unit", "mg")
            protocol["Times_h"] = d.get("times", [0])
            protocol["Infusion_min"] = d.get("infusion_min", 0)

        # Optional: Species/Individual
        if payload.get("species"):
            sim["Species"] = payload["species"]

    # ---- 4) Save
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(snap, f, indent=2)

if __name__ == "__main__":
    main()
