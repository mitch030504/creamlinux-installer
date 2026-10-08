"""Run the complete suite and retain machine-readable test counts."""
import json
from pathlib import Path
import sys
import unittest

suite = unittest.defaultTestLoader.discover(str(Path(sys.argv[1])), pattern='test_*.py')
result = unittest.TextTestRunner(verbosity=1).run(suite)
summary = {'tests_run': result.testsRun, 'failures': len(result.failures),
           'errors': len(result.errors), 'skipped': [{'test': str(t), 'reason': reason} for t,reason in result.skipped]}
summary['status'] = 'passed' if result.wasSuccessful() else 'failed'
Path(sys.argv[2]).write_text(json.dumps(summary, indent=2)+'\n')
sys.exit(0 if result.wasSuccessful() else 1)
