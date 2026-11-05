"""Agent-owned module/API agreements; the controller supplies no app-specific design."""
from typing import Literal

from pydantic import Field

from forge.tasks import Envelope


class SharedInterface(Envelope):
    name: str = Field(min_length=1,max_length=120)
    provider: str = Field(min_length=1,max_length=200,description='Declared file implementing this interface.')
    consumers: list[str] = Field(min_length=1,max_length=20,description='Declared files using this interface.')
    kind: Literal['module','http','server_action']
    contract: str = Field(min_length=1,max_length=1800,
        description='Your exact shared exports/props/types, or HTTP methods/paths/request-response shapes, or async server-action signatures. Choose app-specific names and types yourself.')


def interface_issues(draft):
    paths={file.path for file in draft.files};issues=[];names=set()
    for interface in draft.interfaces:
        if interface.name in names:issues.append('Shared interface names must be unique: '+interface.name)
        names.add(interface.name)
        if interface.provider not in paths:issues.append('Interface provider is outside the manifest: '+interface.provider)
        if len(set(interface.consumers))!=len(interface.consumers):issues.append('Interface consumers must be unique: '+interface.name)
        for consumer in interface.consumers:
            if consumer not in paths:issues.append('Interface consumer is outside the manifest: '+consumer)
            if consumer==interface.provider:issues.append('An interface cannot depend on itself: '+interface.name)
    roles={file.owner for file in draft.files}
    if len(roles)>1 and not draft.interfaces:
        issues.append('Multiple source owners need agent-authored shared interfaces before delegation. Agree on the public boundary yourselves; do not ask the user for types, API paths or folder structure.')
    if not issues:
        try:implementation_order(draft)
        except ValueError as exc:issues.append(str(exc))
    return issues


def implementation_order(draft):
    dependencies={file.path:set() for file in draft.files}
    for interface in draft.interfaces:
        if interface.provider not in dependencies:raise ValueError('Unknown interface provider: '+interface.provider)
        for consumer in interface.consumers:
            if consumer not in dependencies:raise ValueError('Unknown interface consumer: '+consumer)
            dependencies[consumer].add(interface.provider)
    ordered=[];remaining=list(draft.files);done=set()
    while remaining:
        ready=next((file for file in remaining if dependencies[file.path]<=done),None)
        if ready is None:raise ValueError('Shared-interface dependency cycle. Revise the agent-owned boundaries before implementation; do not delegate the cycle to the user.')
        ordered.append(ready);done.add(ready.path);remaining.remove(ready)
    return ordered


def interfaces_for(draft,targets):
    selected=set(targets)
    return [interface.model_dump() for interface in draft.interfaces
        if interface.provider in selected or selected.intersection(interface.consumers)]
