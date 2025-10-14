from biomni.agent import A1


from biomni.tool.prepare_biomni_snapshot import prepare_biomni_snapshot
from biomni.tool.snapshot_builder import build_snapshot_file
from biomni.tool.pksim_runner import run_pksim_snapshot


from biomni.tool.biomni_tool_json_rag import (
    rag_json_sections,
    rag_json_template,
    rag_json_answer,
    rag_snapshot_autobuild,
)



BIOMNI_BASE_PATH = "./data"
DATA_DIR = "./data/snapshot_files"         
SNAPSHOT_OUT_DIR = "./data/generated_snapshot_files"              
SNAPSHOT_OUT_PATH = f"{SNAPSHOT_OUT_DIR}/ibuprofen_snapshot.json"
PROJECT_OUT = "./projects/ibuprofen.pksim5"
PKML_OUT = "./exports/ibuprofen.pkml"
SIM_NAME = "Test_Sim"

agent = A1(llm="gpt-5", path=BIOMNI_BASE_PATH)


agent.add_tool(prepare_biomni_snapshot)
agent.add_tool(build_snapshot_file)
agent.add_tool(run_pksim_snapshot)

agent.add_tool(rag_json_sections)
agent.add_tool(rag_json_template)
agent.add_tool(rag_json_answer)
agent.add_tool(rag_snapshot_autobuild)


agent.go(f"""
Ziel: Erzeuge eine **lauffähige PK-Sim Snapshot-JSON** für 'Ibuprofen' unter '{SNAPSHOT_OUT_PATH}'.
Nutze strikt die Beispiel-Strukturen aus '{DATA_DIR}' (strategy="copy_best"). Keine Web-Recherche, keine freien Felder.

Arbeitsweise:
1) Baue mit 'rag_snapshot_autobuild':
   - sections=None  (alle verfügbaren Abschnitte)
   - strategy="copy_best"
   - seeds=None
   - overrides = {{
       "Compounds": [{{"Name": "Ibuprofen"}}]   # nur den Namen setzen, keine weiteren Properties
     }}
   - out_path='{SNAPSHOT_OUT_PATH}'
   - data_dir='{DATA_DIR}'

2) Verlasse dich auf die integrierte Sanitation:
   - Version=80
   - Individuals: OriginData + Einheiten
   - Formulations: gültiger FormulationType aus Beispielen (z. B. Formulation_Tablet_Weibull)
   - Protocols: Advanced-Protocol-Schema (Schemas/SchemaItems/Parameters)
   - Simulations: gültiges Model (z. B. 4Comp) + korrekte Formulation-Links + OutputSchema
   - Compounds: Mapping auf PK-Sim-Parameter (Molecular weight, Lipophilicity, Fraction unbound, Solubility)

3) Führe den Tool-Call aus und gib eine kurze Zusammenfassung mit Pfad/Abschnittsliste aus.

Konkreter Aufruf:
- rag_snapshot_autobuild(sections=None, strategy="copy_best", seeds=None,
                         overrides={{"Compounds":[{{"Name":"Ibuprofen"}}]}},
                         out_path='{SNAPSHOT_OUT_PATH}', data_dir='{DATA_DIR}')

Ausgabe:
- "Snapshot gebaut" + Pfad + Liste der enthaltenen Abschnitte.
""")