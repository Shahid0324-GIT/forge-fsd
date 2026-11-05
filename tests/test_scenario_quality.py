import pytest

from forge.scenario_quality import quality_findings,validate_quality


def value(text):return {'action':'assert_value','target':{'by':'label','value':'Input'},'value':text}
def fill(text):return {'action':'fill','target':{'by':'label','value':'Input'},'value':text}
def visit(path='/'):return {'action':'visit','path':path}
def click(name):return {'action':'click','target':{'by':'role','value':'button','name':name}}
def suite(*steps):return {'scenarios':[{'id':'behavior','criteria':[1],'steps':list(steps)}]}


def test_baseline_assertion_cannot_verify_a_later_interaction():
    findings=quality_findings(suite(visit(),value(''),fill('unobserved')))
    assert findings[0]['code']=='unobserved_interaction' and findings[0]['step']==3


@pytest.mark.parametrize('postcondition',['','saved text'])
def test_reload_reset_and_persistence_have_observed_noninitial_preconditions(postcondition):
    validate_quality(suite(visit(),value(''),fill('saved text'),value('saved text'),visit(),value(postcondition)))


def test_reload_after_clear_without_observing_precondition_is_rejected():
    findings=quality_findings(suite(visit(),value(''),fill('text'),click('Clear'),visit(),value('')))
    assert [item['code'] for item in findings]==['reload_without_observed_state']


def test_asserting_clear_then_reload_still_does_not_challenge_persistence():
    findings=quality_findings(suite(visit(),value(''),fill('text'),value('text'),click('Clear'),value(''),visit(),value('')))
    assert [item['code'] for item in findings]==['reload_without_state_challenge']


def test_reload_result_cannot_be_hidden_by_another_interaction():
    findings=quality_findings(suite(visit(),value(''),fill('text'),value('text'),visit(),click('Clear'),value('')))
    assert [item['code'] for item in findings]==['reload_without_observed_result']


def test_navigation_and_grouped_form_actions_are_not_rejected_as_reload_checks():
    validate_quality(suite(visit(),fill('value'),click('Submit'),visit('/result'),value('submitted')))


def test_protocol_facts_distinguish_document_reload_from_navigation_without_claiming_execution():
    from forge.scenario_quality import protocol_facts
    data=suite(visit(),value(''),fill('saved'),value('saved'),visit(),value('saved'))
    facts=protocol_facts(data)['behavior']
    assert facts['same_path_document_reloads']==[{'step':5,'path':'/','navigation':'full_document',
        'pre_reload_observation_steps':[4],'post_reload_observation_steps':[6]}]
    assert 'has not executed' in facts['scope']
    assert not protocol_facts(suite(visit(),fill('saved'),visit('/other'),value('saved')))['behavior']['same_path_document_reloads']


def test_static_page_assertions_do_not_require_artificial_interactions():
    validate_quality(suite(visit(),{'action':'assert_title','value':'A landing page'}))


def test_unknown_initial_state_is_not_invented():
    validate_quality(suite(visit(),fill('text'),value('text'),visit(),value('text')))


def test_different_exact_region_values_without_actions_are_flagged_for_scope_review():
    from forge.scenario_quality import exact_observation_conflicts
    def text(expected):return {'action':'assert_text','target':{'by':'role','value':'region','name':'Summary'},'value':expected}
    data=suite(visit(),text('Subtotal 10'),text('Total 12'))
    findings=exact_observation_conflicts(data)
    assert findings[0]['steps']==[2,3] and findings[0]['exact_values']==['Subtotal 10','Total 12']
    assert 'asynchronous' in findings[0]['review_question']
    validate_quality(data)  # Timing behavior is a requirements judgment, not guessed by structure checks.
    assert not exact_observation_conflicts(suite(visit(),text('10'),click('Update'),text('12')))
    assert not exact_observation_conflicts(suite(visit(),text('10'),visit(),text('12')))
