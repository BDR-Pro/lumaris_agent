import argparse
import subprocess
import os
import shutil
import requests
import re
from typing import List

KERNEL_URL = "https://cdn.kernel.org/pub/linux/kernel/v5.x/linux-5.10.1.tar.xz"
KERNEL_ARCHIVE = "linux-5.10.1.tar.xz"
KERNEL_DIR = "linux-5.10.1"
ROOTFS_URL = "https://cloud-images.ubuntu.com/minimal/releases/focal/release/ubuntu-20.04-minimal-cloudimg-amd64.img"
ROOTFS_IMG = "rootfs.img"

def download_file(url, filename):
    if os.path.exists(filename):
        print(f"[+] {filename} already exists.")
        return
    print(f"[+] Downloading {filename} ...")
    with requests.get(url, stream=True) as r:
        r.raise_for_status()
        with open(filename, 'wb') as f:
            shutil.copyfileobj(r.raw, f)
    print(f"[+] Downloaded {filename}.")

def extract_kernel_source():
    if os.path.exists(KERNEL_DIR):
        print(f"[+] Kernel source directory already exists.")
        return
    subprocess.run(["tar", "-xf", KERNEL_ARCHIVE])

def build_kernel():
    os.chdir(KERNEL_DIR)
    subprocess.run(["make", "defconfig"])
    subprocess.run(["make", "-j", str(os.cpu_count())])
    os.chdir("..")
    bzimage = os.path.join(KERNEL_DIR, "arch/x86/boot/bzImage")
    if os.path.exists(bzimage):
        shutil.copy(bzimage, "vmlinux")
        print("[+] Kernel built and copied to vmlinux.")
    else:
        print("[!] Kernel build failed.")

def auto_build_kernel():
    if not os.path.exists("vmlinux"):
        print("[*] Kernel not found. Building from source...")
        download_file(KERNEL_URL, KERNEL_ARCHIVE)
        extract_kernel_source()
        build_kernel()

def list_nvidia_gpus() -> List[str]:
    gpus = []
    try:
        output = subprocess.check_output(['lspci', '-nn'], text=True)
        for line in output.splitlines():
            if 'NVIDIA' in line:
                match = re.search(r'^(\S+)', line)
                if match:
                    gpus.append(match.group(1))
    except Exception as e:
        print(f"[!] GPU detection error: {e}")
    return gpus

def gpu_menu_select(gpus: List[str]) -> List[str]:
    print("Select GPUs to passthrough (comma-separated):")
    for i, gpu in enumerate(gpus):
        print(f"{i}: {gpu}")
    selected = input("Your choice: ").strip()
    try:
        indices = [int(x) for x in selected.split(",") if x.isdigit()]
        return [gpus[i] for i in indices if i < len(gpus)]
    except Exception as e:
        print(f"[!] Invalid input: {e}")
        return []

def vfio_bind(pci_id: str):
    subprocess.run(["modprobe", "vfio-pci"])
    print(f"[+] Binding {pci_id} to vfio-pci...")
    try:
        with open(f"/sys/bus/pci/devices/0000:{pci_id}/driver/unbind", 'w') as f:
            f.write(f"0000:{pci_id}")
    except Exception: pass
    try:
        with open(f"/sys/bus/pci/devices/0000:{pci_id}/vendor") as f:
            vendor = f.read().strip()
        with open(f"/sys/bus/pci/devices/0000:{pci_id}/device") as f:
            device = f.read().strip()
        with open("/sys/bus/pci/drivers/vfio-pci/new_id", 'w') as f:
            f.write(f"{vendor} {device}")
    except Exception as e:
        print(f"[!] Failed to bind GPU: {e}")

def run_qemu(cpu, ram, passthrough_ids):
    vfio_args = []
    for pci_id in passthrough_ids:
        vfio_args += ["-device", f"vfio-pci,host={pci_id}"]

    cmd = [
        "qemu-system-x86_64",
        "-enable-kvm",
        "-machine", "type=q35,accel=kvm",
        "-cpu", "host",
        "-smp", str(cpu),
        "-m", f"{ram}G",
        "-kernel", "vmlinux",
        "-drive", f"file={ROOTFS_IMG},format=raw,if=virtio",
        "-append", "console=ttyS0 root=/dev/vda rw",
        "-nographic"
    ] + vfio_args

    print(f"[+] Starting QEMU...")
    subprocess.run(cmd)

def run_firecracker(cpu, ram):
    print("[*] Starting Firecracker...")
    socket_path = "/tmp/firecracker.socket"
    if os.path.exists(socket_path):
        os.remove(socket_path)
    subprocess.Popen(["firecracker", "--api-sock", socket_path])

    import time, json, requests
    time.sleep(1)
    headers = {"Content-Type": "application/json"}
    url = f"http+unix://{socket_path.replace('/', '%2F')}"

    def put(endpoint, data):
        requests.put(f"{url}{endpoint}", headers=headers, data=json.dumps(data))

    put("/boot-source", {
        "kernel_image_path": "vmlinux",
        "boot_args": "console=ttyS0 reboot=k panic=1 pci=off"
    })
    put("/drives/rootfs", {
        "drive_id": "rootfs",
        "path_on_host": ROOTFS_IMG,
        "is_root_device": True,
        "is_read_only": False
    })
    put("/machine-config", {
        "vcpu_count": cpu,
        "mem_size_mib": ram * 1024,
        "ht_enabled": True
    })
    put("/actions", {"action_type": "InstanceStart"})
    print("[+] Firecracker launched.")
    
def install_dependencies():
    print("[+] Installing QEMU and Firecracker...")

    subprocess.run(["sudo", "apt", "update"])
    subprocess.run(["sudo", "apt", "install", "-y", "qemu-system-x86", "qemu-kvm", "pciutils", "curl", "make", "gcc"])

    if not shutil.which("firecracker"):
        print("[+] Installing Firecracker binary...")
        subprocess.run([
            "bash", "-c",
            "curl -LO https://github.com/firecracker-microvm/firecracker/releases/latest/download/firecracker-x86_64 && "
            "chmod +x firecracker-x86_64 && "
            "sudo mv firecracker-x86_64 /usr/local/bin/firecracker"
        ])
    else:
        print("[✓] Firecracker already installed.")

    print("[✓] All dependencies installed.")

def uninstall_dependencies():
    print("[!] Uninstalling QEMU and Firecracker...")
    
    print("[!] Removing Firecracker binary...")
    subprocess.run(["sudo", "rm", "-f", "/usr/local/bin/firecracker"])

    print("[!] Deleting kernel and rootfs files...")
    for file in [KERNEL_ARCHIVE, "vmlinux", ROOTFS_IMG]:
        if os.path.exists(file):
            os.remove(file)
            print(f"  - Removed {file}")
    if os.path.exists(KERNEL_DIR):
        print(f"  - Removing {KERNEL_DIR}/ source directory...")
        shutil.rmtree(KERNEL_DIR)
        print(f"  - Removed {KERNEL_DIR} source directory")

    print("[!] Purging QEMU from system...")
    subprocess.run(["sudo", "apt", "remove", "--purge", "-y", "qemu-system-x86", "qemu-kvm"])
    subprocess.run(["sudo", "apt", "autoremove", "-y"])

    print("[✓] Uninstall complete.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("vm_type", choices=["qemu", "firecracker"])
    parser.add_argument("--cpu", type=int, default=2)
    parser.add_argument("--ram", type=int, default=2)
    parser.add_argument("--cuda", action="store_true")
    parser.add_argument("--install", action="store_true", help="Install dependencies")
    parser.add_argument("--uninstall", action="store_true", help="Remove QEMU, Firecracker, and downloaded files")

    args = parser.parse_args()
    if args.uninstall:
        uninstall_dependencies()
        return
    if args.install:
        install_dependencies()
        return
    # Ensure rootfs and kernel are ready
    download_file(ROOTFS_URL, ROOTFS_IMG)
    auto_build_kernel()

    gpu_ids = []
    if args.cuda and args.vm_type == "qemu":
        gpus = list_nvidia_gpus()
        if gpus:
            selected = gpu_menu_select(gpus)
            for pci_id in selected:
                vfio_bind(pci_id)
                gpu_ids.append(pci_id)

    if args.vm_type == "qemu":
        run_qemu(args.cpu, args.ram, gpu_ids)
    elif args.vm_type == "firecracker":
        run_firecracker(args.cpu, args.ram)

if __name__ == "__main__":
    main()
