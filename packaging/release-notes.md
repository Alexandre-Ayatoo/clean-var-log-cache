Installation sur Debian/Ubuntu (Python 3.9 minimum) : télécharger le fichier
`clean-system_*_all.deb` ci-dessous, puis lancer :

```sh
sudo apt install ./clean-system_*_all.deb
clean-system --help
clean-system --verbose
sudo clean-system --apply
```

Le même paquet convient aux architectures amd64 et arm64. APT installe Python
si nécessaire. La commande est installée dans `/usr/bin/clean-system`.
Aucun nettoyage ni tâche planifiée n'est exécuté à l'installation.

Pour une mise à jour, installer le nouveau `.deb` avec la même commande.
Pour désinstaller : `sudo apt remove clean-system`.

L'empreinte du paquet est fournie dans `SHA256SUMS` : placer les deux fichiers
dans le même dossier puis lancer `sha256sum --check SHA256SUMS`.
