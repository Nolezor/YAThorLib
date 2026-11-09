"""Check release contents before upload; never distribute research inputs."""
from pathlib import Path, PurePosixPath
import sys
import tarfile
import zipfile


def check(directory: Path) -> None:
    wheels = list(directory.glob('*.whl'))
    sources = list(directory.glob('*.tar.gz'))
    if len(wheels) != 1 or len(sources) != 1:
        raise SystemExit('Expected exactly one wheel and one source distribution')
    for archive in wheels + sources:
        if archive.suffix == '.whl':
            with zipfile.ZipFile(archive) as file:
                names = file.namelist()
            required = {'yathorlib/__init__.py', 'yathorlib/data/catalog.json',
                        'yathorlib/data/native.json', 'yathorlib/py.typed'}
            allowed = lambda p: p.parts[0] == 'yathorlib' or p.parts[0].endswith('.dist-info')
        else:
            with tarfile.open(archive) as file:
                names = ['/'.join(PurePosixPath(m.name).parts[1:]) for m in file.getmembers() if m.isfile()]
            required = {'pyproject.toml', 'README.md', 'LICENSE', 'src/yathorlib/data/catalog.json',
                        'src/yathorlib/data/native.json'}
            allowed = lambda p: p.parts[0] in {'src', 'tests', 'examples', 'docs', 'tools'} or len(p.parts) == 1
        if not required <= set(names):
            raise SystemExit(f'{archive}: missing {required - set(names)}')
        for name in names:
            p = PurePosixPath(name)
            if (not allowed(p) or '..' in p.parts or p.is_absolute()
                    or p.suffix.lower() in {'.dll', '.exe', '.pdf', '.pyc', '.pdb', '.zip'}
                    or any(part in {'research', '__pycache__', 'REA Source', '.tools', '.git'} for part in p.parts)):
                raise SystemExit(f'{archive}: unexpected file {name}')
        print(f'{archive.name}: {len(names)} files checked')


if __name__ == '__main__':
    check(Path(sys.argv[1] if len(sys.argv) > 1 else 'dist'))
