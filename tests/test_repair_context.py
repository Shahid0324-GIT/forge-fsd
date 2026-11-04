import copy
import json
import pytest
from forge.repair_context import compact_repair_context
from forge.provider_errors import ProviderResourceError


def test_compaction_preserves_all_errors_actual_expressions_source_and_requirements():
    content='const value = broken();\n'+'// interface detail\n'*20
    rows=[{'file':'app/page.tsx','line':1,'column':15,'code':f'TS{i}',
        'message':f'Failure {i}','line_text':content.splitlines()[0],
        'expression_at_column':'broken();','source_excerpt':[content]*4} for i in range(20)]
    data={'source':{'app/page.tsx':{'content':content,'sha256':'a'*64}},'diagnostic_locations':rows,
        'original_request':'Build the requested application','acceptance_criteria':['Preserve behavior'],'workspace_fingerprint':'b'*64}
    before=copy.deepcopy(data)
    result=compact_repair_context(data,budget=7000)
    assert len(json.dumps(result,separators=(',',':')))<=7000
    for field in ['source','original_request','acceptance_criteria','workspace_fingerprint']:assert result[field]==before[field]
    assert len(result['diagnostic_locations'])==20
    for row,old in zip(result['diagnostic_locations'],before['diagnostic_locations']):
        for field in ['file','line','column','code','message','expression_at_column']:assert row[field]==old[field]


def test_unavailable_source_excerpts_cannot_be_discarded_to_fit():
    data={'source':{},'diagnostic_locations':[{'file':'external.ts','source_excerpt':['important '*1000]}]}
    with pytest.raises(ProviderResourceError,match='Capacity pause'):compact_repair_context(data,budget=1000)
    assert data['diagnostic_locations'][0]['source_excerpt']


def test_genuinely_oversized_requirements_pause_without_truncation():
    data={'original_request':'requirement '*4000,'source':{}}
    before=data['original_request']
    with pytest.raises(ProviderResourceError):compact_repair_context(data)
    assert data['original_request']==before
