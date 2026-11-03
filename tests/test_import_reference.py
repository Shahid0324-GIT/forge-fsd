from forge.import_reference import relative_import_reference


def missing(module):return f"Cannot find module '{module}' or its corresponding type declarations."


def test_relative_path_is_resolved_from_importer_and_route_boundary_is_visible():
    result=relative_import_reference('app/page.tsx',missing('../api/records/route'),
        {'app/api/records/route.ts':{},'app/api/other/route.ts':{}})
    assert result['resolved_base']=='api/records/route'
    assert result['existing_resolution']==[]
    assert result['existing_suffix_candidates']==[{
        'file':'app/api/records/route.ts','relative_specifier':'./api/records/route',
        'module_kind':'next_http_route','http_route':'/api/records',
        'boundary':'HTTP handler module, not a client helper. Client components call its endpoint with fetch rather than importing handlers.'}]


def test_server_helper_candidate_does_not_invent_exports_or_orm_interface():
    result=relative_import_reference('app/api/records/route.ts',missing('../../lib/store'),{'lib/store.ts':{}})
    assert result['resolved_base']=='app/lib/store'
    assert result['existing_suffix_candidates']==[{'file':'lib/store.ts','relative_specifier':'../../../lib/store'}]


def test_resolving_import_is_not_replaced_with_a_suffix_guess():
    result=relative_import_reference('app/page.tsx',missing('./components/card'),
        {'app/components/card/index.tsx':{},'other/components/card.tsx':{}})
    assert result['existing_resolution']==['app/components/card/index.tsx']
    assert result['existing_suffix_candidates']==[]


def test_candidates_are_ambiguous_bounded_and_snapshot_only():
    source={f'feature{i}/widget.tsx':{} for i in range(8)}
    result=relative_import_reference('app/page.tsx',missing('../widget'),source)
    assert len(result['existing_suffix_candidates'])==5
    assert result['additional_candidates_omitted']==3
    assert relative_import_reference('app/page.tsx',missing('../absent'),source)['existing_suffix_candidates']==[]


def test_external_aliases_and_other_errors_do_not_get_guessed_resolution():
    for message in [missing('some-package'),missing('@/lib/store'),'Unexpected expression']:
        assert relative_import_reference('app/page.tsx',message,{}) is None


def test_explicit_extension_and_outside_root_are_reported_without_reading_disk():
    result=relative_import_reference('app/page.tsx',missing('../../private.ts'),{'private.ts':{}})
    assert result['resolved_base']=='../private.ts'
    assert result['existing_resolution']==[]
    # Explicit extensions are not silently rewritten or resolved outside the snapshot.
    assert result['existing_suffix_candidates']==[]
