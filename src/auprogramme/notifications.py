"""Messages du robot : sur GitHub, dans des tickets (« issues »), à la place de Telegram.

Un ticket ouvert par sujet (« 🔔 Alertes du robot », « 📋 Résumés »…) : chaque nouveau message y est ajouté en
commentaire en te mentionnant (@propriétaire du dépôt). GitHub t'envoie alors un e-mail et une notification dans son
appli. Ferme le ticket quand c'est lu : le message suivant en ouvrira un neuf.

Jeton : GITHUB_TOKEN, fourni automatiquement par GitHub Actions (le workflow doit avoir « issues: write »).
Hors de GitHub (sur ton PC), les messages sont simplement affichés. Un message qui ne part pas ne bloque jamais le robot.
Usage en ligne de commande (étapes « en cas d'échec ») : python -m <paquet>.notifications "texte"
"""
from __future__ import annotations

import os
import sys

import requests

API = "https://api.github.com"
ALERTES = "🔔 Alertes du robot"


def _depot() -> str | None:
    return os.environ.get("GITHUB_REPOSITORY")


def _jeton() -> str | None:
    return os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")


def disponible() -> bool:
    return bool(_depot() and _jeton())


def _appel(methode: str, chemin: str, **kw) -> dict | list:
    r = requests.request(methode, f"{API}/repos/{_depot()}{chemin}", timeout=30,
                         headers={"Authorization": f"Bearer {_jeton()}", "Accept": "application/vnd.github+json",
                                  "X-GitHub-Api-Version": "2022-11-28"}, **kw)
    if r.status_code >= 400:
        raise RuntimeError(f"GitHub « {methode} {chemin} » a échoué ({r.status_code}) : {r.text[:200]}")
    return r.json() if r.text else {}


def _mention() -> str:
    proprio = os.environ.get("GITHUB_REPOSITORY_OWNER")
    return f"@{proprio} " if proprio else ""


def ticket_ouvert(titre: str, etiquette: str) -> int | None:
    for t in _appel("GET", "/issues", params={"state": "open", "labels": etiquette, "per_page": 50}):
        if t.get("title") == titre and "pull_request" not in t:
            return t["number"]
    return None


def creer_ticket(titre: str, corps: str, etiquettes: list[str]) -> int:
    return _appel("POST", "/issues", json={"title": titre, "body": corps, "labels": etiquettes})["number"]


def commenter(numero: int, corps: str) -> None:
    _appel("POST", f"/issues/{numero}/comments", json={"body": corps})


def fermer(numero: int | None) -> None:
    if numero and disponible():
        try:
            _appel("PATCH", f"/issues/{numero}", json={"state": "closed"})
        except (RuntimeError, requests.RequestException) as e:
            print(f"(ticket {numero} non fermé : {e})")


def signaler(texte: str, sujet: str = ALERTES, etiquette: str = "alerte", ticket: int | None = None) -> int | None:
    """Ajoute le message au ticket donné, sinon au ticket ouvert du sujet (créé s'il n'existe pas). Jamais bloquant."""
    print(texte)
    if not disponible():
        return None
    corps = f"{_mention()}{texte}"
    try:
        numero = ticket or ticket_ouvert(sujet, etiquette)
        if numero:
            commenter(numero, corps)
            return numero
        return creer_ticket(sujet, corps, [etiquette])
    except (RuntimeError, requests.RequestException) as e:
        print(f"(message GitHub non envoyé : {e})")
        return None


def adresse_fichier(chemin: str) -> str | None:
    """Adresse d'un fichier du dépôt, affichable dans un ticket (une fois le fichier envoyé sur GitHub)."""
    return f"https://github.com/{_depot()}/blob/main/{chemin}?raw=true" if _depot() else None


if __name__ == "__main__":
    signaler(" ".join(sys.argv[1:]) or "(message vide)")
