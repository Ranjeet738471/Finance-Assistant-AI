"""Start the TBX backend and frontend together on Windows."""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
FRONTEND_FILES = [PROJECT_ROOT / "frontend" / "app.py"]


def start_process(command: list[str], name: str) -> subprocess.Popen:
    print(f"Starting {name}: {' '.join(command)}", flush=True)
    return subprocess.Popen(command, cwd=PROJECT_ROOT, env=os.environ.copy())


def stop_process(process: subprocess.Popen, name: str) -> None:
    if process.poll() is None:
        print(f"Stopping {name}...", flush=True)
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def file_signature(paths: list[Path]) -> tuple[tuple[str, int, int], ...]:
    return tuple(
        (str(path), path.stat().st_mtime_ns, path.stat().st_size)
        for path in paths
        if path.exists()
    )


def start_frontend(environment: dict[str, str]) -> subprocess.Popen:
    print("Starting frontend on http://localhost:8502", flush=True)
    return subprocess.Popen(
        [sys.executable, "frontend/app.py"],
        cwd=PROJECT_ROOT,
        env=environment,
    )


def main() -> int:
    environment = os.environ.copy()
    environment.setdefault("FIN_DB_BACKEND", "mysql")

    backend = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "backend.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8000",
            "--reload",
            "--reload-dir",
            str(PROJECT_ROOT / "backend"),
        ],
        cwd=PROJECT_ROOT,
        env=environment,
    )
    print("Backend started on http://localhost:8000", flush=True)

    frontend = start_frontend(environment)
    frontend_signature = file_signature(FRONTEND_FILES)
    print("Frontend started on http://localhost:8502", flush=True)
    print("Backend reloads automatically; frontend restarts when frontend/app.py changes.", flush=True)
    print("Press Ctrl+C to stop both services.", flush=True)

    try:
        while True:
            backend_code = backend.poll()
            frontend_code = frontend.poll()
            if backend_code is not None:
                print(f"Backend exited with code {backend_code}.", flush=True)
                return backend_code
            if frontend_code is not None:
                print(f"Frontend exited with code {frontend_code}.", flush=True)
                return frontend_code
            current_signature = file_signature(FRONTEND_FILES)
            if current_signature != frontend_signature:
                print("Frontend change detected; restarting frontend.", flush=True)
                stop_process(frontend, "frontend")
                frontend = start_frontend(environment)
                frontend_signature = current_signature
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutdown requested.", flush=True)
        return 0
    finally:
        stop_process(frontend, "frontend")
        stop_process(backend, "backend")


if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal.default_int_handler)
    raise SystemExit(main())
