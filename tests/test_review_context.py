from types import SimpleNamespace
import json

from forge.senior_review import scoped_review_context
from forge.source_agent import diagnostic_context


def test_generated_route_diagnostics_map_to_owned_source_without_fake_coordinates():
    path='app/api/items/[id]/route.ts'
    source={path:{'content':'export async function DELETE() {}'}}
    failure={'checks':[{'summary':'.next/types/'+path+'(252,7): error TS2344: Invalid route params'}]}
    location=diagnostic_context(failure,source)[0]
    assert location['file']==path and location['line'] is None and location['column'] is None
    assert location['generated_location']['line']==252
    assert location['source_excerpt']==[] and location['line_text']==''
    assert diagnostic_context({'checks':[{'summary':path+'(252,7): error TS2344: Unknown source line'}]},source)==[]


def test_large_senior_review_keeps_current_interfaces_and_all_requirements():
    route='app/api/items/[id]/route.ts'
    source={route:"import {remove} from '../../../../lib/store'; export async function DELETE(){}",
        'lib/store.ts':'export function remove() {}',
        'app/page.tsx':'/* unrelated UI body */'*800,
        'lib/types.ts':'export interface Item {id:number}'}
    files=[{'path':path,'owner':'frontend' if path=='app/page.tsx' else 'backend','purpose':'Chosen app role'} for path in source]
    design={'title':'App','design':'Chosen interfaces','database':'sqlite','acceptance_criteria':['Remove item','Keep state'],
        'assumptions':['Single user'],'files':files,'test_strategy':'Original test proposal '*400}
    context={'current_source':source,'approved_design':design,'original_request':'Remove items and keep state','source_fingerprint':'a'*64}
    failure={'checks':[{'summary':'.next/types/'+route+'(252,7): error TS2344: Invalid route params'}]}
    result=scoped_review_context(context,SimpleNamespace(task=SimpleNamespace(owner='backend')),failure)
    assert len(json.dumps(context))>20000 and len(json.dumps(result))<10000
    assert set(result['current_source'])=={route,'lib/store.ts','lib/types.ts'}
    assert result['current_source'][route]==source[route]
    assert result['approved_design']['acceptance_criteria']==design['acceptance_criteria']
    assert result['approved_design']['assumptions']==design['assumptions']
    assert result['approved_design']['design']==design['design']
    assert result['original_request']==context['original_request']
    assert result['context_omitted'][0]['file']=='app/page.tsx' and len(result['context_omitted'][0]['sha256'])==64
    assert {row['field'] for row in result['context_omitted_fields']}=={'approved_design.files','approved_design.test_strategy'}
    assert set(source)=={row['file'] for row in result['source_inventory']}


def test_review_without_a_source_snapshot_preserves_planning_context():
    context={'original_request':'Build an app','latest_proposal':{'title':'App'}}
    assert scoped_review_context(context,None,None) is context
