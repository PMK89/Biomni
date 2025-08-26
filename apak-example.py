from biomni.agent.apak import APKA_Agent
import json

auditor = APKA_Agent(model="gpt-5")

# 2. Load the agent transcript from the file.
file_path = "/Users/mohamedaminekina/Desktop/esqlabs/Biomni/runs/gpt-5-test.txt"
try:
    with open(file_path, 'r', encoding='utf-8') as f:
        message_history = f.read()
    print(f"Successfully loaded transcript from '{file_path}'.")
except FileNotFoundError:
    print(f"Error: The file '{file_path}' was not found.")
    message_history = None

# 3. Pass the transcript to the agent for analysis.
if message_history:
    analysis_result = auditor.analyze_transcript(message_history)

    # 4. Print the structured result.
    print("\n--- APKA Evaluation Result ---")
    # Using json.dumps for pretty printing the output dictionary
    print(json.dumps(analysis_result, indent=2))