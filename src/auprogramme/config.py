"""Chemins et chargement de la configuration."""
from __future__ import annotations

import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
CONTENU_DIR = ROOT / "contenu"
ASSETS_DIR = ROOT / "assets"
DATA_DIR = ROOT / "data"
OUTPUT_DIR = ROOT / "output"
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


def _yaml(nom: str) -> dict:
    return yaml.safe_load((CONFIG_DIR / nom).read_text(encoding="utf-8"))


def load_settings() -> dict:
    return _yaml("settings.yaml")


def load_candidats() -> list[dict]:
    return _yaml("candidats.yaml")["candidats"]


def load_themes() -> list[dict]:
    return _yaml("themes.yaml")["themes"]


def env(name: str, required: bool = True) -> str | None:
    value = os.environ.get(name)
    if required and not value:
        raise RuntimeError(f"Variable d'environnement manquante : {name} (à définir dans les secrets GitHub)")
    return value
