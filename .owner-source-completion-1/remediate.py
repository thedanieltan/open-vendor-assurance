from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from tools.openva.catalog_source_completion import EXPECTED_GROUPS, build_report, vendor_completion
from tools.openva.source_discovery import unavailable_record

ROOT = Path('.')
REVIEWED_AT = '2026-07-14T00:00:00Z'
NEXT_REVIEW = '2026-10-12'
TODAY = date(2026, 7, 14)

REMOVE_IDS = {
    '1password-compliance-page', 'adp-compliance-page', 'aiven-compliance-page',
    'aiven-trust-center', 'alloy-compliance-page', 'basecamp-subprocessors-list',
    'bigcommerce-security-page', 'bitdefender-certification-reference',
    'bitdefender-compliance-page', 'braze-compliance-page', 'braze-trust-center',
    'campaign-monitor-certification-reference', 'campaign-monitor-compliance-page',
    'circleci-certification-reference', 'coda-compliance-page', 'coda-dpa',
    'commercetools-security-page', 'complyadvantage-trust-center',
    'confluent-certification-reference', 'customer-io-compliance-page',
    'darwinbox-compliance-page', 'doodle-certification-reference',
    'emarsys-trust-center', 'fiserv-trust-center', 'gitlab-compliance-page',
    'greenhouse-compliance-page', 'greythr-compliance-page', 'klarna-trust-center',
    'linear-certification-reference', 'onetrust-compliance-page',
    'pandadoc-trust-center', 'pipedrive-security-page', 'scaleway-compliance-page',
    'second-front-systems-certification-reference',
    'second-front-systems-compliance-page', 'starburst-certification-reference',
    'strapi-certification-reference', 'trulioo-certification-reference',
    'typeform-compliance-page', 'vertafore-certification-reference',
    'wiz-certification-reference', 'worldpay-compliance-page', 'worldpay-dpa',
    'worldpay-security-page',
}

CANONICALIZE = {
    'bigcommerce-trust-center': 'https://security.bigcommerce.com/',
    'campaign-monitor-trust-center': 'https://trust.campaignmonitor.meetmarigold.com/',
    'railway-trust-center': 'https://trust.railway.com/',
    'vtex-compliance-page': 'https://compliance.vtex.com/',
}

COVERAGE_CLAIMS = {
    'alloy-trust-center': ['compliance_page'],
    'bigcommerce-trust-center': ['security_page'],
    'campaign-monitor-trust-center': ['compliance_page', 'certification_reference'],
    'linear-trust-center': ['compliance_page'],
    'pipedrive-trust-center': ['security_page'],
}

RECLASSIFY = {
    'bigcommerce-compliance-page': ('bigcommerce-certification-reference', 'certification_reference'),
    'checkout-com-compliance-page': ('checkout-com-certification-reference', 'certification_reference'),
    'redox-compliance-page': ('redox-certification-reference', 'certification_reference'),
}

RETAINED_EXCEPTIONS = {
    'adyen-security-page': 'Exact official security path returned HTTP 200 with strong security semantics; sparse title only.',
    'complyadvantage-dpa': 'Exact official DPA path returned HTTP 200 with strong DPA semantics.',
    'fly-io-certification-reference': 'Official vendor article specifically documents Fly.io SOC 2 status.',
    'gitlab-certification-reference': 'Official GitLab security article directly documents GitLab certification and audit posture.',
    'marqeta-certification-reference': 'SafeBase item-specific certifications URL despite a shared client-rendered shell.',
    'marqeta-subprocessors-list': 'SafeBase item-specific subprocessors URL despite a shared client-rendered shell.',
    'neon-dpa': 'Official product-specific legal schedule contains DPA terms at the anchored section.',
    'netlify-certification-reference': 'Official vendor announcement directly documents ISO 27001 certification.',
    'shift-technology-certification-reference': 'Official vendor announcement directly documents SOC 2 Type II certification.',
    'sumsub-certification-reference': 'Official vendor announcement directly documents SOC 2 reporting.',
}


def load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict):
        raise ValueError(f'{path}: expected mapping')
    return data


def write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding='utf-8')


def main() -> int:
    output_dir = ROOT / '.owner-source-completion-1/results'
    marker = output_dir / 'remediation-summary.json'
    if marker.exists() and not (ROOT / 'data/vendors/adp/sources/adp-compliance-page.yaml').exists():
        print('Remediation already applied; skipping mutation.')
        return 0

    audit = json.loads((output_dir / 'adversarial-audit.json').read_text(encoding='utf-8'))
    audit_by_id = {str(row.get('source_id')): row for row in audit.get('sources') or [] if row.get('source_id')}
    removed_rows: list[dict[str, Any]] = []
    missing_requested: list[str] = []

    def bundle_paths(vendor_id: str, source_id: str) -> list[Path]:
        base = ROOT / 'data/vendors' / vendor_id
        return [
            base / 'sources' / f'{source_id}.yaml',
            base / 'artifacts' / f'{source_id}.yaml',
            base / 'changes' / f'candidate-promotion-{source_id}.yaml',
        ]

    for source_id in sorted(REMOVE_IDS):
        row = audit_by_id.get(source_id)
        if row is None:
            missing_requested.append(source_id)
            continue
        vendor_id = str(row['vendor_id'])
        found = False
        for path in bundle_paths(vendor_id, source_id):
            if path.exists():
                path.unlink()
                found = True
        removed_rows.append({
            'vendor_id': vendor_id,
            'source_id': source_id,
            'source_type': row.get('source_type'),
            'source_url': row.get('source_url'),
            'final_url': row.get('final_url'),
            'verification_status': row.get('verification_status'),
            'removed_files_found': found,
        })

    renamed: list[dict[str, Any]] = []
    for old_id, (new_id, new_type) in sorted(RECLASSIFY.items()):
        row = audit_by_id.get(old_id)
        if row is None:
            missing_requested.append(old_id)
            continue
        vendor_id = str(row['vendor_id'])
        base = ROOT / 'data/vendors' / vendor_id
        old_source = base / 'sources' / f'{old_id}.yaml'
        old_artifact = base / 'artifacts' / f'{old_id}.yaml'
        old_change = base / 'changes' / f'candidate-promotion-{old_id}.yaml'
        source = load_yaml(old_source)
        artifact = load_yaml(old_artifact)
        change = load_yaml(old_change)
        source['source_id'] = new_id
        source['source_type'] = new_type
        source['title_native'] = 'Certification Reference'
        if 'title_en' in source:
            source['title_en'] = 'Certification Reference'
        artifact['artifact_id'] = new_id
        artifact['source_id'] = new_id
        artifact['artifact_type'] = new_type
        change['change_id'] = f'candidate-promotion-{new_id}'
        change['source_id'] = new_id
        change['artifact_id'] = new_id
        change['summary'] = 'Owner-led source completion promoted a source-type-correct official certification reference after page-purpose review.'
        write_yaml(base / 'sources' / f'{new_id}.yaml', source)
        write_yaml(base / 'artifacts' / f'{new_id}.yaml', artifact)
        write_yaml(base / 'changes' / f'candidate-promotion-{new_id}.yaml', change)
        old_source.unlink()
        old_artifact.unlink()
        old_change.unlink()
        (base / 'unavailable_sources' / f'{vendor_id}-{new_type}.yaml').unlink(missing_ok=True)
        renamed.append({'vendor_id': vendor_id, 'old_source_id': old_id, 'new_source_id': new_id, 'source_type': new_type})

    canonicalized: list[dict[str, Any]] = []
    for source_id, url in sorted(CANONICALIZE.items()):
        row = audit_by_id.get(source_id)
        if row is None:
            missing_requested.append(source_id)
            continue
        vendor_id = str(row['vendor_id'])
        base = ROOT / 'data/vendors' / vendor_id
        source_path = base / 'sources' / f'{source_id}.yaml'
        artifact_path = base / 'artifacts' / f'{source_id}.yaml'
        source = load_yaml(source_path)
        artifact = load_yaml(artifact_path)
        source['source_url'] = url
        artifact['canonical_url'] = url
        write_yaml(source_path, source)
        write_yaml(artifact_path, artifact)
        canonicalized.append({'vendor_id': vendor_id, 'source_id': source_id, 'canonical_url': url})

    claims_added: list[dict[str, Any]] = []
    for source_id, roles in sorted(COVERAGE_CLAIMS.items()):
        matches = list((ROOT / 'data/vendors').glob(f'*/sources/{source_id}.yaml'))
        if len(matches) != 1:
            missing_requested.append(source_id)
            continue
        source_path = matches[0]
        source = load_yaml(source_path)
        claims = list(source.get('coverage_claims') or [])
        for role in roles:
            if any(isinstance(claim, dict) and claim.get('role') == role for claim in claims):
                continue
            claims.append({
                'role': role,
                'coverage_type': 'contains',
                'evidence': 'Independent source-completion verification found strong role-specific terms on this same official public page; a separate inferred URL was removed during page-purpose remediation.',
            })
            claims_added.append({'vendor_id': source.get('vendor_id'), 'source_id': source_id, 'role': role})
        source['coverage_claims'] = claims
        write_yaml(source_path, source)
        for role in roles:
            (source_path.parents[1] / 'unavailable_sources' / f"{source.get('vendor_id')}-{role}.yaml").unlink(missing_ok=True)

    contradictory_removed: list[str] = []
    for vendor_dir in sorted((ROOT / 'data/vendors').glob('*')):
        if not (vendor_dir / 'vendor.yaml').exists():
            continue
        current = vendor_completion(vendor_dir, today=TODAY)
        for role in sorted(set(current['canonical_covered_roles'])):
            path = vendor_dir / 'unavailable_sources' / f'{vendor_dir.name}-{role}.yaml'
            if path.exists():
                path.unlink()
                contradictory_removed.append(str(path))

    pre_absence = build_report(ROOT, today=TODAY, generated_at=REVIEWED_AT)
    removed_by_vendor: dict[str, list[dict[str, Any]]] = {}
    for row in removed_rows:
        removed_by_vendor.setdefault(str(row['vendor_id']), []).append(row)
    unavailable_written: list[dict[str, Any]] = []
    for vendor_row in pre_absence['vendors']:
        vendor_id = str(vendor_row['vendor_id'])
        vendor_dir = ROOT / 'data/vendors' / vendor_id
        vendor = load_yaml(vendor_dir / 'vendor.yaml')
        official_checks = [str(item) for item in (vendor.get('public_entrypoints') or []) if item]
        official_checks.extend(f'https://{domain}' for domain in (vendor.get('official_domains') or []) if domain)
        rejected = removed_by_vendor.get(vendor_id, [])
        for group in vendor_row['unresolved_groups']:
            for source_type in sorted(EXPECTED_GROUPS[group]):
                path = vendor_dir / 'unavailable_sources' / f'{vendor_id}-{source_type}.yaml'
                if path.exists():
                    continue
                rejected_urls = [
                    str(row['source_url']) for row in rejected
                    if row.get('source_type') == source_type and row.get('source_url')
                ]
                record = unavailable_record(
                    vendor_id,
                    source_type,
                    list(dict.fromkeys([*rejected_urls, *official_checks])),
                    REVIEWED_AT,
                    NEXT_REVIEW,
                )
                record['notes'] = 'No source-type-correct canonical public source was retained after official-path, link, sitemap, independent HTTP/semantic, redirect, duplicate-content, and page-purpose review. Rejected generic, editorial, user-generated, or not-found pages are not treated as vendor assurance sources. This is a search result, not a vendor quality or risk conclusion.'
                write_yaml(path, record)
                unavailable_written.append({'vendor_id': vendor_id, 'source_type': source_type, 'path': str(path)})

    final = build_report(ROOT, today=TODAY, generated_at=REVIEWED_AT)
    summary = {
        'schema_version': '0.1.0',
        'report_type': 'owner_source_completion_remediation_summary',
        'removed_source_count': len(removed_rows),
        'renamed_source_count': len(renamed),
        'canonicalized_source_count': len(canonicalized),
        'coverage_claim_count': len(claims_added),
        'unavailable_records_written': len(unavailable_written),
        'contradictory_unavailable_records_removed': len(contradictory_removed),
        'missing_requested_records': sorted(set(missing_requested)),
        'removed_sources': removed_rows,
        'renamed_sources': renamed,
        'canonicalized_sources': canonicalized,
        'coverage_claims_added': claims_added,
        'retained_reviewed_exceptions': RETAINED_EXCEPTIONS,
        'completion_summary': final['summary'],
        'not_advice': True,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps(summary, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    (output_dir / 'post-remediation-completion.json').write_text(json.dumps(final, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    if summary['missing_requested_records']:
        raise SystemExit(f"remediation ledger referenced missing records: {summary['missing_requested_records']}")
    if final['summary']['unresolved_group_count']:
        raise SystemExit(f"completion gaps remain: {final['summary']}")
    print(json.dumps({
        'removed_source_count': summary['removed_source_count'],
        'renamed_source_count': summary['renamed_source_count'],
        'canonicalized_source_count': summary['canonicalized_source_count'],
        'coverage_claim_count': summary['coverage_claim_count'],
        'unavailable_records_written': summary['unavailable_records_written'],
        'completion_summary': summary['completion_summary'],
    }, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
