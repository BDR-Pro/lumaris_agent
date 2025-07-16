import nbformat
from nbclient import NotebookClient
import time
import logging

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")

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
async def run_notebook_code(code: str) -> str:
    logging.info("Received code for execution")
    nb = nbformat.v4.new_notebook()
    nb.cells = [nbformat.v4.new_code_cell(code)]

    client = NotebookClient(nb, timeout=300, kernel_name="python3")
    client.execute()

    output_texts = []
    for cell in nb.cells:
        for output in cell.get("outputs", []):
            if output["output_type"] == "execute_result":
                output_texts.append(output["data"]["text/plain"])
            elif output["output_type"] == "stream":
                output_texts.append(output["text"])
            elif output["output_type"] == "error":
                output_texts.append(f"Error: {output['ename']}: {output['evalue']}")

    full_output = "\n".join(output_texts)
    logging.info("Execution complete. Returning result.")
    return full_output
