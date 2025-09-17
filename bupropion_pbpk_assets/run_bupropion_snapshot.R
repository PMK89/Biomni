# run_bupropion_snapshot.R
# Headless runner for PK-Sim snapshot using ospsuite R
# Requirements: R >= 4.1, ospsuite >= 11, PK-Sim installed for snapshot import if needed.

suppressPackageStartupMessages({
  library(ospsuite)
})

snapshotPath <- "bupropion_pbpk_assets/bupropion_pbpk_snapshot.json"
outDir <- "bupropion_pbpk_outputs"
dir.create(outDir, showWarnings = FALSE, recursive = TRUE)

logMsg <- function(msg) cat(sprintf("[%s] %s\n", format(Sys.time(), "%Y-%m-%d %H:%M:%S"), msg))

logMsg("Attempting to load simulation(s) from snapshot...")

# NOTE:
# In ospsuite R, snapshots (JSON) are typically imported via PK-Sim GUI/CLI to create simulations.
# If your ospsuite version provides a function like `loadProjectFromSnapshot` or `importSnapshot`,
# use it here. Otherwise:
# 1) Open PK-Sim, import the snapshot JSON, create the simulation, and export the Simulation to PKML.
# 2) Then, use ospsuite::loadSimulation('path/to/simulation.pkml') to run headlessly.

if (!exists("loadProjectFromSnapshot")) {
  logMsg("No direct snapshot loader exposed in this ospsuite version.")
  logMsg("Please import the snapshot in PK-Sim, configure simulation, and export PKML for headless run.")
  logMsg("Exiting after writing this instruction log.")
  writeLines(c(
    "Instructions:",
    "1) Open PK-Sim (v11+).",
    "2) File -> Import -> Snapshot, select bupropion_pbpk_assets/bupropion_pbpk_snapshot.json",
    "3) Ensure compounds, enzymes, population, and protocol are set. Fill kinetic parameters from Marok 2021 tables.",
    "4) Create a simulation for Adults 18–55, IR 150 mg single dose.",
    "5) Add observers (plasma conc, AUC, Cmax, Tmax, metabolite/parent ratios).",
    "6) Export Simulation to PKML.",
    "7) Use ospsuite R: sim <- loadSimulation('exported.pkml'); runSimulation(sim); exportResults()"
  ), file.path(outDir, "RUN_INSTRUCTIONS.txt"))
  quit(save="no", status=0)
}

# If loadProjectFromSnapshot is available in your ospsuite build (pseudo-code):
# project <- loadProjectFromSnapshot(snapshotPath)
# sim <- getSimulationByName(project, "Adults_18to55_IR_150mg") # adapt to actual simulation name
# runSimulation(sim)
# results <- getOutputValues(sim)
# write.csv(results, file.path(outDir, "simulation_outputs.csv"), row.names = FALSE)
# logMsg("Exported simulation outputs.")
