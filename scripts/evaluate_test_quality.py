"""Calibrate local-model test review on strong and superficial fixed test proposals.

No app source is generated/executed. A rejected review counts only when the model
returned valid, bound findings, never for a service/schema failure.
"""
import json
from uuid import uuid4

from forge.acceptance_review import review_suite
from forge.autonomous_acceptance import AcceptanceSuite
from forge.agents import OllamaAgents
from forge.persistence import JobStore
from forge.scenario_quality import validate_quality
from forge.source_checks import PROJECT
from forge.tasks import Task,TaskLedger


def main():
    directory=PROJECT/'artifacts/test-quality-evaluation'/uuid4().hex;directory.mkdir(parents=True)
    store=JobStore(directory/'jobs.sqlite3');agents=OllamaAgents('qwen2.5-coder:7b');agents.trace_directory=directory/'model-calls'
    summary={'passed':False,'scope':'Fixed test-review calibration only; no generated app or app execution.',
        'human_approval':'NOT_CLAIMED','cases':[]}
    print('Evidence: '+str(directory),flush=True)
    for variant in ['meaningful','superficial']:
        job=store.create({'description':'Internal addition-calculator test-quality calibration','model':agents.model_name})
        ledger=TaskLedger(store,job)
        review={'fingerprint':'a'*64,'binding':{'model':agents.model_name,'inputs':{
            'original_request':'Build a calculator that adds two numbers when I press Add and displays their sum.'}},
            'draft':{'acceptance_criteria':['Entering two numbers and pressing Add displays their sum.']}}
        state=ledger.reserve_action(ledger.start(ledger.create(Task(owner='qa',goal='Calibrate independent test quality review',
            inputs={'review_fingerprint':review['fingerprint']},required_checks=['acceptance_contract']))),'qa')
        steps=[{'action':'visit','path':'/'}]
        if variant=='meaningful':
            for first,second,total in [('2','3','5'),('-4','4','0'),('1.5','2.5','4')]:steps.extend([
                {'action':'fill','target':{'by':'label','value':'First number'},'value':first},
                {'action':'fill','target':{'by':'label','value':'Second number'},'value':second},
                {'action':'click','target':{'by':'role','value':'button','name':'Add'}},
                {'action':'assert_text','target':{'by':'role','value':'status'},'value':total}])
        else:steps.append({'action':'assert_title','value':'Addition calculator'})
        suite=AcceptanceSuite.model_validate({'scenarios':[{'id':'adds_numbers','criteria':[1],'steps':steps}],'uncovered':[]})
        validate_quality(suite.model_dump());result={'variant':variant,'job_id':job,'expected':'accept' if variant=='meaningful' else 'revise'}
        try:
            result['review']=review_suite(ledger,state,agents,review,suite,lambda:None);result['outcome']='accept'
        except ValueError as exc:
            result['outcome']='revise' if str(exc).startswith('Independent QA review requires revision:') else 'error'
            result['reason']=str(exc)
        except Exception as exc:result.update(outcome='error',reason=f'{type(exc).__name__}: {exc}')
        result['expected_outcome_observed']=result['outcome']==result['expected'];summary['cases'].append(result)
        print(json.dumps(result),flush=True)
    summary['passed']=all(row['expected_outcome_observed'] for row in summary['cases'])
    (directory/'result.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps({'passed':summary['passed'],'report':str(directory/'result.json')}),flush=True)
    return int(not summary['passed'])


if __name__=='__main__':raise SystemExit(main())
