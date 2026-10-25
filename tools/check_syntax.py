"""Compile project Python sources in memory without generating bytecode files."""
from pathlib import Path

root = Path(__file__).resolve().parents[1]
paths = [root / 'main.py', root / 'Pi_Receiver.py']
paths += sorted((root / 'tests').glob('*.py'))
paths += sorted((root / 'tools').glob('*.py'))
for path in paths:
    compile(path.read_text(encoding='utf-8'), str(path.relative_to(root)), 'exec')
print(f'Syntax passed: {len(paths)} Python files (in-memory compilation).')
