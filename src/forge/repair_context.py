"""Remove duplicate debugging views without discarding source or requirements."""
import json

from forge.provider_errors import ProviderResourceError


def compact_repair_context(data,budget=22000):
    def fits():return len(json.dumps(data,separators=(',',':')))<=budget
    if fits():return data
    source=data.get('source',{})
    note='Diagnostic line/column coordinates refer to the complete current modules in source; duplicate excerpts are omitted.'
    for row in data.get('diagnostic_locations',[]):
        if row.get('file') in source and isinstance(source[row['file']].get('content'),str):
            row.pop('source_excerpt',None)
    data['diagnostic_source_reference']=note
    if fits():return data
    for row in data.get('diagnostic_locations',[]):
        content=source.get(row.get('file'),{}).get('content')
        line=row.get('line')
        if isinstance(content,str) and isinstance(line,int) and 1<=line<=len(content.splitlines()):
            if row.get('line_text')==content.splitlines()[line-1]:row.pop('line_text',None)
    if fits():return data
    # These derived obligations are consumed only by rejected-state cycle repair.
    # Ordinary diagnoses retain every original diagnostic and its exact expression.
    diagnostics={(row.get('file'),row.get('code'),row.get('message')) for row in data.get('diagnostic_locations',[])}
    if not data.get('rejected_state') and all(
        (row.get('file'),row.get('code'),row.get('message')) in diagnostics for row in data.get('failure_obligations',[])):
        data.pop('failure_obligations',None)
    if fits():return data
    raise ProviderResourceError('Repair context exceeds the complete-source budget after duplicate views were removed. Capacity pause; split the task before resuming. No source edit attempted.')
