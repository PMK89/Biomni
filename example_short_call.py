from biomni.agent import A1
from biomni.tool.create_drug_snapshot_guided import create_drug_snapshot_guided
from biomni.tool.biomni_tool_json_rag_V2 import rag_json_build

# Pfade
BIOMNI_BASE_PATH = "./data"
DATA_DIR = "./data/snapshot_files"
SNAPSHOT_OUT_DIR = "./data/generated_snapshot_files"

# Agent initialisieren
agent = A1(llm="gpt-5", path=BIOMNI_BASE_PATH)

# Tools registrieren
agent.add_tool(create_drug_snapshot_guided)
agent.add_tool(rag_json_build)

# SUPER EINFACHER AUFRUF!
drug = "Metoprolol"  # oder beliebiges anderes Medikament

agent.go(f"Erstelle mir eine Snapshot-Datei für das Medikament {drug}.")