import json, copy
from pathlib import Path

p = Path(r"ibuprofen_snapshot.json")
data = json.loads(p.read_text(encoding="utf-8"))

# 1) Individuals → OriginData + Einheiten-Objekte
inds = data.get("Individuals") or []
for ind in inds:
    # OriginData
    if "OriginData" not in ind:
        ind["OriginData"] = {}
    od = ind["OriginData"]
    if "Species" in ind and "Species" not in od:
        od["Species"] = ind.pop("Species")
    od.setdefault("Species", "Human")
    od.setdefault("Population", "European_ICRP_2002")

    # Einheitenfelder
    def ensure_unit(obj, key, unit):
        val = obj.get(key)
        if isinstance(val, (int, float)):
            obj[key] = {"Value": val, "Unit": unit}
    ensure_unit(ind, "Age", "years")
    ensure_unit(ind, "Weight", "kg")
    ensure_unit(ind, "Height", "cm")

data["Individuals"] = inds

# 2) Formulations → Type normalisieren, Dose raus (Dosis ins Protocol)
forms = data.get("Formulations") or []
for f in forms:
    t = (f.get("Type") or "").lower()
    if "tablet" in t or "tablets" in t:
        f["Type"] = "Tablet"
    elif not f.get("Type"):
        # heuristisch aus dem Namen
        if "tablet" in (f.get("Name","").lower()):
            f["Type"] = "Tablet"
        elif "capsule" in (f.get("Name","").lower()):
            f["Type"] = "Capsule"
        else:
            f["Type"] = "OralSolution"
    # optional: Dose entfernen (sauberer)
    f.pop("Dose", None)
data["Formulations"] = forms

# 3) Protocols → Dosing hinzufügen, Applications → Application vereinheitlichen
prots = data.get("Protocols") or []
for pr in prots:
    # Applications -> Application (erstes nehmen)
    if "Applications" in pr and not pr.get("Application"):
        apps = pr.pop("Applications") or []
        if apps:
            pr["Application"] = apps[0]
    # Dosing ergänzen falls fehlt und Formulation 200 mg im Namen hat
    if not pr.get("Dosing"):
        # heuristik: 200 mg Single Dose
        pr["Dosing"] = [{
            "Time": {"Value": 0, "Unit": "h"},
            "Amount": {"Value": 200, "Unit": "mg"}
        }]
data["Protocols"] = prots

# 4) Simulations → Individual als String, CompoundSet -> Compounds, Protocol an Compound
sims = data.get("Simulations") or []
for s in sims:
    # Individual: Objekt -> String(Name)
    ind = s.get("Individual")
    if isinstance(ind, dict) and isinstance(ind.get("Name"), str):
        s["Individual"] = ind["Name"]

    # CompoundSet -> Compounds
    if "CompoundSet" in s and "Compounds" not in s:
        s["Compounds"] = s.pop("CompoundSet")

    # Protocol: Top-Level -> in jeden Compound mergen (falls fehlt)
    top_prot = s.pop("Protocol", None)
    comps = s.get("Compounds") or []
    for c in comps:
        if isinstance(c, str):
            c = {"Name": c}
        if "Protocol" not in c and top_prot:
            c["Protocol"] = top_prot
    s["Compounds"] = comps
data["Simulations"] = sims

# 5) Version sicherheitshalber auf 80 setzen
data["Version"] = 80

# Speichern
p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
print("Patched snapshot written to:", p)
