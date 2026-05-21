# Release Downloads For Spreadsheet Users

OpenVA publishes spreadsheet-friendly release assets through GitHub Releases.

These files are for users who want to inspect public vendor assurance metadata without installing Python, running Docker, or hosting a service.

## Where to find the files

1. Open the OpenVA repository on GitHub.
2. Select **Releases** in the right sidebar or open the latest release from the repository home page.
3. Expand **Assets**.
4. Download the files you need.

## Which file to download

Use:

```text
openva-csv.zip
```

to browse OpenVA in a spreadsheet. This is the main non-technical download.

It contains:

```text
vendors.csv
sources.csv
artifacts.csv
observations.csv
candidate_sources.csv
unavailable_sources.csv
source_coverage.csv
```

Use:

```text
openva-inventory-template.csv
```

to prepare your own vendor inventory for matching with OpenVA tooling. The expected columns are:

```text
vendor_name,domain,category
```

Use:

```text
openva-sample-inventory.csv
```

to see a small example inventory.

Use:

```text
openva-release-downloads-manifest.json
release-artifacts.json
```

only if you want checksums and release artifact metadata.

## How to read the CSVs

Start with `vendors.csv` to find a vendor by name or domain.

Use `source_coverage.csv` to see which public source types OpenVA currently records for each vendor, such as DPA, privacy notice, security page, and subprocessors.

Use `sources.csv` to inspect the public URLs themselves.

Use `candidate_sources.csv` and `unavailable_sources.csv` carefully:

- candidate sources are not canonical records yet;
- unavailable sources are catalog notes, not negative compliance findings;
- observations are fetch-time facts, not vendor ratings.

## Matching your own vendor list

OpenVA does not operate a public upload service. Do not upload private vendor inventories to OpenVA.

If you want to match a vendor list against OpenVA today:

- prepare your file using `openva-inventory-template.csv`;
- run the local Python matcher, or ask a technical teammate to run it locally;
- keep the input vendor inventory inside your own environment.

The local matcher accepts:

```text
vendor_name,domain,category
```

and writes an enriched CSV with OpenVA public metadata references.

## Missing or stale data

If a vendor is missing, a public source moved, or OpenVA records incomplete metadata, open a GitHub issue using the **Vendor catalog update** form.

Submit public URLs only. Do not submit private agreements, gated portal exports, screenshots, copied document text, credentials, SOC reports, private certificates, or customer-specific terms.

## Non-advisory reminder

OpenVA records public-source metadata only.

It does not approve, recommend, certify, score, or determine whether any vendor is compliant, safe, adequate, suitable, low risk, or high risk.
