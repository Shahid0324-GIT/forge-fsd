from forge.source_scope import scope_source,resolve_import


def packet(content):return {'content':content,'sha256':'a'*64}


def test_missing_helper_receives_actual_consumers_without_unrelated_ui_and_config():
    source={'app/api/items/route.ts':packet("import {list} from '@/lib/store'; export function GET(){return list()}"),
        'app/page.tsx':packet("export default function Page(){return <main>UI</main>}"),
        'tsconfig.json':packet('{}'),'lib/types.ts':packet('export interface Item {id:number}')}
    scoped,omitted,inventory=scope_source(source,['lib/store.ts'],[*source,'lib/store.ts'])
    assert set(scoped)=={'app/api/items/route.ts','lib/types.ts'}
    assert {item['file'] for item in omitted}=={'app/page.tsx','tsconfig.json'}
    assert all(item['sha256']=='a'*64 for item in omitted)
    assert next(item for item in inventory if item['file']=='lib/store.ts')['exists'] is False


def test_page_sees_http_handlers_layout_and_actual_direct_imports():
    source={'app/page.tsx':packet("import {Panel} from './components/Panel'"),
        'app/components/Panel.tsx':packet('export function Panel(){}'),
        'app/api/items/route.ts':packet('export function GET(){}'),
        'app/layout.tsx':packet('layout'),'lib/store.ts':packet('server body'),'app/globals.css':packet('css')}
    scoped,_,_=scope_source(source,['app/page.tsx'],source)
    assert set(scoped)=={'app/page.tsx','app/components/Panel.tsx','app/api/items/route.ts','app/layout.tsx'}


def test_nested_page_keeps_actual_http_interfaces_without_server_implementation_bodies():
    source={'app/items/page.tsx':packet('export default function Page(){}'),
        'app/api/items/route.ts':packet("import {list} from '@/lib/store'"),
        'lib/store.ts':packet('server implementation'),'app/layout.tsx':packet('layout')}
    scoped,omitted,_=scope_source(source,['app/items/page.tsx'],source)
    assert set(scoped)=={'app/items/page.tsx','app/api/items/route.ts','app/layout.tsx'}
    assert {row['file'] for row in omitted}=={'lib/store.ts'}


def test_repair_can_include_multiple_diagnostic_modules_and_css_consumers():
    source={'app/page.tsx':packet('page'),'app/layout.tsx':packet("import './globals.css'"),
        'app/globals.css':packet('css'),'lib/math.ts':packet('helper')}
    scoped,_,_=scope_source(source,['app/globals.css','lib/math.ts'],source)
    assert set(scoped)==set(source)


def test_relative_alias_index_and_incorrect_relative_candidates_are_snapshot_only():
    paths={'lib/store.ts','app/components/Panel/index.tsx','app/api/items/route.ts'}
    assert resolve_import('app/api/items/route.ts','@/lib/store',paths)=={'lib/store.ts'}
    assert resolve_import('app/page.tsx','./components/Panel',paths)=={'app/components/Panel/index.tsx'}
    assert resolve_import('app/page.tsx','../api/items/route',paths)=={'app/api/items/route.ts'}
    assert resolve_import('app/page.tsx','node:fs',paths)==set()
    assert resolve_import('app/page.tsx','../../outside',paths)==set()
