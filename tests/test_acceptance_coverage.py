import json
from forge.acceptance_coverage import review_coverage
from forge.autonomous_acceptance import AcceptanceSuite
from test_autonomous_acceptance import context,proposal


def test_coverage_review_receives_exact_protocol_and_ignores_old_unbound_cache(context):
    ledger,state,review,agent=context;calls=[]
    def generate(schema,instruction,data,**options):
        calls.append((instruction,data,options))
        return schema.model_validate({'can_check':False,'reason':'Server restart is not an available action','strategy':[]})
    agent.generate=generate
    directory=ledger.store.path.parent/'acceptance-plans'/ledger.job_id;directory.mkdir(parents=True)
    old=directory/f'coverage-{state.task.id}-r{state.revision}-c3.json'
    old.write_text(json.dumps({'decision':{'can_check':True,'reason':'Invented CSS capability','strategy':['Use CSS selectors']}}),encoding='utf-8')
    suite=AcceptanceSuite.model_validate(proposal())
    review_coverage(ledger,state,agent,review,suite,lambda:None)
    instruction,data,options=calls[0]
    assert data['browser_contract_schema']==AcceptanceSuite.model_json_schema()
    assert data['browser_contract_schema']['$defs']['TextTarget']['properties']['by']['enum']==['label','text','placeholder']
    assert 'NO CSS/XPath selectors' in instruction and 'conditional strategy' in instruction
    assert 'source' not in data and 'current_source' not in data and options['coding'] is True
    assert data['browser_capabilities_sha256']
    review_coverage(ledger,state,agent,review,suite,lambda:None)
    assert len(calls)==1
