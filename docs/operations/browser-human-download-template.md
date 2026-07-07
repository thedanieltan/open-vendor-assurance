# Browser human download template

The GitHub Pages browser-local matcher should emit the same human-facing vendor information columns as the local compiler:

```text
matched_vendor_name,official_domain,trust_security_url,dpa_url,subprocessors_url,privacy_notice_url,status_page_url
```

The browser output remains local-only: user CSV contents stay in browser memory and are not uploaded to OpenVA.
