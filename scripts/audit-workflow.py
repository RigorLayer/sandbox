"""Container-only audit commands. Paths are fixed, never supplied by the target."""
import contextlib
import datetime
import fcntl
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit

AUDIT_ROOT = Path('/audit')
LOCK_PATH = Path('/opt/audit/operation.lock')
FINDINGS_EXIT = 10
LIMITATIONS = [
    'Semgrep p/default requires registry access; downloaded rules are not pinned.',
    'Scanner defaults, size limits, ignored files, inline suppressions, and target-controlled configuration can exclude findings.',
    'Submodules and Git LFS contents are not fetched; dependencies are not installed.',
    'Static checks do not execute target code or establish that a repository is secure.',
]


def valid_url(value):
    if not value or any(c.isspace() or ord(c) < 32 for c in value):
        return False
    if value.startswith(('https://', 'ssh://')):
        try:
            parsed = urlsplit(value)
            return bool(parsed.hostname and not parsed.hostname.startswith('-')
                        and parsed.path not in ('', '/') and not parsed.query
                        and not parsed.fragment and parsed.password is None
                        and (parsed.port is None or parsed.port > 0))
        except ValueError:
            return False
    return bool(re.fullmatch(r'(?:[\w.-]+@)?[a-zA-Z0-9][\w.-]*:[^/\s:][^\s]*', value))


@contextlib.contextmanager
def operation_lock():
    # Provisioned by the image in a root-owned directory, outside reset's scope.
    with LOCK_PATH.open('r+') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError('Another clone or reset is running; try again later.') from exc
        yield


def run_logged(command, cwd, log, env):
    with log.open('w') as output:
        try:
            return subprocess.run(command, cwd=cwd, env=env, stdout=output,
                                  stderr=subprocess.STDOUT, check=False).returncode
        except OSError as exc:
            output.write(f'{exc}\n')
            return 127


def report_result(name, path, status):
    problems = []
    count = None
    if status not in ((0,) if name == 'semgrep' else (0, FINDINGS_EXIT)):
        problems.append(f'Scanner exited with status {status}.')
    try:
        data = json.loads(path.read_text())
        if name == 'semgrep':
            if not isinstance(data, dict) or not isinstance(data.get('results'), list) or not isinstance(data.get('errors'), list):
                raise ValueError('Expected Semgrep results and errors arrays')
            count = len(data['results'])
            if data['errors']:
                problems.append(f"Semgrep reported {len(data['errors'])} scanning error(s).")
        else:
            if not isinstance(data, list):
                raise ValueError('Expected a Gitleaks findings array')
            count = len(data)
            if (status == FINDINGS_EXIT) != bool(count):
                problems.append('Gitleaks findings and exit status disagree.')
    except (OSError, ValueError) as exc:
        problems.append(f'Missing or invalid JSON report: {exc}')
    return {'exit_status': status, 'finding_count': count,
            'complete': not problems, 'incomplete_reasons': problems,
            'report': path.name, 'log': f'{name}.log'}


def clone(url):
    audit = Path(tempfile.mkdtemp(prefix='audit-' + datetime.datetime.now(
        datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ-'), dir=AUDIT_ROOT))
    repo = audit / 'repo'
    reports = audit / 'reports'
    reports.mkdir(mode=0o700)
    print(f'Repository: {repo}\nReports: {reports}\nEnter repository: cd {shlex.quote(str(repo))}', flush=True)
    env = dict(os.environ, SEMGREP_SEND_METRICS='off', SEMGREP_ENABLE_VERSION_CHECK='0',
               GIT_LFS_SKIP_SMUDGE='1', GIT_TERMINAL_PROMPT='0')
    summary = {'revision': None, 'complete': False, 'clone_exit_status': None,
               'tool_versions': {}, 'scans': {}, 'incomplete_reasons': ['Audit interrupted before completion.'],
               'coverage_limitations': LIMITATIONS}
    summary_path = reports / 'summary.json'

    def save():
        summary_path.write_text(json.dumps(summary, indent=2) + '\n')

    save()
    for name, command in [('git', ['git', '--version']), ('semgrep', ['semgrep', '--version']),
                          ('gitleaks', ['gitleaks', 'version'])]:
        log = reports / f'{name}-version.log'
        status = run_logged(command, AUDIT_ROOT, log, env)
        summary['tool_versions'][name] = {'output': log.read_text().strip(), 'exit_status': status}
    status = run_logged(['git', '-c', 'core.hooksPath=/dev/null', '-c', 'protocol.file.allow=never',
                         'clone', '--no-recurse-submodules', '--config', 'core.hooksPath=/dev/null',
                         '--', url, str(repo)], AUDIT_ROOT, reports / 'clone.log', env)
    summary['clone_exit_status'] = status
    summary['incomplete_reasons'] = []
    if status:
        summary['incomplete_reasons'].append('Clone failed; scanners were not run. See clone.log.')
        save()
        return 1
    revision_log = reports / 'revision.log'
    revision_status = run_logged(['git', 'rev-parse', '--verify', 'HEAD'], repo, revision_log, env)
    if revision_status == 0:
        summary['revision'] = revision_log.read_text().strip()
    else:
        summary['incomplete_reasons'].append('Could not determine HEAD revision; repository may be empty.')
    commands = {
        'semgrep': ['semgrep', 'scan', '--config', 'p/default', '--metrics=off',
                    '--disable-version-check', '--json', '--output', str(reports / 'semgrep.json'), '.'],
        'gitleaks-files': ['gitleaks', 'dir'],
        'gitleaks-history': ['gitleaks', 'git'],
    }
    for name, command in commands.items():
        report = reports / f'{name}.json'
        if name != 'semgrep':
            command += ['--redact', '--exit-code', str(FINDINGS_EXIT), '--report-format', 'json',
                        '--report-path', str(report)]
            if name == 'gitleaks-history':
                command += ['--log-opts=--all']
            command += ['.']
        status = run_logged(command, repo, reports / f'{name}.log', env)
        result = report_result(name, report, status)
        result['command'] = command
        summary['scans'][name] = result
        save()
    summary['complete'] = (not summary['incomplete_reasons']
                           and all(scan['complete'] for scan in summary['scans'].values()))
    save()
    print(f"Scans {'completed' if summary['complete'] else 'incomplete'}: {summary_path}")
    return 0 if summary['complete'] else 1


def reset(confirmed):
    if not confirmed:
        if not sys.stdin.isatty():
            print('Noninteractive reset requires --yes.', file=sys.stderr)
            return 2
        try:
            answer = input('Delete every clone and report in /audit? Type yes: ')
        except EOFError:
            answer = ''
        if answer != 'yes':
            print('Reset cancelled.')
            return 0
    # fd-based rmtree prevents symlink substitution from escaping the directory.
    if not shutil.rmtree.avoids_symlink_attacks:
        raise RuntimeError('This platform lacks safe directory deletion.')
    for entry in AUDIT_ROOT.iterdir():
        if entry.is_symlink() or not entry.is_dir():
            entry.unlink()
        else:
            shutil.rmtree(entry)
    print('Audit data cleared. Tools and agent login state preserved.')
    return 0


def main(args=None):
    args = sys.argv[1:] if args is None else args
    if args == ['clone', '--help']:
        print('Usage: clone.sh <https-or-ssh-git-url>')
        return 0
    if args == ['reset', '--help']:
        print('Usage: reset.sh [--yes]')
        return 0
    if not (len(args) == 2 and args[0] == 'clone' and valid_url(args[1])) and args not in (['reset'], ['reset', '--yes']):
        print('Usage: clone.sh <https-or-ssh-git-url> | reset.sh [--yes]', file=sys.stderr)
        return 2
    try:
        if AUDIT_ROOT.is_symlink() or not AUDIT_ROOT.is_dir():
            raise RuntimeError('/audit must be a real directory mounted by Docker.')
        with operation_lock():
            old_umask = os.umask(0o077)
            try:
                return clone(args[1]) if args[0] == 'clone' else reset(len(args) == 2)
            finally:
                os.umask(old_umask)
    except (OSError, RuntimeError) as exc:
        print(f'Audit failed: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
