import json
from pathlib import Path

SNAP = Path(r"C:\Users\mkoenig\DFKI\CITAH\ESQLabs\Biomni\data\generated_snapshot_files\ibuprofen_snapshot.json")

d = json.loads(SNAP.read_text(encoding="utf-8"))

# --- Helper ------------------------------------------------------
def first_name(seq, fallback=None):
    if isinstance(seq, list) and seq:
        n = seq[0].get("Name") if isinstance(seq[0], dict) else None
        return n or fallback
    return fallback

# 1) Stelle sicher, dass es einen Compound 'Ibuprofen' gibt
compounds = d.get("Compounds") or []
if not compounds:
    compounds = [{"Name": "Ibuprofen", "IsSmallMolecule": True, "Parameters": []}]
    d["Compounds"] = compounds

target_compound = first_name(compounds, "Ibuprofen")

# 2) Wähle ein existierendes Protocol und eine existierende Formulation
protocols = d.get("Protocols") or []
formulations = d.get("Formulations") or []

protocol_name = first_name(protocols, "200mg_SD")
if not protocols:
    # Minimal-Protocol anlegen, falls leer
    protocols = [{
        "Name": protocol_name,
        "Schemas": [{
            "Name": "Schema 1",
            "SchemaItems": [{
                "Name": "Schema Item 1",
                "ApplicationType": "Oral",
                "FormulationKey": "Formulation",
                "Parameters": [
                    {"Name": "Start time", "Value": 0.0, "Unit": "h"},
                    {"Name": "InputDose", "Value": 200.0, "Unit": "mg"},
                    {"Name": "Volume of water/body weight", "Value": 3.5, "Unit": "ml/kg"},
                ],
            }],
            "Parameters": [
                {"Name": "Start time", "Value": 0.0, "Unit": "h"},
                {"Name": "NumberOfRepetitions", "Value": 1.0},
                {"Name": "TimeBetweenRepetitions", "Value": 24.0, "Unit": "h"},
            ],
        }],
        "TimeUnit": "h",
    }]
    d["Protocols"] = protocols

formulation_name = first_name(formulations, "Ibuprofen IR Tablet 200 mg")
if not formulations:
    # Minimal-Formulation anlegen, falls leer
    formulations = [{
        "Name": formulation_name,
        "FormulationType": "Formulation_Tablet_Weibull",
        "Parameters": [
            {"Name": "Dissolution time (50% dissolved)", "Value": 10.0, "Unit": "min"},
            {"Name": "Lag time", "Value": 0.0, "Unit": "min"},
            {"Name": "Dissolution shape", "Value": 1.5},
            {"Name": "Use as suspension", "Value": 1.0},
        ],
    }]
    d["Formulations"] = formulations

# 3) Individuals – nimm vorhandenen, sonst lege Standard an
individuals = d.get("Individuals") or []
if not individuals:
    individuals = [{
        "Name": "Standard Adult",
        "OriginData": {"Species": "Human", "Population": "European_ICRP_2002"},
        "Gender": "Male",
        "Age": {"Value": 30, "Unit": "years"},
        "Weight": {"Value": 70, "Unit": "kg"},
        "Height": {"Value": 175, "Unit": "cm"},
    }]
    d["Individuals"] = individuals
default_individual = first_name(individuals, "Standard Adult")

# 4) Simulations bereinigen und auf Ibuprofen mappen
sims = d.get("Simulations") or []
if not sims:
    # Minimal-Simulation erzeugen
    sims = [{
        "Name": "Ibuprofen_200mg_SD",
        "Model": "4Comp",
        "Individual": default_individual,
        "Compounds": [{
            "Name": target_compound,
            "Protocol": {"Name": protocol_name, "Formulations": [{"Name": formulation_name, "Key": "Formulation"}]},
        }],
        "OutputSchema": [{
            "Parameters": [
                {"Name": "Start time", "Value": 0.0, "Unit": "h"},
                {"Name": "End time", "Value": 24.0, "Unit": "h"},
                {"Name": "Resolution", "Value": 4.0, "Unit": "pts/h"},
            ]
        }],
    }]
else:
    for s in sims:
        # Individual verlinken
        s["Individual"] = default_individual

        # Compounds in der Simulation auf Ibuprofen setzen
        comp_list = s.get("Compounds") or []
        if not comp_list:
            comp_list = [{}]
        for c in comp_list:
            c["Name"] = target_compound
            prot = c.get("Protocol") or {}
            prot["Name"] = protocol_name
            # Formulation-Link sicherstellen
            forms = prot.get("Formulations") or []
            if not any(isinstance(f, dict) and f.get("Name") == formulation_name for f in forms):
                forms.append({"Name": formulation_name, "Key": "Formulation"})
            prot["Formulations"] = forms
            c["Protocol"] = prot
        s["Compounds"] = comp_list

        # Saubermachen: fremde Artefakte entfernen
        s.pop("ObservedData", None)
        s.pop("ObservedDataClassifications", None)
        s.pop("Interactions", None)
        s.pop("Parameters", None)  # fremde "Path": "Events|300mg_BID|..." Einträge entfernen

        # ggf. neutralen Namen setzen
        if "Ibuprofen" not in s.get("Name",""):
            s["Name"] = "Ibuprofen_200mg_SD"

d["Simulations"] = sims

# 5) Optional: Atazanavir-Referenzen auf Top-Level entfernen (ObservedData, Classifications)
for key in ["ObservedData", "ObservedDataClassifications", "SimulationClassifications"]:
    if key in d:
        d.pop(key, None)

# 6) Version
d["Version"] = 80

SNAP.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
print("✅ Simulations & Referenzen auf Ibuprofen gemappt, Fremd-Artefakte entfernt.")
