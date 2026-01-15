import json
import re
import math
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional
from functools import lru_cache

__all__ = [
    "rag_json_sections",
    "rag_json_template",
    "rag_json_answer",
    "rag_json_build",
    "rag_snapshot_autobuild",
]

# -----------------------------
# Simple tokenizer & TF-IDF for example retrieval
# -----------------------------
_STOP = set(
    """a an the and or if to of in on for with by from as at is are was were be been being
ein eine einen einem einer und oder der die das des den dem im am zu vom beim mit aus als ist sind war
waren sein gewesen werden wird""".split()
)

def _tok(text: str) -> List[str]:
    text = text.lower()
    toks = re.split(r"[^a-z0-9_äöüß]+", text)
    return [t for t in toks if t and t not in _STOP]

class _TfIdf:
    def __init__(self):
        self.doc_terms: Dict[int, Dict[str, float]] = {}
        self.doc_norm: Dict[int, float] = {}
        self.df: Dict[str, int] = {}
        self.N = 0
        self.meta: List[Dict[str, Any]] = []

    def add(self, text: str, meta: Dict[str, Any]):
        tf: Dict[str, int] = {}
        for t in _tok(text):
            tf[t] = tf.get(t, 0) + 1
        self.N += 1
        doc_id = self.N - 1
        self.meta.append(meta)
        for t in tf:
            self.df[t] = self.df.get(t, 0) + 1
        self.doc_terms[doc_id] = tf

    def finalize(self):
        for i, tf in self.doc_terms.items():
            tfidf = {}
            for t, c in tf.items():
                idf = math.log((1 + self.N) / (1 + self.df.get(t, 0))) + 1.0
                tfidf[t] = (1 + math.log(c)) * idf
            self.doc_terms[i] = tfidf
            self.doc_norm[i] = math.sqrt(sum(v * v for v in tfidf.values())) or 1.0

    def query(self, q: str, topk: int = 5) -> List[Tuple[float, Dict[str, Any]]]:
        qtf: Dict[str, int] = {}
        for t in _tok(q):
            qtf[t] = qtf.get(t, 0) + 1
        if not qtf:
            return []
        qv = {}
        for t, c in qtf.items():
            idf = math.log((1 + self.N) / (1 + self.df.get(t, 0))) + 1.0
            qv[t] = (1 + math.log(c)) * idf
        qn = math.sqrt(sum(v * v for v in qv.values())) or 1.0
        out = []
        for i, tfidf in self.doc_terms.items():
            dot = 0.0
            for t, v in qv.items():
                if t in tfidf:
                    dot += v * tfidf[t]
            sim = dot / (qn * self.doc_norm[i])
            if sim > 0:
                out.append((sim, self.meta[i]))
        out.sort(key=lambda x: x[0], reverse=True)
        return out[:topk]

# -----------------------------
# JSON schema inference helpers
# -----------------------------
def _merge(a: Optional[dict], b: Optional[dict]) -> dict:
    if not a:
        return b or {}
    if not b:
        return a
    ta, tb = a.get("type"), b.get("type")
    if ta == tb:
        if ta == "object":
            props = {}
            keys = set(a.get("props", {})) | set(b.get("props", {}))
            for k in keys:
                props[k] = _merge(a.get("props", {}).get(k), b.get("props", {}).get(k))
            return {"type": "object", "props": props}
        if ta == "array":
            return {"type": "array", "items": _merge(a.get("items"), b.get("items"))}
        return a
    return {"type": "any"}

def _infer(x: Any) -> dict:
    if isinstance(x, dict):
        return {"type": "object", "props": {k: _infer(v) for k, v in x.items()}}
    if isinstance(x, list):
        if not x:
            return {"type": "array", "items": {"type": "any"}}
        s = None
        for el in x:
            s = _merge(s, _infer(el))
        return {"type": "array", "items": s}
    if isinstance(x, bool):
        return {"type": "boolean"}
    if isinstance(x, (int, float)):
        return {"type": "number"}
    if x is None:
        return {"type": "null"}
    return {"type": "string"}

def _tmpl(schema: dict) -> Any:
    t = schema.get("type")
    if t == "object":
        return {k: _tmpl(v) for k, v in schema.get("props", {}).items()}
    if t == "array":
        return [_tmpl(schema.get("items", {"type": "any"}))]
    if t == "number":
        return "<number>"
    if t == "boolean":
        return "<true|false>"
    if t == "null":
        return None
    if t == "string":
        return "<string>"
    return "<any>"

def _iter_chunks(fname: str, data: Any):
    if isinstance(data, dict):
        for k, v in data.items():
            if isinstance(v, list):
                for i, el in enumerate(v):
                    path = f"{fname}::{k}[{i}]"
                    text = (
                        f"SECTION:{k}\nFILENAME:{fname}\nINDEX:{i}\n"
                        + json.dumps(el, ensure_ascii=False, indent=2)
                    )
                    yield (k, path, text, el)
            else:
                path = f"{fname}::{k}"
                text = f"SECTION:{k}\nFILENAME:{fname}\n" + json.dumps(v, ensure_ascii=False, indent=2)
                yield (k, path, text, v)
    else:
        path = f"{fname}::value"
        yield ("value", path, str(data), data)

# -----------------------------
# Snapshot sanitation for PK-Sim (incl. robust array normalization + minimal builders)
# -----------------------------
def _first_or_none(seq):
    return seq[0] if isinstance(seq, list) and seq else None

def _ensure_version(result: dict):
    result["Version"] = 80

def _ensure_array_field(obj: dict, key: str):
    """Ensure obj[key] is a list if it is a dict (singleton); None -> []."""
    val = obj.get(key)
    if isinstance(val, list):
        return
    if isinstance(val, dict):
        obj[key] = [val]
    elif val is None:
        obj[key] = []
    else:
        obj[key] = [val]

def _normalize_root_sections_to_arrays(result: dict):
    """Normalize root sections that PK-Sim expects as arrays."""
    must_be_arrays = [
        "Compounds",
        "Events",
        "ExpressionProfiles",
        "Formulations",
        "Individuals",
        "ObservedData",
        "ObservedDataClassifications",
        "Protocols",
        "SimulationClassifications",
        "Simulations",
    ]
    for k in must_be_arrays:
        _ensure_array_field(result, k)

def _sanitize_individuals(result: dict, default_population: str = "European_ICRP_2002"):
    inds = result.get("Individuals")
    if not isinstance(inds, list):
        return
    for ind in inds:
        if not isinstance(ind, dict):
            continue
        origin = ind.get("OriginData", {})
        if not isinstance(origin, dict):
            origin = {}
        species_val = origin.get("Species")
        if isinstance(species_val, str) and species_val.strip():
            species_str = species_val.strip()
        elif isinstance(species_val, dict) and isinstance(species_val.get("Name"), str):
            species_str = species_val["Name"].strip()
        elif isinstance(ind.get("Species"), str) and ind["Species"].strip():
            species_str = ind["Species"].strip()
        else:
            species_str = "Human"
        origin["Species"] = species_str
        pop = origin.get("Population")
        if not isinstance(pop, str) or not pop.strip():
            origin["Population"] = default_population
        ind["OriginData"] = origin

def _ensure_individual_units(result: dict):
    inds = result.get("Individuals")
    if not isinstance(inds, list):
        return
    for ind in inds:
        if not isinstance(ind, dict):
            continue
        def _wrap(obj, key, unit):
            val = obj.get(key)
            if isinstance(val, (int, float)):
                obj[key] = {"Value": val, "Unit": unit}
        _wrap(ind, "Age", "years")
        _wrap(ind, "Weight", "kg")
        _wrap(ind, "Height", "cm")

def _ensure_minimal_individual_if_needed(result: dict):
    """Create a minimal individual if none exists."""
    inds = result.get("Individuals")
    if not isinstance(inds, list) or not inds:
        result["Individuals"] = [{
            "Name": "Individual_1",
            "Age": {"Value": 30, "Unit": "years"},
            "Weight": {"Value": 70, "Unit": "kg"},
            "Height": {"Value": 175, "Unit": "cm"},
            "OriginData": {"Species": "Human", "Population": "European_ICRP_2002"},
        }]

# ---- learn valid formulation types & model names from examples ----
def _collect_valid_formulation_types(data_dir: Path) -> List[str]:
    types = set()
    for p in data_dir.glob("*.json"):
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        for f in obj.get("Formulations") or []:
            t = (f.get("FormulationType") or f.get("Type") or "").strip()
            if t:
                types.add(t)
    return sorted(types)

def _choose_formulation_type(name: str, valid_types: List[str]) -> str:
    lname = (name or "").lower()
    if any("tablet" in t.lower() for t in valid_types):
        if "tablet" in lname:
            for t in valid_types:
                if "tablet" in t.lower():
                    return t
    for pref in ["Formulation_Tablet_Weibull", "OralSolution", "Capsule"]:
        for t in valid_types:
            if t.lower() == pref.lower():
                return t
    return valid_types[0] if valid_types else "OralSolution"

def _collect_model_names(data_dir: Path) -> List[str]:
    names = set()
    for p in data_dir.glob("*.json"):
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        for s in obj.get("Simulations") or []:
            m = s.get("Model") or s.get("ModelName")
            if isinstance(m, str) and m.strip():
                names.add(m.strip())
            mp = s.get("ModelProperties") or {}
            m2 = mp.get("Model") or mp.get("Name")
            if isinstance(m2, str) and m2.strip():
                names.add(m2.strip())
    return sorted(names)

def _preferred_model(valid_models: List[str]) -> str:
    for pref in ["4Comp", "WholeBody", "Whole-Body", "MinimalPBPK"]:
        for m in valid_models:
            if m.lower() == pref.lower():
                return m
    return valid_models[0] if valid_models else "4Comp"

# ---- compounds: map generic keys to PK-Sim structures ----
def _sanitize_compounds_to_pksim(result: dict):
    comps = result.get("Compounds")
    if not isinstance(comps, list):
        return
    for c in comps:
        if not isinstance(c, dict):
            continue
        c["IsSmallMolecule"] = True

        props = c.get("properties") or c.get("Properties") or {}
        # Molecular weight
        mw = None
        if isinstance(props.get("molecularWeight"), dict):
            mw = props["molecularWeight"].get("value")
        if isinstance(mw, (int, float)):
            c["Parameters"] = [
                {"Name": "Molecular weight", "Value": float(mw), "Unit": "g/mol"}
            ]
        else:
            c.setdefault("Parameters", c.get("Parameters", []))

        # Lipophilicity (logP)
        lip = None
        if isinstance(props.get("lipophilicity"), dict):
            lip = props["lipophilicity"].get("value")
        if isinstance(lip, (int, float)):
            c["Lipophilicity"] = [{
                "Name": "Measurement",
                "Parameters": [{"Name": "Lipophilicity", "Value": float(lip), "Unit": "Log Units"}]
            }]

        # Fraction unbound
        fu = None
        if isinstance(props.get("fractionUnboundPlasma"), dict):
            fu = props["fractionUnboundPlasma"].get("value")
        if isinstance(fu, (int, float)):
            c["FractionUnbound"] = [{
                "Name": "Measurement",
                "Species": "Human",
                "Parameters": [{"Name": "Fraction unbound (plasma, reference value)", "Value": float(fu)}]
            }]

        # Solubility at reference pH
        sol_entry = None
        if isinstance(props.get("solubility"), list) and props["solubility"]:
            sol_entry = props["solubility"][0]
        if isinstance(sol_entry, dict):
            val = sol_entry.get("value")
            ph = sol_entry.get("pH", 7.0)
            if isinstance(val, (int, float)):
                c["Solubility"] = [{
                    "Name": "Assumption",
                    "Parameters": [
                        {"Name": "Solubility at reference pH", "Value": float(val), "Unit": "mg/l"},
                        {"Name": "Reference pH", "Value": float(ph)}
                    ]
                }]

        # clean up generic blocks if mapped
        if any(k in c for k in ["Parameters", "Lipophilicity", "FractionUnbound", "Solubility"]):
            for k in ["properties", "Properties", "ADME"]:
                c.pop(k, None)

# ---- formulations: ensure FormulationType + Name; create default if missing ----
def _sanitize_formulations(result: dict, data_dir: Path):
    forms = result.get("Formulations")
    # create default if empty/missing
    if not isinstance(forms, list) or not forms:
        valid_types = _collect_valid_formulation_types(data_dir)
        default_type = _choose_formulation_type("Oral IR Formulation", valid_types) if valid_types else "Formulation_Tablet_Weibull"
        result["Formulations"] = [{
            "Name": "Oral IR Formulation",
            "FormulationType": default_type
        }]
        return

    valid_types = _collect_valid_formulation_types(data_dir)
    for i, f in enumerate(forms):
        if not isinstance(f, dict):
            continue
        # enforce name
        if not isinstance(f.get("Name"), str) or not f["Name"].strip():
            f["Name"] = f.get("name") or f"Formulation_{i+1}"
        # map/validate type
        if "FormulationType" not in f and "Type" in f:
            f["FormulationType"] = f.pop("Type")
        ft = (f.get("FormulationType") or "").strip()
        if not ft or (valid_types and ft not in valid_types):
            f["FormulationType"] = _choose_formulation_type(f["Name"], valid_types) if valid_types else "Formulation_Tablet_Weibull"
        # cleanup
        f.pop("Dose", None)
        f.pop("Disintegration time", None)
        forms[i] = f
    result["Formulations"] = forms

# ---- protocols: ensure Advanced Protocol schema + Name; create default if missing ----
def _sanitize_protocols(result: dict, data_dir: Path):
    # ensure formulations exist & have a name
    forms = result.get("Formulations") or []
    if not isinstance(forms, list) or not forms:
        _sanitize_formulations(result, data_dir)
        forms = result.get("Formulations") or []
    form_name = (forms[0].get("Name") if forms and isinstance(forms[0], dict) else "Oral IR Formulation")

    prots = result.get("Protocols")
    # create default Protocol if missing
    if not isinstance(prots, list) or not prots:
        pr = {
            "Name": "Protocol_Main",
            "Applications": [{
                "Name": "Application_1",
                "ApplicationType": "Oral",
                "FormulationKey": "Formulation",
                "Parameters": [
                    {"Name": "Start time", "Value": 0.0, "Unit": "h"}
                ]
            }],
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
        }
        result["Protocols"] = [pr]
        prots = result["Protocols"]

    # normalize first protocol
    pr = prots[0]
    if not isinstance(pr.get("Name"), str) or not pr["Name"].strip():
        pr["Name"] = "Protocol_Main"

    # Application -> Applications
    if "Applications" not in pr:
        app = pr.get("Application") or {}
        pr["Applications"] = [app]
        pr.pop("Application", None)

    if pr["Applications"]:
        app0 = pr["Applications"][0] or {}
        app0.setdefault("Name", "Application_1")
        app0.setdefault("ApplicationType", "Oral")
        app0.setdefault("FormulationKey", "Formulation")
        app0.setdefault("Parameters", [])
        if "Route" in app0:
            app0.pop("Route", None)
        if "Time" in app0:
            t = app0.pop("Time", None)
            if isinstance(t, dict) and "Value" in t:
                app0["Parameters"].append({"Name": "Start time", "Value": t["Value"], "Unit": t.get("Unit", "h")})
        if "Formulation" in app0:
            app0.pop("Formulation", None)
        pr["Applications"][0] = app0

    # Schemas
    if "Schemas" not in pr:
        pr["Schemas"] = [{
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
        }]
        pr["TimeUnit"] = "h"

    prots[0] = pr
    result["Protocols"] = prots

def _existing_names(items, key="Name"):
    names = []
    if isinstance(items, list):
        for it in items:
            if isinstance(it, dict) and isinstance(it.get(key), str) and it[key].strip():
                names.append(it[key].strip())
    return names

def _normalize_simulation_subarrays(sim: dict):
    """Normalize common simulation subarrays that may appear as singleton objects in examples."""
    for key in [
        "Compounds",
        "Events",
        "OutputSchema",
        "Parameters",
        "ObservedData",
        "IndividualAnalyses",
        "Interactions",
    ]:
        _ensure_array_field(sim, key)

def _ensure_minimal_simulations_if_needed(result: dict, data_dir: Path):
    """If no simulations exist, create a minimal, valid one that will run."""
    sims = result.get("Simulations")
    if isinstance(sims, list) and sims:
        return  # already present

    # Ensure basic building blocks exist
    _ensure_minimal_individual_if_needed(result)
    _sanitize_formulations(result, data_dir)
    _sanitize_protocols(result, data_dir)

    # pick available names
    comp_names = _existing_names(result.get("Compounds"))
    if not comp_names:
        # Create a placeholder compound if none exists
        result["Compounds"] = [{"Name": "Compound_1"}]
        comp_names = ["Compound_1"]

    protocol_names = _existing_names(result.get("Protocols"))
    form_names = _existing_names(result.get("Formulations"))
    individual_names = _existing_names(result.get("Individuals"))

    target_compound = comp_names[0]
    protocol_name = protocol_names[0] if protocol_names else "Protocol_Main"
    form_name = form_names[0] if form_names else "Oral IR Formulation"
    individual_name = individual_names[0] if individual_names else "Individual_1"

    # choose a model
    valid_models = _collect_model_names(data_dir)
    model_name = _preferred_model(valid_models)

    sim = {
        "Name": f"{target_compound}_Simulation",
        "Model": model_name,
        "Individual": individual_name,
        "Compounds": [{
            "Name": target_compound,
            "Protocol": {
                "Name": protocol_name,
                "Formulations": [{"Name": form_name, "Key": "Formulation"}]
            }
        }],
        "OutputSchema": [{
            "Parameters": [
                {"Name": "Start time", "Value": 0.0, "Unit": "h"},
                {"Name": "End time",   "Value": 24.0, "Unit": "h"},
                {"Name": "Resolution", "Value": 4.0,  "Unit": "pts/h"},
            ]
        }]
    }
    result["Simulations"] = [sim]

# ---- simulations: ensure model, links, outputs, and retarget to current compounds ----
def _sanitize_simulations(result: dict, data_dir: Path):
    _ensure_array_field(result, "Simulations")
    sims = result.get("Simulations")
    if not isinstance(sims, list) or not sims:
        return

    # normalize subarrays inside simulations to avoid schema mismatches
    for s in sims:
        if isinstance(s, dict):
            _normalize_simulation_subarrays(s)

    # Gather available names from other sections to validate links
    compound_names = set(_existing_names(result.get("Compounds")))
    protocol_names  = _existing_names(result.get("Protocols"))
    form_names = _existing_names(result.get("Formulations"))
    individual_names = _existing_names(result.get("Individuals"))

    # Fallback: create defaults if missing
    if not protocol_names:
        result.setdefault("Protocols", [])
        result["Protocols"].append({"Name": "Protocol_Main"})
        protocol_names = _existing_names(result.get("Protocols"))
    if not form_names:
        result.setdefault("Formulations", [])
        result["Formulations"].append({"Name": "Oral IR Formulation"})
        form_names = _existing_names(result.get("Formulations"))

    default_protocol = protocol_names[0] if protocol_names else None
    default_form = form_names[0] if form_names else None
    default_individual = individual_names[0] if individual_names else None

    # Learn model names from examples
    valid_models = _collect_model_names(data_dir)
    model_name = _preferred_model(valid_models)

    # Determine target compound for retargeting
    target_compound = next(iter(compound_names)) if compound_names else None

    for s in sims:
        if not isinstance(s, dict):
            continue

        # ensure simulation has a name
        if not isinstance(s.get("Name"), str) or not s["Name"].strip():
            s["Name"] = "Simulation_1"

        # Ensure model
        if not isinstance(s.get("Model"), str) or not s["Model"].strip():
            s["Model"] = model_name

        # Ensure an existing individual
        ind_name = s.get("Individual")
        if not isinstance(ind_name, str) or ind_name not in individual_names:
            if default_individual:
                s["Individual"] = default_individual
            else:
                s.pop("Individual", None)

        # Normalize "Compounds" at sim-level (string/dict/list → list[dict])
        if "Compounds" not in s and "Compound" in s:
            val = s.pop("Compound")
            if isinstance(val, str):
                s["Compounds"] = [{"Name": val}]
            elif isinstance(val, dict):
                s["Compounds"] = [val]
            elif isinstance(val, list):
                canonical = []
                for el in val:
                    if isinstance(el, str):
                        canonical.append({"Name": el})
                    elif isinstance(el, dict):
                        canonical.append(el)
                if canonical:
                    s["Compounds"] = canonical

        comps = s.get("Compounds")
        if not isinstance(comps, list) or not comps:
            if target_compound:
                s["Compounds"] = [{"Name": target_compound}]
            else:
                continue

        # Retarget all compounds inside the simulation to the new target_compound
        fixed = []
        for comp in s["Compounds"]:
            if isinstance(comp, str):
                comp = {"Name": comp}

            # ensure/retarget Name
            if not isinstance(comp.get("Name"), str) or not comp["Name"].strip():
                if target_compound:
                    comp["Name"] = target_compound
            elif target_compound and comp["Name"] != target_compound:
                comp["Name"] = target_compound

            # Protocol link → ensure it points to an existing Protocol + Formulation
            prot = comp.get("Protocol") or {}
            if not isinstance(prot, dict):
                prot = {}

            pname = prot.get("Name")
            if not isinstance(pname, str) or pname not in protocol_names:
                if default_protocol:
                    prot["Name"] = default_protocol
                else:
                    prot["Name"] = "Protocol_Main"

            # Formulation(s)
            forms_list = prot.get("Formulations")
            if not isinstance(forms_list, list):
                forms_list = []
            has_valid_form = any(isinstance(f, dict) and f.get("Name") in form_names for f in forms_list)
            if not has_valid_form:
                if default_form:
                    forms_list = [{"Name": default_form, "Key": "Formulation"}]
                else:
                    forms_list = [{"Name": "Oral IR Formulation", "Key": "Formulation"}]
            prot["Formulations"] = forms_list
            comp["Protocol"] = prot

            # drop example-specific extras
            comp.pop("CalculationMethods", None)
            comp.pop("Alternatives", None)
            comp.pop("Processes", None)

            fixed.append(comp)

        s["Compounds"] = fixed

        # --- Clean/retarget outputs & results ---
        # safest: drop OutputSelections copied from other drug snapshots
        if isinstance(s.get("OutputSelections"), list):
            s.pop("OutputSelections", None)

        # Always provide a minimal OutputSchema if missing
        if "OutputSchema" not in s:
            s["OutputSchema"] = [{
                "Parameters": [
                    {"Name": "Start time", "Value": 0.0, "Unit": "h"},
                    {"Name": "End time",   "Value": 24.0, "Unit": "h"},
                    {"Name": "Resolution", "Value": 4.0,  "Unit": "pts/h"},
                ]
            }]

        # Remove example-specific analysis/results blocks that often mismatch
        s.pop("ObservedData", None)
        s.pop("HasResults", None)
        s.pop("IndividualAnalyses", None)
        s.pop("Interactions", None)

        # Remove stale building block references to avoid NullReference on load
        s.pop("UsedBuildingBlocks", None)
        s.pop("BuildingBlocks", None)
        s.pop("BuildingBlockReferences", None)

        # Simulation-level Parameters: remove entries that reference missing protocol/formulation names
        if isinstance(s.get("Parameters"), list):
            cleaned = []
            for prm in s["Parameters"]:
                if not isinstance(prm, dict):
                    continue
                path = prm.get("Path")
                if not isinstance(path, str):
                    cleaned.append(prm)
                    continue
                parts = path.split("|")
                if len(parts) >= 3 and parts[0] == "Events":
                    p_name = parts[1]
                    f_name = parts[2] if len(parts) > 2 else None
                    if (p_name and p_name not in protocol_names) or (f_name and f_name not in form_names):
                        continue  # drop invalid path parameter
                cleaned.append(prm)
            s["Parameters"] = cleaned

def _sanitize_snapshot(result: dict, data_dir: Optional[Path] = None):
    # 1) Normalize & basics
    _ensure_version(result)
    _normalize_root_sections_to_arrays(result)

    # 2) Individuals
    _sanitize_individuals(result)
    _ensure_individual_units(result)
    _ensure_minimal_individual_if_needed(result)

    # 3) Remaining building blocks
    if data_dir is None:
        data_dir = Path(".")
    _sanitize_formulations(result, data_dir)
    _sanitize_protocols(result, data_dir)
    _sanitize_compounds_to_pksim(result)

    # 4) If no simulations exist (or wurden geleert), erzeuge eine minimale, gültige
    _ensure_minimal_simulations_if_needed(result, data_dir)

    # 5) Final pass: sanitize/retarget simulations
    _sanitize_simulations(result, data_dir)

# -----------------------------
# JSON RAG index over examples
# -----------------------------
class _JsonRAG:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.index = _TfIdf()
        self.section_schema: Dict[str, dict] = {}
        self._build()

    def _build(self):
        for p in self.data_dir.glob("*.json"):
            try:
                obj = json.loads(Path(p).read_text(encoding="utf-8"))
            except Exception as e:
                obj = {"_error": str(e)}
            for sec, path, text, el in _iter_chunks(p.name, obj):
                self.index.add(text, {"path": path, "section": sec, "filename": p.name, "preview": text[:600]})
                s = _infer(el)
                self.section_schema[sec] = _merge(self.section_schema.get(sec), s)
        self.index.finalize()

    def list_sections(self) -> List[str]:
        return sorted(self.section_schema.keys())

    def template(self, section: str) -> Dict[str, Any]:
        s = self.section_schema.get(section)
        if not s:
            raise KeyError(f"Unknown section: {section}")
        return _tmpl(s)

    def examples(self, section: str, topk: int = 3) -> List[Dict[str, Any]]:
        hits = []
        for m in self.index.meta:
            if m.get("section", "").lower() == section.lower():
                hits.append(m)
                if len(hits) >= topk:
                    break
        return hits

    def answer(self, query: str, topk: int = 5) -> Dict[str, Any]:
        ql = query.lower()
        m = re.search(r"(compound|compounds|expressionprofiles|individuals|formulations|protocols|simulations|populations)", ql)
        if m:
            sec = m.group(1)
            sec_norm = sec[0].upper() + sec[1:]
            candidates = [sec_norm, sec_norm.rstrip("s"), sec_norm + "s"]
            key = next((c for c in candidates if c in self.section_schema), None)
            if not key:
                return {"message": f"Section '{sec}' not found", "sections": self.list_sections()}
            tmpl = self.template(key)
            examples = self.examples(key)
            return {
                "style": "rag_format_and_examples",
                "section": key,
                "format": {key: tmpl},
                "examples": examples,
            }
        scored = self.index.query(query, topk=topk)
        return {
            "style": "semantic_hits",
            "hits": [{"score": float(f"{s:.3f}"), **m} for s, m in scored],
            "sections": self.list_sections(),
        }

@lru_cache(maxsize=8)
def _load(data_dir: str) -> _JsonRAG:
    return _JsonRAG(Path(data_dir))

def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))

def _obj_from_path(data_dir: Path, path_str: str) -> Any:
    if "::" not in path_str:
        raise ValueError("Path must look like 'File.json::Section' or 'File.json::Section[i]'")
    fname, tail = path_str.split("::", 1)
    fpath = data_dir / fname
    obj = _read_json(fpath)
    m = re.match(r"^([A-Za-z0-9_]+)(?:\[(\d+)\])?$", tail)
    if not m:
        raise ValueError(f"Unrecognized path tail: {tail}")
    section = m.group(1)
    idx = m.group(2)
    sec_val = obj.get(section)
    if idx is None:
        return sec_val
    i = int(idx)
    if not isinstance(sec_val, list):
        raise ValueError(f"Section {section} is not a list in {fname}")
    return sec_val[i]

def _deep_merge(base: Any, override: Any) -> Any:
    if isinstance(base, dict) and isinstance(override, dict):
        out = dict(base)
        for k, v in override.items():
            out[k] = _deep_merge(base.get(k), v) if k in base else v
        return out
    if isinstance(override, list):
        return override
    return override if override is not None else base

# ---------- Public API ----------
def rag_json_sections(data_dir: str) -> List[str]:
    return _load(data_dir).list_sections()

def rag_json_template(section: str, data_dir: str) -> Dict[str, Any]:
    return {section: _load(data_dir).template(section)}

def rag_json_answer(query: str, data_dir: str, topk: int = 5) -> Dict[str, Any]:
    return _load(data_dir).answer(query, topk=topk)

def rag_json_build(
    section: str,
    values: Dict[str, Any],
    out_path: str,
    data_dir: str,
    inherit_rest: bool = False,
    seeds: Optional[Dict[str, str]] = None,
    overrides: Optional[Dict[str, Any]] = None,
    rebuild_simulations: bool = False,  
) -> Dict[str, Any]:
    """
    Build a snapshot JSON.

    - Default (inherit_rest=False): previous behavior — create a document with only {section: values}.
    - inherit_rest=True: create 'section' fresh; fill all other sections from examples (copy_best),
      optionally from 'seeds', and apply 'overrides'.
    - rebuild_simulations=True: ignoriert übernommene Simulationen und erzeugt eine minimale,
      gültige Simulation, die auf die aktuellen Building Blocks verweist.
    """
    data_dir_p = Path(data_dir)
    rag = _load(data_dir)

    # Start with the requested section only
    result: Dict[str, Any] = {"Version": 80, section: values}

    # Inherit the remaining sections from examples/seeds/templates
    if inherit_rest:
        for sec in rag.list_sections():
            if sec == section:
                continue
            if seeds and sec in seeds:
                base_value = _obj_from_path(data_dir_p, seeds[sec])
            else:
                ex = rag.examples(sec, topk=1)
                if ex:
                    base_value = _obj_from_path(data_dir_p, ex[0]["path"])
                else:
                    base_value = rag.template(sec)
            if overrides and sec in overrides:
                base_value = _deep_merge(base_value, overrides[sec])
            result[sec] = base_value

    # If caller asks to rebuild simulations: empty them so sanitizer builds minimal fresh ones
    if rebuild_simulations:
        result["Simulations"] = []

    # PK-Sim compatibility sanitation (+ minimal simulation builder if empty)
    _sanitize_snapshot(result, data_dir_p)

    # Write output
    # Sanitize output path to avoid writing to root /snapshots
    if out_path.startswith("/snapshots") or out_path.startswith("/data"):
        out_path = out_path.lstrip("/")
    
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    included = [section] + ([s for s in rag.list_sections() if s != section] if inherit_rest else [])
    mode = "single+inherit" if inherit_rest else "single"
    if rebuild_simulations:
        mode += "+rebuild_sims"
    return {"out_path": str(out.resolve()), "sections": included, "mode": mode}

def rag_snapshot_autobuild(
    sections: Optional[List[str]],
    strategy: str,
    seeds: Optional[Dict[str, str]],
    overrides: Optional[Dict[str, Any]],
    out_path: str,
    data_dir: str,
) -> Dict[str, Any]:
    rag = _load(data_dir)
    all_secs = rag.list_sections()
    if not sections:
        sections = all_secs
    sections = [s for s in sections if s in all_secs]

    result: Dict[str, Any] = {"Version": 80}
    data_dir_p = Path(data_dir)

    for sec in sections:
        if strategy == "template":
            base_value: Any = rag.template(sec)
        elif strategy == "seeded" and seeds and sec in seeds:
            base_value = _obj_from_path(data_dir_p, seeds[sec])
        else:  # copy_best
            ex = rag.examples(sec, topk=1)
            if ex:
                base_value = _obj_from_path(data_dir_p, ex[0]["path"])
            else:
                base_value = rag.template(sec)

        if overrides and sec in overrides:
            base_value = _deep_merge(base_value, overrides[sec])

        result[sec] = base_value

    # PK-Sim compatibility sanitation (uses example-driven knowledge via data_dir)
    _sanitize_snapshot(result, data_dir_p)

    # Sanitize output path to avoid writing to root /snapshots
    if out_path.startswith("/snapshots") or out_path.startswith("/data"):
        out_path = out_path.lstrip("/")

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"out_path": str(out.resolve()), "sections": sections, "strategy": strategy}
