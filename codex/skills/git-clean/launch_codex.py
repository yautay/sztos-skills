#!/usr/bin/env python3
"""Start an interactive git-clean session on the explicitly selected cheap model."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess

MODEL = 'gpt-6-luna'
REASONING = 'low'
SKILL_DIR = Path(__file__).resolve().parent


def build_command(repo, flags, executable='codex'):
    workflow = SKILL_DIR / 'references/workflow.md'
    prompt = ('Wykonaj git-clean bezpośrednio według instrukcji z pliku '
              + json.dumps(str(workflow), ensure_ascii=False)
              + '. Katalog skilla (SKILL_DIR): '
              + json.dumps(str(SKILL_DIR), ensure_ascii=False)
              + '. Jesteś przypisanym wykonawcą GPT-6 Luna; nie deleguj tego workflow dalej. '
              'Zachowaj instrukcje badanego repo i uzyskaj konkretne zgody przed mutacjami. '
              'Argumenty użytkownika (JSON): ' + json.dumps(flags, ensure_ascii=False))
    return [executable, '--model', MODEL, '--config', f'model_reasoning_effort={REASONING}',
            '--cd', str(Path(repo).resolve()), prompt]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', default=str(Path.cwd()))
    parser.add_argument('--dry-run', action='store_true', help='Print argv as JSON; do not start Codex.')
    parser.add_argument('skill_args', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    flags = args.skill_args[1:] if args.skill_args[:1] == ['--'] else args.skill_args
    repo = Path(args.repo).resolve()
    if not repo.is_dir():
        parser.error('The repository directory does not exist.')
    if args.dry_run:
        print(json.dumps(build_command(repo, flags), ensure_ascii=False, indent=2))
        return 0
    executable = shutil.which('codex')
    if executable is None:
        parser.error('Codex CLI is missing; install the official CLI before running this command.')
    # An argv list avoids invoking a shell; the CLI owns approvals and model availability.
    # No expensive fallback, global model change, or sandbox/approval override.
    return subprocess.call(build_command(repo, flags, executable))


if __name__ == '__main__':
    raise SystemExit(main())
