"""Contas: offline e Microsoft (device code -> Xbox Live -> Minecraft)."""
from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import uuid as uuidlib
from typing import Callable

from . import net, paths, settings

MS_DEVICE_CODE = "https://login.microsoftonline.com/consumers/oauth2/v2.0/devicecode"
MS_TOKEN = "https://login.microsoftonline.com/consumers/oauth2/v2.0/token"
XBL_AUTH = "https://user.auth.xboxlive.com/user/authenticate"
XSTS_AUTH = "https://xsts.auth.xboxlive.com/xsts/authorize"
MC_LOGIN = "https://api.minecraftservices.com/authentication/login_with_xbox"
MC_PROFILE = "https://api.minecraftservices.com/minecraft/profile"
SCOPE = "XboxLive.signin offline_access"


class AuthError(Exception):
    pass


# --------------------------------------------------------------------------
# Armazenamento
# --------------------------------------------------------------------------

def _load() -> dict:
    try:
        return json.loads(paths.accounts_file().read_text("utf-8"))
    except (OSError, ValueError):
        return {"default": None, "accounts": []}


def _save(data: dict) -> None:
    path = paths.accounts_file()
    path.write_text(json.dumps(data, indent=2), "utf-8")
    try:
        os.chmod(path, 0o600)  # contém tokens
    except OSError:
        pass


def list_accounts() -> list[dict]:
    return _load()["accounts"]


def get_default() -> dict | None:
    data = _load()
    accounts = data["accounts"]
    return next((a for a in accounts if a["uuid"] == data.get("default")),
                accounts[0] if accounts else None)


def find(name_or_uuid: str) -> dict | None:
    key = name_or_uuid.lower()
    return next((a for a in list_accounts()
                 if a["name"].lower() == key or a["uuid"] == key), None)


def save_account(account: dict, make_default: bool = False) -> None:
    data = _load()
    data["accounts"] = [a for a in data["accounts"] if a["uuid"] != account["uuid"]]
    data["accounts"].append(account)
    if make_default or not data.get("default"):
        data["default"] = account["uuid"]
    _save(data)


def set_default(uuid: str) -> None:
    data = _load()
    data["default"] = uuid
    _save(data)


def remove(uuid: str) -> None:
    data = _load()
    data["accounts"] = [a for a in data["accounts"] if a["uuid"] != uuid]
    if data.get("default") == uuid:
        data["default"] = data["accounts"][0]["uuid"] if data["accounts"] else None
    _save(data)


# --------------------------------------------------------------------------
# Offline
# --------------------------------------------------------------------------

def offline_uuid(name: str) -> str:
    """Mesmo UUID que o servidor gera em modo offline (UUID.nameUUIDFromBytes)."""
    digest = bytearray(hashlib.md5(f"OfflinePlayer:{name}".encode()).digest())
    digest[6] = (digest[6] & 0x0F) | 0x30
    digest[8] = (digest[8] & 0x3F) | 0x80
    return str(uuidlib.UUID(bytes=bytes(digest)))


def add_offline(name: str) -> dict:
    if not (3 <= len(name) <= 16) or not all(c.isalnum() or c == "_" for c in name):
        raise AuthError("Nome inválido: use 3-16 letras, números ou _")
    account = {"type": "offline", "name": name, "uuid": offline_uuid(name)}
    save_account(account)
    return account


# --------------------------------------------------------------------------
# Microsoft
# --------------------------------------------------------------------------

def _client_id() -> str:
    cid = settings.get("msa_client_id")
    if not cid:
        raise AuthError("Login Microsoft requer um Client ID do Azure. Defina 'msa_client_id' "
                        "em settings.json ou a variável PACKLAUNCHER_MSA_CLIENT_ID.")
    return cid


def _post_form_allow_error(url: str, fields: dict) -> dict:
    try:
        return net.post_form(url, fields)
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8"))
        except ValueError:
            raise AuthError(f"HTTP {e.code} em {url}") from e


def login_microsoft(show_code: Callable[[str, str], None],
                    cancelled: Callable[[], bool] = lambda: False) -> dict:
    """Login por device code. show_code(url, código) deve exibir as instruções."""
    cid = _client_id()
    dc = net.post_form(MS_DEVICE_CODE, {"client_id": cid, "scope": SCOPE})
    show_code(dc["verification_uri"], dc["user_code"])
    interval = int(dc.get("interval", 5))
    deadline = time.time() + int(dc.get("expires_in", 900))
    while time.time() < deadline:
        if cancelled():
            raise AuthError("Login cancelado")
        time.sleep(interval)
        tok = _post_form_allow_error(MS_TOKEN, {
            "client_id": cid,
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "device_code": dc["device_code"],
        })
        err = tok.get("error")
        if err == "authorization_pending":
            continue
        if err == "slow_down":
            interval += 5
            continue
        if err:
            raise AuthError(tok.get("error_description", err))
        account = _minecraft_from_ms(tok)
        save_account(account, make_default=True)
        return account
    raise AuthError("Código expirou")


def _minecraft_from_ms(ms_token: dict) -> dict:
    xbl = net.post_json(XBL_AUTH, {
        "Properties": {"AuthMethod": "RPS", "SiteName": "user.auth.xboxlive.com",
                       "RpsTicket": f"d={ms_token['access_token']}"},
        "RelyingParty": "http://auth.xboxlive.com", "TokenType": "JWT",
    })
    try:
        xsts = net.post_json(XSTS_AUTH, {
            "Properties": {"SandboxId": "RETAIL", "UserTokens": [xbl["Token"]]},
            "RelyingParty": "rp://api.minecraftservices.com/", "TokenType": "JWT",
        })
    except urllib.error.HTTPError as e:
        code = ""
        try:
            code = str(json.loads(e.read().decode()).get("XErr", ""))
        except ValueError:
            pass
        reasons = {"2148916233": "a conta não tem perfil Xbox",
                   "2148916238": "conta de menor precisa ser adicionada a uma família"}
        raise AuthError("Xbox Live recusou: " + reasons.get(code, f"erro {e.code} {code}")) from e
    uhs = xsts["DisplayClaims"]["xui"][0]["uhs"]
    mc = net.post_json(MC_LOGIN, {"identityToken": f"XBL3.0 x={uhs};{xsts['Token']}"})
    try:
        profile = net.get_json(MC_PROFILE, {"Authorization": f"Bearer {mc['access_token']}"})
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise AuthError("Esta conta não possui o Minecraft: Java Edition") from e
        raise
    pid = profile["id"]
    return {
        "type": "msa",
        "name": profile["name"],
        "uuid": str(uuidlib.UUID(pid)),
        "access_token": mc["access_token"],
        "expires_at": time.time() + int(mc.get("expires_in", 86400)) - 300,
        "refresh_token": ms_token.get("refresh_token"),
        "xuid": xsts["DisplayClaims"]["xui"][0].get("xid", ""),
    }


def ensure_valid(account: dict) -> dict:
    """Renova o token Microsoft se expirou. Contas offline passam direto."""
    if account["type"] != "msa" or time.time() < account.get("expires_at", 0):
        return account
    if not account.get("refresh_token"):
        raise AuthError("Sessão expirada; faça login novamente")
    tok = _post_form_allow_error(MS_TOKEN, {
        "client_id": _client_id(), "grant_type": "refresh_token",
        "refresh_token": account["refresh_token"], "scope": SCOPE,
    })
    if tok.get("error"):
        raise AuthError("Sessão expirada; faça login novamente")
    fresh = _minecraft_from_ms(tok)
    save_account(fresh)
    return fresh
