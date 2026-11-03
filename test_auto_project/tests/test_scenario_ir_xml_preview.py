"""Display XML is derived data and must not change execution mappings or artifacts."""
from copy import deepcopy
import xml.etree.ElementTree as ET

import pytest

from tap.ir.xml_preview import build_xml_preview


def test_fixed_and_bound_values_use_exact_dataset_paths_and_preserve_original():
    xml='<Root><Dataset id="dsInput"><rows><row><venCd>003766</venCd><ordNo>EXAMPLE</ordNo></row></rows></Dataset><Dataset id="other"><rows><row><venCd>003766</venCd></row></rows></Dataset></Root>'
    path='/Root/Dataset[@id="dsInput"]/rows/row/'
    inputs=[dict(field='venCd',parameter_path='$.venCd',xml_path=path+'venCd',source='fixed',value='001442'),
            dict(field='ordNo',parameter_path='$.ordNo',xml_path=path+'ordNo',source='bind',ref='B-1',value=None)]
    bindings=[dict(binding_id='B-1',**{'from':dict(from_step_id='1-1',output_name='ordNo')})]
    before=deepcopy((inputs,bindings))
    preview=build_xml_preview(xml,inputs,bindings)
    original=ET.fromstring(preview['original_xml']);applied=ET.fromstring(preview['applied_xml'])
    assert original.find('./Dataset[@id="dsInput"]/rows/row/venCd').text=='003766'
    assert applied.find('./Dataset[@id="dsInput"]/rows/row/venCd').text=='001442'
    assert applied.find('./Dataset[@id="dsInput"]/rows/row/ordNo').text=='{{1-1.ordNo}}'
    assert applied.find('./Dataset[@id="other"]/rows/row/venCd').text=='003766'
    assert sum(line['changed'] for line in preview['applied_lines'])==2
    assert '__tap_preview_changed__' not in preview['applied_xml']
    assert (inputs,bindings)==before


def test_xml_attributes_escaping_and_pending_values():
    xml='<Root><row code="old"><name>old</name><id>123</id><pending>EXAMPLE</pending><same>0</same></row></Root>'
    inputs=[dict(field='code',xml_path='/Root/row/@code',source='fixed',value='A&B"'),
            dict(field='name',xml_path='/Root/row/name',source='fixed',value='<script> & data'),
            dict(field='id',xml_path='/Root/row/id',source='run_input'),
            dict(field='pending',xml_path='/Root/row/pending',source='bind',ref='missing'),
            dict(field='same',xml_path='/Root/row/same',source='fixed',value=0),
            dict(field='header',parameter_path='$.headers.key',source='fixed',value='secret')]
    preview=build_xml_preview(xml,inputs,[])
    row=ET.fromstring(preview['applied_xml']).find('./row')
    assert row.get('code')=='A&B"'
    assert row.find('./name').text=='<script> & data'
    assert row.find('./id').text=='{{입력 필요: id}}'
    assert row.find('./pending').text=='{{연결 미정}}'
    assert any('Binding' in warning for warning in preview['warnings'])
    assert not any('secret' in line['text'] for line in preview['applied_lines'])
    assert not any(line['changed'] for line in preview['applied_lines'] if '<same>' in line['text'])


@pytest.mark.parametrize('xml',[None,'','<Root>broken'])
def test_missing_or_invalid_baseline_xml_is_nonfatal(xml):
    preview=build_xml_preview(xml,[],[])
    assert preview['available'] is False and preview['warnings']
    assert not preview['applied_xml']


def test_unknown_path_and_composite_element_are_not_silently_replaced():
    preview=build_xml_preview('<Root><row><child>keep</child></row></Root>',[
        dict(field='missing',xml_path='/Root/row/missing',source='fixed',value='new'),
        dict(field='composite',xml_path='/Root/row',source='fixed',value='destroy'),
        dict(field='wrongRoot',xml_path='/Elsewhere/row',source='fixed',value='new'),
        dict(field='badXPath',xml_path='/Root/row[',source='fixed',value='new')],[])
    assert ET.fromstring(preview['applied_xml']).find('./row/child').text=='keep'
    assert len(preview['warnings'])==4
    assert not any(change['applied'] for change in preview['changes'])
