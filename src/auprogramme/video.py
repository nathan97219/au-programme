"""La vidéo du jour (Reel, ~30-45 s) : le candidat, ses propositions sur le thème de la semaine, les sources.

- Tout le texte vient de la fiche validée : rien n'est rédigé par une IA.
- Même maquette, même rythme et même nombre de mesures maximum pour tous les candidats.
- Voix off de synthèse neutre (edge-tts), jamais d'imitation d'une voix réelle. Sans réseau : vidéo sans voix.
- Musique NCS très discrète, qui s'efface quand la voix parle. Le crédit est ajouté à la légende.
"""
from __future__ import annotations

import asyncio
import json
import re
import subprocess
import tempfile
from datetime import date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .config import ASSETS_DIR, TEMPLATES_DIR

L, H, IPS = 1080, 1920, 30
PAUSE = 0.45
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
        "novembre", "décembre"]
MOIS_COURTS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]


def insecable(texte: str | None) -> str | None:
    """Espaces insécables devant les unités (« 5,5 % » ne se coupe jamais), mots inchangés."""
    if not texte:
        return texte
    t = re.sub(r"(\d) (%|€|euros|centimes|milliards|millions|heures|minutes|mois|ans)\b", "\\1\u00a0\\2", texte)
    t = re.sub(r"(\d) (\d{3})\b", "\\1\u202f\\2", t)            # « 1 000 » ne se coupe pas
    return re.sub(r"(\d) (%|€)", "\\1\u00a0\\2", t)


def date_longue(d: date) -> str:
    return f"{'1er' if d.day == 1 else d.day} {MOIS[d.month - 1]} {d.year}"


def date_courte(d: date) -> str:
    return f"{d.day} {MOIS_COURTS[d.month - 1]} {d.year}"


def ffmpeg() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


# ---------- Le texte ----------

def pour_la_voix(texte: str) -> str:
    """Ce qui s'affiche → ce qui se lit."""
    t = texte.replace("«", "").replace("»", "").replace(" ", " ").replace(" ", " ")
    t = re.sub(r"\b1er\b", "premier", t)
    t = re.sub(r"(\d)\s?%", r"\1 pour cent", t)
    t = re.sub(r"(\d)\s?€", r"\1 euros", t)
    t = t.replace("(CEE)", "").replace("SMIC", "Smic")
    return re.sub(r"\s+", " ", t).strip()


def phrases(prog: dict, fiche: dict) -> list[dict]:
    """Les scènes de la vidéo, chacune avec le texte lu à voix haute."""
    c, theme = prog["candidat"], prog["theme"]
    scenes = [{"type": "intro", "voix": f"{theme['nom']}. Au programme aujourd'hui : {c['nom']}, {c['parti']}."}]
    if fiche.get("aucune_proposition"):
        scenes.append({"type": "aucune",
                       "voix": "Sur ce thème, aucune proposition vérifiable n'a été trouvée à ce jour."})
    else:
        for i, m in enumerate(fiche["mesures"], 1):
            scenes.append({"type": "mesure", "numero": i, "mesure": m,
                           "voix": f"Proposition {i} : {m['titre']}. {m['explication']}"})
    s = prog["suivant"]
    if s["meme_theme"]:
        fin = f"Demain : {s['candidat']['nom']}, sur le même thème. Toutes les sources sont en légende."
    else:
        fin = f"Lundi, nouveau thème : {s['theme']['nom']}. Toutes les sources sont en légende."
    scenes.append({"type": "fin", "voix": fin})
    return scenes


def chronologie(scenes: list[dict], durees: list[float] | None) -> list[dict]:
    minimum = {"intro": 3.4, "mesure": 5.5, "aucune": 5.0, "fin": 4.0}
    t, out = 0.0, []
    for i, s in enumerate(scenes):
        lue = durees[i] if durees else max(1.6, len(s["voix"]) * 0.068)
        d = max(minimum[s["type"]], lue + PAUSE + (1.2 if s.get("mesure", {}).get("citation") else 0))
        out.append({"debut": round(t, 3), "fin": round(t + d, 3), "voix": round(lue, 3)})
        t += d
    return out


# ---------- La musique et la photo ----------

def morceau(jour: date) -> tuple[Path, str] | None:
    import yaml
    dossier = ASSETS_DIR / "musique"
    f = dossier / "credits.yaml"
    if not f.exists():
        return None
    liste = [(dossier / m["fichier"], str(m["credit"]).strip())
             for m in (yaml.safe_load(f.read_text(encoding="utf-8")) or {}).get("morceaux") or []
             if m.get("fichier") and m.get("credit") and (dossier / m["fichier"]).exists()]
    return liste[jour.toordinal() % len(liste)] if liste else None


def photo(candidat_id: str) -> tuple[Path | None, str | None]:
    """La photo libre de droits du candidat et son crédit (voir photos.py), ou (None, None)."""
    import yaml
    dossier = ASSETS_DIR / "candidats"
    p = dossier / f"{candidat_id}.jpg"
    credits = dossier / "credits.yaml"
    if not p.exists() or not credits.exists():
        return None, None
    c = (yaml.safe_load(credits.read_text(encoding="utf-8")) or {}).get(candidat_id)
    if not c or not c.get("credit"):
        return None, None                                       # jamais de photo sans crédit
    return p, c["credit"]


def initiales(nom: str) -> str:
    mots = [m for m in re.split(r"[\s-]+", nom) if m]
    return (mots[0][0] + mots[-1][0]).upper()


# ---------- La voix ----------

def _duree(fichier: Path) -> float:
    r = subprocess.run([ffmpeg(), "-hide_banner", "-i", str(fichier), "-f", "null", "-"], capture_output=True, text=True)
    temps = re.findall(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)", r.stderr)
    if not temps:
        raise RuntimeError("durée de la voix illisible")
    h, m, s = temps[-1]
    return int(h) * 3600 + int(m) * 60 + float(s)


def voix(textes: list[str], dossier: Path, voix_choisie: str) -> list[tuple[Path, float]] | None:
    try:
        import edge_tts

        async def tout():
            for i, t in enumerate(textes):
                await edge_tts.Communicate(pour_la_voix(t), voix_choisie, rate="+4%").save(str(dossier / f"v{i}.mp3"))
        asyncio.run(tout())
        return [(dossier / f"v{i}.mp3", _duree(dossier / f"v{i}.mp3")) for i in range(len(textes))]
    except Exception as e:                                       # jamais bloquant
        print(f"⚠️ Voix off indisponible ({type(e).__name__}: {e}) : vidéo sans voix.")
        return None


# ---------- L'image ----------

def page_html(prog: dict, fiche: dict, settings: dict, scenes: list[dict], temps: list[dict]) -> str:
    c = prog["candidat"]
    img, credit = photo(c["id"])
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=select_autoescape(["html"]))
    for s in scenes:
        if s["type"] == "mesure":
            s["mesure"] = {**s["mesure"], **{k: insecable(s["mesure"].get(k)) for k in ("titre", "explication", "citation")}}
            src = s["mesure"]["source"]
            s["source"] = f"{src['media']} · {date_courte(src['date'])}"
    return env.get_template("video.html").render(
        polices=(ASSETS_DIR / "fonts").resolve().as_uri(), marque=settings["marque"], prog=prog, c=c,
        scenes=scenes, photo=img.resolve().as_uri() if img else None, credit_photo=credit, initiales=initiales(c["nom"]),
        consulte=date_longue(fiche["consulte_le"]),
        donnees={"total": temps[-1]["fin"], "scenes": temps})


def fabriquer(prog: dict, fiche: dict, settings: dict, sortie: Path, avec_voix: bool = True,
              apercu: list[float] | None = None) -> dict:
    """Fabrique la vidéo MP4 (H.264 + AAC, 1080×1920). Renvoie {chemin, duree, voix, musique}."""
    from playwright.sync_api import sync_playwright

    scenes = phrases(prog, fiche)
    musique = morceau(prog["date"])
    sortie.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        pistes = voix([s["voix"] for s in scenes], tmp, settings["video"]["voix"]) if avec_voix else None
        temps = chronologie(scenes, [d for _, d in pistes] if pistes else None)
        total = temps[-1]["fin"]
        page_f = tmp / "video.html"
        page_f.write_text(page_html(prog, fiche, settings, scenes, temps), encoding="utf-8")

        if apercu is not None:                                   # quelques images de contrôle, sans vidéo
            with sync_playwright() as p:
                nav = p.chromium.launch()
                page = nav.new_page(viewport={"width": L, "height": H})
                page.goto(page_f.as_uri())
                page.evaluate("document.fonts.ready")
                images = []
                for x in apercu:
                    t = x if x >= 0 else total + x
                    page.evaluate(f"poser({t:.3f})")
                    f = sortie.parent / f"{sortie.stem}_{t:.1f}.jpg"
                    page.screenshot(path=str(f), type="jpeg", quality=80)
                    images.append(f)
                nav.close()
            return {"images": images, "duree": total, "temps": temps}

        cmd = [ffmpeg(), "-hide_banner", "-loglevel", "error", "-y",
               "-f", "image2pipe", "-framerate", str(IPS), "-c:v", "mjpeg", "-i", "-"]
        filtres, n = [], 1
        if pistes:
            for p_, _ in pistes:
                cmd += ["-i", str(p_)]
            filtres += [f"[{i + 1}:a]aresample=48000,apad=whole_dur={s['fin'] - s['debut']:.3f}[a{i}]"
                        for i, s in enumerate(temps)]
            filtres.append("".join(f"[a{i}]" for i in range(len(temps))) + f"concat=n={len(temps)}:v=0:a=1,"
                           "aformat=channel_layouts=stereo[voix]")
            n += len(pistes)
        else:
            cmd += ["-f", "lavfi", "-i", f"anullsrc=r=48000:cl=stereo:d={total:.3f}"]
            filtres.append(f"[{n}:a]anull[voix]")
            n += 1
        if musique:
            cmd += ["-stream_loop", "-1", "-i", str(musique[0])]
            vol = settings["video"].get("volume_musique", 0.08) if pistes else 0.5
            filtres.append(f"[{n}:a]aresample=48000,aformat=channel_layouts=stereo,atrim=0:{total:.3f},"
                           f"volume={vol},afade=t=in:d=1,afade=t=out:st={max(0.0, total - 1.8):.3f}:d=1.8[mus]")
            if pistes:
                filtres += ["[voix]asplit[v1][v2]",
                            "[mus][v2]sidechaincompress=threshold=0.03:ratio=6:attack=15:release=350[musb]",
                            "[v1][musb]amix=inputs=2:duration=first:normalize=0[a]"]
            else:
                filtres.append("[voix][mus]amix=inputs=2:duration=first:normalize=0[a]")
        else:
            filtres.append("[voix]anull[a]")
        cmd += ["-filter_complex", ";".join(filtres), "-map", "0:v", "-map", "[a]",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-profile:v", "high", "-preset", "veryfast", "-crf", "20",
                "-r", str(IPS), "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-movflags", "+faststart",
                "-t", f"{total:.3f}", str(sortie)]
        enc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        try:
            with sync_playwright() as p:
                nav = p.chromium.launch()
                page = nav.new_page(viewport={"width": L, "height": H})
                page.goto(page_f.as_uri())
                page.evaluate("document.fonts.ready")
                for k in range(int(total * IPS)):
                    page.evaluate(f"poser({k / IPS:.4f})")
                    enc.stdin.write(page.screenshot(type="jpeg", quality=90))
                nav.close()
        finally:
            enc.stdin.close()
            code = enc.wait()
        if code != 0:
            raise RuntimeError(f"assemblage de la vidéo impossible (ffmpeg {code})")
    return {"chemin": sortie, "duree": round(total, 1), "voix": bool(pistes), "musique": musique[1] if musique else None}


def resume_json(prog: dict) -> str:
    return json.dumps({"date": prog["date"].isoformat(), "theme": prog["theme"]["id"],
                       "candidat": prog["candidat"]["id"], "rang": prog["rang"]}, ensure_ascii=False)
