# clean-var-log-cache

Nettoyage ciblé pour Linux, Python 3.9 ou plus récent, sans dépendance externe.
Installation Debian/Ubuntu : télécharger le `.deb` depuis les
[releases](https://github.com/Alexandre-Ayatoo/clean-var-log-cache/releases), puis :

```sh
sudo apt install ./clean-system_1.1.0_all.deb
clean-system --help
clean-system --verbose       # simulation, aucune modification
sudo clean-system --apply   # nettoyage réel
```

Le paquet installe `/usr/bin/clean-system`, déclare la dépendance Python et
convient à toutes les architectures (dont amd64 et arm64). Aucun nettoyage
ni tâche planifiée n'est lancé à l'installation. Pour mettre à jour, installer
le nouveau `.deb` avec la même commande ; pour retirer le paquet :
`sudo apt remove clean-system`.

Installation directe dans `/usr/local/bin`, depuis ce dépôt, avec Python déjà
installé : `sudo install -m 0755 clean-system.py /usr/local/bin/clean-system`.
Répéter pour mettre à jour, ou retirer `/usr/local/bin/clean-system` pour
désinstaller. Choisir une seule méthode pour éviter de masquer la commande
installée par le paquet.

Toute la documentation d'utilisation (périmètre, protections, options,
installation et cron) est intégrée à `clean-system --help`. Sans installation,
le script reste utilisable avec `./clean-system.py --help`.

Les deux anciens noms `.sh` redirigent vers le script unifié, avec leur
périmètre respectif. Ils simulent également par défaut. Les anciennes variables
d'environnement (`DRY_RUN`, `AGGRESSIVE`, etc.) sont remplacées par les options
documentées dans `--help` ; elles ne sont plus interprétées.

Vérification : `python3 -m unittest discover -s tests -v`.

Construction du `.deb` sur Debian/Ubuntu, sans root, avec Python et `dpkg-deb`
(fourni par `dpkg`) : `python3 scripts/build-deb.py`. Le paquet et son empreinte
SHA-256 sont générés dans `dist/`. Le workflow GitHub vérifie l'installation,
la réinstallation et la désinstallation ; les tags `vX.Y.Z` publient ensuite
le paquet dans une release, si le tag correspond à `VERSION` dans le script.
