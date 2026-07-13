# Owner HR and education tranche diagnostic

The fail-fast generator, observation, or validation lane exited non-zero.

```text
Traceback (most recent call last):
  File "<frozen runpy>", line 198, in _run_module_as_main
  File "<frozen runpy>", line 88, in _run_code
  File "/home/runner/work/open-vendor-assurance/open-vendor-assurance/tools/openva/catalog_batch.py", line 226, in <module>
    raise SystemExit(main())
                     ^^^^^^
  File "/home/runner/work/open-vendor-assurance/open-vendor-assurance/tools/openva/catalog_batch.py", line 222, in main
    return generate_catalog_batch(args.manifest, force=args.force, build=args.build_indexes)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/runner/work/open-vendor-assurance/open-vendor-assurance/tools/openva/catalog_batch.py", line 189, in generate_catalog_batch
    manifest = load_yaml(manifest_path)
               ^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/runner/work/open-vendor-assurance/open-vendor-assurance/tools/openva/catalog_batch.py", line 23, in load_yaml
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
                          ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/opt/hostedtoolcache/Python/3.12.13/x64/lib/python3.12/pathlib.py", line 1027, in read_text
    with self.open(mode='r', encoding=encoding, errors=errors) as f:
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/opt/hostedtoolcache/Python/3.12.13/x64/lib/python3.12/pathlib.py", line 1013, in open
    return io.open(self, mode, buffering, encoding, errors, newline)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
FileNotFoundError: [Errno 2] No such file or directory: 'catalog-batches/owner-hr-education-expansion-1.yaml'
```
