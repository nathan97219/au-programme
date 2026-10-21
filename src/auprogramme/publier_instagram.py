"""Publication d'une image ou d'une vidéo (Reel) via l'API officielle Instagram (gratuite), « Instagram API with Instagram Login ».

Même principe que Le Chiffre Utile :
- compte Instagram professionnel (Créateur ou Entreprise), ajouté comme testeur de l'app Meta ;
- l'API exige une ADRESSE PUBLIQUE de l'image (JPEG uniquement) : on la dépose quelques secondes dans un
  stockage Supabase public au nom imprévisible, Instagram la lit, puis on la supprime (toujours, même en cas d'échec).
Secrets : IG_ACCESS_TOKEN (60 jours, renouvelé chaque mois automatiquement), IG_USER_ID facultatif (trouvé tout seul),
          SUPABASE_URL, SUPABASE_SECRET_KEY.
"""
from __future__ import annotations

import secrets
import time
from pathlib import Path

import requests

from .config import env

GRAPH = "https://graph.instagram.com/{version}"


def _supabase(settings: dict) -> tuple[str, dict, str]:
    url = env("SUPABASE_URL").rstrip("/")
    if url.endswith("/rest/v1"):
        url = url[: -len("/rest/v1")]
    return url, {"apikey": env("SUPABASE_SECRET_KEY")}, settings["instagram"].get("bucket", "auprogramme")


TYPES = {".jpg": "image/jpeg", ".mp4": "video/mp4"}


def heberger_image(image: Path, settings: dict) -> tuple[str, str]:
    """Dépose le fichier (JPEG ou MP4) dans le stockage public, sous un nom impossible à deviner."""
    url, headers, bucket = _supabase(settings)
    ext = image.suffix.lower()
    chemin = f"{image.stem}-{secrets.token_hex(8)}{ext}"
    r = requests.post(f"{url}/storage/v1/object/{bucket}/{chemin}", data=image.read_bytes(), timeout=300,
                      headers={**headers, "Content-Type": TYPES.get(ext, "image/jpeg"), "x-upsert": "true"})
    if "Bucket not found" in r.text or "NoSuchBucket" in r.text:
        raise RuntimeError(f"Le bucket « {bucket} » n'existe pas dans le projet Supabase de SUPABASE_URL : "
                           "crée-le (Storage → New bucket, Public) ou vérifie l'adresse du projet.")
    if r.status_code in (400, 413, 415) and ext == ".mp4":
        raise RuntimeError("Le stockage Supabase refuse la vidéo : dans Storage → bucket « auprogramme » → Edit, "
                           "autorise le type video/mp4 (ou aucun filtre) et une taille de 50 Mo. "
                           f"Détail : {r.text[:200]}")
    _check(r, "dépôt du fichier dans le stockage")
    return f"{url}/storage/v1/object/public/{bucket}/{chemin}", chemin


def supprimer_image(chemin: str, settings: dict) -> None:
    url, headers, bucket = _supabase(settings)
    try:
        requests.delete(f"{url}/storage/v1/object/{bucket}/{chemin}", headers=headers, timeout=60)
    except requests.RequestException as e:
        print(f"⚠️ Image non supprimée du stockage ({e})")


def _check(r: requests.Response, etape: str) -> dict:
    if r.status_code >= 400:
        raise RuntimeError(f"Échec de l'étape « {etape} » ({r.status_code}) : {r.text[:400]}")
    return r.json()


def _base(settings: dict) -> str:
    return GRAPH.format(version=settings["instagram"].get("graph_version", "v21.0"))


def compte(settings: dict) -> dict:
    r = requests.get(f"{_base(settings)}/me", timeout=30,
                     params={"fields": "user_id,username,account_type", "access_token": env("IG_ACCESS_TOKEN")})
    return _check(r, "vérification du compte")


def renouveler_jeton() -> str:
    r = requests.get("https://graph.instagram.com/refresh_access_token", timeout=30,
                     params={"grant_type": "ig_refresh_token", "access_token": env("IG_ACCESS_TOKEN")})
    return _check(r, "renouvellement du jeton")["access_token"]


def publier_image(image: Path, legende: str, settings: dict, attente_max: int = 300, publier: bool = True) -> dict:
    """publier=False : répétition générale (tout le circuit, sauf le dernier clic « publier »)."""
    return _publier(Path(image), legende, settings, lambda adresse: {"image_url": adresse}, attente_max, publier)


def publier_video(video: Path, legende: str, settings: dict, attente_max: int = 900, publier: bool = True) -> dict:
    """Publie un Reel (MP4 H.264/AAC, 9:16), aussi affiché dans le fil du compte."""
    return _publier(Path(video), legende, settings,
                    lambda adresse: {"media_type": "REELS", "video_url": adresse, "share_to_feed": "true"},
                    attente_max, publier)


def _publier(fichier: Path, legende: str, settings: dict, champs, attente_max: int, publier: bool) -> dict:
    base, token = _base(settings), env("IG_ACCESS_TOKEN")
    user_id = env("IG_USER_ID", required=False) or compte(settings)["user_id"]   # trouvé tout seul si absent
    adresse, chemin = heberger_image(fichier, settings)
    try:
        conteneur = _check(requests.post(f"{base}/{user_id}/media", timeout=60, data={
            **champs(adresse), "caption": legende, "access_token": token}), "création de la publication")["id"]
        fin = time.time() + attente_max
        while time.time() < fin:
            etat = _check(requests.get(f"{base}/{conteneur}", timeout=30,
                                       params={"fields": "status_code", "access_token": token}), "suivi")
            if etat.get("status_code") == "FINISHED":
                break
            if etat.get("status_code") in ("ERROR", "EXPIRED"):
                raise RuntimeError(f"Instagram a refusé le fichier : {etat}")
            time.sleep(5)
        else:
            raise TimeoutError("Instagram n'a pas fini de traiter le fichier à temps")
        if not publier:
            return {"repetition": True, "conteneur": conteneur, "statut": "FINISHED"}
        media = _check(requests.post(f"{base}/{user_id}/media_publish", timeout=60,
                                     data={"creation_id": conteneur, "access_token": token}), "publication")["id"]
        info = requests.get(f"{base}/{media}", params={"fields": "permalink", "access_token": token}, timeout=30).json()
        return {"media_id": media, "permalink": info.get("permalink")}
    finally:
        supprimer_image(chemin, settings)
