from biomni.agent import A1

# Initialize the agent with data path, Data lake will be automatically downloaded on first run (~11GB)
agent = A1(path='/Users/mohamedaminekina/Desktop/esqlabs/Biomni/data', llm='azure-gpt-5')

# Execute biomedical tasks using natural language
#agent.go("Plan a CRISPR screen to identify genes that regulate T cell exhaustion, generate 32 genes that maximize the perturbation effect.")
#agent.go("Perform scRNA-seq annotation at [PATH] and generate meaningful hypothesis")
#agent.go("Predict ADMET properties for this compound: CC(C)CC1=CC=C(C=C1)C(C)C(=O)O") 


agent.go("""Plan a CRISPR screen to identify genes that regulate T cell exhaustion,
        measured by the change in T cell receptor (TCR) signaling between acute
       (interleukin-2 [IL-2] only) and chronic (anti-CD3 and IL-2) stimulation conditions.
       Generate 32 genes that maximize the perturbation effect.""")


#agent.go("Using R library perform a differential expression analysis on a dataset of your choice and generate a summary of the results.")