from forge.design_interfaces import interface_issues,implementation_order,interfaces_for
from test_autonomous_planning import draft


def proposal():
    value=draft().model_dump()
    value.update(files=[{'path':'app/page.tsx','owner':'frontend','purpose':'Interaction'},
        {'path':'custom/domain.ts','owner':'backend','purpose':'Agent-chosen service'}],
        interfaces=[{'name':'custom boundary','provider':'custom/domain.ts','consumers':['app/page.tsx'],
            'kind':'server_action','contract':'export async function readValue():Promise<number>'}])
    return type(draft()).model_validate(value)


def test_agent_chosen_paths_and_signatures_drive_provider_first_order():
    value=proposal()
    assert interface_issues(value)==[]
    assert [file.path for file in implementation_order(value)]==['custom/domain.ts','app/page.tsx']
    assert interfaces_for(value,['app/page.tsx'])[0]['contract'].endswith('Promise<number>')
    assert interfaces_for(value,['unrelated.ts'])==[]


def test_unknown_paths_self_dependencies_duplicate_names_and_cycles_fail():
    value=proposal();value.interfaces[0].consumers=['missing.ts']
    assert 'outside the manifest' in ' '.join(interface_issues(value))
    value=proposal();value.interfaces[0].consumers=['custom/domain.ts']
    assert 'itself' in ' '.join(interface_issues(value))
    value=proposal();value.interfaces.append(value.interfaces[0].model_copy())
    assert 'unique' in ' '.join(interface_issues(value))
    value=proposal();value.interfaces.append(value.interfaces[0].model_copy(update={
        'name':'reverse','provider':'app/page.tsx','consumers':['custom/domain.ts']}))
    assert 'cycle' in ' '.join(interface_issues(value))


def test_single_file_needs_no_artificial_backend_but_cross_role_work_needs_agreement():
    assert interface_issues(draft())==[]
    value=proposal();value.interfaces=[]
    assert 'shared interfaces' in ' '.join(interface_issues(value))
