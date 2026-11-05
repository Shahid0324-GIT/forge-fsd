"""Shared facts about the trusted browser runner, not model-granted permissions."""
import hashlib
from pathlib import Path

MAX_SCENARIOS=6
MAX_SUITE_STEPS=96


def browser_capabilities():
    root=Path(__file__).resolve().parents[2]
    protocol=hashlib.sha256(b''.join((root/path).read_bytes() for path in
        ('tests/acceptance/browser-protocol.mjs','tests/acceptance/browser.mjs'))).hexdigest()
    return {
        'protocol_sha256':protocol,
        'actions':['visit','click','fill','select','check',
            'assert_visible','assert_text','assert_value','assert_count','assert_title'],
        'navigation_semantics':{
            'visit':{'implementation':'Playwright page.goto',
                'navigation':'full_document','client_router_navigation':False,
                'same_path_visit':'Reloads the document and resets JavaScript in-memory state.',
                'browser_context':'The same browser context is retained within a scenario; localStorage, sessionStorage and cookies survive the document navigation.',
                'server_restart':False},
            'reload_action':'There is no separate reload verb. Use visit with the same path for a full document reload.'},
        'scenario_session':{'isolation':'Fresh browser context per scenario.',
            'credentials':'The runner supplies no login credentials, preloaded cookies or storage state.',
            'service_workers':'blocked',
            'guest_access':'Visiting and using the app in this fresh context can check that the exercised workflow does not require login; this does not prove all security properties.'},
        'targets':['accessible role and name','label','text','placeholder'],
        'work_budget':{'max_scenarios':MAX_SCENARIOS,'max_total_steps':MAX_SUITE_STEPS,
            'scope':'The step budget is shared across the complete suite. Keep a stateful sequence intact; do not remove observations to fit an artificial per-scenario quota.'},
        'assertion_semantics':{
            'assert_text':'Exact complete visible innerText of one semantic target, including descendants; whitespace normalized. '
                'A container with multiple rows cannot equal just one row. Combine its entire expected text into one assertion or target a smaller element. No substring operator.',
            'assert_value':'Exact input value, not visible text or an accessible name.',
            'assert_count':'Exact number of matches; it does not inspect attributes.',
            'target_matching':'Exact accessible name, label, text or placeholder. Accessible names do not replace innerText. '
                'Single-element actions require one match; assert_count intentionally allows multiple matches. '
                'Framework accessibility nodes may share roles with app nodes: Next.js can supply a route-announcer alert. '
                'Do not assume an unnamed alert target identifies only the app validation message; choose unambiguous names or exact visible text.'},
        'unsupported':['CSS/XPath selectors','attribute assertions','keyboard actions',
            'storage/cookie inspection','screen-reader execution','server/container restart',
            'database filesystem inspection','security scans','cloud deployment'],
        'coverage':'Keep acceptance criteria atomic when possible. Preserve requested unsupported behavior; disclose it as unverified. '
            'For mixed criteria, scenarios can exercise checked_behavior while an uncovered coverage=partial entry explains the remaining gap. '
            'Partial coverage cannot establish complete app success.',
        'scope':'Use the actual response schema. Prior model suggestions cannot add capabilities; '
            'retain genuinely unsupported criteria or remaining aspects as uncovered.',
    }
