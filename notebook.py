import nbformat
from nbclient import NotebookClient
import time
import logging
import base64
import json
import subprocess
import uuid
import os
from typing import List, Union

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")

DOCKER_IMAGE = "jupyter/minimal-notebook"
TIMEOUT = 30

# Decorator to time any async function
def timed(func):
    async def wrapper(*args, **kwargs):
        start = time.time()
        try:
            result = await func(*args, **kwargs)
            duration = round(time.time() - start, 4)
            return {"result": result, "duration_seconds": duration}
        except Exception as e:
            duration = round(time.time() - start, 4)
            logging.exception("Execution failed")
            return {"error": str(e), "duration_seconds": duration}
    return wrapper

@timed
async def run_notebook_code(code: Union[str, List[str], dict]) -> List[dict]:
    logging.info("Received code for Docker-based execution")

    # Prepare notebook
    if isinstance(code, dict):
        nb = nbformat.from_dict(code)
    else:
        nb = nbformat.v4.new_notebook()
        cells = [code] if isinstance(code, str) else code
        nb.cells = [nbformat.v4.new_code_cell(c) for c in cells]

    # Save notebook to temp file
    notebook_id = str(uuid.uuid4())
    input_path = f"/tmp/{notebook_id}_input.ipynb"
    output_path = f"/tmp/{notebook_id}_output.ipynb"

    with open(input_path, "w") as f:
        nbformat.write(nb, f)

    # Run notebook inside Docker
    try:
        subprocess.run([
            "docker", "run", "--rm",
            "-v", f"{os.path.abspath(input_path)}:/home/jovyan/input.ipynb",
            "-v", f"{os.path.abspath(output_path)}:/home/jovyan/output.ipynb",
            DOCKER_IMAGE,
            "jupyter", "nbconvert", "--to", "notebook", "--execute",
            "--ExecutePreprocessor.timeout=25", "--output", "output.ipynb",
            "input.ipynb"
        ], check=True, timeout=TIMEOUT)
    except subprocess.CalledProcessError as e:
        logging.error("Docker execution failed")
        return [{"type": "error", "value": "Docker execution error"}]
    except subprocess.TimeoutExpired:
        logging.warning("Docker execution timed out")
        return [{"type": "error", "value": "Execution timed out"}]

    # Read output notebook
    if not os.path.exists(output_path):
        return [{"type": "error", "value": "Output notebook not found"}]

    with open(output_path) as f:
        executed_nb = nbformat.read(f, as_version=4)

    output_objects = []
    for cell in executed_nb.cells:
        for output in cell.get("outputs", []):
            if output["output_type"] == "execute_result":
                output_objects.append({"type": "text", "value": output["data"].get("text/plain", "")})
            elif output["output_type"] == "stream":
                output_objects.append({"type": "text", "value": output.get("text", "")})
            elif output["output_type"] == "error":
                output_objects.append({"type": "error", "value": f"{output['ename']}: {output['evalue']}"})
            elif output["output_type"] == "display_data":
                data = output.get("data", {})
                if "image/png" in data:
                    output_objects.append({"type": "image", "mime": "image/png", "base64": data["image/png"]})
                elif "text/html" in data:
                    output_objects.append({"type": "html", "value": data["text/html"]})

    logging.info("Docker notebook execution complete")

    # Cleanup
    os.remove(input_path)
    if os.path.exists(output_path):
        os.remove(output_path)

    return output_objects
