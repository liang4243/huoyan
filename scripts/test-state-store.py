"""Offline migration and canonical path tests; no browser or credentials."""
import json
import runpy
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from python.huoyan_browser import atomic_json, load_json
from python.state_store import state_directory

migrate = runpy.run_path(str(ROOT/'scripts/migrate-state-store.py'))['migrate']


class StateTests(unittest.TestCase):
    def test_fresh_install_and_existing_legacy_migration_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with patch('python.state_store.ROOT',root):
                self.assertEqual(state_directory({'out':'data'}), root/'data')
                atomic_json(root/'output/playwright/product-tabs.json',{'products':{}})
                with self.assertRaisesRegex(RuntimeError,'STATE_MIGRATION_REQUIRED'):
                    state_directory({'out':'output/playwright'})
                atomic_json(root/'data/state-migration-v1.json',{'version':1})
                self.assertEqual(state_directory({'out':'output/playwright'}),root/'data')

    def test_known_aliases_share_canonical_store_but_tests_stay_isolated(self):
        self.assertEqual(state_directory({'out':str(ROOT/'data')}), state_directory({'out':str(ROOT/'output/playwright')}))
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(state_directory({'out':tmp}), Path(tmp).resolve())
            self.assertEqual(state_directory({'out':str(ROOT/'data'),'stateDir':tmp}), Path(tmp).resolve())

    def test_migration_preserves_outbox_and_grants_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            primary, legacy = Path(tmp)/'primary', Path(tmp)/'legacy'
            for root, key in [(primary,'a'),(legacy,'b')]:
                atomic_json(root/'merchant-chat/state.json', {'endpoint':'local','outbox':{key:{'status':'sent_unconfirmed','text':key}}})
                atomic_json(root/'merchant-chat/authorizations.json', {'endpoint':'local','grants':{key:{'used':[key]}}})
                atomic_json(root/'shop-visits.json', {'endpoint':'local','visits':{key:{'sourceTabId':key}},'latest':{key:key}})
            r=migrate(primary,legacy)
            self.assertEqual(set(load_json(primary/'merchant-chat/state.json',{})['outbox']),{'a','b'})
            self.assertEqual(set(load_json(primary/'merchant-chat/authorizations.json',{})['grants']),{'a','b'})
            self.assertEqual(set(load_json(primary/'shop-visits.json',{})['visits']),{'a','b'})
            self.assertTrue((Path(r['backup'])/'legacy/merchant-chat/state.json').exists())
            self.assertTrue(migrate(primary,legacy)['alreadyMigrated'])
            self.assertEqual(set(load_json(legacy/'merchant-chat/state.json',{})['outbox']),{'b'})

    def test_conflicting_send_intent_aborts_before_any_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            primary, legacy=Path(tmp)/'primary',Path(tmp)/'legacy'
            atomic_json(primary/'merchant-chat/state.json',{'endpoint':'local','outbox':{'same':{'text':'a'}}})
            atomic_json(legacy/'merchant-chat/state.json',{'endpoint':'local','outbox':{'same':{'text':'b'}}})
            before=(primary/'merchant-chat/state.json').read_bytes()
            with self.assertRaisesRegex(RuntimeError,'Conflicting immutable record'):
                migrate(primary,legacy)
            self.assertEqual((primary/'merchant-chat/state.json').read_bytes(),before)
            self.assertFalse((primary/'state-migration-v1.json').exists())

    def test_conflicting_inbox_switch_journal_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            primary,legacy = Path(tmp)/'primary',Path(tmp)/'legacy'
            for folder,target in ((primary,'a'),(legacy,'b')):
                atomic_json(folder/'merchant-chat/state.json',{'endpoint':'local','inboxSwitches':{'same':{'entryKey':target,'actionAttempted':True}}})
            before=(primary/'merchant-chat/state.json').read_bytes()
            with self.assertRaisesRegex(RuntimeError,'Conflicting immutable record'):
                migrate(primary,legacy)
            self.assertEqual((primary/'merchant-chat/state.json').read_bytes(),before)

    def test_favorites_migrate_and_conflicting_account_action_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            primary,legacy=Path(tmp)/'primary',Path(tmp)/'legacy'
            for root,key in [(primary,'a'),(legacy,'b')]:
                atomic_json(root/'local-favorites.json',{'favorites':{key:{'title':key}}})
                atomic_json(root/'favorite-actions.json',{'endpoint':'local','attempts':{key:{'confirmed':False}}})
            migrate(primary,legacy)
            self.assertEqual(set(load_json(primary/'local-favorites.json',{})['favorites']),{'a','b'})
            self.assertEqual(set(load_json(primary/'favorite-actions.json',{})['attempts']),{'a','b'})
        with tempfile.TemporaryDirectory() as tmp:
            primary,legacy=Path(tmp)/'primary',Path(tmp)/'legacy'
            atomic_json(primary/'favorite-actions.json',{'attempts':{'same':{'selected':True}}})
            atomic_json(legacy/'favorite-actions.json',{'attempts':{'same':{'selected':False}}})
            before=(primary/'favorite-actions.json').read_bytes()
            with self.assertRaisesRegex(RuntimeError,'Conflicting immutable record'):migrate(primary,legacy)
            self.assertEqual((primary/'favorite-actions.json').read_bytes(),before)


if __name__ == '__main__':unittest.main(verbosity=2)
