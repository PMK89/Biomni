import json
import os
from pathlib import Path

# --- Configuration ---
# Set the path to the generated metadata file.
# The tool needs to know where to find its catalog.
SCRIPT_DIR = Path(__file__).resolve().parent
# Go up TWO levels from the script's directory
METADATA_FILE_PATH = SCRIPT_DIR.parent.parent / "data" / "biomni_data" / "data_lake_metadata.json"


# --- The Tool Function ---

def get_metadata(filename: str) -> dict:
    """
    Retrieves the pre-generated metadata for a specific file from the data lake catalog.

    This tool allows an agent to quickly understand the schema and contents of a dataset
    without having to parse the file itself.

    Args:
        filename (str): The name of the file (e.g., "proteinatlas.tsv") to look up.

    Returns:
        dict: The metadata dictionary for the requested file.
              Returns an error message if the file is not found in the catalog.
    """
    print(f"Attempting to retrieve metadata for: {filename}")

    # 1. Check if the metadata catalog exists.
    if not os.path.exists(METADATA_FILE_PATH):
        return {
            "error": f"Metadata catalog not found at '{METADATA_FILE_PATH}'. Please run the scanner script first."
        }

    # 2. Load the entire metadata catalog from the JSON file.
    try:
        with open(METADATA_FILE_PATH, 'r') as f:
            catalog = json.load(f)
    except json.JSONDecodeError:
        return {"error": "Metadata file is corrupted or not a valid JSON."}
    except Exception as e:
        return {"error": f"Failed to read metadata file: {e}"}

    # 3. Look up the specific filename in the catalog.
    metadata = catalog.get(filename)

    # 4. Return the result.
    if metadata:
        print(f"Successfully found metadata for '{filename}'.")
        return metadata
    else:
        print(f"Warning: No metadata found for '{filename}' in the catalog.")
        return {
            "error": f"No metadata entry found for '{filename}'. It might not have been scanned or supported."
        }

