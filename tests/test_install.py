"""Exercise installer preflight/template with fake OS accounts, without installing."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
GIT_BASH = Path('C:/Program Files/Git/bin/bash.exe')
BASH = str(GIT_BASH) if GIT_BASH.exists() else shutil.which('bash')


@unittest.skipUnless(BASH, 'Bash required')
class InstallTests(unittest.TestCase):
    def run_preflight(self, sudo_user='', args=(), uid='1001'):
        source = (ROOT / 'scripts/install_pi.sh').read_text(encoding='utf-8')
        preflight = source.split('apt-get update', 1)[0]
        # Keep account selection verbatim but supply deterministic OS identity.
        preflight = preflight.replace(
            'SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"',
            'SOURCE_DIR="$PWD"')
        mocks = '''
id() {
  if [[ "$1" == -u ]]; then echo 0; else echo operators; fi
}
getent() {
  if [[ "$1" == passwd && "$2" == alice ]]; then
    echo "alice:x:$TEST_UID:123:Alice:/srv/users/alice:/bin/bash"
  elif [[ "$1" == group && "$2" == video ]]; then
    echo 'video:x:44:'
  else return 2; fi
}
'''
        # Run the real rendering block too; redirect its output into a temp file.
        render = source.split('DEVICE_GROUPS=""', 1)[1].split('chmod 0644', 1)[0]
        render = 'DEVICE_GROUPS=""' + render
        render = render.replace('/etc/systemd/system/autocar.service', '"$TEST_UNIT"')
        with tempfile.TemporaryDirectory() as folder:
            unit = Path(folder) / 'autocar.service'
            env = dict(os.environ, SUDO_USER=sudo_user, TEST_UID=uid,
                       TEST_UNIT=unit.as_posix())
            result = subprocess.run([BASH, '-c', mocks + preflight + render,
                                     'installer', *args], cwd=ROOT, env=env,
                                    capture_output=True, text=True, encoding='utf-8')
            return result, unit.read_text() if unit.exists() else ''

    def test_sudo_account_custom_home_and_distinct_group(self):
        result, unit = self.run_preflight('alice')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('/srv/users/alice/Videos/autocar', result.stdout)
        self.assertIn('User=alice\nGroup=operators\nSupplementaryGroups=video\n', unit)
        self.assertNotIn('@AUTOCAR_', unit)

    def test_explicit_account_from_root(self):
        result, unit = self.run_preflight('root', ('alice',))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('User=alice', unit)

    def test_invalid_accounts_fail_before_installation(self):
        for user, args, uid in [('', (), '1001'), ('root', (), '1001'),
                                ('missing', (), '1001'), ('alice', (), '0'),
                                ('alice', ('alice', 'extra'), '1001')]:
            with self.subTest(user=user, args=args, uid=uid):
                result, unit = self.run_preflight(user, args, uid)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(unit, '')


if __name__ == '__main__':
    unittest.main()
