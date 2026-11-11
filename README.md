# clean-var-log-cache

Nettoyage ciblé pour Linux, Python 3.9 ou plus récent, sans dépendance externe.
Toute la documentation (périmètre, protections, options et cron) est intégrée :

```sh
./clean-system.py --help
./clean-system.py --verbose       # simulation, aucune modification
sudo ./clean-system.py --apply   # nettoyage réel
```

Les deux anciens noms `.sh` redirigent vers le script unifié, avec leur
périmètre respectif. Ils simulent également par défaut. Les anciennes variables
d'environnement (`DRY_RUN`, `AGGRESSIVE`, etc.) sont remplacées par les options
documentées dans `--help` ; elles ne sont plus interprétées.

Vérification : `python3 -m unittest discover -s tests -v`.
