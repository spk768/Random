"""HTTP: requisições JSON e downloads paralelos com verificação de hash."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from . import __version__

USER_AGENT = f"PackLauncher/{__version__} (github.com/spk768/random)"

ProgressFn = Callable[[int, int], None]


class DownloadError(Exception):
    pass


def open_url(url: str, data: bytes | None = None, headers: dict | None = None,
             timeout: float = 30, retries: int = 3):
    """Abre uma URL com novas tentativas em erros de rede, 429 e 5xx."""
    h = {"User-Agent": USER_AGENT}
    if headers:
        h.update(headers)
    last: Exception | None = None
    for attempt in range(retries):
        req = urllib.request.Request(url, data=data, headers=h)
        try:
            return urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            if e.code < 500 and e.code != 429:
                raise
            last = e
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last = e
        if attempt + 1 < retries:
            time.sleep(2 ** attempt)
    raise DownloadError(f"Falha ao acessar {url}: {last}")


def get_json(url: str, headers: dict | None = None):
    with open_url(url, headers=headers) as resp:
        return json.loads(resp.read().decode("utf-8"))


def post_json(url: str, payload, headers: dict | None = None):
    h = {"Content-Type": "application/json", "Accept": "application/json"}
    if headers:
        h.update(headers)
    with open_url(url, data=json.dumps(payload).encode(), headers=h) as resp:
        body = resp.read()
    return json.loads(body.decode("utf-8")) if body else None


def post_form(url: str, fields: dict):
    data = urllib.parse.urlencode(fields).encode()
    h = {"Content-Type": "application/x-www-form-urlencoded"}
    with open_url(url, data=data, headers=h) as resp:
        return json.loads(resp.read().decode("utf-8"))


def hash_file(path: Path, algo: str = "sha1") -> str:
    h = hashlib.new(algo)
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class Download:
    url: str | list[str]
    dest: Path
    sha1: str | None = None
    sha512: str | None = None
    size: int | None = None

    @property
    def urls(self) -> list[str]:
        return [self.url] if isinstance(self.url, str) else list(self.url)

    def is_valid(self) -> bool:
        """True se o arquivo já existe e confere com tamanho/hash conhecidos."""
        if not self.dest.is_file():
            return False
        if self.size is not None and self.dest.stat().st_size != self.size:
            return False
        if self.sha512:
            return hash_file(self.dest, "sha512") == self.sha512.lower()
        if self.sha1:
            return hash_file(self.dest, "sha1") == self.sha1.lower()
        return True


def download(d: Download) -> bool:
    """Baixa um arquivo se necessário. Retorna True se algo foi baixado."""
    if d.is_valid():
        return False
    if not d.urls:
        raise DownloadError(f"Nenhuma URL para {d.dest.name}")
    errors = []
    d.dest.parent.mkdir(parents=True, exist_ok=True)
    for url in d.urls:
        fd, tmp = tempfile.mkstemp(dir=d.dest.parent, prefix=".dl-")
        try:
            h1, h512, size = hashlib.sha1(), hashlib.sha512(), 0
            with os.fdopen(fd, "wb") as out, open_url(url, timeout=60) as resp:
                for chunk in iter(lambda: resp.read(1 << 16), b""):
                    out.write(chunk)
                    h1.update(chunk)
                    h512.update(chunk)
                    size += len(chunk)
            if d.size is not None and size != d.size:
                raise DownloadError(f"tamanho {size} != {d.size}")
            if d.sha512 and h512.hexdigest() != d.sha512.lower():
                raise DownloadError("sha512 não confere")
            if d.sha1 and h1.hexdigest() != d.sha1.lower():
                raise DownloadError("sha1 não confere")
            os.replace(tmp, d.dest)
            return True
        except Exception as e:  # tenta a próxima URL
            errors.append(f"{url}: {e}")
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
    raise DownloadError(f"Falha ao baixar {d.dest.name}: " + "; ".join(errors))


def download_many(downloads: Iterable[Download], workers: int = 8,
                  progress: ProgressFn | None = None) -> None:
    unique: dict[Path, Download] = {}
    for d in downloads:
        unique.setdefault(d.dest, d)
    items = list(unique.values())
    total = len(items)
    if not total:
        return
    done = 0
    lock = threading.Lock()
    errors: list[str] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = [pool.submit(download, d) for d in items]
        for fut in as_completed(futures):
            try:
                fut.result()
            except Exception as e:
                errors.append(str(e))
            with lock:
                done += 1
                if progress:
                    progress(done, total)
    if errors:
        more = f" (+{len(errors) - 5} erros)" if len(errors) > 5 else ""
        raise DownloadError("\n".join(errors[:5]) + more)
