"""Shared facts about the trusted browser runner, not model-granted permissions."""


def browser_capabilities():
    return {
        'actions':['visit/reload within one session','click','fill','select','check',
            'assert_visible','assert_text','assert_value','assert_count','assert_title'],
        'targets':['accessible role and name','label','text','placeholder'],
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
