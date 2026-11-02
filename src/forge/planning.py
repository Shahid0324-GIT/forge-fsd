"""Small role inputs grounded in the same contract, without generated-source feedback."""
from forge.contracts import record_shapes


INTAKE_INSTRUCTION = '''Route a request for ForgeFSD, a tool for building small single-user
Next.js web apps with a local model. Return intent=build when the app and functionality
are understandable. Optional styling, currency formatting, reset buttons, filters and
extra features are NOT blockers: use sensible defaults later. Do not ask for feature
expansions, filenames, API design, or decisions already answered in supplied clarifications.
Use clarify only when the business goal is genuinely indeterminate or needs unsupported
authentication, payments, external services, new dependencies or a different platform.
Give the concrete blocking reason and a focused business question.
Use help with the appropriate topic for explanations of Forge; out_of_scope for unrelated questions.
Help facts: requirements -> architecture -> acceptance planning -> human approval ->
generation -> isolated tests/repairs -> approved preview -> separately approved app CI
and deployment. Forge currently has no live weather, general web search, or unrestricted
execution tools. Do not invent live information, app status, or fetched sources.
A clear app request should produce only {"intent":"build"}.'''

HELP_RESPONSES={
    'workflow':'Forge gathers requirements, designs the app and acceptance checks, asks for plan approval, generates source, then runs isolated checks and bounded repairs. Preview and publishing/deployment have separate approvals.',
    'capabilities':'Forge supports bounded single-user Next.js apps with a stateless API or local SQLite. Authentication, payments, new dependencies and external services need additional implementation. Persistent SQLite apps cannot be deployed unchanged to Vercel.',
    'approvals':'You review the app plan before generation. Local preview, app publishing and cloud deployment each require separate approval. Model summaries do not count as passing tests.',
    'status':'Open the relevant run to inspect its saved activity and evidence. This intake response does not query or change another run.'}


BUSINESS_INSTRUCTION = '''You gather requirements for a small single-user web app.
The user describes functionality. Choose concrete, visible business defaults; never ask
the user for filenames, internal schemas or API designs. Preserve the requested domain.
Use database=sqlite for persisted records, none for stateless tools. Use one page unless
the request needs more. Pages are static HTML paths including /, not APIs.
Use separate entities for managed records or requested relationships; plain labels may use text or enums.
List stored business fields only: an integer id is supplied by the platform. Enum fields
MUST list actual choices; otherwise use text. References name an existing entity.
Numeric bounds use lower/upper objects with value and inclusive; string fields use length rules. Calculated outputs
belong in computed_outputs, not stored fields. Describe their formulas in the criteria.
Ask material business questions for ambiguous or unsupported requirements, not cosmetic
or technical choices. This platform has Next.js, React, Node SQLite, no authentication,
payments, external integrations or new packages. Never silently replace requested features.
Return the complete structured business brief. No code or claimed execution results.'''


API_INSTRUCTION = """You design BUSINESS OPERATIONS for the supplied app, not HTTP routing.
Choose unique operation ids describing behavior and associate requirement IDs.
Use entity actions create/list/read/update/delete for the supplied stored entities.
Their input/output types, identity inputs, HTTP methods, statuses and filenames are
compiled by the platform. Do not repeat those fields or invent framework paths.
Use action=custom for computations, aggregates and business-specific state changes.
Custom input/output types reference exact provided record names, primitives/arrays,
extra records declared in records, or none. The records property is REQUIRED: define
each new custom record and all its fields there; a type name alone is not a definition.
Set read_only truthfully. Declare success
and business error statuses; malformed JSON input automatically returns error 400.
Use the provided EmptyInput for an empty JSON object. Do not redefine entity/platform
types. Extra records contain concrete field names/types, not code or schema descriptions.
Cover the requested calculations, validations, persistence and state transitions.
Choose only operations needed for the request; the small-app operation budget is
encoded in the schema. Avoid duplicating standard entity actions as custom operations.
No unrelated features or claims that implementation/testing has happened."""


LAYOUT_INSTRUCTION = '''You are the implementation architect. Choose a compact UI and helper
layout for the supplied business/API contract. Implement exactly the approved pages.
Separate components and server helpers only when they help; an empty list is valid.
Respect the supplied file_budget shared between optional components and helpers.
Each page contains its component DEFINITIONS directly in components, never string
references to a separate registry. Components select the exact endpoint_ids they display or invoke and describe their UI
behavior. The compiler derives result props and callable callbacks from those operations.
Helpers select endpoint_ids they implement; the compiler derives their function names,
parameters and return types. Do not invent props, callbacks, functions or type signatures.
An operation can be assigned to at most one server helper. Empty helper/component lists
are valid when the page or route can implement its behavior directly.
Pages describe their user interactions and direct operation IDs, with
state refresh after mutations. Every business operation must be referenced by at least
one page or one of its components. Component operation IDs are automatically included
in their parent's context. Each page lists relevant requirement IDs. Function parameters
must include the actual data needed by their stated behavior; callbacks are callable
props, not internal event handlers. Prefer fewer modules over redundant indirection.
Choose names, not filenames: framework filenames are controller-derived. Client code
uses HTTP operations; database helpers remain server-only. Shared DTOs are provided by
lib/forge_contracts.ts and are imported with import type. No new packages, tests or execution claims.'''


ACCEPTANCE_INSTRUCTION = '''You design independent application checks from the original request
and approved typed operations, never from generated source. Reference operation_id, not
methods, paths or filenames. Those are compiled from the contract. For a path parameter,
provide path_captures with its exact parameter name and a PREVIOUSLY saved scalar capture.
Save a created id with save_as and save_pointer=/id. Body bindings replace EXISTING JSON
fixture values; never attach a body binding to a null body. Use native JSON, arrays for
array responses. For numeric capture fields put a numeric placeholder such as 0 in
the body or expected fixture, then bind that JSON pointer to the saved capture with
body_bindings or expect_bindings. Never put string templates into numeric fields.
Use null for unused body/expected assertions. Success status and JSON shapes
must match the operation. Negative fixtures may violate input validation and assert one
of its declared error statuses; avoid invented exact error-message assertions.
Include representative success and invalid-input cases, meaningful assertions for
requested calculations and changes, and requirement IDs. SQLite also needs a restart GET
asserting a separate record created and LEFT in storage during functional checks. Do not
delete the only persisted fixture and expect it to reappear. At most 40 steps total.
Never remove requested behavior to pass validation. No source code or claimed test results.'''


def business_context(brief, original_request):
    return {'original_request':original_request, 'title':brief.title,
            'requirements':{f'R{i+1}':text for i,text in enumerate(brief.acceptance_criteria)},
            'assumptions':brief.assumptions, 'database':brief.database, 'pages':brief.pages,
            'data_contract':brief.data_contract.model_dump() if brief.data_contract else None,
            'provided_records':{name:record.model_dump() for name,record in record_shapes(brief.data_contract).items()},
            'primitive_types':['string','number','boolean'], 'no_body_type':'none'}


def api_context(brief, api):
    return {'records':[record.model_dump() for record in api.records], 'operations':[{'id':e.id,'method':e.method,'path':e.path,
                'path_parameters':e.parameter_names,
                'input_type':e.input_type,'output_type':e.output_type,'success_status':e.success_status,
                'error_statuses':e.error_statuses,'behavior':e.behavior,'requirement_ids':e.requirement_ids} for e in api.endpoints]}
