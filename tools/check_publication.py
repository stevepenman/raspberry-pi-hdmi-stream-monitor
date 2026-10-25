"""Conservative publication hygiene check, not a proof of confidentiality or rights.

Checks Git's index plus nonignored untracked files; ignored local files are excluded.
Flags categories and paths only, never prints a matched secret value.
"""
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
ALLOWED = {
    '.env.example', '.gitattributes', '.gitignore', 'README.md', 'requirements.txt',
    'THIRD_PARTY_NOTICES.md', 'main.py', 'Pi_Receiver.py',
    '.github/workflows/ci.yml', 'tests/test_streamer.py',
    'tools/check_publication.py', 'tools/check_syntax.py', 'tools/smoke_demo.py',
    'docs/demo.png', 'docs/HARDWARE.md', 'docs/PORTFOLIO.md',
    'docs/GITHUB_UPLOAD.md', 'docs/PUBLICATION_REVIEW.md', 'docs/VERIFICATION.md',
    'static/vendor/hls.min.js', 'static/vendor/HLSJS_LICENSE.txt',
    'static/vendor/APACHE-2.0.txt',
}
PATTERNS = {
    'private network address': r'(?<![\w.])(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})(?![\w.])',
    'private key marker': r'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----',
    'certificate marker': r'-----BEGIN ' r'CERTIFICATE-----',
    'email address': r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b',
    'credential in URL': r'https?://[^\s/]+:[^\s/]+@',
    'common access token': r'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|AKIA[A-Z0-9]{16})\b',
    'bcrypt account hash': r'\$2[aby]\$\d{2}\$[./A-Za-z0-9]{53}',
    'personal Windows path': r'[A-Za-z]:[\\/]Users[\\/][^\s\\/]+',
    'personal Linux path': r'/' r'home/(?!example(?:/|\b))[^\s/]+',
}


def main():
    try:
        top = subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', '--show-toplevel'],
                                      text=True, stderr=subprocess.DEVNULL).strip()
        if Path(top).resolve() != ROOT:
            raise ValueError('Not the portfolio repository')
        raw = subprocess.check_output(['git', '-C', str(ROOT), 'ls-files', '-z', '--cached',
                                       '--others', '--exclude-standard'])
    except (OSError, subprocess.CalledProcessError, ValueError):
        print('Run this check inside the initialized portfolio Git repository.', file=sys.stderr)
        return 2
    paths = sorted(set(raw.decode('utf-8').rstrip('\0').split('\0')) - {''})
    failures = []
    for name in sorted(ALLOWED - set(paths)):
        failures.append((name, 'missing reviewed publication file'))
    for name in paths:
        if name not in ALLOWED:
            failures.append((name, 'file outside reviewed publication allowlist'))
            continue
        path = ROOT / name
        if path.is_symlink() or not path.is_file():
            failures.append((name, 'missing file or symbolic link'))
            continue
        if name == 'docs/demo.png':
            if not path.read_bytes().startswith(b'\x89PNG\r\n\x1a\n'):
                failures.append((name, 'invalid demonstration image'))
            continue
        content = path.read_text(encoding='utf-8')
        for category, pattern in PATTERNS.items():
            if re.search(pattern, content):
                failures.append((name, category))
    for name, category in failures:
        print(f'REVIEW: {name}: {category}')
    if failures:
        return 1
    print(f'Publication hygiene passed: {len(paths)} candidate files; manual review still required.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
