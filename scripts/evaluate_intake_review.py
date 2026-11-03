"""Fixed local-model calibration of clarification ownership; no app execution."""
import json
from uuid import uuid4

from forge.agents import OllamaAgents
from forge.contracts import IntakeDecision
from forge.intake_review import review_clarification
from forge.persistence import JobStore
from forge.source_checks import PROJECT
from forge.tasks import Task,TaskLedger


def main():
    directory=PROJECT/'artifacts/intake-review-evaluation'/uuid4().hex;directory.mkdir(parents=True)
    agents=OllamaAgents('qwen2.5-coder:7b');agents.trace_directory=directory/'model-calls';store=JobStore(directory/'jobs.sqlite3')
    summary={'passed':False,'human_approval':'NOT_CLAIMED','scope':'Question-ownership calibration only; no app generated or executed.','cases':[]}
    print('Evidence: '+str(directory),flush=True)
    fixtures=[('implementation','Build a small saved-notes app using local SQLite.',
        'The API and server/client interfaces are not designed yet.',
        ['How should the API and server/client data flow be designed?'],'delegate_to_planner'),
        ('unsupported','Build a shop that takes online card payments.',
         'Payment integration is not supported by the current local platform.',
         ['Can payment integration be omitted from this POC?'],'ask_user')]
    for name,request,reason,questions,expected in fixtures:
        job=store.create({'description':request});ledger=TaskLedger(store,job)
        state=ledger.reserve_action(ledger.start(ledger.create(Task(owner='requirements',goal='Classify this fixed clarification',
            inputs={'original_request':request},required_checks=['intake_schema']))),'requirements')
        row={'variant':name,'job_id':job,'expected':expected,'outcome':'error'}
        try:
            proposed=IntakeDecision.model_validate({'intent':'clarify','blocking_reason':reason,'questions':questions})
            decision=review_clarification(ledger,state,agents,{'application_request':request,'human_clarifications':[],
                'human_review_feedback':[],'protocol_errors':[]},proposed)
            row.update(outcome=decision.disposition,decision=decision.model_dump())
        except Exception as exc:row['error']=f'{type(exc).__name__}: {exc}'
        row['expected_outcome_observed']=row['outcome']==expected;summary['cases'].append(row);print(json.dumps(row),flush=True)
    summary['passed']=all(row['expected_outcome_observed'] for row in summary['cases'])
    (directory/'result.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps({'passed':summary['passed'],'report':str(directory/'result.json')}),flush=True)
    return int(not summary['passed'])


if __name__=='__main__':raise SystemExit(main())
