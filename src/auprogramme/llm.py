"""Appel au LLM (repris de Le Chiffre Utile). Fournisseur : Google Gemini (offre gratuite, clé sur aistudio.google.com).

La clé est envoyée dans un en-tête HTTP (jamais dans l'URL), pour qu'elle n'apparaisse pas dans les erreurs.
Si le modèle configuré n'existe plus (Google retire régulièrement des versions), un modèle "flash"
disponible est choisi automatiquement.
"""
from __future__ import annotations

import json
import re
import time

import requests

from .config import env

BASE = "https://generativelanguage.googleapis.com/v1beta"
_resolved_model: str | None = None


def _headers() -> dict:
    return {"x-goog-api-key": env("GEMINI_API_KEY"), "Content-Type": "application/json"}


def _extract_json(text: str) -> dict:
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fenced:
        text = fenced.group(1)
    start, end = text.find("{"), text.rfind("}")
    return json.loads(text[start : end + 1])


def list_models() -> list[str]:
    """Modèles de texte utilisables avec ta clé."""
    r = requests.get(f"{BASE}/models", headers=_headers(), params={"pageSize": 200}, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"Impossible de lister les modèles ({r.status_code}) : {r.text[:300]}")
    names = []
    for m in r.json().get("models", []):
        if "generateContent" in m.get("supportedGenerationMethods", []):
            names.append(m["name"].removeprefix("models/"))
    return names


def _pick_fallback(names: list[str]) -> str | None:
    banned = ("image", "tts", "audio", "live", "embedding", "vision", "thinking", "exp", "preview")
    flash = [n for n in names if "flash" in n and not any(b in n for b in banned)]
    if not flash:
        flash = [n for n in names if "flash" in n] or names
    if not flash:
        return None
    latest = [n for n in flash if "latest" in n]
    return latest[0] if latest else sorted(flash)[-1]


def _call(model: str, body: dict) -> requests.Response:
    return requests.post(f"{BASE}/models/{model}:generateContent", headers=_headers(), json=body, timeout=(15, 180))


def generate_json(prompt: str, settings: dict, retries: int = 2) -> dict:
    """Essaie le modèle principal, puis les modèles de secours (settings.llm.fallback_models)."""
    modeles = [settings["llm"]["model"]] + list(settings["llm"].get("fallback_models", []))
    erreurs = []
    for m in modeles:
        try:
            return _generate_json(prompt, {**settings, "llm": {**settings["llm"], "model": m}}, retries)
        except RuntimeError as e:
            if "Clé API refusée" in str(e):
                raise
            erreurs.append(str(e))
            print(f"ℹ️ {m} indisponible, essai du modèle suivant.")
    raise RuntimeError(" | ".join(erreurs))


def _generate_json(prompt: str, settings: dict, retries: int = 2) -> dict:
    global _resolved_model
    llm = settings["llm"]
    if llm["provider"] != "gemini":
        raise NotImplementedError(f"Fournisseur LLM non géré : {llm['provider']}")

    model = llm["model"]
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": llm.get("temperature", 0.5),
            "responseMimeType": "application/json",
        },
    }
    last_error = "inconnue"
    for attempt in range(1, retries + 1):
        try:
            r = _call(model, body)
            if r.status_code == 404:  # modèle retiré : on en choisit un autre automatiquement
                fallback = _pick_fallback(list_models())
                if not fallback or fallback == model:
                    raise RuntimeError(f"Modèle '{model}' introuvable et aucun remplaçant disponible.")
                print(f"ℹ️ Modèle '{model}' indisponible, utilisation de '{fallback}'. "
                      f"Mets 'model: \"{fallback}\"' dans config/settings.yaml pour le fixer.")
                model = _resolved_model = fallback
                r = _call(model, body)
            if r.status_code == 429:  # quota gratuit dépassé momentanément
                last_error = "quota gratuit dépassé (429)"
                time.sleep(20 * attempt)
                continue
            if r.status_code in (400, 401, 403):
                raise RuntimeError(f"Clé API refusée ou requête invalide ({r.status_code}) : {r.text[:300]}")
            if r.status_code != 200:
                last_error = f"HTTP {r.status_code} : {r.text[:200]}"
                time.sleep(3 * attempt)
                continue
            _resolved_model = model
            text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            return _extract_json(text)
        except requests.RequestException as e:
            last_error = f"réseau : {type(e).__name__}"
            time.sleep(3 * attempt)
        except (KeyError, IndexError, ValueError) as e:
            last_error = f"réponse illisible : {e}"
            time.sleep(3 * attempt)
    raise RuntimeError(f"Échec de l'appel LLM ({model}) après {retries} tentatives : {last_error}")


def rechercher(prompt: str, settings: dict, retries: int = 3) -> tuple[dict, list[dict]]:
    """Recherche avec Google Search (« grounding ») : renvoie (réponse JSON, sources consultées [{uri, title}]).

    Les liens renvoyés par Google sont des redirections : ils sont suivis plus tard pour obtenir l'adresse réelle.
    Le format JSON forcé n'est pas compatible avec la recherche : le JSON est donc extrait du texte.
    """
    modeles = [settings["llm"]["model"]] + list(settings["llm"].get("fallback_models", []))
    body = {"contents": [{"parts": [{"text": prompt}]}], "tools": [{"google_search": {}}],
            "generationConfig": {"temperature": 0.2}}
    derniere = "inconnue"
    for model in modeles:
        for attempt in range(1, retries + 1):
            try:
                r = _call(model, body)
                if r.status_code == 404:
                    break
                if r.status_code == 429:
                    derniere = "quota gratuit dépassé (429)"
                    time.sleep(30 * attempt)
                    continue
                if r.status_code in (401, 403):
                    raise RuntimeError(f"Clé API refusée ({r.status_code}) : {r.text[:300]}")
                if r.status_code != 200:
                    derniere = f"HTTP {r.status_code} : {r.text[:200]}"
                    time.sleep(5 * attempt)
                    continue
                cand = r.json()["candidates"][0]
                texte = "".join(p.get("text", "") for p in cand["content"]["parts"])
                chunks = (cand.get("groundingMetadata") or {}).get("groundingChunks") or []
                sources = [c["web"] for c in chunks if c.get("web", {}).get("uri")]
                return _extract_json(texte), sources
            except requests.RequestException as e:
                derniere = f"réseau : {type(e).__name__}"
                time.sleep(5 * attempt)
            except (KeyError, IndexError, ValueError) as e:
                derniere = f"réponse illisible : {e}"
                time.sleep(3 * attempt)
    raise RuntimeError(f"Recherche impossible : {derniere}")
