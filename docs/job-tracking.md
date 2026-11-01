# Suivi des jobs et opérations

Jobs, Opérations et le tableau de bord utilisent le même historique : recherches Google Places, sites IA, rédaction publicitaire, voix off OpenAI/ElevenLabs, mixages FFmpeg, préparation/actualisation des plans et exports MP4.

Chaque nouvelle opération vidéo crée un job distinct lié au projet et au prospect : les relances conservent l'historique. Les étapes et la progression suivent le traitement réel (instructions, visuels IA, captures, composition, encodage). Les pourcentages représentent l'avancement des étapes, pas une estimation du temps restant. Les tâches audio n'affichent aucun pourcentage estimé pendant les appels fournisseurs.

Les filtres par type, état et recherche restent sélectionnés pendant l'actualisation toutes les cinq secondes. Les compteurs portent sur les activités filtrées. Les anciennes vidéos et les audios enregistrés restent visibles ; aucune durée d'exécution n'est inventée pour ces ressources historiques. Les détails des recherches conservent leurs résultats Google Places ; les détails créatifs affichent leur propre suivi et un lien vers le studio concerné. Aucun bouton générique de relance ne transforme une tâche créative en recherche Google Places.

Au démarrage, les opérations audio et vidéo interrompues sont marquées en erreur et peuvent être relancées dans leur studio. Les appels fournisseurs et le mixage restent exécutés hors de la boucle HTTP. Les textes publicitaires, contenus audio et clés ne sont pas enregistrés dans les jobs.

Deux colonnes facultatives (`resource_id`, `stage`) sont ajoutées automatiquement à la table SQLite `jobs` au prochain démarrage. Redémarrer ProfileFinder après mise à jour. Les API `/api/jobs` et `/api/ops` exposent le même flux enrichi ; les entrées historiques de médias utilisent un identifiant préfixé et leur champ `url` pointe directement vers le studio. Les jobs persistants conservent leurs identifiants numériques et leur page `/jobs/{id}`.
