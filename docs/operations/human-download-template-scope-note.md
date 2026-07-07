# Human download template scope note

The local compiler has moved to the simple compiled vendor information template.
A follow-up browser/static-site PR should apply the same CSV output shape to `site/src/app.js` and retire the old `openva_*` browser download fields.

Required browser-template paths for that follow-up:

- `site/src/app.js`
- `tests/test_site.py`

This note is intentionally policy-only preparation and should be removed or replaced by a proper scope-manifest update if browser output scope is widened.
