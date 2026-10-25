"""Avaliação das regras de SO/arquitetura/features dos JSONs de versão da Mojang."""
from __future__ import annotations

import platform
import re
import struct
import sys


def os_name() -> str:
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "osx"
    return "linux"


def is_64bit() -> bool:
    return struct.calcsize("P") == 8


def machine() -> str:
    m = platform.machine().lower()
    if m in ("arm64", "aarch64"):
        return "arm64"
    if m in ("x86_64", "amd64"):
        return "x86_64"
    if m in ("i386", "i686", "x86"):
        return "x86"
    return m


def _rule_matches(rule: dict, features: dict) -> bool:
    os_rule = rule.get("os")
    if os_rule:
        if "name" in os_rule and os_rule["name"] != os_name():
            return False
        if "arch" in os_rule:
            arch = os_rule["arch"]
            if arch == "x86" and is_64bit():
                return False
            if arch not in ("x86",) and arch != machine():
                return False
        if "version" in os_rule:
            if not re.search(os_rule["version"], platform.release()):
                return False
    for key, wanted in (rule.get("features") or {}).items():
        if bool(features.get(key, False)) != bool(wanted):
            return False
    return True


def allows(rules: list | None, features: dict | None = None) -> bool:
    if not rules:
        return True
    features = features or {}
    allowed = False
    for rule in rules:
        if _rule_matches(rule, features):
            allowed = rule.get("action", "allow") == "allow"
    return allowed
