# OpenVA Vendor Inventory Matcher

Conservative CSV matcher that enriches a vendor inventory with OpenVA public metadata references.

## Install

```bash
python -m pip install adapters/python/openva_pack_reader
python -m pip install adapters/python/openva_vendor_inventory_matcher
```

## Input

The input is a CSV file with `vendor_name`, `business_entity_name`, `domain`, or any combination of those columns. `registered_address` may be included as optional context and is preserved in the output. Other input columns are preserved too.

```csv
vendor_name,business_entity_name,registered_address,domain
Stripe,,,
,Slack Technologies LLC,,
```

## Basic usage

```bash
python -m openva_vendor_inventory_matcher --pack . --input customer_vendors.csv --out matched_vendors.csv
```

Or from Python:

```python
from openva_vendor_inventory_matcher import match_inventory

output = match_inventory(".", "customer_vendors.csv", "matched_vendors.csv")
```

The matcher uses exact official-domain matches, safe subdomain matches, and exact normalized name matches. Match confidence is identifier-matching confidence only.

## Boundary

The matcher does not approve vendors, assess risk, determine compliance, or decide suitability. It enriches inventory rows with public OpenVA metadata references and non-advisory adapter annotations.
