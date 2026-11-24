# Supervision IZICERFA

Le journal privé présente les événements AIU et ENIO reçus depuis la mise en production. Il distingue l’heure de réception, les dates IZICERFA, le statut du paiement et le résultat du traitement technique. Les données sont conservées 30 jours dans un volume SQLite du projet de supervision. Les refus HTTP antérieurs à l’enregistrement sont consultables dans les journaux Railway du service API.

Le service web reçoit des lots authentifiés, puis les déduplique par identifiant de réception. Il ne possède aucun accès à HubSpot ou à la base de production. Les recherches par email sont envoyées par POST pour garder les adresses hors des URL. Les jetons de connexion à usage unique sont distribués par email, transmis en fragment, puis échangés contre un cookie de session sécurisé. Le journaling HTTP applicatif est désactivé.

Le relais du projet source interroge toutes les deux minutes une vue limitée. Le mode setup installe la vue et le compte SQL de lecture. Il vérifie l’interdiction de lire la table complète et d’y écrire. Retirer SETUP_DATABASE_URL avant d’activer le mode relay. Le processus permanent refuse de démarrer si cette variable contient une valeur. La synchronisation reprend au dernier point confirmé avec un recouvrement et une relecture quotidienne des 30 derniers jours.

Configuration du web : JOURNAL_ORIGIN, OWNER_EMAIL, FEED_KEY, DATA_DIR, RESEND_API_KEY et MAIL_FROM. Configuration du relais : MODE, JOURNAL_ORIGIN, FEED_KEY, PGHOST, PGPORT, PGDATABASE et READER_PASSWORD. Le mot de passe SQL et la clé de transfert sont générés séparément. Aucune valeur de production ne figure dans le dépôt.
