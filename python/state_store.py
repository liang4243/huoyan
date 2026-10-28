"""One persistent store for the dedicated browser; custom test stores stay isolated."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def state_directory(args):
    if args.get('stateDir'):
        return Path(args['stateDir']).resolve()
    value = args.get('out', 'data')
    requested = (ROOT / value).resolve() if str(value).replace('\\', '/').rstrip('/') in ('data', 'output/playwright') else Path(value).resolve()
    if requested in (ROOT / 'data', ROOT / 'output' / 'playwright'):
        legacy = ROOT / 'output' / 'playwright'
        has_legacy = any((legacy / name).exists() for name in ('product-tabs.json', 'merchant-chat/state.json', 'shop-tabs.json', 'research-candidates.json', 'tab-budget.json','local-favorites.json','favorite-actions.json'))
        if has_legacy and not (ROOT / 'data' / 'state-migration-v1.json').exists():
            raise RuntimeError('STATE_MIGRATION_REQUIRED: run scripts/migrate-state-store.py before browser operations.')
        return ROOT / 'data'
    return requested
