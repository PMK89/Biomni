import json
import re
from biomni.llm import get_llm
from langchain_core.messages import SystemMessage, HumanMessage

class APKA_Agent:
    """
    Agent Performance and Knowledge Auditor (APKA).

    This agent analyzes the full execution transcript of another AI agent
    to produce a structured evaluation of its performance and to audit
    its use of internal (parametric) knowledge.
    """

    # The system prompt that defines the agent's role, instructions, and output format.
    SYSTEM_PROMPT = """
You are APKA, an Agent Performance and Knowledge Auditor. Your task is to analyze the full execution transcript of a biomedical AI agent and produce a structured JSON evaluation.

You will assess two key areas: Performance and Internal Knowledge Usage.

## Instructions:

1.  **Analyze Performance**: Evaluate the agent's process based on the following criteria. Provide a score from 1 (poor) to 5 (excellent) and a brief justification for each.
    * **Plan Adherence**: Did the agent create a logical plan and follow it? Did it update its checklist correctly?
    * **Reasoning Quality**: Was the agent's thinking clear, logical, and did it justify its actions?
    * **Tool Usage**: Were the chosen tools appropriate for the task? Were the parameters correct?
    * **Error Handling**: How well did the agent adapt to failed tool calls or unexpected errors? Did it modify its plan effectively?
    * **Solution Quality**: Did the final solution directly address all parts of the user's request? Was it well-structured and accurate based on the successful steps?

2.  **Audit for Internal Knowledge**: Identify and list every instance where the agent stated a fact or performed a step that could not have come from the provided context.
    * **Definition of Internal Knowledge**: Any factual statement, data, or complex procedure that is NOT found in:
        a. The initial system prompt or tool descriptions.
        b. The user's prompt.
        c. The `<observation>` block of a successful tool call.
    * For each instance, you must provide the line number from the transcript, the exact text, and a brief justification for why it's considered internal knowledge.

## Output Format:
Your entire output MUST be a single, valid JSON object with the following structure:

{
  "overall_summary": "A brief, one-paragraph summary of the agent's performance.",
  "performance_assessment": {
    "plan_adherence": { "score": 1, "justification": "..." },
    "reasoning_quality": { "score": 1, "justification": "..." },
    "tool_usage": { "score": 1, "justification": "..." },
    "error_handling": { "score": 1, "justification": "..." },
    "solution_quality": { "score": 1, "justification": "..." }
  },
  "internal_knowledge_audit": [
    {
      "line_number": 0,
      "text": "The exact quote from the agent's reasoning or solution.",
      "justification": "Explanation of why this is internal knowledge (e.g., 'This curated list of genes was not provided by any tool output.')."
    }
  ]
}
"""

    def __init__(self, model: str | None = None, temperature: float = 1.0):
        """
        Initializes the APKA_Agent with a live LLM.

        Args:
            model (str): The name of the language model to use.
            temperature (float): The temperature for the LLM. A low value is recommended for this analytical task.
        """
        # The get_llm function from your llm.py handles API key loading from environment variables.
        self.llm_client = get_llm(model=model, temperature=temperature)
        print(f"APKA Agent initialized with live model: {model}.")

    def analyze_transcript(self, transcript: str) -> dict:
        """
        Analyzes a given agent transcript and returns a structured evaluation.

        Args:
            transcript: A string containing the entire message history and
                        tool outputs from an agent's run.

        Returns:
            A dictionary containing the structured performance and knowledge audit,
            or an error dictionary if the analysis fails.
        """
        print(f"Analyzing transcript of {len(transcript)} characters...")

        # Add line numbers to the transcript for easier reference by the LLM
        lines = transcript.split('\n')
        numbered_transcript = "\n".join(f"{i+1}: {line}" for i, line in enumerate(lines))

        # --- MODIFIED: Changed message format for LangChain and the LLM call ---
        try:
            # LangChain models expect a list of message objects.
            messages = [
                SystemMessage(content=self.SYSTEM_PROMPT),
                HumanMessage(content=numbered_transcript)
            ]

            print("\n--- SENDING REQUEST TO LLM ---")
            # Use the .invoke() method for the real LLM call
            response_object = self.llm_client.invoke(messages)
            
            # The text response is in the .content attribute of the response object
            raw_response = response_object.content
            
            # The response from the LLM is expected to be a JSON string.
            # It's good practice to clean it up in case the LLM wraps it in markdown.
            json_match = re.search(r'\{.*\}', raw_response, re.DOTALL)
            if not json_match:
                raise ValueError("LLM response did not contain a valid JSON object.")
            
            clean_json_string = json_match.group(0)
            
            # Parse the JSON string into a Python dictionary
            evaluation = json.loads(clean_json_string)
            print("--- ANALYSIS COMPLETE ---")
            return evaluation

        except json.JSONDecodeError as e:
            print(f"Error: Failed to decode JSON from LLM response. Details: {e}")
            return {"error": "JSONDecodeError", "details": str(e), "raw_response": raw_response}
        except Exception as e:
            print(f"An unexpected error occurred: {e}")
            return {"error": "UnexpectedError", "details": str(e)}
        # --- END MODIFICATION ---

