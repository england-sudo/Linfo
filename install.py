#!/usr/bin/env python3
import os
import re
import shutil
import subprocess
import sys


def resource_path(relative_path):
    # Always resolve relative to the install.py location
    base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)



APP_NAME = "linfo"
DESKTOP_ENTRY_NAME = f"{APP_NAME}.desktop"
LOCAL_APPS_PATH = os.path.expanduser("~/.local/share/applications")
ICON_TARGET_PATH = os.path.expanduser(f"~/.local/share/icons/{APP_NAME}.svg")
INSTALL_DIR = os.path.expanduser("~/.local/share/linfo")
VENV_PATH = os.path.join(INSTALL_DIR, ".venv")
LAUNCHER_TARGET_PATH = os.path.join(INSTALL_DIR, "linfo_launcher.sh")
EXECUTABLE_PATH = os.path.abspath("hwtop.py")


def detect_package_manager():
    for manager in ("apt-get", "dnf", "pacman"):
        if shutil.which(manager):
            return manager
    return None


def build_install_command(package_manager, packages):
    if package_manager == "apt-get":
        return [
            ["apt-get", "update"],
            ["apt-get", "install", "-y", *packages],
        ]
    if package_manager == "dnf":
        return [["dnf", "install", "-y", *packages]]
    if package_manager == "pacman":
        return [["pacman", "-S", "--noconfirm", "--needed", *packages]]
    return []


def run_with_privilege(cmd):
    if os.geteuid() == 0:
        subprocess.check_call(cmd)
        return

    if shutil.which("pkexec"):
        subprocess.check_call(["pkexec", *cmd])
        return

    if shutil.which("sudo"):
        subprocess.check_call(["sudo", *cmd])
        return

    raise RuntimeError("No privilege escalation tool found (pkexec/sudo).")


def needs_venv_module():
    try:
        import venv  # noqa: F401
        return False
    except ImportError:
        return True

def ensure_icon():
    source_icon = resource_path("icon.svg")
    if os.path.exists(source_icon):
        os.makedirs(os.path.dirname(ICON_TARGET_PATH), exist_ok=True)
        with open(source_icon, "rb") as src, open(ICON_TARGET_PATH, "wb") as dst:
            dst.write(src.read())
        print(f"Copied icon to {ICON_TARGET_PATH}")
    else:
        print("Warning: icon.svg not found. Icon will not appear in launcher.")

DESKTOP_ENTRY_CONTENT = f"""[Desktop Entry]
Type=Application
Name=Linfo
Comment=Linux Hardware Monitor
Comment[en_US]=Linux Hardware Monitor
Exec={LAUNCHER_TARGET_PATH}
TryExec={LAUNCHER_TARGET_PATH}
Icon={ICON_TARGET_PATH}
Terminal=false
Categories=Utility;
"""

def ensure_venv():
    if os.path.exists(VENV_PATH):
        return
    print(f"Creating virtual environment at {VENV_PATH}...")
    os.makedirs(INSTALL_DIR, exist_ok=True)
    subprocess.check_call([sys.executable, "-m", "venv", VENV_PATH])


def parse_requirements(requirements_path):
    packages = []
    with open(requirements_path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            name = re.split(r"[<=>;\[]", line, maxsplit=1)[0].strip()
            if name:
                packages.append(name)
    return packages


def missing_python_packages(venv_python, packages):
    missing = []
    for package in packages:
        result = subprocess.run(
            [venv_python, "-m", "pip", "show", package],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if result.returncode != 0:
            missing.append(package)
    return missing


def ensure_requirements():
    if not os.path.exists("requirements.txt"):
        print("No requirements.txt found, skipping dependency install.")
        return

    venv_python = os.path.join(VENV_PATH, "bin", "python")
    packages = parse_requirements("requirements.txt")
    missing = missing_python_packages(venv_python, packages)
    if not missing:
        print("Python dependencies already satisfied.")
        return

    print("Installing missing Python dependencies into the local virtual environment...")
    subprocess.check_call([venv_python, "-m", "pip", "install", "--upgrade", "pip"])
    subprocess.check_call([venv_python, "-m", "pip", "install", *missing])


def ensure_system_packages():
    package_manager = detect_package_manager()
    if not package_manager:
        print("No supported package manager found (apt-get/dnf/pacman). Skipping system package install.")
        return

    needed_packages = []
    if not shutil.which("dmidecode"):
        needed_packages.append("dmidecode")

    if needs_venv_module():
        if package_manager == "apt-get":
            needed_packages.append("python3-venv")
        elif package_manager == "dnf":
            needed_packages.append("python3-virtualenv")
        elif package_manager == "pacman":
            needed_packages.append("python-virtualenv")

    if not needed_packages:
        print("System packages already satisfied.")
        return

    print(f"Installing missing system packages via {package_manager}: {', '.join(needed_packages)}")
    for cmd in build_install_command(package_manager, needed_packages):
        run_with_privilege(cmd)


def ensure_launcher():
    os.makedirs(INSTALL_DIR, exist_ok=True)
    source_launcher = resource_path("linfo_launcher.sh")
    with open(source_launcher, "r", encoding="utf-8") as src:
        launcher_contents = src.read()

    launcher_contents = launcher_contents.replace(
        'APP_DIR="${LINFO_APP_DIR:-$SCRIPT_DIR}"',
        f'APP_DIR="${{LINFO_APP_DIR:-{os.path.dirname(EXECUTABLE_PATH)}}}"'
    ).replace(
        'VENV_PYTHON="${LINFO_PYTHON:-$SCRIPT_DIR/.venv/bin/python}"',
        f'VENV_PYTHON="${{LINFO_PYTHON:-{VENV_PATH}/bin/python}}"'
    )

    with open(LAUNCHER_TARGET_PATH, "w", encoding="utf-8") as dst:
        dst.write(launcher_contents)
    os.chmod(LAUNCHER_TARGET_PATH, 0o755)

def ensure_desktop_entry():
    desktop_path = os.path.join(LOCAL_APPS_PATH, DESKTOP_ENTRY_NAME)
    os.makedirs(LOCAL_APPS_PATH, exist_ok=True)
    if os.path.exists(desktop_path):
        with open(desktop_path, "r", encoding="utf-8") as f:
            existing_content = f.read()
    else:
        existing_content = ""

    if existing_content != DESKTOP_ENTRY_CONTENT:
        print("Writing desktop entry...")
        with open(desktop_path, "w", encoding="utf-8") as f:
            f.write(DESKTOP_ENTRY_CONTENT)
        os.chmod(desktop_path, 0o755)
        print(f"Desktop entry updated at {desktop_path}")
    else:
        print("Desktop entry already up to date.")

def launch_linfo():
    from hwtop import LinfoApp
    from PyQt6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    window = LinfoApp()
    window.show()
    sys.exit(app.exec())


def should_launch_gui():
    if os.environ.get("LINFO_NO_LAUNCH") == "1":
        print("Skipping GUI launch (LINFO_NO_LAUNCH=1).")
        return False
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        print("Skipping GUI launch (no DISPLAY/WAYLAND_DISPLAY).")
        return False
    return True

def ensure_executables():
    paths_to_fix = [
        os.path.abspath("hwtop.py"),
        os.path.abspath("linfo_launcher.sh"),
        os.path.abspath(__file__),  # Optional: make install.py executable too
    ]

    for path in paths_to_fix:
        if os.path.exists(path):
            current_mode = os.stat(path).st_mode
            os.chmod(path, current_mode | 0o111)
            print(f"Made {path} executable.")
        else:
            print(f"Warning: {path} not found.")



if __name__ == "__main__":
    ensure_system_packages()
    ensure_executables()
    ensure_icon()
    ensure_venv()
    ensure_launcher()
    ensure_desktop_entry()
    ensure_requirements()
    if should_launch_gui():
        launch_linfo()
