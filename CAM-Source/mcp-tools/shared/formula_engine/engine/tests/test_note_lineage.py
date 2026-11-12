import copy, unittest
from excel_formula_engine.note_lineage import audit_note_lineage

class NoteLineageTests(unittest.TestCase):
    def call(self, source=None, output=None, **kwargs):
        return audit_note_lineage(source if source is not None else [{'id':'r1','cpn':'P','mpn':'M','reason':'Source reason'}],
                                  output if output is not None else [{'ref':'r1','part':'P','mpn':'M','remarks':'Source reason'}],
                                  source_id_field='id',output_source_id_field='ref',
                                  field_map=kwargs.get('field_map',{'cpn':'part','mpn':'mpn','reason':'remarks'}))
    def codes(self,r):return [d['code'] for d in r['diagnostics']]
    def test_exact_gate_is_not_release(self):
        r=self.call();self.assertTrue(r['correspondence_gate_passed']);self.assertFalse(r['release_ready']);self.assertEqual(r['exact_rows_matched'],1)
    def test_lost_reason(self):
        r=self.call(output=[{'ref':'r1','part':'P','mpn':'M','remarks':''}]);self.assertIn('required_output_value_missing',self.codes(r));self.assertFalse(r['correspondence_gate_passed'])
    def test_different_mpn_not_joined_by_cpn(self):
        r=self.call(output=[{'ref':'r1','part':'P','mpn':'OTHER','remarks':'Source reason'}]);self.assertIn('source_output_value_mismatch',self.codes(r))
    def test_missing_source_does_not_allow_invention(self):
        r=self.call(source=[{'id':'r1','cpn':'P','mpn':'M'}]);self.assertIn('required_source_value_missing',self.codes(r))
    def test_ambiguous_source_id(self):
        r=self.call(source=[{'id':'r1'},{'id':'r1'}]);self.assertIn('ambiguous_source_identity',self.codes(r));self.assertIn('output_source_identity_ambiguous',self.codes(r));self.assertEqual(r['bound_rows_checked'],0)
    def test_missing_lineage(self):
        r=self.call(output=[{'part':'P','mpn':'M','remarks':'Source reason'}]);self.assertIn('output_source_identity_missing_or_invalid',self.codes(r))
    def test_unknown_lineage(self):
        r=self.call(output=[{'ref':'unknown'}]);self.assertIn('unbound_output_source_identity',self.codes(r))
    def test_typed_ids_never_alias(self):
        for invalid in [True,1.0,None,' ',[],{}]:
            with self.subTest(invalid=invalid):
                r=self.call(source=[{'id':invalid}]);self.assertIn('source_identity_missing_or_invalid',self.codes(r))
        r=self.call(source=[{'id':1}],output=[{'ref':'1'}]);self.assertIn('unbound_output_source_identity',self.codes(r))
    def test_typed_values_and_exact_spaces(self):
        for source,output in [(True,1),(1,1.0),('A','a'),('x ','x')]:
            with self.subTest(source=source,output=output):
                r=self.call(source=[{'id':'r1','v':source}],output=[{'ref':'r1','v':output}],field_map={'v':'v'});self.assertIn('source_output_value_mismatch',self.codes(r))
    def test_zero_false_values_not_missing(self):
        for v in [0,False]:
            with self.subTest(v=v):self.assertTrue(self.call(source=[{'id':'r1','v':v}],output=[{'ref':'r1','v':v}],field_map={'v':'v'})['correspondence_gate_passed'])
    def test_empty_outputs_not_pass(self):
        self.assertIn('no_output_rows_to_check',self.codes(self.call(output=[])))
    def test_bad_contract_rejected(self):
        for fields in [{},{'reason':'remarks','mpn':'remarks'},{'':'a'},{'a':None}]:
            with self.subTest(fields=fields):
                with self.assertRaises(ValueError):self.call(field_map=fields)
    def test_malformed_rows_fail_closed(self):
        r=self.call(source=[None],output=[None]);self.assertEqual(self.codes(r),['source_row_not_mapping','output_row_not_mapping'])
    def test_nonscalar_and_nonfinite_never_pass(self):
        for v in [[],{},float('inf'),float('-inf'),float('nan')]:
            with self.subTest(v=v):
                r=self.call(source=[{'id':'r1','v':v}],output=[{'ref':'r1','v':v}],field_map={'v':'v'})
                self.assertIn('unsupported_note_value_type',self.codes(r));self.assertFalse(r['correspondence_gate_passed'])
    def test_duplicate_outputs_and_omitted_sources_are_not_coverage(self):
        source=[{'id':'r1','v':'reason'},{'id':'r2','v':'other'}]
        output=[{'ref':'r1','v':'reason'},{'ref':'r1','v':'reason'}]
        r=self.call(source,output,field_map={'v':'v'})
        self.assertTrue(r['correspondence_gate_passed']);self.assertEqual(r['exact_rows_matched'],2)
        self.assertFalse(r['release_ready']);self.assertIn('duplicate-output',r['scope'])
    def test_transport_date_requires_explicit_format(self):
        import datetime
        v=datetime.date(2027,5,31)
        r=self.call(source=[{'id':'r1','v':v}],output=[{'ref':'r1','v':v}],field_map={'v':'v'})
        self.assertIn('unsupported_note_value_type',self.codes(r))
    def test_inputs_unchanged(self):
        s=[{'id':'r1','v':'reason'}];o=[{'ref':'r1','v':'reason'}];before=copy.deepcopy((s,o));self.call(s,o,field_map={'v':'v'});self.assertEqual((s,o),before)

if __name__=='__main__':unittest.main(verbosity=2)
