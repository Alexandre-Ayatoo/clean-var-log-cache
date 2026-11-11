#!/usr/bin/env python3
"""Construire le paquet binaire avec Python et dpkg-deb, sans privilèges root."""

import argparse
import ast
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def source_version():
    tree = ast.parse((ROOT / "clean-system.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "VERSION" for target in node.targets
        ):
            version = ast.literal_eval(node.value)
            if isinstance(version, str) and re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
                return version
    raise ValueError("VERSION doit être au format X.Y.Z dans clean-system.py")


def build(output):
    version = source_version()
    dpkg = shutil.which("dpkg-deb")
    if dpkg is None:
        raise ValueError("dpkg-deb absent : construire sur Debian/Ubuntu (paquet dpkg)")
    output.mkdir(parents=True, exist_ok=True)
    artifact = output / f"clean-system_{version}_all.deb"
    with tempfile.TemporaryDirectory(prefix="clean-system-deb-") as temporary:
        stage = Path(temporary) / "package"
        binary = stage / "usr/bin/clean-system"
        documentation = stage / "usr/share/doc/clean-system/README"
        control = stage / "DEBIAN/control"
        for file in (binary, documentation, control):
            file.parent.mkdir(parents=True, exist_ok=True)
        # Un paquet utilise l'interpréteur système déclaré dans Depends,
        # indépendamment du PATH de l'utilisateur.
        source = (ROOT / "clean-system.py").read_text(encoding="utf-8")
        binary.write_text(source.replace("#!/usr/bin/env python3", "#!/usr/bin/python3", 1),
                          encoding="utf-8")
        documentation.write_bytes((ROOT / "README.md").read_bytes())
        binary.chmod(0o755)
        documentation.chmod(0o644)
        size = (binary.stat().st_size + documentation.stat().st_size + 1023) // 1024
        control.write_text(
            "Package: clean-system\n"
            f"Version: {version}\n"
            "Section: admin\n"
            "Priority: optional\n"
            "Architecture: all\n"
            "Maintainer: Alexandre-Ayatoo <Alexandre-Ayatoo@users.noreply.github.com>\n"
            "Depends: python3 (>= 3.9)\n"
            f"Installed-Size: {size}\n"
            "Homepage: https://github.com/Alexandre-Ayatoo/clean-var-log-cache\n"
            "Description: Targeted Linux log and cache cleanup\n"
            " Preview by default; explicit --apply, configurable retention and exclusions.\n"
            " Includes built-in help. No service, timer or automatic cleanup is installed.\n",
            encoding="utf-8",
        )
        checksums = stage / "DEBIAN/md5sums"
        checksums.write_text("".join(
            f"{hashlib.md5(file.read_bytes()).hexdigest()}  {file.relative_to(stage)}\n"
            for file in (binary, documentation)
        ), encoding="ascii")
        control.chmod(0o644)
        checksums.chmod(0o644)
        # Permissions indépendantes de l'umask ; propriétaires root sans sudo.
        for directory, _, _ in os.walk(stage):
            Path(directory).chmod(0o755)
        subprocess.run([dpkg, "--build", "--root-owner-group", "-Zxz", str(stage),
                        str(artifact)], check=True)
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    (output / "SHA256SUMS").write_text(f"{digest}  {artifact.name}\n", encoding="ascii")
    print(f"Paquet : {artifact}\nInstallation : sudo apt install ./{artifact.name}")
    return artifact


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--output-dir", type=Path, default=ROOT / "dist",
                     help="dossier de sortie (défaut : dist à la racine du dépôt)")
    args = cli.parse_args()
    try:
        build(args.output_dir.resolve())
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        cli.exit(1, f"Erreur de construction : {exc}\n")


if __name__ == "__main__":
    main()
