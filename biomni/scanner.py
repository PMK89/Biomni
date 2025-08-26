import os
import json
import pandas as pd
import traceback

# Import the get_llm function
from biomni.llm import get_llm

from dotenv import load_dotenv
# Load environment variables from .env file
load_dotenv()

# --- Configuration ---
# Set a file size limit (in bytes) to optimize memory usage when reading files
FILE_SIZE_LIMIT_MB = 100

def get_semantic_schema_from_llm(df: pd.DataFrame, filename: str, llm_instance):
    """
    Uses an LLM to analyze a DataFrame's schema and content to determine the
    semantic meaning of its columns. (This function is unchanged)
    
    Args:
        df (pd.DataFrame): The DataFrame to analyze.
        filename (str): The name of the file for context.
        llm_instance: An initialized LLM chat model instance.

    Returns:
        dict: A dictionary representing the semantic schema, or None on failure.
    """
    print(f"\nAnalyzing '{filename}' with the LLM...")

    sample_df = df.head(5)
    preview = f"""
File Name: {filename}
Column Names: {df.columns.tolist()}
First 5 Rows (as dictionary): {sample_df.to_dict(orient='records')}
"""
    prompt = f"""
You are an expert bioinformatician data curator. Your task is to analyze the schema of a data file and create a tailored metadata description by discovering its semantic structure.

Based on the following data preview, identify the primary semantic concepts contained in the data and map them to their corresponding column names.

Data Preview:
{preview}

Instructions:
1.  Examine the column names and sample data to understand their meaning.
2.  Identify key biological concepts (e.g., "gene_symbols", "disease_name", "protein_class").
3.  Create a JSON object that maps these **discovered semantic concepts** to the actual column names.
4.  **Be selective.** Exclude generic metadata, URLs, or internal flags.
5.  Provide a brief, one-sentence description of the file's likely content.
6.  Your final output MUST be a single, valid JSON object.

JSON Output Format:
{{
  "description": "A brief, one-sentence description of the file's content.",
  "columns": {{
    "discovered_semantic_role_1": "actual_column_name_1"
  }}
}}
"""
    try:
        response = llm_instance.invoke(prompt)
        content_str = response.content
        
        if "```json" in content_str:
            content_str = content_str.split("```json")[1].split("```")[0].strip()
            
        parsed_json = json.loads(content_str)
        print(f"Successfully parsed LLM response for '{filename}'.")
        return parsed_json
    except Exception as e:
        print(f"Error processing LLM response for '{filename}': {e}")
        return None

# --- NEW IMPORTABLE FUNCTION ---
def generate_metadata_for_file(file_path: str, llm_instance):
    """
    Generates semantic metadata for a single data file.

    This function reads a supported file, prepares a preview, and uses an LLM
    to extract a semantic schema and description.

    Args:
        file_path (str): The full path to the data file.
        llm_instance: An initialized LLM chat model instance.

    Returns:
        dict: A dictionary containing the metadata, or None on failure.
    """
    filename = os.path.basename(file_path)

    if not os.path.isfile(file_path):
        print(f"Warning: Path '{file_path}' is not a valid file. Skipping metadata generation.")
        return None
        
    try:
        df = None
        file_size_bytes = os.path.getsize(file_path)
        
        # Determine how to read the file based on its extension
        if filename.endswith(".parquet"):
            df = pd.read_parquet(file_path)
        elif filename.endswith((".tsv", ".tsv.gz")):
            compression = 'gzip' if filename.endswith(".gz") else 'infer'
            if file_size_bytes > FILE_SIZE_LIMIT_MB * 1024 * 1024:
                print(f"File '{filename}' is large. Reading first 10000 rows for preview.")
                df = pd.read_csv(file_path, sep='\t', on_bad_lines='warn', compression=compression, nrows=10000)
            else:
                df = pd.read_csv(file_path, sep='\t', on_bad_lines='warn', compression=compression)
        elif filename.endswith((".csv", ".csv.gz")):
            compression = 'gzip' if filename.endswith(".gz") else 'infer'
            if file_size_bytes > FILE_SIZE_LIMIT_MB * 1024 * 1024:
                print(f"File '{filename}' is large. Reading first 10000 rows for preview.")
                df = pd.read_csv(file_path, on_bad_lines='warn', compression=compression, nrows=10000)
            else:
                df = pd.read_csv(file_path, on_bad_lines='warn', compression=compression)
        else:
            print(f"Skipping unsupported file type: {filename}")
            return None # Unsupported file type
        
        print(f"--- Generating metadata for: {filename} ---")
        
        # Get the semantic schema from the LLM
        return get_semantic_schema_from_llm(df, filename, llm_instance)

    except Exception as e:
        print(f"\nCritical Error generating metadata for {filename}. Skipping.")
        print(f"Details: {e}")
        traceback.print_exc()
        return None

# --- Main Scanner Logic (for standalone execution) ---
def main():
    """
    Example usage: Scans a directory and generates a single metadata file.
    This demonstrates how to use the generate_metadata_for_file function.
    """
    print("--- Starting Data Lake Metadata Scanner (Example Run) ---")
    
    # Configuration for the example run
    DATA_LAKE_PATH = "/Users/mohamedaminekina/Desktop/esqlabs/Biomni/data/biomni_data/data_lake"
    METADATA_OUTPUT_FILE = "data_lake_metadata.json"
    
    try:
        llm = get_llm(model='gpt-5', temperature=1.0, source='AzureOpenAI')
        print("LLM instance created successfully for scanning.")
    except Exception as e:
        print(f"Fatal Error: Could not initialize the LLM. Error: {e}")
        return

    full_metadata_catalog = {}
    for filename in os.listdir(DATA_LAKE_PATH):
        file_path = os.path.join(DATA_LAKE_PATH, filename)
        metadata = generate_metadata_for_file(file_path, llm)
        if metadata:
            full_metadata_catalog[filename] = metadata

    if full_metadata_catalog:
        try:
            with open(METADATA_OUTPUT_FILE, 'w') as f:
                json.dump(full_metadata_catalog, f, indent=2)
            print(f"\n--- Metadata catalog successfully generated! ---")
            print(f"Output saved to: {METADATA_OUTPUT_FILE}")
        except Exception as e:
            print(f"\nError writing metadata to file: {e}")
    else:
        print("\n--- Scanner finished, but no metadata was generated. ---")


if __name__ == "__main__":
    main()