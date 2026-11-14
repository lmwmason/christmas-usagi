"""Known contaminated recordings must not re-enter through renamed duplicates."""
from pathlib import Path
import json

POLICY = Path(__file__).resolve().parents[1] / 'assets/sources/policy.json'


def allowed_source(item):
    rejected = json.loads(POLICY.read_text())['blocked']
    return not any(item.get('id') == row['id'] or
                   (item.get('sha256') and item['sha256'] == row['sha256'])
                   for row in rejected)
