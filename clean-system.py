#!/usr/bin/env python3
"""Nettoyage Linux ciblé, sans dépendance Python externe (Python >= 3.9)."""

import argparse
import contextlib
import fcntl
import os
from pathlib import Path
import re
import shlex
import shutil
import stat
import subprocess
import sys
import time

VERSION = "1.1.1"
LOG_ROOT = Path("/var/log")
MAN_ROOT = Path("/var/cache/man")
LOCK_PATH = "/run/lock/clean-system.lock"
SAFE_PATH = "/usr/sbin:/usr/bin:/sbin:/bin"
PROTECTED = {"journal", "private", "audit", "zabbix"}
# Seuls les noms de rotations identifiables sont retenus, pas toute archive.
ROTATED = re.compile(
    r"^(?:.+\.log|syslog|messages|debug|kern|daemon|mail\.(?:info|warn|err)|"
    r"wtmp|btmp|lastlog|faillog|dmesg)"
    r"(?:\.[0-9]+|[-.]\d{8}(?:[-_]\d{6})?)(?:\.(?:gz|xz|bz2|zst))?$",
    re.DOTALL,
)


def positive(value):
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("un entier positif est requis") from exc
    if not 1 <= number <= 365000:
        raise argparse.ArgumentTypeError("valeur attendue entre 1 et 365000")
    return number


def parser():
    cli = argparse.ArgumentParser(
        description="Nettoie les anciens logs et caches Linux. Simulation par défaut.",
        add_help=False,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""Périmètre et garanties :
  logs     /var/log : rotations reconnues (.log.1, syslog.2.gz,
           app.log-20260101.xz...), selon leur dernière modification.
           Les logs actifs ne sont jamais vidés. Les dossiers journal,
           private, audit et zabbix sont protégés à toute profondeur.
  cache    Paquets téléchargés : apt-get clean, dnf clean packages ou
           yum clean packages (premier outil disponible). Ne désinstalle
           aucun paquet. Cache man : fichiers anciens de /var/cache/man.
           Aucun nettoyage générique de /var/cache ou des caches personnels.
           Fontconfig est conservé : son cache sert encore au système.
  journal  journalctl --vacuum-time : uniquement les journaux archivés.
           Les fichiers actifs restent conservés. Pas de rotation forcée.
  tmp      OPTIONNEL : systemd-tmpfiles --clean limité à /tmp et /var/tmp,
           selon les politiques d'âge du système, pas --days.

  Par défaut : logs,cache,journal. Outils absents : étape ignorée et signalée.
  --days ne concerne ni les paquets (cache entier), ni le journal, ni tmp.
  Aucun lien symbolique suivi, aucun autre périphérique parcouru pour les
  suppressions directes. Dossiers et fichiers à liens multiples conservés.
  Les exclusions concernent les suppressions directes uniquement : pour
  désactiver une commande native, retirer sa catégorie avec --only.
  Simulation : lecture seule, sans fichier de rapport ni verrou créé.
  Les commandes natives sont affichées, sans estimation de leur gain.
  --apply exige root, ne demande pas de confirmation et prend un verrou.
  Les suppressions sont définitives ; conserver les logs requis avant usage.
  Le bilan compte les octets alloués des fichiers directement supprimés ;
  ce n'est pas une mesure exacte de l'espace disque récupéré (snapshots,
  fichiers encore ouverts, compression et commandes natives notamment).
  Python >= 3.9 et Linux requis. Aucun paquet Python à installer.

Installation et mise à jour (Debian/Ubuntu, paquet téléchargé) :
  sudo apt install ./clean-system_{VERSION}_all.deb
  sudo apt remove clean-system               # désinstallation
  Le paquet installe /usr/bin/clean-system et déclare Python >= 3.9.
  Aucun nettoyage ni tâche planifiée n'est lancé à l'installation.

Installation directe (autres Linux, Python >= 3.9 déjà installé) :
  sudo install -m 0755 clean-system.py /usr/local/bin/clean-system
  Mise à jour : répéter la même commande avec le nouveau fichier.
  Désinstallation : sudo rm /usr/local/bin/clean-system
  Choisir une seule méthode : /usr/local/bin peut masquer /usr/bin.
  Depuis le dépôt sans installation : remplacer clean-system ci-dessous
  par ./clean-system.py.

Exemples :
  clean-system --help
  clean-system --verbose                     # aperçu détaillé
  sudo clean-system --apply                  # nettoyage standard
  sudo clean-system --apply --days 30 --journal-days 30
  clean-system --only logs --exclude /var/log/nginx --verbose
  sudo clean-system --apply --only cache
  sudo clean-system --apply --only logs,cache,journal,tmp
  sudo clean-system --apply > nettoyage.txt 2>&1
  # Cron root, chaque dimanche à 03:15 (chemin absolu à adapter) :
  15 3 * * 0 /usr/bin/clean-system --apply

Codes de sortie : 0 succès (y compris outils absents), 1 erreur d'exécution
ou accès refusé, 2 arguments invalides, 130 interruption clavier.
Une erreur n'annule pas les actions déjà effectuées. Les étapes indépendantes
continuent, sauf interruption ou verrou déjà pris.
""",
    )
    cli.add_argument("-h", "--help", action="help", help="afficher cette aide et quitter")
    mode = cli.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="exécuter le nettoyage (root)")
    mode.add_argument("--dry-run", action="store_true", help="simuler (mode par défaut)")
    cli.add_argument("--only", default="logs,cache,journal", metavar="CATÉGORIES",
                     help="liste séparée par des virgules : logs,cache,journal,tmp")
    cli.add_argument("--days", type=positive, default=14, metavar="N",
                     help="âge minimal des rotations, en jours (défaut : 14)")
    cli.add_argument("--cache-days", type=positive, default=30, metavar="N",
                     help="âge minimal des fichiers du cache man (défaut : 30)")
    cli.add_argument("--journal-days", type=positive, default=14, metavar="N",
                     help="rétention du journal archivé, en jours (défaut : 14)")
    cli.add_argument("--exclude", action="append", default=[], metavar="CHEMIN",
                     help="chemin absolu à conserver, répétable (logs/cache man)")
    cli.add_argument("--verbose", "-v", action="store_true", help="afficher chaque fichier ciblé")
    cli.add_argument("--command-timeout", type=positive, default=300, metavar="SECONDES",
                     help="durée maximale par commande native (défaut : 300)")
    cli.add_argument("--version", action="version", version=f"%(prog)s {VERSION}",
                     help="afficher la version et quitter")
    return cli


def parse_args(argv=None):
    cli = parser()
    args = cli.parse_args(argv)
    args.categories = set(args.only.split(","))
    if not args.categories <= {"logs", "cache", "journal", "tmp"}:
        cli.error("--only accepte logs,cache,journal,tmp, sans espaces ni catégorie vide")
    args.excludes = []
    for item in args.exclude:
        if not os.path.isabs(item) or ".." in Path(item).parts:
            cli.error("--exclude exige un chemin absolu sans '..'")
        args.excludes.append(Path(os.path.normpath(item)))
    return args


@contextlib.contextmanager
def open_directory(path):
    """Ouvre chaque composant sans suivre de symlink, y compris les parents."""
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in Path(path).parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                            dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd
    finally:
        os.close(fd)


@contextlib.contextmanager
def execution_lock():
    fd = os.open(LOCK_PATH, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_nlink != 1:
            raise OSError("fichier de verrou non sûr")
        if info.st_mode & 0o022:
            raise OSError("verrou accessible en écriture à d'autres utilisateurs")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise OSError("un autre nettoyage est déjà en cours") from exc
        yield
    finally:
        # Garder le fichier évite une course entre deux prises de verrou.
        os.close(fd)


class Cleaner:
    def __init__(self, args):
        self.args = args
        self.now = time.time()
        self.errors = 0
        self.files = 0
        self.allocated = 0
        self.commands = 0

    def error(self, message):
        self.errors += 1
        print(f"[ERREUR] {message}", file=sys.stderr)

    def excluded(self, path):
        return any(path == item or item in path.parents for item in self.args.excludes)

    def scan(self, root, days, logs=False):
        count = allocated = 0
        cutoff = self.now - days * 86400
        if self.excluded(root):
            print(f"[IGNORÉ] {root} : exclusion")
            return
        try:
            with open_directory(root) as root_fd:
                device = os.fstat(root_fd).st_dev
                for current, dirs, names, fd in os.fwalk(
                    ".", topdown=True, onerror=self.error,
                    follow_symlinks=False, dir_fd=root_fd,
                ):
                    relative = Path(current)
                    directory = root / relative
                    kept = []
                    for name in dirs:
                        path = directory / name
                        if self.excluded(path) or (logs and name in PROTECTED):
                            continue
                        try:
                            info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                            if stat.S_ISDIR(info.st_mode) and info.st_dev == device:
                                kept.append(name)
                        except FileNotFoundError:
                            pass  # Une rotation concurrente est normale.
                        except OSError as exc:
                            self.error(f"{str(path)!r} : {exc}")
                    dirs[:] = kept
                    for name in names:
                        path = directory / name
                        if self.excluded(path) or (logs and not ROTATED.fullmatch(name)):
                            continue
                        try:
                            info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                            if (not stat.S_ISREG(info.st_mode) or info.st_dev != device
                                    or info.st_nlink != 1 or info.st_mtime >= cutoff):
                                continue
                            if self.args.apply:
                                # Revalider juste avant unlink ; jamais de récursion rm.
                                latest = os.stat(name, dir_fd=fd, follow_symlinks=False)
                                if (latest.st_dev, latest.st_ino, latest.st_mtime_ns,
                                    latest.st_ctime_ns, latest.st_size, latest.st_nlink) != (
                                    info.st_dev, info.st_ino, info.st_mtime_ns,
                                    info.st_ctime_ns, info.st_size, info.st_nlink):
                                    continue
                                os.unlink(name, dir_fd=fd)
                            count += 1
                            allocated += info.st_blocks * 512
                            if self.args.verbose:
                                print(f"  {'SUPPRIMÉ' if self.args.apply else 'CIBLE'} {str(path)!r}")
                        except FileNotFoundError:
                            continue
                        except OSError as exc:
                            self.error(f"{str(path)!r} : {exc}")
        except FileNotFoundError:
            print(f"[IGNORÉ] {root} absent")
            return
        except OSError as exc:
            self.error(f"{root} : {exc}")
        self.files += count
        self.allocated += allocated
        print(f"[FICHIERS] {root} : {count} fichier(s), {allocated / 1048576:.2f} Mio alloués")

    def command(self, name, *arguments):
        executable = shutil.which(name, path=SAFE_PATH)
        if executable is None:
            print(f"[IGNORÉ] {name} absent")
            return
        command = [executable, *arguments]
        print(f"[{'EXÉCUTION' if self.args.apply else 'PRÉVU'}] {shlex.join(command)}", flush=True)
        if not self.args.apply:
            return
        # Pas de shell ; PATH fixé et pas de configuration utilisateur héritée.
        environment = {"PATH": SAFE_PATH, "HOME": "/root", "LC_ALL": "C",
                       "DEBIAN_FRONTEND": "noninteractive"}
        try:
            subprocess.run(command, check=True, stdin=subprocess.DEVNULL,
                           timeout=self.args.command_timeout, env=environment)
            self.commands += 1
        except (OSError, subprocess.SubprocessError) as exc:
            self.error(f"{name} : {exc}")

    def run(self):
        print("Nettoyage Linux — " + ("EXÉCUTION" if self.args.apply else "SIMULATION (aucune modification)"))
        print("Catégories : " + ", ".join(sorted(self.args.categories)))
        if "logs" in self.args.categories:
            self.scan(LOG_ROOT, self.args.days, logs=True)
        if "cache" in self.args.categories:
            for name, arguments in (("apt-get", ("clean",)),
                                    ("dnf", ("clean", "packages")),
                                    ("yum", ("clean", "packages"))):
                if shutil.which(name, path=SAFE_PATH):
                    self.command(name, *arguments)
                    break
            else:
                print("[IGNORÉ] aucun gestionnaire de paquets pris en charge (apt/dnf/yum)")
            self.scan(MAN_ROOT, self.args.cache_days)
        if "journal" in self.args.categories:
            self.command("journalctl", f"--vacuum-time={self.args.journal_days}d")
        if "tmp" in self.args.categories:
            self.command("systemd-tmpfiles", "--clean", "--prefix=/tmp", "--prefix=/var/tmp")
        verb = "supprimé(s)" if self.args.apply else "ciblé(s)"
        print(f"Bilan : {self.files} fichier(s) {verb}, "
              f"{self.allocated / 1048576:.2f} Mio alloués, "
              f"{self.commands} commande(s) réussie(s), {self.errors} erreur(s).")
        return int(bool(self.errors))


def main(argv=None):
    args = parse_args(argv)
    if sys.platform != "linux":
        print("[ERREUR] outil destiné à Linux ; --help reste disponible.", file=sys.stderr)
        return 1
    if args.apply and os.geteuid() != 0:
        print("[ERREUR] --apply exige root : utiliser sudo.", file=sys.stderr)
        return 1
    try:
        with execution_lock() if args.apply else contextlib.nullcontext():
            return Cleaner(args).run()
    except KeyboardInterrupt:
        print("\nInterrompu ; certaines actions ont pu être effectuées.", file=sys.stderr)
        return 130
    except OSError as exc:
        print(f"[ERREUR] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
