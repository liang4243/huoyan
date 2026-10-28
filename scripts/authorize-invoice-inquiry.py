"""Local exact-draft authorization. Run only after actual user consent.

This command cannot authenticate a human and is not a shell-access security boundary.
It is intentionally NOT registered as an MCP tool or inferred from merchant content.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from python.huoyan_browser import Controller, OutputLock
from python.merchant_chat import authorize_drafts

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--draft', action='append', required=True, help='Exact draft ID approved by user; repeat at most three times.')
parser.add_argument('--user-reference', required=True, help='Reference to explicit user consent for the displayed exact draft(s).')
parser.add_argument('--out', default='data')
parser.add_argument('--cdp', default='http://127.0.0.1:9222')
parser.add_argument('--ttl', type=int, default=3600)
parser.add_argument('--wording-reviewed', action='store_true', help='Operator checked model wording against original intent and facts; not a substitute for user consent.')
args = parser.parse_args()
c = Controller({'out': args.out, 'cdp': args.cdp})
with OutputLock(c.out):
    print(json.dumps(authorize_drafts(c, args.draft, args.user_reference, args.ttl, wording_reviewed=args.wording_reviewed), ensure_ascii=False))
