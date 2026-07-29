# Veille logement étudiant Nantes — site auto-actualisé

Ce dossier contient tout pour publier un **site qui se met à jour tout seul** : toutes les 3 heures, il recollecte les annonces (PAP + résidences) et régénère la page. Meli ouvre un lien → elle voit la dernière version, sans notification, sans que tu aies à republier.

## Ce qu'il y a dans le dossier
- `build_site.py` — le « moteur » : collecte les annonces et fabrique `index.html`.
- `requirements.txt` — les librairies Python nécessaires.
- `.github/workflows/update.yml` — la tâche planifiée (toutes les 3 h) + le bouton « lancer à la main ».
- `README.md` — ce fichier.

## Mise en place (une seule fois, ~10 min)

1. **Compte GitHub** — si tu n'en as pas, crée-en un (gratuit) sur https://github.com.
2. **Nouveau dépôt** — clique sur « + » → « New repository ».
   - Nom : par ex. `logement-nantes`
   - Coche **Public**
   - Crée le dépôt (ne coche rien d'autre).
3. **Ajouter les fichiers** — sur la page du dépôt vide, clique « uploading an existing file », puis **glisse-dépose** le contenu de ce dossier (y compris le dossier `.github`). Valide avec « Commit changes ».
   - ⚠️ Le dossier `.github/workflows/` doit être conservé tel quel (c'est lui qui contient la tâche automatique).
4. **Autoriser l'écriture** — Settings → Actions → General → tout en bas « Workflow permissions » → coche **Read and write permissions** → Save.
5. **Activer la page web** — Settings → Pages → « Build and deployment » → Source : **Deploy from a branch** → Branch : **main** / **/(root)** → Save.
6. **Premier lancement** — onglet **Actions** → clique « Veille logement Nantes » → bouton **Run workflow** → Run. Attends 1–2 min (une coche verte apparaît).
7. **Ton lien** — l'adresse est : `https://TON-PSEUDO.github.io/logement-nantes/`
   (remplace TON-PSEUDO par ton identifiant GitHub). C'est ce lien que tu envoies à Meli.

Ensuite, plus rien à faire : la page se régénère automatiquement toutes les 3 heures.

## Si les annonces n'apparaissent pas
C'est le risque annoncé : PAP peut bloquer les serveurs de GitHub. La page s'affichera quand même (guide + liens + alertes), mais la section annonces sera vide.
→ Va dans **Actions**, ouvre le dernier run, déroule l'étape « Collecter les annonces », et **copie-colle le journal** : on ajustera la collecte ensemble.

## Régler la fréquence
Dans `.github/workflows/update.yml`, la ligne `cron: "0 */3 * * *"` = toutes les 3 h.
- Toutes les 2 h : `0 */2 * * *`
- Toutes les 6 h : `0 */6 * * *`
- 1×/jour à 8h UTC : `0 8 * * *`

## Critères de recherche
Dans `build_site.py`, en haut : `MAX_PRICE = 650` et les URL des sources. Modifie-les si besoin (budget, etc.).
