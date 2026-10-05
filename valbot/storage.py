from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile

from cryptography.fernet import Fernet, InvalidToken
import portalocker

ROOT = Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    path = Path(os.environ.get("VALBOT_DATA_DIR", ROOT / "data")).resolve()
    if not path.exists():
        path.mkdir(parents=True, mode=0o700)
        if os.name == "nt":
            # Use the current user's SID; avoid localized account/group names.
            sid = subprocess.check_output(["whoami", "/user", "/fo", "csv", "/nh"], text=True)
            import csv
            user_sid = next(csv.reader([sid.strip()]))[1]
            subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r",
                            f"*{user_sid}:(OI)(CI)F"], check=True, capture_output=True)
    if os.name != "nt":
        path.chmod(0o700)
    return path


def atomic_write(path: Path, content: bytes) -> None:
    fd, name = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(content)
        os.replace(name, path)
        if os.name != "nt":
            path.chmod(0o600)
    finally:
        if os.path.exists(name):
            os.unlink(name)


class Vault:
    """Encryption at rest; the local key must be protected together with the OS account."""

    def __init__(self, directory: Path | None = None):
        self.directory = directory or data_dir()
        self.directory.mkdir(parents=True, exist_ok=True)
        with portalocker.Lock(str(self.directory / "key.lock"), timeout=30):
            key = self.directory / "vault.key"
            if not key.exists():
                atomic_write(key, Fernet.generate_key())
            self.cipher = Fernet(key.read_bytes())

    def read(self, name: str) -> dict:
        path = self.directory / f"{name}.enc"
        if not path.exists():
            return {}
        try:
            return json.loads(self.cipher.decrypt(path.read_bytes()))
        except (InvalidToken, ValueError) as exc:
            raise RuntimeError("本機加密資料無法讀取；請還原 vault.key 或重新執行 setup.py。") from exc

    def write(self, name: str, value: dict) -> None:
        atomic_write(self.directory / f"{name}.enc",
                     self.cipher.encrypt(json.dumps(value, ensure_ascii=False).encode()))

    def lock(self, name: str):
        return portalocker.Lock(str(self.directory / f"{name}.lock"), timeout=60)


def load_config() -> dict:
    config = Vault().read("config")
    if not config:
        raise RuntimeError("尚未設定，請先執行 setup.py。")
    return config
