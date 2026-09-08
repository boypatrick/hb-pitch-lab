import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from module_specs import ROOT
from optimize import read_json, write_json
from quality_check import CHECKS, append_jsonl, check_manifest, execute, verify_run


class QualityTests(unittest.TestCase):
    def test_fixed_check_contract(self):
        self.assertEqual([c[0] for c in CHECKS],[f'Q{i:02d}' for i in range(1,10)])

    def test_append_preserves_prior_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'history.jsonl'
            append_jsonl(p,{'n':1});before=p.read_bytes();append_jsonl(p,{'n':2})
            self.assertTrue(p.read_bytes().startswith(before))
            self.assertEqual([json.loads(line)['n'] for line in p.read_text().splitlines()],[1,2])

    def test_invalid_input_logs_fail_and_does_not_run_tools(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);out=root/'run';bad=root/'bad.json';write_json(bad,{'wrong':'schema'})
            original=append_jsonl
            def redirect(path, record):
                original(root/'history.jsonl' if Path(path).name=='history.jsonl' else path,record)
            with patch('quality_check.append_jsonl',side_effect=redirect),patch('quality_check.run_command') as command:
                result=execute(ROOT/'examples/modules.json',bad,out)
                command.assert_not_called()
            self.assertEqual(result['status'],'FAIL');self.assertEqual(result['checks'][0]['status'],'FAIL')
            self.assertTrue(all(c['status']=='NOT_RUN' for c in result['checks'][1:]))
            self.assertEqual(len((out/'events.jsonl').read_text().splitlines()),2)
            with self.assertRaisesRegex(ValueError,'not a completed PASS'):verify_run(out)
            with self.assertRaisesRegex(ValueError,'directory exists'):
                execute(ROOT/'examples/modules.json',bad,out)

    def test_missing_required_check_cannot_claim_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            write_json(root/'run.json',{'format':'hb-qc-run-v1','status':'PASS','checks':[]})
            with self.assertRaisesRegex(ValueError,'required quality checks'):verify_run(root)

    def test_manifest_change_is_detected(self):
        import shutil
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'rtl';shutil.copytree(ROOT/'results/generated_v02',root)
            check_manifest(root)
            with (root/'rtl/hb_link.sv').open('a') as stream:stream.write('\n// changed\n')
            with self.assertRaisesRegex(ValueError,'changed'):check_manifest(root)


if __name__=='__main__':unittest.main()
