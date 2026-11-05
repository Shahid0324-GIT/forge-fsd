from copy import deepcopy

from forge.schema_wire import compact_titles


def test_only_schema_titles_are_removed_while_data_named_title_remains_required():
    schema={'title':'Root','type':'object','additionalProperties':False,'required':['title','nested'],
        'properties':{'title':{'title':'Title','type':'string','minLength':3,'description':'The requested title'},
            'nested':{'$ref':'#/$defs/title'}},
        '$defs':{'title':{'title':'Nested schema','type':'object','properties':{'title':{'type':'integer','minimum':1}},'required':['title']}},
        'default':{'title':'Default title'},'examples':[{'title':'Example title'}],
        'enum':[{'title':'Literal title'}]}
    original=deepcopy(schema);wire=compact_titles(schema)
    assert schema==original and 'title' not in wire
    assert 'title' in wire['properties'] and 'title' in wire['$defs']
    assert wire['required']==['title','nested'] and wire['additionalProperties'] is False
    assert wire['properties']['title']=={'type':'string','minLength':3,'description':'The requested title'}
    for key in ('default','examples','enum'):assert wire[key]==schema[key]
    assert wire['properties']['nested']['$ref']=='#/$defs/title'
    assert wire['$defs']['title']['properties']['title']['minimum']==1


def test_nested_combinators_constraints_and_constant_objects_are_preserved():
    schema={'title':'Choice','anyOf':[{'title':'Tuple','type':'array','prefixItems':[
        {'title':'One','const':{'title':'literal'}},{'title':'Two','const':7}],'minItems':2,'maxItems':2},
        {'title':'Map','type':'object','additionalProperties':{'title':'Value','type':'number','minimum':0}}]}
    wire=compact_titles(schema)
    assert wire['anyOf'][0]['prefixItems'][0]['const']=={'title':'literal'}
    assert wire['anyOf'][0]['minItems']==wire['anyOf'][0]['maxItems']==2
    assert wire['anyOf'][1]['additionalProperties']=={'type':'number','minimum':0}
    assert compact_titles(False) is False
