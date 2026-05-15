# Region Taxonomy

OpenVA uses controlled region tags for public vendor metadata filtering.

These tags are for broad market-discovery metadata only. They are not legal advice, data-residency statements, service availability commitments, regulatory determinations, or procurement conclusions.

## Field distinction

Use uppercase ISO-3166 alpha-2 country codes only for country-specific fields such as:

```yaml
headquarters_country: SG
```

Use lowercase controlled market tags for broad region fields such as:

```yaml
regions_served:
  - global
  - apac
  - sg
```

Artifact `region_scope` follows the same lowercase controlled tag convention:

```yaml
region_scope:
  - global
```

## Controlled source

The allowed tags are defined in:

```text
config/region-taxonomy.yaml
```

The taxonomy currently separates:

```text
country_markets
regional_markets
```

Country-market tags use lowercase keys such as:

```text
sg, us, cn, hk, jp, kr, in, au, ca, uk
```

Regional-market tags use lowercase keys such as:

```text
global, apac, sea, eu, eea, emea, latam, mena
```

## Validation

The validator rejects region tags that are not lowercase or not defined in `config/region-taxonomy.yaml`.

Run:

```bash
python -m tools.openva.validate validate
```

## Non-advisory posture

A region tag means only that public metadata has been labeled for broad catalog filtering. It does not mean that a vendor is available, compliant, approved, suitable, or safe in that country or region.
