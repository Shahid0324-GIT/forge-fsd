"""Lossless validation-schema transport compaction; application values stay intact."""
from copy import deepcopy

_MAPS={'properties','$defs','definitions','patternProperties','dependentSchemas'}
_LISTS={'allOf','anyOf','oneOf','prefixItems'}
_CHILDREN={'items','contains','not','if','then','else','additionalProperties',
    'unevaluatedProperties','unevaluatedItems','additionalItems','propertyNames','contentSchema'}


def compact_titles(schema):
    """Omit schema-node title annotations, never a property/default named title.

    Descriptions, required/default values, references and validation keywords are
    retained. The original Pydantic schema is never mutated.
    """
    if isinstance(schema,list):return [compact_titles(item) for item in schema]
    if not isinstance(schema,dict):return deepcopy(schema)
    result={}
    for key,value in schema.items():
        if key=='title':continue
        if key in _MAPS and isinstance(value,dict):
            result[key]={name:compact_titles(child) for name,child in value.items()}
        elif key in _LISTS or key in _CHILDREN:result[key]=compact_titles(value)
        else:result[key]=deepcopy(value)
    return result
