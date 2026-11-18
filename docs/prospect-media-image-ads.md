# Médias et Image Ads

**Médias** est accessible depuis le menu et depuis chaque fiche prospect. Importez des images PNG, JPEG ou WebP, des séquences MP4 H.264 et des pistes MP3 ou WAV. Les fichiers sont limités à 24 Mio, les images à 20 mégapixels et les fichiers vidéo et audio à trois minutes. Les pistes audio sont limitées à 20 Mio, comme dans Audio Ads. Les images sont normalisées en PNG. Les fichiers et leurs métadonnées sont stockés dans SQLite avec l’identifiant du prospect.

Les photos Google déjà disponibles sont affichées avec l’attribution. Ajoutez celle à réutiliser à la bibliothèque pour en conserver une copie avec sa provenance et son attribution. Une URL Google expirée peut nécessiter une actualisation des données Google du prospect.


## Composition d’un flyer Image Ads

La création IA propose le type Flyer par défaut. Le rendu PNG utilise le nom affiché, le métier et les coordonnées disponibles sur la fiche prospect. L’accroche est facultative. Son placement peut être choisi dans le studio ou précisé en mode Automatique, par exemple « Accroche : en haut » ou « Accroche : à gauche ». Le style visuel agit sur la palette et la typographie de l’annonce et guide aussi le fond en Création IA. OpenAI crée le visuel principal, puis ProfileFinder compose les textes et le logo localement. Le studio propose un aperçu local quand une photo ou un fond existe. **Retoucher le flyer** réutilise ce visuel. **Modifier le visuel avec l’IA** utilise le dernier fond sans texte comme référence principale. L’envoi du flyer complet précédent est facultatif. **Générer le flyer complet avec l’IA** transmet ensemble le brief, l’instruction libre, les champs à imprimer, le style et les références. Ce mode produit une image finale en une seule pièce. Coché par défaut pour les nouvelles créations, le réglage Pictogrammes de contact place les symboles de téléphone et de localisation près des champs renseignés en composition locale et précise ce placement dans le brief du flyer complet. Relisez les textes, les coordonnées et le logo avant diffusion. Pour modifier les textes localement sans appel IA, utilisez une composition disposant d’un fond séparé. **Créer une variante** crée un projet séparé. Les rendus enregistrés peuvent être comparés, téléchargés et restaurés depuis l’historique. Les mises en page Commerciale, Éditoriale et Promotionnelle changent la composition locale.

## Studios

- **Audio Ads** remplace le libellé Ads. Les URL `/ads` et les anciennes API continuent à servir. Les médias sélectionnés comme contexte alimentent le message via leurs intitulés, catégories et formats. Les pistes choisies comme voix et musique sont vérifiées et chargées côté serveur pour le mixage, puis les sélections sont enregistrées avec le spot.
- **Image Ads** propose quatre formats PNG. Photo réelle compose l’image choisie avec le texte et un logo indépendant. Création IA utilise jusqu’à quatre références image via OpenAI et enregistre le fond séparément du PNG final. Changer le texte, sa couleur, son placement, l’alignement, le cadrage ou le logo réutilise le fond existant. Une modification du brief visuel, du format ou des références peut demander un nouveau fond. Pour un prospect avec site IA, la palette et la direction de ce dernier sont disponibles. Sinon, Image Ads recherche le thème déclaré et les couleurs des styles intégrés dans la page d’accueil publique. La récupération se limite à la page HTML et peut fournir une palette partielle ou vide.
- **Sites IA** affiche les visuels et les vidéos sélectionnés dans la vitrine et utilise le logo dans l’en-tête. Une sélection de photos réelles remplace la génération payante d’illustrations pour cette nouvelle vitrine.
- **Video Ads** distribue les images et vidéos choisies entre les plans. Le storyboard montre un aperçu fixe des clips. Le rendu MP4 lit les clips et les boucle lorsqu’ils sont plus courts que le plan, en conservant la bande-son de l’annonce. Le logo est superposé indépendamment du fond. Les plans avec une sélection de médias réels ne déclenchent pas de génération de visuels IA.

Un rendu Image Ads crée une entrée dans Jobs, Opérations, le tableau de bord et la fiche prospect. Le studio présente l’aperçu et l’historique de ses tentatives. Après redémarrage, les tentatives interrompues sont marquées en erreur. Ouvrez la création et cliquez sur **Relancer la composition**. Un fond IA déjà enregistré reste réutilisable.

## Mise à jour Ubuntu

La base de développement de ce changement est `feat/ads-video-studios`. Pour une installation existante, arrêtez le service, sauvegardez l’installation avec sa base SQLite et ses fichiers média, puis appliquez la version revue.

1. Arrêter le service avec `sudo systemctl stop profilefinder`.
2. Sauvegarder la base SQLite définie par `DATABASE_URL` (par défaut `data/profilefinder.db`), `ADS_MEDIA_ROOT` (par défaut `data/ads`) et `app/static/generated`. Conserver le fichier `.env` avec ses réglages et protéger la sauvegarde comme les données d’origine. Les nouveaux médias et PNG font partie de la sauvegarde SQL.
3. Depuis la racine du dépôt, exécuter `bash scripts/install.sh` ou installer `ffmpeg` et `fonts-dejavu-core` via APT puis exécuter `.venv/bin/pip install -r requirements.txt`. Les rendus vidéo continuent à utiliser le Chromium configuré par le script.
4. Vérifier `OPENAI_API_KEY`, `OPENAI_MODEL` et `OPENAI_IMAGE_MODEL`. La clé ElevenLabs reste facultative pour Audio Ads.
5. Démarrer avec `sudo systemctl start profilefinder` et contrôler `sudo journalctl -u profilefinder -n 50`. Au démarrage, l’application crée les tables de médias et d’Image Ads et ajoute les métadonnées de sélection à la table audio existante. Les processus de rendu et de récupération utilisent une instance applicative avec un seul processus Uvicorn, comme le service fourni.
6. Contrôler un ancien site, un ancien audio et un ancien projet vidéo. Sur un prospect de test, importer une photo, composer en mode Photo réelle et vérifier le PNG ainsi que l’entrée dans Jobs.

Les API et les rendus sans appel payant sont couverts par `.venv/bin/python -m pytest -q tests/test_prospect_media_image_ads.py`. Ce test utilise SQLite temporaire, un fournisseur OpenAI simulé et FFmpeg local pour vérifier que les vidéos restent animées.
