"""Conservative scenario-structure checks; never infer an app's business logic."""
import json


INTERACTIONS={'click','fill','select','check'}
ASSERTIONS={'assert_visible','assert_text','assert_value','assert_count','assert_title'}


def _observation(step):
    action=step['action']
    if action not in ASSERTIONS:return None
    target=json.dumps(step.get('target'),sort_keys=True,separators=(',',':'))
    value=step.get('count') if action=='assert_count' else step.get('value',True)
    if action=='assert_text':value=' '.join(value.split())
    return (action,target),value


def _observations(steps):
    return dict(observed for step in steps if (observed:=_observation(step)) is not None)


def exact_observation_conflicts(suite):
    """Review obligations, not automatic failures: asynchronous UI can change itself."""
    conflicts=[]
    for case in suite['scenarios']:
        seen={}
        for index,step in enumerate(case['steps']):
            if step['action'] in INTERACTIONS|{'visit'}:
                seen.clear()
            observed=_observation(step)
            if observed is None or step['action']!='assert_text':continue
            key,value=observed
            if key in seen and seen[key][1]!=value:
                previous,expected=seen[key]
                conflicts.append({'scenario':case['id'],'steps':[previous+1,index+1],
                    'target':step['target'],'exact_values':[expected,value],
                    'review_question':'No interaction or navigation separates these different exact full-text expectations. '
                        'Does an approved asynchronous state transition explain them? Otherwise require one complete container expectation or smaller semantic targets.'})
            seen[key]=(index,value)
    return conflicts


def quality_findings(suite):
    """Find missing observations and provably unchallenged same-page reloads.

    Unknown state is not guessed. Navigation to another route is not a reload.
    A scenario may group input/submit actions before observing their joint result.
    """
    findings=[]
    for case in suite['scenarios']:
        steps=case['steps']
        def issue(code,index,message):
            findings.append({'scenario':case['id'],'step':index+1,'code':code,'message':message})
        interactions=[i for i,step in enumerate(steps) if step['action'] in INTERACTIONS]
        if interactions and not any(step['action'] in ASSERTIONS for step in steps[interactions[-1]+1:]):
            issue('unobserved_interaction',interactions[-1],
                'The final interaction has no subsequent assertion. Observe its requested result; an earlier baseline assertion cannot verify this action.')
        visits=[i for i,step in enumerate(steps) if step['action']=='visit']
        for start,end in zip(visits,visits[1:]):
            if steps[start]['path']!=steps[end]['path']:continue
            changes=[i for i in interactions if start<i<end]
            if not changes:continue
            before=_observations(steps[changes[-1]+1:end])
            if not before:
                issue('reload_without_observed_state',end,
                    'Assert the changed state after interacting and before reloading. An input or click alone does not establish the pre-reload state.')
                continue
            stop=next((i for i in range(end+1,len(steps)) if steps[i]['action'] in INTERACTIONS|{'visit'}),len(steps))
            after=_observations(steps[end+1:stop])
            if not after:
                issue('reload_without_observed_result',end,
                    'Observe the reload result before another interaction; later actions can hide what the reload did.')
                continue
            baseline=_observations(steps[start+1:changes[0]])
            if all(key in baseline and value==baseline[key] and key in after and value==after[key]
                   for key,value in before.items()):
                issue('reload_without_state_challenge',end,
                    'The observed state before and after reload equals the initial baseline. Arrange and assert a distinct state before reload, then assert the required reset or persistence. Clearing back to the baseline first cannot distinguish these behaviors.')
    return findings


def validate_quality(suite):
    findings=quality_findings(suite)
    if findings:raise ValueError('Scenario quality checks require revision: '+json.dumps(findings[:10],separators=(',',':')))
