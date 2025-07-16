import time
import httpx
import logging
from notebook import run_notebook_code
import asyncio
import subprocess

FASTAPI_SERVER_URL = "http://localhost:8000"
API_KEY = "supersecretkey"
AGENT_ID = "default"

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")

def send_heartbeat():
    try:
        response = httpx.post(
            f"{FASTAPI_SERVER_URL}/heartbeat",
            json={"status": "ready", "agent_id": AGENT_ID},
            headers={"x-api-key": API_KEY},
            timeout=5
        )
        if response.status_code == 200:
            logging.info("💓 Heartbeat sent successfully")
        elif response.status_code == 202:
            logging.info("📬 Task available, fetching...")
            fetch_task()
        elif response.status_code == 426:
            logging.info("⚙️ Full VM task received, fetching VM task config...")
            fetch_vm_task()
        else:
            logging.warning(f"⚠️ Heartbeat failed: {response.status_code} {response.text}")
    except Exception as e:
        logging.error(f"❌ Exception during heartbeat: {e}")

def fetch_task():
    try:
        response = httpx.get(
            f"{FASTAPI_SERVER_URL}/send_task",
            params={"agent_id": AGENT_ID},
            headers={"x-api-key": API_KEY},
            timeout=10
        )
        if response.status_code == 200:
            task = response.json()
            logging.info(f"📥 Task received: {task}")
            result = asyncio.run(run_notebook_code(task.get("code", "")))
            logging.info(f"✅ Task result: {result}")
        else:
            logging.warning(f"⚠️ Task fetch failed: {response.status_code} {response.text}")
    except Exception as e:
        logging.error(f"❌ Exception while fetching task: {e}")

def fetch_vm_task():
    try:
        response = httpx.get(
            f"{FASTAPI_SERVER_URL}/send_task",
            params={"agent_id": AGENT_ID},
            headers={"x-api-key": API_KEY},
            timeout=10
        )
        if response.status_code == 200:
            task = response.json()
            logging.info(f"🔧 VM Task received: {task}")

            args = ["python3", "vm.py", task.get("vm_type", "qemu")]
            if task.get("cpu"):
                args += ["--cpu", str(task["cpu"])]
            if task.get("ram"):
                args += ["--ram", str(task["ram"])]
            if task.get("cuda"):
                args += ["--cuda"]
            if task.get("install"):
                args += ["--install"]
            if task.get("uninstall"):
                args += ["--uninstall"]

            logging.info(f"🚀 Launching VM with args: {args}")
            subprocess.run(args)
        else:
            logging.warning(f"⚠️ VM Task fetch failed: {response.status_code} {response.text}")
    except Exception as e:
        logging.error(f"❌ Exception while fetching VM task: {e}")

if __name__ == "__main__":
    while True:
        send_heartbeat()
        time.sleep(5)
