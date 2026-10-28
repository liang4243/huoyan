"""Offline, locked, backed-up merge of the two historical dedicated browser stores."""
import copy
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from python.huoyan_browser import OutputLock, atomic_json, load_json


def merge(a, b, strict=False):
    if isinstance(a, dict) and isinstance(b, dict):
        result = copy.deepcopy(a)
        for key, value in b.items():
            if key not in result:
                result[key] = copy.deepcopy(value)
            elif result[key] != value:
                if strict:
                    raise RuntimeError('Conflicting immutable record: ' + key)
                result[key] = copy.deepcopy(value)
        return result
    return copy.deepcopy(b)


def migrate(primary, legacy):
    marker = primary / 'state-migration-v1.json'
    names = ['product-tabs.json', 'shop-tabs.json', 'tab-budget.json', 'research-candidates.json',
             'image-research.json', 'detail-panels.json', 'merchant-chat/state.json',
             'merchant-chat/authorizations.json', 'focus-state.json', 'shopping-controls.json',
             'page-controls.json', 'research-progress.json', 'shop-visits.json', 'home-recovery-state.json',
             'local-favorites.json', 'favorite-actions.json', 'favorite-controls.json']
    previous = load_json(marker, {})
    if previous:
        names = [name for name in names if name not in previous['files'] and any((p/name).exists() for p in (primary,legacy))]
        if not names:
            return {'alreadyMigrated': True, 'stateDir': str(primary)}
    combined = {}
    for name in names:
        files = sorted([p / name for p in (primary, legacy) if (p / name).exists()], key=lambda p: p.stat().st_mtime)
        if not files:
            continue
        result = {}
        for file in files:
            value = load_json(file, {})
            if result.get('endpoint') and value.get('endpoint') and result['endpoint'] != value['endpoint']:
                raise RuntimeError('Endpoint mismatch; no migration performed.')
            for key, item in value.items():
                if key not in result:
                    result[key] = copy.deepcopy(item)
                elif isinstance(item, dict) and key not in ('state', 'lastCleanup'):
                    # Conversation evidence, authorizations and send intents must never
                    # silently overwrite a different record with the same identifier.
                    strict = (name.startswith('merchant-chat/') and key in ('conversations', 'inquiries', 'drafts', 'outbox', 'grants', 'inboxSwitches') or
                              name=='favorite-actions.json' and key=='attempts')
                    result[key] = merge(result[key], item, strict)
                else:
                    result[key] = copy.deepcopy(item)
        combined[name] = result
    backup = primary / 'state-backups' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    for label, folder in [('data', primary), ('legacy', legacy)]:
        for name in names:
            if (folder / name).exists():
                dest = backup / label / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(folder / name, dest)
    for name, value in combined.items():
        atomic_json(primary / name, value)
    result = {'stateDir': str(primary), 'backup': str(backup), 'files': list(dict.fromkeys(previous.get('files', []) + list(combined))), 'version': 1}
    if previous:
        result['previousMigration'] = previous
    atomic_json(marker, result)
    return result


if __name__ == '__main__':
    primary, legacy = ROOT / 'data', ROOT / 'output' / 'playwright'
    with OutputLock(primary), OutputLock(legacy):
        print(json.dumps(migrate(primary, legacy), ensure_ascii=False))
