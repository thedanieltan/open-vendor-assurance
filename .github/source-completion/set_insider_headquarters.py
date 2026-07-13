from pathlib import Path

import yaml

path = Path('data/vendors/insider/vendor.yaml')
record = yaml.safe_load(path.read_text(encoding='utf-8')) or {}
record['headquarters_country'] = 'SG'
path.write_text(yaml.safe_dump(record, sort_keys=False, allow_unicode=True), encoding='utf-8')
print('set insider headquarters_country=SG')
