"""The llama-server child process: started by the gateway and reached on
127.0.0.1 only, never from outside the container.

The gateway owns its life: it starts it with the model found in the models
folder (/models by default), watches it, and reports in /v1/health whether
it is loading, dead or missing.
"""
import os
import subprocess
from pathlib import Path

# the binary, its local port and the models folder, each set from the environment
LLAMA_BIN = os.environ.get("FESPP_IA_LLAMA_BIN", "/app/llama-server")
LLAMA_PORT = int(os.environ.get("FESPP_IA_LLAMA_PORT", "8081"))
MODELS_DIR = Path(os.environ.get("FESPP_IA_MODELS", "/models"))


def find_model(models_dir=MODELS_DIR, wanted=None):
    """The chat model: FESPP_IA_CHAT_MODEL when it names a file (absolute, or
    relative to the models folder), else the only .gguf of the folder; None
    otherwise. Several .gguf and no choice give no model: guessing could
    load the wrong one."""
    wanted = wanted if wanted is not None else os.environ.get("FESPP_IA_CHAT_MODEL", "")
    if wanted:
        p = Path(wanted)
        p = p if p.is_absolute() else Path(models_dir) / p
        return p if p.is_file() else None
    found = sorted(Path(models_dir).glob("*.gguf")) if Path(models_dir).is_dir() else []
    return found[0] if len(found) == 1 else None


def command(model, port=LLAMA_PORT):
    """The llama-server command line, every knob from the environment."""
    env = os.environ.get
    return [
        LLAMA_BIN, "--model", str(model),
        "--host", "127.0.0.1", "--port", str(port),
        "--ctx-size", env("FESPP_IA_CTX", "8192"),
        "--parallel", env("FESPP_IA_PARALLEL", "1"),
        # 0 on the cpu image, 99 (every layer) on the cuda one
        "--n-gpu-layers", env("FESPP_IA_GPU_LAYERS", "0"),
        "--no-webui",
    ]


class LlamaProcess:
    """The llama-server process, the model it serves, and why it could not
    start (`error`, "" when it started)."""

    def __init__(self):
        self.model = None
        self.proc = None
        self.error = ""

    def start(self):
        """Find the model and start llama-server; without a model, set
        `error` and start nothing."""
        self.model = find_model()
        if self.model is None:
            self.error = f"no model: put ONE .gguf in {MODELS_DIR} or set FESPP_IA_CHAT_MODEL"
            print("[fespp_ia]", self.error, flush=True)
            return
        cmd = command(self.model)
        print("[fespp_ia] starting:", " ".join(cmd), flush=True)
        # its shared libraries sit next to the binary (the layout of
        # llama.cpp's image): run from that folder, with it on LD_LIBRARY_PATH
        home = str(Path(LLAMA_BIN).parent)
        env = dict(os.environ)
        env["LD_LIBRARY_PATH"] = ":".join(filter(None, [home, env.get("LD_LIBRARY_PATH")]))
        self.proc = subprocess.Popen(cmd, cwd=home, env=env)

    def alive(self):
        """True while the process runs."""
        return self.proc is not None and self.proc.poll() is None

    def stop(self):
        """Terminate the process, and kill it if it has not exited after 10 s."""
        if self.alive():
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
