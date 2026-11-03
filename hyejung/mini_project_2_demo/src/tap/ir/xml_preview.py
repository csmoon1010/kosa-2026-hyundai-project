"""Display-only XML snapshots; never edit Baseline artifacts or execute requests."""
from copy import deepcopy
import json
import re
import xml.etree.ElementTree as ET


def build_xml_preview(xml, inputs, bindings):
    result = dict(available=False, original_xml='', applied_xml='', applied_lines=[], changes=[], warnings=[])
    if not isinstance(xml, str) or not xml.strip():
        result['warnings'].append('Baseline XML이 없습니다.')
        return result
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        result['warnings'].append('Baseline XML을 읽을 수 없습니다.')
        return result
    applied = deepcopy(root)
    references = {b['binding_id']: b['from'] for b in bindings}
    changed = set()
    for item in inputs:
        path = item.get('xml_path')
        if not path:
            # Headers and JSON-only inputs have no XML location.
            continue
        change = dict(parameter_path=item.get('parameter_path'), xml_path=path, applied=False)
        source = item.get('source')
        if source == 'fixed' and item.get('value') is not None:
            value = item['value']
            text = value if isinstance(value,str) else json.dumps(value,ensure_ascii=False)
        elif source == 'bind':
            origin = references.get(item.get('ref'))
            text = '{{'+origin['from_step_id']+'.'+origin['output_name']+'}}' if origin else '{{연결 미정}}'
            if not origin: result['warnings'].append(str(item.get('field') or path)+': Binding 정의가 없습니다.')
        elif source in ['unresolved','run_input']:
            text = '{{입력 필요: '+str(item.get('field') or item.get('parameter_path'))+'}}'
        else:
            result['warnings'].append(str(item.get('field') or path)+': 확정된 값이 없어 원본을 유지합니다.')
            result['changes'].append(change)
            continue
        element_path, separator, attribute = path.rpartition('/@')
        if not separator: element_path, attribute = path, None
        prefix = '/'+applied.tag
        if not (element_path == prefix or element_path.startswith(prefix+'/')):
            matches = []
        else:
            relative = '.'+element_path[len(prefix):]
            try: matches = applied.findall(relative)
            except (SyntaxError, KeyError, TypeError): matches = []
        if not matches:
            result['warnings'].append(str(item.get('field') or path)+': XML 위치를 찾을 수 없습니다.')
            result['changes'].append(change)
            continue
        for node in matches:
            before = node.get(attribute) if attribute else node.text or ''
            if attribute: node.set(attribute,text)
            elif len(node):
                result['warnings'].append(path+': 복합 요소는 자동 대체하지 않습니다.')
                continue
            else: node.text = text
            change.update(applied=True, before=before, after=text)
            if before != text: changed.add(node)
        result['changes'].append(change)
    # Mark changed elements only while serializing, then remove the temporary marks.
    marker = '__tap_preview_changed__'
    while any(marker in n.attrib for n in applied.iter()): marker += '_'
    for node in changed: node.set(marker,'1')
    ET.indent(root,space='  '); ET.indent(applied,space='  ')
    lines = ET.tostring(applied,encoding='unicode').splitlines()
    pattern = re.compile(r'\s+'+re.escape(marker)+r'="1"')
    result['applied_lines'] = [dict(text=pattern.sub('',line),changed=marker+'=' in line) for line in lines]
    result.update(available=True, original_xml=ET.tostring(root,encoding='unicode'),
                  applied_xml='\n'.join(line['text'] for line in result['applied_lines']))
    return result
