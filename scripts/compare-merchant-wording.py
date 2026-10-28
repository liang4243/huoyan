"""Prepare 30 anonymous cases; --live generates previews only, never sends chat."""
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from python.merchant_wording import build_spec, rewrite, DEFAULT_MODEL, COMPARE_MODEL, configured_api_key
from python.huoyan_browser import atomic_json, stamp


def cases():
    seeds = [
        ('shop-first', 'invoice_shop', None, [], [], '你好，你们家能开票吗？金额按实付开吗？'),
        ('shop-capability', 'invoice_shop', ['can_invoice'], [], [], '你好，你们家能开票吗？'),
        ('shop-amount', 'invoice_shop', ['paid_amount'], ['可以开票'], ['can_invoice'], '那金额按实付开吗？'),
        ('product-first', 'invoice_product', None, [], [], '你好，这款能开票吗？开票一共多少钱？'),
        ('product-total', 'invoice_product', ['total_price'], ['可以开票'], ['can_invoice'], '那开票一共多少钱？'),
        ('tax-first', 'tax_price', None, ['可以开票'], [], '这个价含税吗？开票还要加钱吗？'),
        ('tax-included', 'tax_price', ['tax_included'], ['开票不用另外加钱'], ['extra_tax_cost'], '这个价含税吗？'),
        ('tax-extra', 'tax_price', ['extra_tax_cost'], ['可以开票'], [], '开票还要另外加钱吗？'),
        ('shipping-total', 'total_shipping', None, ['开票按实付'], [], '算上运费一共多少钱？'),
        ('invoice-type', 'invoice_type', None, ['可以开票'], [], '可以开哪种发票？'),
    ]
    result = []
    for name, intent, ids, messages, answered, reference in seeds:
        for variant, prefix in enumerate(([], ['你好'], ['稍等，刚看到消息'])):
            result.append({'caseId': f'{name}-{variant + 1}', 'spec': build_spec(intent, ids),
                           'recentMessages': [{'direction': 'incoming', 'text': text} for text in prefix + messages],
                           'answeredQuestionIds': answered, 'referenceExample': reference})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', help='Make paid text-only Ark preview calls, maximum 60 by default. No browser or merchant contact.')
    parser.add_argument('--models', nargs='+', default=[DEFAULT_MODEL, COMPARE_MODEL])
    parser.add_argument('--limit', type=int, default=30)
    parser.add_argument('--out', default=str(ROOT / 'output/playwright/wording-comparison.json'))
    args = parser.parse_args()
    if not 1 <= args.limit <= 30 or not 1 <= len(args.models) <= 3:
        parser.error('limit must be 1..30 and models must contain 1..3 IDs.')
    configured = bool(configured_api_key())
    report = {'createdAt': stamp(), 'liveRequested': args.live, 'apiKeyConfigured': configured,
              'status': 'running' if args.live and configured else 'missing_api_key' if args.live else 'prepared_not_run',
              'models': args.models, 'cases': [], 'sent': False, 'browserConnected': False,
              'note': 'Reference examples are hand-written targets, not GPT or Doubao test outputs. No model winner without output review.'}
    for item in cases()[:args.limit]:
        row = {**item, 'results': [], 'humanRatings': {'naturalness': None, 'meaningPreserved': None, 'preferredModel': None}}
        if args.live and configured:
            for model in args.models:
                result = rewrite(item['spec'], item['recentMessages'], mode='doubao', model=model, answered=item['answeredQuestionIds'])
                row['results'].append(result)
                # Stop account/config faults; do not repeat 60 doomed API requests.
                if result.get('reason') in ('provider_http_401', 'provider_http_403', 'provider_http_404', 'provider_http_429', 'provider_unavailable'):
                    report['status'] = 'stopped_provider_error'
                    break
        report['cases'].append(row)
        atomic_json(Path(args.out), report)
        if report['status'] == 'stopped_provider_error':
            break
    if report['status'] == 'running':
        report['status'] = 'generated_needs_review'
    atomic_json(Path(args.out), report)
    print(json.dumps({'status': report['status'], 'caseCount': len(report['cases']), 'out': str(Path(args.out).resolve()),
                      'actualModelCalls': sum(len(row['results']) for row in report['cases']), 'sent': False}, ensure_ascii=False))
    return 2 if report['status'] in ('missing_api_key', 'stopped_provider_error') else 0


if __name__ == '__main__':
    sys.exit(main())
