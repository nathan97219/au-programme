# Au Programme (@au.programme)

Les programmes de la présidentielle 2027, expliqués sans parti pris. **Un thème par semaine, un candidat par jour**,
dans un ordre tiré au sort. Après l'élection : le programme du président élu, passé au crible.

## Les règles de neutralité (appliquées par le robot)

- **Les fiches** `contenu/<thème>/<candidat>.yaml` sont préparées chaque mercredi par le robot de recherche :
  Gemini PROPOSE des mesures, le code ne garde que ce qu'il a VÉRIFIÉ dans la page source (site reconnu, page
  accessible, nom du candidat, date de publication récente lue dans la page, chaque chiffre présent, citation mot
  pour mot, relecture indépendante de la page). Rien de vérifiable : « aucune proposition vérifiable trouvée ».
- **Sources professionnelles uniquement** : une fiche part directement (sans relecture) seulement si TOUTES ses sources
  sont dans la liste `publication.sources_reconnues` (grands médias, sites officiels, sites des candidats et partis).
  Sinon : rien n'est publié et une alerte part sur Telegram. `statut: bloque` empêche toujours une publication.
- **Même traitement pour tous** : même maquette, 1 ou 2 mesures chacun, même voix neutre, même musique.
- **Chaque mesure a sa source** (média, titre, lien, date), affichée dans la vidéo et en légende.
- **Aucune étiquette** (« gauche », « droite », « extrême »…) ni jugement : le contrôle `verifier` les refuse.
- **Pas de proposition trouvée** : le candidat garde son jour, avec « pas de proposition détaillée publiée à ce jour ».
- **Ordre tiré au sort**, reproductible : `random.Random("<thème>|<date du lundi>")`. Jamais deux jours de suite le même candidat.
- **Photos libres de droits** (Wikimedia Commons), avec le crédit de l'auteur.

## Chaque semaine : rien à faire

Le mercredi, le robot prépare les fiches de la semaine suivante, supprime celles des thèmes passés et envoie un
résumé sur Telegram. Facultatif : corriger une fiche à la main, la bloquer (`statut: bloque`), ou regarder les
vidéos avant leur sortie avec **Actions → Aperçu de la semaine**.

Commandes locales : `python -m auprogramme.pipeline calendrier --semaines 4` (qui passe quand, état des fiches),
`python -m auprogramme.pipeline verifier` (contrôle de neutralité).

## Les robots (dossier `.github/workflows`)

| Robot | Quand | Rôle |
|---|---|---|
| Préparer les fiches de la semaine | chaque mercredi, 08:43 | recherche + vérification des 7 fiches suivantes, ménage |
| Publier la vidéo du jour | tous les jours, 18:00 (Paris, été) | vidéo + légende du candidat du jour (sources reconnues uniquement) |
| Aperçu de la semaine | à la main | les 7 vidéos d'une semaine, pour relecture |
| Photos des candidats | à la main | photos libres + crédits (à relancer si un candidat change) |
| Vérifier | à chaque envoi | tests + contrôle de neutralité |
| Renouveler le jeton Instagram | le 1er du mois | prolonge le jeton de 60 jours |

Secrets GitHub : `GEMINI_API_KEY`, `IG_ACCESS_TOKEN`, `IG_USER_ID` (facultatif), `SUPABASE_URL`, `SUPABASE_SECRET_KEY`,
`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `GH_PAT`. Bucket Supabase public `auprogramme` (video/mp4, 50 Mo).

## Les phases du compte

1. **Jusqu'à la liste officielle** (Conseil constitutionnel) : les 7 candidats de `config/candidats.yaml`.
2. **Liste officielle, puis second tour** : modifier `config/candidats.yaml` (avec 2 candidats, 2 vidéos par semaine).
3. **Après l'élection** : le programme du président élu, mesure par mesure (nouveau calendrier à prévoir).
4. **Veille et jour de vote** : `calendrier.pauses` dans `config/settings.yaml` (aucune publication).
