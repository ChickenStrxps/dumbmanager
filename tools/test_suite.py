"""Run a real suite and retain counts for the draft release's review record."""
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
def main():
    suite=sys.argv[1]
    assert suite in ('api','host')
    tests=unittest.defaultTestLoader.discover(str(ROOT/'tests'/suite))
    result=unittest.TextTestRunner(verbosity=2).run(tests)
    report={'suite':suite,'tests':result.testsRun,'failures':len(result.failures),
            'errors':len(result.errors),'skipped':[{'test':str(t),'reason':why} for t,why in result.skipped],
            'passed':result.testsRun-len(result.failures)-len(result.errors)-len(result.skipped),
            'successful':result.wasSuccessful(),'live_integrations_tested':False}
    out=ROOT/'dist';out.mkdir(exist_ok=True)
    (out/(suite+'-checks.json')).write_text(json.dumps(report,indent=2),encoding='utf-8')
    return not result.wasSuccessful()
if __name__=='__main__':raise SystemExit(main())
