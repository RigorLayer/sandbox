"""Offline command regression tests: temporary data, fake tools, no commits."""
import contextlib
import fcntl
import importlib.util
import io
import json
import os
import shlex
import shutil
import subprocess
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

REAL_GIT = shutil.which('git')

SPEC = importlib.util.spec_from_file_location(
    'workflow', Path(__file__).resolve().parents[1] / 'scripts' / 'audit-workflow.py')
workflow = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(workflow)

FAKE_TOOL = '''#!/usr/bin/env python3
import json, os, pathlib, sys
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
with open(os.environ['CALLS'], 'a') as log:
    log.write(json.dumps([name] + args) + '\\n')
if args in (['--version'], ['version']):
    print(name + ' test-version')
    sys.exit(0)
if name == 'git':
    if 'clone' in args:
        if os.getenv('CLONE_FAIL'):
            sys.exit(128)
        repo = pathlib.Path(args[-1])
        repo.mkdir()
        (repo / '.devcontainer').mkdir()
        (repo / '.devcontainer' / 'devcontainer.json').write_text('untrusted')
        (repo / '.vscode').mkdir()
        (repo / 'app.py').write_text('pass')
    else:
        print('a' * 40)
    sys.exit(0)
key = 'semgrep' if name == 'semgrep' else 'gitleaks-' + ('files' if args[0] == 'dir' else 'history')
mode = json.loads(os.getenv('MODES', '{}')).get(key, 'clean')
flag = '--output' if name == 'semgrep' else '--report-path'
report = pathlib.Path(args[args.index(flag) + 1])
findings = [{'test': 'finding'}] if mode == 'findings' else []
data = {'results': findings, 'errors': [{'message': 'parse error'}] if mode == 'errors' else []} if name == 'semgrep' else findings
if mode != 'missing':
    report.write_text('invalid' if mode == 'invalid' else json.dumps(data))
print('scanner log')
if mode == 'failure':
    sys.exit(1)
sys.exit(10 if name == 'gitleaks' and findings else 0)
'''


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='audit-tests-')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'audit'
        self.root.mkdir()
        self.lock = self.base / 'operation.lock'
        self.lock.touch()
        self.bin = self.base / 'bin'
        self.bin.mkdir()
        for name in ('git', 'semgrep', 'gitleaks'):
            tool = self.bin / name
            tool.write_text(FAKE_TOOL)
            tool.chmod(0o755)
        self.calls = self.base / 'calls.jsonl'
        for patcher in (patch.object(workflow, 'AUDIT_ROOT', self.root),
                        patch.object(workflow, 'LOCK_PATH', self.lock),
                        patch.dict(os.environ, {'PATH': str(self.bin) + os.pathsep + os.environ['PATH'],
                                                'CALLS': str(self.calls)})):
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_command(self, *args):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return workflow.main(list(args))

    def clone(self, **modes):
        with patch.dict(os.environ, {'MODES': json.dumps(modes)}):
            return self.run_command('clone', 'https://example.invalid/org/repo.git')

    def summary(self):
        audit, = self.root.iterdir()
        return json.loads((audit / 'reports' / 'summary.json').read_text())

    def test_url_validation(self):
        for url in ('https://example.invalid/a.git', 'ssh://git@example.invalid:2222/a.git',
                    'git@example.invalid:org/repo.git', 'example.invalid:org/repo'):
            self.assertTrue(workflow.valid_url(url), url)
        for url in ('/tmp/repo', './repo', 'file:///tmp/repo', 'http://host/repo',
                    'ext::command', '--upload-pack=evil', 'https://host',
                    'https://host/repo\n', 'ssh://-host/repo', 'https://host:bad/repo',
                    'https://user:password@host/repo', 'https://host/repo?token=secret'):
            self.assertFalse(workflow.valid_url(url), url)
        for args in ((), ('clone',), ('clone', 'a', 'b'), ('reset', '/tmp'), ('reset', '--bad')):
            self.assertEqual(self.run_command(*args), 2)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_unique_private_directories_and_reports_outside_repo(self):
        for _ in range(2):
            self.assertEqual(self.clone(), 0)
        audits = list(self.root.iterdir())
        self.assertEqual(len(audits), 2)
        for audit in audits:
            self.assertEqual(audit.stat().st_mode & 0o777, 0o700)
            self.assertEqual((audit / 'repo' / '.devcontainer' / 'devcontainer.json').read_text(), 'untrusted')
            self.assertTrue((audit / 'repo' / '.vscode').is_dir())
            self.assertFalse(list((audit / 'repo').glob('*.json')))
            self.assertEqual(len(list((audit / 'reports').glob('*.json'))), 4)

    def test_commands_and_revision(self):
        self.assertEqual(self.clone(), 0)
        calls = [json.loads(line) for line in self.calls.read_text().splitlines()]
        clone, = [call for call in calls if 'clone' in call]
        self.assertIn('core.hooksPath=/dev/null', clone)
        self.assertIn('--no-recurse-submodules', clone)
        self.assertFalse(any(arg.startswith('--depth') for arg in clone))
        scan, = [call for call in calls if 'scan' in call]
        for option in ('p/default', '--metrics=off', '--disable-version-check'):
            self.assertIn(option, scan)
        leaks = [call for call in calls if call[0] == 'gitleaks' and call[1] != 'version']
        self.assertEqual(len(leaks), 2)
        for call in leaks:
            self.assertIn('--redact', call)
            self.assertIn('--exit-code', call)
        self.assertIn('--log-opts=--all', leaks[1])
        summary = self.summary()
        self.assertEqual(summary['revision'], 'a' * 40)
        self.assertTrue(summary['complete'])
        self.assertEqual(set(summary['tool_versions']), {'git', 'semgrep', 'gitleaks'})
        self.assertTrue(summary['coverage_limitations'])

    def test_findings_are_success(self):
        self.assertEqual(self.clone(**dict.fromkeys(('semgrep', 'gitleaks-files', 'gitleaks-history'), 'findings')), 0)
        for scan in self.summary()['scans'].values():
            self.assertTrue(scan['complete'])
            self.assertEqual(scan['finding_count'], 1)

    @unittest.skipUnless(REAL_GIT, 'Git is required for the offline transport test')
    def test_real_git_clone_over_offline_ssh_transport(self):
        bare = self.base / 'empty-remote.git'
        subprocess.run([REAL_GIT, 'init', '--bare', str(bare)], check=True, capture_output=True)
        (self.bin / 'git').unlink()
        (self.bin / 'git').symlink_to(REAL_GIT)
        ssh = self.bin / 'offline-ssh'
        ssh.write_text('#!/bin/sh\nexec git-upload-pack ' + shlex.quote(str(bare)) + '\n')
        ssh.chmod(0o755)
        with patch.dict(os.environ, {'GIT_SSH_COMMAND': shlex.quote(str(ssh)), 'GIT_SSH_VARIANT': 'ssh'}):
            self.assertEqual(self.run_command('clone', 'ssh://git@offline.invalid/repo.git'), 1)
        summary = self.summary()
        self.assertEqual(summary['clone_exit_status'], 0)
        self.assertIsNone(summary['revision'])  # No commits were made for this fixture.
        self.assertEqual(len(summary['scans']), 3)
        audit, = self.root.iterdir()
        hooks = subprocess.check_output([REAL_GIT, '-C', str(audit / 'repo'),
                                         'config', 'core.hooksPath'], text=True)
        self.assertEqual(hooks.strip(), '/dev/null')
        self.assertFalse((audit / 'repo' / '.git' / 'shallow').exists())

    def test_clone_failure_retained(self):
        with patch.dict(os.environ, {'CLONE_FAIL': '1'}):
            self.assertEqual(self.clone(), 1)
        summary = self.summary()
        self.assertEqual(summary['clone_exit_status'], 128)
        self.assertFalse(summary['complete'])
        self.assertEqual(summary['scans'], {})

    def test_scanner_failure_does_not_skip_later_scans(self):
        self.assertEqual(self.clone(semgrep='failure', **{'gitleaks-files': 'failure'}), 1)
        scans = self.summary()['scans']
        self.assertEqual(len(scans), 3)
        self.assertFalse(scans['semgrep']['complete'])
        self.assertFalse(scans['gitleaks-files']['complete'])
        self.assertTrue(scans['gitleaks-history']['complete'])

    def test_report_errors_and_invalid_json_are_incomplete(self):
        for mode in ('errors', 'invalid', 'missing'):
            with self.subTest(mode=mode):
                self.assertEqual(self.clone(semgrep=mode), 1)
                self.assertFalse(self.summary()['scans']['semgrep']['complete'])
                self.assertEqual(self.run_command('reset', '--yes'), 0)

    def test_missing_scanner_still_runs_other_scans(self):
        original = workflow.run_logged
        with patch.object(workflow, 'run_logged') as run:
            def missing(command, *args):
                if command[0] == 'semgrep':
                    command = ['nonexistent-audit-scanner'] + command[1:]
                return original(command, *args)
            run.side_effect = missing
            self.assertEqual(self.clone(), 1)
        self.assertTrue(self.summary()['scans']['gitleaks-history']['complete'])

    def test_reset_noninteractive_requires_yes_and_cancellation(self):
        marker = self.root / 'keep'
        marker.touch()
        with patch('sys.stdin.isatty', return_value=False):
            self.assertEqual(self.run_command('reset'), 2)
        with patch('sys.stdin.isatty', return_value=True), patch('builtins.input', return_value='no'):
            self.assertEqual(self.run_command('reset'), 0)
        self.assertTrue(marker.exists())
        with patch('sys.stdin.isatty', return_value=True), patch('builtins.input', return_value='yes'):
            self.assertEqual(self.run_command('reset'), 0)
        self.assertFalse(marker.exists())

    def test_reset_hidden_entries_and_symlink_safety(self):
        outside = self.base / 'login-state'
        outside.mkdir()
        marker = outside / 'credential-placeholder'
        marker.write_text('synthetic')
        (self.root / '.hidden').mkdir()
        (self.root / '.hidden' / 'escape').symlink_to(outside, target_is_directory=True)
        (self.root / 'escape').symlink_to(outside, target_is_directory=True)
        (self.root / '.file').touch()
        (self.root / 'broken').symlink_to(self.base / 'missing')
        self.assertEqual(self.run_command('reset', '--yes'), 0)
        self.assertEqual(list(self.root.iterdir()), [])
        self.assertEqual(marker.read_text(), 'synthetic')
        self.assertTrue(self.lock.exists())

    def test_clone_and_reset_share_nonblocking_lock(self):
        with self.lock.open('r+') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual(self.clone(), 1)
            self.assertEqual(self.run_command('reset', '--yes'), 1)
        self.assertEqual(list(self.root.iterdir()), [])
        self.assertEqual(self.clone(), 0)

    def test_refuses_symlink_audit_root(self):
        self.root.rmdir()
        self.root.symlink_to(self.base, target_is_directory=True)
        self.assertEqual(self.run_command('reset', '--yes'), 1)


if __name__ == '__main__':
    unittest.main()
