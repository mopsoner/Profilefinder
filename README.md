# ProfileFinder

Application web de prospection locale pour Ubuntu utilisant Google Places API (New).

## V1
- recherche autour d'un GPS par grille ;
- sélection de types d'entreprises ;
- déduplication globale par Google Place ID ;
- conservation des établissements avec téléphone et sans site web ;
- scoring : +2 zéro avis, +2 sans site, +1 téléphone ;
- SQLite : jobs, leads et association job/leads ;
- dashboard, historique des jobs, liste prospects, filtres et export CSV ;
- API JSON ;
- retry/backoff Google Places ;
- scripts Ubuntu et modèle systemd.

Le lien WhatsApp généré avec wa.me indique uniquement que le téléphone a un format exploitable. Il ne confirme pas l'existence d'un compte WhatsApp.

Google Places ne fournit pas directement l'email ni la date réelle de création d'un établissement. Zéro avis ne signifie pas entreprise récente.

## Installation Ubuntu

```bash
git clone https://github.com/mopsoner/Profilefinder.git
cd Profilefinder
bash scripts/install.sh
nano .env
bash scripts/start.sh
```

Dans `.env`, renseigner `GOOGLE_PLACES_API_KEY`. Activer Places API (New) dans Google Cloud. Ne jamais committer le fichier `.env`.

Ouvrir ensuite `http://IP_DU_SERVEUR:8000`.

## Tests

```bash
PYTHONPATH=. pytest -q
```

## API
- `GET /api/stats`
- `GET /api/jobs`
- `GET /api/jobs/{id}`
- `GET /api/leads`

## systemd
Adapter `User` et `WorkingDirectory` dans `systemd/profilefinder.service`, puis copier le fichier dans `/etc/systemd/system/`.

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now profilefinder
sudo systemctl status profilefinder
```

## Avis
L'architecture reste extensible pour une future synchronisation d'avis. Le stockage permanent des textes d'avis Google n'est pas activé avant validation des règles de conservation et d'attribution applicables.
