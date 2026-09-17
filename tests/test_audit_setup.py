"""Host-side setup regression tests; no network, credentials, or commits."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'audit-setup.sh'


class AuditSetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='audit-setup-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'target with spaces'
        self.source.mkdir()
        self.output = self.root / 'workspaces'
        self.env = dict(os.environ, AUDIT_WORKSPACE_ROOT=str(self.output))

    def run_setup(self, *args, env=None):
        return subprocess.run([str(SCRIPT), *map(str, args)], env=env or self.env,
                              capture_output=True, text=True)

    def test_snapshot_preserves_source_and_quarantines_configuration(self):
        (self.source / 'app.py').write_text('uncommitted source\n')
        (self.source / '.git').write_text('gitdir: /host/private/worktree\n')
        (self.source / '.vscode').mkdir()
        (self.source / '.vscode' / 'tasks.json').write_text('untrusted tasks')
        (self.source / '.devcontainer').symlink_to('/nonexistent/unsafe')
        (self.source / 'external').symlink_to('/nonexistent/external')
        result = self.run_setup(self.source)
        self.assertEqual(result.returncode, 0, result.stderr)
        workspace, = self.output.iterdir()
        self.assertEqual((workspace / 'app.py').read_text(), 'uncommitted source\n')
        self.assertFalse((workspace / '.git').exists())
        self.assertFalse((workspace / '.vscode').exists())
        self.assertTrue((workspace / '.devcontainer' / 'Dockerfile').is_file())
        backup, = workspace.glob('.audit-original-config-*')
        self.assertTrue((backup / '.devcontainer').is_symlink())
        self.assertEqual((backup / '.vscode' / 'tasks.json').read_text(), 'untrusted tasks')
        self.assertTrue((workspace / 'external').is_symlink())
        self.assertTrue((self.source / '.git').is_file())
        self.assertTrue((self.source / '.devcontainer').is_symlink())

    def test_repeated_runs_create_distinct_workspaces(self):
        for _ in range(2):
            result = self.run_setup(self.source)
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(list(self.output.iterdir())), 2)

    def test_rejects_recursive_copy(self):
        env = dict(self.env, AUDIT_WORKSPACE_ROOT=str(self.source / 'nested'))
        result = self.run_setup(self.source, env=env)
        self.assertEqual(result.returncode, 2)
        self.assertIn('outside the target', result.stderr)
        self.assertFalse((self.source / 'nested').exists())

    def test_rejects_workspace_inside_template(self):
        for parent in [SCRIPT.parents[1], SCRIPT.parents[1] / 'audit-workspaces']:
            env = dict(self.env, AUDIT_WORKSPACE_ROOT=str(parent))
            result = self.run_setup(self.source, env=env)
            self.assertEqual(result.returncode, 2)
            self.assertIn('outside the template', result.stderr)

    def test_rejects_recursive_copy_through_symlink(self):
        alias = self.root / 'source-alias'
        alias.symlink_to(self.source, target_is_directory=True)
        env = dict(self.env, AUDIT_WORKSPACE_ROOT=str(alias / 'nested'))
        result = self.run_setup(self.source, env=env)
        self.assertEqual(result.returncode, 2)
        self.assertFalse((self.source / 'nested').exists())

    def test_workspace_root_stays_private(self):
        self.source.chmod(0o755)
        result = self.run_setup(self.source)
        self.assertEqual(result.returncode, 0, result.stderr)
        workspace, = self.output.iterdir()
        self.assertEqual(workspace.stat().st_mode & 0o777, 0o700)
        self.assertEqual(self.source.stat().st_mode & 0o777, 0o755)

    def test_failed_snapshot_keeps_private_workspace(self):
        self.source.chmod(0o755)
        os.mkfifo(self.source / 'unsupported-pipe')
        result = self.run_setup(self.source)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('incomplete workspace retained', result.stderr)
        workspace, = self.output.iterdir()
        self.assertEqual(workspace.stat().st_mode & 0o777, 0o700)

    def test_invalid_input_and_help(self):
        for args in [(), ('--bad',), ('/missing/folder',), ('a', 'b')]:
            self.assertEqual(self.run_setup(*args).returncode, 2)
        self.assertEqual(self.run_setup('--help').returncode, 0)

    def test_rejects_filesystem_root_snapshot(self):
        result = self.run_setup('/')
        self.assertEqual(result.returncode, 2)
        self.assertFalse(self.output.exists())

    def test_clone_path_with_local_git_transport(self):
        # Map an HTTPS URL to a local empty bare repository, exercising real Git
        # clone without contacting a server or creating any commits.
        bare = self.root / 'remote.git'
        subprocess.run(['git', 'init', '--bare', str(bare)], check=True,
                       capture_output=True)
        env = dict(self.env, GIT_CONFIG_COUNT='1',
                   GIT_CONFIG_KEY_0=f'url.{bare}.insteadOf',
                   GIT_CONFIG_VALUE_0='https://audit-test.invalid/repo.git')
        result = self.run_setup('https://audit-test.invalid/repo.git', env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        workspace, = self.output.iterdir()
        self.assertTrue((workspace / '.git').is_dir())
        self.assertTrue((workspace / '.devcontainer' / 'devcontainer.json').is_file())
        hooks = subprocess.check_output(
            ['git', '-C', str(workspace), 'config', 'core.hooksPath'], text=True)
        self.assertEqual(hooks.strip(), '/dev/null')


if __name__ == '__main__':
    unittest.main()
