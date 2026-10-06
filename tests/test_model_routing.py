import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / 'codex/skills/git-clean/launch_codex.py'
spec = importlib.util.spec_from_file_location('launch_codex', LAUNCHER)
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


class ModelRoutingTests(unittest.TestCase):
    def test_launcher_pins_luna_and_low_without_weakening_permissions(self):
        command = launcher.build_command(ROOT, ['--no-fetch', '--no-sync'])
        self.assertEqual(command[command.index('--model') + 1], 'gpt-6-luna')
        self.assertEqual(command[command.index('--config') + 1], 'model_reasoning_effort=low')
        self.assertFalse(any('bypass' in arg or arg in ('--ask-for-approval', '--sandbox') for arg in command))
        self.assertIn('references', command[-1])
        self.assertTrue((launcher.SKILL_DIR / 'references/workflow.md').exists())

    def test_dry_run_preserves_argument_data_without_launching_codex(self):
        with tempfile.TemporaryDirectory(prefix='model routing ') as repo:
            result = subprocess.run([sys.executable, str(LAUNCHER), '--repo', repo, '--dry-run',
                                     '--', '--stale-days', '30'], capture_output=True, text=True, check=True)
            command = json.loads(result.stdout)
            self.assertEqual(command[command.index('--cd') + 1], str(Path(repo).resolve()))
            self.assertIn('["--stale-days", "30"]', command[-1])


if __name__ == '__main__':
    unittest.main()
