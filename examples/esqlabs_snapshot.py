"""Example showing how to register ESQlabs snapshot tools with the Biomni agent."""
from biomni.agent.a1 import A1
from biomni_esqlabs_tools.registry import iter_esqlabs_tools

BIOMNI_BASE_PATH = "./data"
DATA_DIR = "./data/esqlabs/snapshot_files"
SNAPSHOT_OUT_DIR = "./data/esqlabs/generated_snapshot_files"

def main(drug: str = "Aspirin") -> None:
    agent = A1(llm="gpt-5", path=BIOMNI_BASE_PATH)
    for tool in iter_esqlabs_tools():
        agent.add_tool(tool)
    agent.go(
        f"""
Erstelle mir eine Snapshot-Datei für das Medikament {drug}.
Speichere sie unter '{SNAPSHOT_OUT_DIR}/{drug.lower()}_snapshot.json'.
Verwende '{DATA_DIR}' als Beispielbasis.

Gehe wie folgt vor:
1. Rufe create_drug_snapshot auf, um Anweisungen zu erhalten
2. Recherchiere die benötigten pharmakokinetischen Daten im Internet
3. Baue die Snapshot-Datei mit den gefundenen Daten
4. Gib eine Zusammenfassung mit allen verwendeten Werten und deren Quellen aus
"""
    )

if __name__ == "__main__":
    main()
