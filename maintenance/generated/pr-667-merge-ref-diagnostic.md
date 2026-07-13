# PR 667 merge-ref diagnostic

Validator exit: 1
Source-maintenance exit: 1

## Validator

```text
Built OpenVA indexes, registry outputs, and pack manifest.
data/vendors/docebo/vendor.yaml: vendor_categories tag learning_management is not defined in config/category-taxonomy.yaml
data/vendors/docebo/vendor.yaml: vendor_categories tag enterprise_software is not defined in config/category-taxonomy.yaml
data/vendors/red-hat/vendor.yaml: vendor_categories tag enterprise_software is not defined in config/category-taxonomy.yaml
Validation failed: 3 issue(s).
```

## Source-maintenance tests

```text
.......................................................F................ [ 22%]
........................................................................ [ 45%]
........................................................................ [ 67%]
........................................................................ [ 90%]
..............................                                           [100%]
=================================== FAILURES ===================================
____ test_current_catalog_accepts_absent_candidate_and_unavailable_ledgers _____
tests/test_source_ledger_validation.py:6: in test_current_catalog_accepts_absent_candidate_and_unavailable_ledgers
    assert validate_quality_gates() == []
E   AssertionError: assert ['data/vendor...axonomy.yaml'] == []
E     
E     Left contains 3 more items, first extra item: 'data/vendors/docebo/vendor.yaml: vendor_categories tag learning_management is not defined in config/category-taxonomy.yaml'
E     
E     Full diff:
E     - []
E     + [
E     +     'data/vendors/docebo/vendor.yaml: vendor_categories tag '
E     +     'learning_management is not defined in config/category-taxonomy.yaml',
E     +     'data/vendors/docebo/vendor.yaml: vendor_categories tag '
E     +     'enterprise_software is not defined in config/category-taxonomy.yaml',
E     +     'data/vendors/red-hat/vendor.yaml: vendor_categories tag '
E     +     'enterprise_software is not defined in config/category-taxonomy.yaml',
E     + ]
=========================== short test summary info ============================
FAILED tests/test_source_ledger_validation.py::test_current_catalog_accepts_absent_candidate_and_unavailable_ledgers - AssertionError: assert ['data/vendor...axonomy.yaml'] == []
  
  Left contains 3 more items, first extra item: 'data/vendors/docebo/vendor.yaml: vendor_categories tag learning_management is not defined in config/category-taxonomy.yaml'
  
  Full diff:
  - []
  + [
  +     'data/vendors/docebo/vendor.yaml: vendor_categories tag '
  +     'learning_management is not defined in config/category-taxonomy.yaml',
  +     'data/vendors/docebo/vendor.yaml: vendor_categories tag '
  +     'enterprise_software is not defined in config/category-taxonomy.yaml',
  +     'data/vendors/red-hat/vendor.yaml: vendor_categories tag '
  +     'enterprise_software is not defined in config/category-taxonomy.yaml',
  + ]
1 failed, 317 passed in 16.55s
```
