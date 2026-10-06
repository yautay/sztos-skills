import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'shared/git-clean'
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location('git_clean_report', SCRIPTS / 'report.py')
report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report)
import graph


class GitFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='git clean tests ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / 'repo with spaces'
        self.repo.mkdir()
        empty_config = self.root / 'global-config'
        empty_config.write_text('')
        self.env = dict(os.environ, GIT_CONFIG_GLOBAL=str(empty_config), GIT_CONFIG_NOSYSTEM='1',
                        GIT_TERMINAL_PROMPT='0', PYTHONUTF8='1',
                        GIT_AUTHOR_NAME='Fixture | author', GIT_AUTHOR_EMAIL='fixture@example.invalid',
                        GIT_COMMITTER_NAME='Fixture | author', GIT_COMMITTER_EMAIL='fixture@example.invalid')
        for key in ('GIT_CONFIG_COUNT', 'GIT_CONFIG_KEY_0', 'GIT_CONFIG_VALUE_0'):
            self.env.pop(key, None)
        self.git('init', '-b', 'main')
        self.commit('base.txt', 'base\n', 'Fixture base')

    def run_command(self, args, check=True):
        result = subprocess.run(args, cwd=self.repo, env=self.env, capture_output=True,
                                text=True, encoding='utf-8', errors='replace', timeout=60)
        if check and result.returncode:
            self.fail(f'{args}: {result.returncode}\n{result.stdout}\n{result.stderr}')
        return result

    def git(self, *args):
        return self.run_command(['git', *args]).stdout.strip()

    def commit(self, name, content, message):
        (self.repo / name).write_text(content)
        self.git('add', '--', name)
        self.git('commit', '-m', message)

    def bash(self, script, *args, check=True):
        bash = shutil.which('bash')
        if os.name == 'nt':
            git_root = Path(shutil.which('git')).resolve().parents[1]
            bash = str(git_root / 'bin/bash.exe')
        return self.run_command([bash, '-c', 'export PATH="/usr/bin:/bin:$PATH"; exec bash "$@"',
                                 '--', str(SCRIPTS / script), *args], check=check)

    def audit(self):
        self.bash('audit.sh', '--no-fetch')
        return report.parse_audit((self.repo / '.git/git-clean/audit.txt').read_text(encoding='utf-8'))

    def remote(self):
        self.git('init', '--bare', str(self.root / 'origin.git'))
        self.git('remote', 'add', 'origin', str(self.root / 'origin.git'))
        self.git('push', '-u', 'origin', 'main')
        self.git('remote', 'set-head', 'origin', 'main')

    def test_unique_stash_index_is_preserved(self):
        (self.repo / 'base.txt').write_text('unique staged content\n')
        self.git('add', 'base.txt')
        (self.repo / 'base.txt').write_text('base\n')
        self.git('stash', 'push', '-m', 'Unique index')
        before = self.git('show-ref')
        a = self.audit()
        c = report.classify(a, report.PROTECTED_DEFAULT)
        self.assertEqual(a['stash'][0]['index_state'], 'distinct')
        self.assertEqual(c['plan']['C'], [])
        self.assertEqual(c['stash'][0]['kind'], 'rescue')
        summary = report.text_summary(a, c, None, None, self.repo / 'report.html')
        self.assertIn('do usunięcia C: 0', summary)
        self.assertIn('stash do oceny E: 1', summary)
        self.assertEqual(self.git('show', 'stash@{0}^2:base.txt'), 'unique staged content')
        self.assertEqual(self.git('show-ref'), before)

    def test_duplicate_unstaged_stash_can_be_dropped(self):
        (self.repo / 'base.txt').write_text('already applied\n')
        self.git('stash', 'push', '-m', 'Duplicate worktree')
        self.git('stash', 'apply')
        a = self.audit()
        c = report.classify(a, report.PROTECTED_DEFAULT)
        self.assertEqual(a['stash'][0]['index_state'], 'base')
        self.assertEqual(len(c['plan']['C']), 1)

    def test_untracked_stash_content_is_preserved(self):
        (self.repo / 'untracked.txt').write_text('only copy\n')
        self.git('stash', 'push', '-u', '-m', 'Untracked only')
        a = self.audit()
        self.assertEqual(a['stash'][0]['untracked'], '1')
        self.assertEqual(report.classify(a, report.PROTECTED_DEFAULT)['plan']['C'], [])

    def test_git_metadata_and_commands_are_not_shell_code(self):
        # Windows filesystem disallows | in a loose ref; apostrophe and ; are valid.
        name = "topic'quote;echo"
        self.git('switch', '-c', name)
        self.commit('feature.txt', 'feature\n', 'Message | with <script>alert(1)</script>')
        self.git('switch', 'main')
        self.git('merge', '--no-ff', '-m', 'Fixture merge', name)
        a = self.audit()
        b = next(b for b in a['local'] if b['name'] == name)
        self.assertEqual(b['author'], 'Fixture | author')
        self.assertEqual(len(b['sha']), 40)
        c = report.classify(a, report.PROTECTED_DEFAULT, 'bash')
        command = c['plan']['A'][0]['cmd']
        self.run_command([self.bash_executable(), '-c', command])
        self.assertNotIn(name, self.git('branch', '--format=%(refname:short)').splitlines())
        # Repeat with the PowerShell command representation, including a literal apostrophe.
        if os.name == 'nt':
            self.git('branch', name, b['sha'])
            command = report.classify(a, report.PROTECTED_DEFAULT, 'powershell')['plan']['A'][0]['cmd']
            self.run_command(['powershell.exe', '-NoProfile', '-Command', command])
            self.assertNotIn(name, self.git('branch', '--format=%(refname:short)').splitlines())

    def bash_executable(self):
        if os.name == 'nt':
            return str(Path(shutil.which('git')).resolve().parents[1] / 'bin/bash.exe')
        return shutil.which('bash')

    def test_offline_remote_deletions_are_not_in_block_b(self):
        self.git('switch', '-c', 'feature')
        self.commit('feature.txt', 'feature\n', 'Feature')
        self.git('switch', 'main')
        self.git('merge', '--no-ff', '-m', 'Merge', 'feature')
        self.remote()
        self.git('push', 'origin', 'feature')
        a = self.audit()
        self.assertEqual(report.classify(a, report.PROTECTED_DEFAULT)['plan']['B'], [])
        a['net'] = 'fresh'
        self.assertEqual(len(report.classify(a, report.PROTECTED_DEFAULT)['plan']['B']), 1)

    def test_abandoned_protected_and_current_branches_have_no_delete_plan(self):
        self.git('branch', 'release/old')
        a = self.audit()
        for b in a['local']:
            b['ms'], b['age'] = 'NOT_MERGED', '999'
        c = report.classify(a, report.PROTECTED_DEFAULT)
        self.assertFalse(any('branch -D' in p['cmd'] for p in c['plan']['E']))

    def test_dag_edges_and_html_escaping(self):
        self.git('switch', '-c', 'feature')
        self.commit('feature.txt', 'feature\n', '</script><svg onload="alert(1)"> | feature')
        self.git('switch', 'main')
        self.commit('main.txt', 'main\n', 'Main')
        self.git('merge', '--no-ff', '-m', 'Merge', 'feature')
        a = self.audit()
        c = report.classify(a, report.PROTECTED_DEFAULT)
        positions = graph.layout(a['graph'])
        merge = next(node for node in a['graph'] if node['subject'] == 'Merge')
        self.assertEqual(len(merge['parents'].split()), 2)
        for node in a['graph']:
            for parent in node['parents'].split():
                self.assertGreater(positions[parent][1], positions[node['oid']][1])
        rendered = graph.render_graph(a)
        svg = rendered[rendered.index('<svg '):rendered.index('</svg>') + 6]
        ET.fromstring(svg)
        self.assertNotIn('<svg onload', rendered)
        self.assertIn('&lt;/script&gt;', rendered)
        self.assertEqual(rendered.count('class="graph-edge"'), sum(len(n['parents'].split()) for n in a['graph']))
        html = report.render(a, c, None, None, ['audit.txt'], report.PROTECTED_DEFAULT)
        self.assertIn('id="graph-focus"', html)

    def test_preview_preserves_refs_and_checks_untracked_worktree(self):
        self.remote()
        self.git('switch', '-c', 'feature')
        self.commit('feature.txt', 'feature\n', 'Feature')
        self.git('switch', 'main')
        self.commit('main.txt', 'main\n', 'New base')
        self.git('push', 'origin', 'main')
        self.git('switch', 'feature')
        (self.repo / 'only-local.txt').write_text('untracked\n')
        before = self.git('show-ref')
        output = self.bash('sync.sh', '--dry-run').stdout
        self.assertIn('SKIP_BLOCKED', output)
        self.assertEqual(self.git('show-ref'), before)

    def test_unknown_sync_flag_does_not_apply_changes(self):
        self.remote()
        before = self.git('show-ref')
        result = self.bash('sync.sh', '--dry-rnu', check=False)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.git('show-ref'), before)

    def test_sync_error_stops_before_other_branches(self):
        self.remote()
        self.git('switch', '-c', 'a-feature')
        self.commit('feature.txt', 'feature\n', 'Feature')
        self.git('switch', 'main')
        self.commit('main.txt', 'main\n', 'New base')
        self.git('push', 'origin', 'main')
        self.git('branch', 'b-feature', 'a-feature')
        self.git('switch', '--detach', 'main')
        before = self.git('show-ref')
        self.git('config', 'user.useConfigOnly', 'true')
        for key in ('GIT_AUTHOR_NAME', 'GIT_AUTHOR_EMAIL', 'GIT_COMMITTER_NAME', 'GIT_COMMITTER_EMAIL'):
            self.env.pop(key, None)
        result = self.bash('sync.sh', check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn('a-feature|ERROR|', result.stdout)
        self.assertNotIn('b-feature|', result.stdout)
        self.assertEqual(self.git('show-ref'), before)

    def test_conflict_metadata_preserves_author_separators(self):
        self.remote()
        self.git('switch', '-c', 'feature')
        self.commit('base.txt', 'feature\n', 'Feature')
        self.git('switch', 'main')
        self.commit('base.txt', 'main\n', 'Main')
        self.git('push', 'origin', 'main')
        result = self.bash('sync.sh', '--dry-run')
        sync = report.parse_sync(result.stdout, 0)
        self.assertEqual(sync['conflicts'][0]['nfiles'], '1')
        self.assertEqual(sync['conflicts'][0]['files'], 'base.txt')
        self.assertIn('Fixture | author', sync['conflicts'][0]['owners'])

    def test_sync_apply_preserves_commit_instructions_and_full_recovery_sha(self):
        self.remote()
        self.git('switch', '-c', "feature'quote;echo")
        self.commit('feature.txt', 'feature\n', 'Feature')
        self.git('switch', 'main')
        self.commit('main.txt', 'main\n', 'New base')
        self.git('push', 'origin', 'main')
        self.git('switch', "feature'quote;echo")
        before = self.git('rev-parse', 'HEAD')
        result = self.bash('sync.sh', '--msg-suffix', ' @disable-code-review',
                           '--trailer', 'Reviewed-in: temporary fixture')
        self.assertIn('@disable-code-review', self.git('log', '-1', '--format=%B'))
        self.assertIn('Reviewed-in: temporary fixture', self.git('log', '-1', '--format=%B'))
        sync = report.parse_sync(result.stdout, 0)
        changed = next(r for r in sync['rows'] if r['status'] == 'MERGED')
        self.assertEqual(changed['old_sha'], before)
        self.assertEqual(len(changed['new_sha']), 40)
        # A generated Bash push remains a vector of three arguments after conversion.
        import shlex
        command = next(c for c in sync['push'] if c.startswith('git push'))
        self.assertEqual(shlex.split(command)[-1], "feature'quote;echo")

    def test_graph_bound_and_invalid_numeric_options(self):
        self.commit('next.txt', 'next\n', 'Next')
        self.bash('audit.sh', '--no-fetch', '--graph-limit', '01')
        a = report.parse_audit((self.repo / '.git/git-clean/audit.txt').read_text(encoding='utf-8'))
        self.assertEqual(len(a['graph']), 1)
        self.assertTrue(a['graph_truncated'])
        self.assertEqual(self.bash('audit.sh', '--no-fetch', '--graph-limit', 'abc', check=False).returncode, 2)

    @unittest.skipUnless(os.name == 'nt', 'Windows launcher')
    def test_powershell_launcher_restores_git_tools_and_preserves_paths(self):
        for mode, args in (('audit', ['--no-fetch']), ('report', ['--sync', 'none'])):
            self.run_command(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                              str(SCRIPTS / 'run.ps1'), mode, *args])
        self.assertTrue((self.repo / '.git/git-clean/report.html').exists())


class ReportMigrationTests(unittest.TestCase):
    def test_expanding_recovery_sha_does_not_invent_history_changes(self):
        import json
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            history = output / 'history'
            history.mkdir()
            oid = 'a' * 40
            previous = {'generated_at': 1700000000, 'local': {'main': oid[:12]},
                        'remote': {'main': oid[:12]}, 'stash': {oid[:12]: 'keep'}, 'worktrees': 1}
            (history / '20231114-221320.json').write_text(json.dumps(previous))
            current = {'generated_at': 1700000060, 'local': [{'name': 'main', 'sha': oid}],
                       'remote_rows': [{'name': 'main', 'sha': oid}],
                       'stash': [{'sha': oid, 'message': 'keep'}], 'worktrees': ['fixture']}
            changes = report.save_and_diff(output, current)
            self.assertEqual(changes['local']['changed'], [])
            self.assertEqual(changes['remote']['changed'], [])
            self.assertEqual(changes['stash']['removed'], [])
            self.assertEqual(changes['stash']['added'], [])


if __name__ == '__main__':
    unittest.main()
