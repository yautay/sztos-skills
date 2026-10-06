#!/usr/bin/env python3
"""Package standalone provider skills from shared sources; --check detects drift."""
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    failures = []
    sources = [p for p in sorted((ROOT / 'shared/git-clean').iterdir())
               if p.suffix in ('.sh', '.ps1', '.py')]
    providers = sorted(p for p in ROOT.iterdir() if (p / 'skills/git-clean/SKILL.md').is_file())
    for provider in providers:
        target = provider / 'skills/git-clean'
        for source in sources:
            data = source.read_bytes()
            destination = target / source.name
            if args.check:
                if not destination.exists() or destination.read_bytes() != data:
                    failures.append(str(destination.relative_to(ROOT)))
            else:
                destination.write_bytes(data)
    if failures:
        print('Outdated packages: ' + ', '.join(failures))
        return 1
    print(('Checked' if args.check else 'Built') + f' {len(providers)} provider packages.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
