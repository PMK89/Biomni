# Simple Direct Test Prompts for Agent

These are simplified, action-focused prompts designed to trigger immediate tool execution rather than planning/explanation.

---

## Simple Test 1: Basic Literature Search + PBPK Simulation

**Prompt:**
```
Search PubMed for "Venetoclax pharmacokinetics" and save any papers you find. Then create a PBPK snapshot for Venetoclax with these parameters: MW=868.4, logP=7.8, fu=0.00001, solubility=0.01 mg/L, dose=400 mg oral. Run the simulation for 48 hours. Analyze the results and plot the concentration-time curve.
```

---

## Simple Test 2: Quick Drug Property Lookup + Model

**Prompt:**
```
Find the molecular weight, logP, and half-life of Midazolam from literature. Create a PBPK model with a 5 mg oral dose. Simulate for 24 hours and calculate Cmax and AUC from the results.
```

---

## Simple Test 3: Direct Simulation with Known Parameters

**Prompt:**
```
Create a PBPK simulation for Oseltamivir: MW=312.4, logP=1.1, fu=0.97, dose=75 mg oral, bioavailability=0.8, half-life=8 hours. Run simulation for 48 hours. Plot the results and calculate PK parameters (Cmax, Tmax, AUC).
```

---

## Debugging Notes

If the agent still generates text instead of executing:

1. **Check system prompt**: The agent's base system prompt in `biomni/agent/a1.py` line ~1146 should emphasize immediate execution over planning
2. **Check LLM model**: Some models (especially older ones) tend to be more verbose and planning-focused
3. **Check temperature**: Higher temperature (>0.7) can lead to more exploratory/planning behavior
4. **Force execution**: Add explicit instruction like "Start immediately with <execute> tags, do not write a plan first"

## Modified Prompt Format (Forces Execution)

**Ultra-Direct Format:**
```
Execute now: Search PubMed for "Venetoclax pharmacokinetics". Save papers. Create PBPK model (MW=868.4, logP=7.8, fu=0.00001, dose=400mg oral). Run simulation 48h. Plot results. No planning, just execute.
```

This format:
- Uses imperative commands
- Removes all explanatory context
- Explicitly says "no planning"
- Forces immediate action
