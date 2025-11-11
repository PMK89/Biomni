from biomni.agent import A1
from biomni.tool.create_drug_snapshot import create_drug_snapshot
from biomni.tool.biomni_tool_json_rag_V2 import rag_json_build

# Pfade
BIOMNI_BASE_PATH = "./data"
DATA_DIR = "./data/snapshot_files"
SNAPSHOT_OUT_DIR = "./data/generated_snapshot_files"

# Agent initialisieren
agent = A1(llm="gpt-5", path=BIOMNI_BASE_PATH)

# Tools registrieren
agent.add_tool(create_drug_snapshot)
agent.add_tool(rag_json_build)

drug = "Aspirin"  # oder beliebiges anderes Medikament
agent.go(f"""
Erstelle mir eine Snapshot-Datei für das Medikament {drug}.
Speichere sie unter '{SNAPSHOT_OUT_DIR}/{drug.lower()}_snapshot.json'.
Verwende '{DATA_DIR}' als Beispielbasis.

Gehe wie folgt vor:
1. Rufe create_drug_snapshot auf, um Anweisungen zu erhalten
2. Recherchiere die benötigten pharmakokinetischen Daten im Internet
3. Baue die Snapshot-Datei mit den gefundenen Daten
4. Gib eine Zusammenfassung mit allen verwendeten Werten und deren Quellen aus
""")