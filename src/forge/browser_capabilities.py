"""Shared facts about the trusted browser runner, not model-granted permissions."""


def browser_capabilities():
    return {
        'actions':['visit/reload within one session','click','fill','select','check',
            'assert_visible','assert_text','assert_value','assert_count','assert_title'],
        'targets':['accessible role and name','label','text','placeholder'],
        'unsupported':['CSS/XPath selectors','attribute assertions','keyboard actions',
            'storage/cookie inspection','screen-reader execution','server/container restart',
            'database filesystem inspection','security scans','cloud deployment'],
        'coverage':'Keep acceptance criteria atomic when possible. Preserve requested unsupported behavior; disclose it as unverified. '
            'For mixed criteria, scenarios can exercise checked_behavior while an uncovered coverage=partial entry explains the remaining gap. '
            'Partial coverage cannot establish complete app success.',
        'scope':'Use the actual response schema. Prior model suggestions cannot add capabilities; '
            'retain genuinely unsupported criteria or remaining aspects as uncovered.',
    }
