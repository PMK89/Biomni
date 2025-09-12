from biomni.agent import A1
from biomni.tool.prepare_biomni_snapshot import prepare_biomni_snapshot
from biomni.tool.snapshot_builder import build_snapshot_file
from biomni.tool.pksim_runner import run_pksim_snapshot
import os

BIOMNI_BASE_PATH: str = "./data"
agent = A1(
        llm="gpt-5",
        path=BIOMNI_BASE_PATH,
)

agent.add_tool(prepare_biomni_snapshot)

agent.add_tool(build_snapshot_file)

agent.add_tool(run_pksim_snapshot)

# Direkt-Test einzelner Module, bspw run_pksim_snapshot
'''
result = run_pksim_snapshot(
    snapshot_in="data/pkml/",                       
    project_out="projects/ibuprofen.pksim5",
    export_pkml="exports/ibuprofen.pkml",
    sim_name="Test_Sim",
    input_mode="folder"
)
print("\n".join(result["logs"]))

print("Project:", result["built_project"])
print("PKML exported:", result["pkml_exported"])
print("Used command:", result["export_command_used"])
'''


agent.go(
    "Find PK/ADME baseline data for Ibuprofen, map them to the snapshot schema, "
    "and create a snapshot configuration file."
)
