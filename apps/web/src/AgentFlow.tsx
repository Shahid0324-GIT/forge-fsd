type WorkflowEvent={sequence:number;timestamp:string;status:string;payload:Record<string,any>};
type Props={workflow?:'typed'|'autonomous';events:WorkflowEvent[];busy:boolean;status:string;onContext:(event:WorkflowEvent)=>void};

const roles:Record<string,string>={IntakeDecision:'Intake',BusinessBrief:'Requirements',ApiDesign:'API architect',ApiProposal:'API architect',LayoutDesign:'Implementation architect',AcceptanceDesign:'Acceptance planner',api_architect:'API architect',implementation_architect:'Implementation architect',FileOperation:'Builder',RequirementsDocument:'Requirements',AppBrief:'Requirements',AppRequirements:'Requirements',AppImplementationPlan:'Architect',ImplementationPlan:'Architect',NativeAcceptancePlan:'Acceptance planner',ArchitectureReview:'Architecture reviewer',AcceptanceReview:'Acceptance reviewer',AppAcceptancePlan:'QA',architecture_reviewer:'Architecture reviewer',acceptance_reviewer:'Acceptance reviewer',requirements_agent:'Requirements',architect_agent:'Architect',qa:'Test planning & repair',backend_builder:'Backend',frontend_builder:'Frontend',implementation_coordinator:'Build coordinator',verification:'Test runner',ci_agent:'App CI',deployment_agent:'Deployment'};
const name=(value:string)=>(value==='LayoutProposal'?'Implementation architect':roles[value])??value?.replaceAll('_',' ')??'Agent';
Object.assign(roles,{AppDraft:'Planner',RecoveryDecision:'Senior reviewer',requirements:'Requirements',planner:'Planner',senior_reviewer:'Senior reviewer'});
Object.assign(roles,{SourceEdit:'Source builder',RepairFocus:'QA diagnosis',builder:'Builder',frontend:'Frontend',backend:'Backend'});
Object.assign(roles,{SourceText:'Source builder',SourceTarget:'Repair target selection',CycleRepairActions:'Cycle recovery plan'});
Object.assign(roles,{AcceptanceSuite:'Acceptance QA',acceptance_qa:'Acceptance QA',CoverageDecision:'Coverage review',coverage_reviewer:'Coverage review'});
Object.assign(roles,{AcceptanceCritique:'Test quality review',acceptance_reviewer:'Test quality review'});
Object.assign(roles,{ClarificationReview:'Requirements review',intake_reviewer:'Requirements review'});
Object.assign(roles,{ScopeAssessment:'Requirements scope review',requirements_reviewer:'Requirements scope review'});
export function conciseIssue(message:string):string{
  if(message.includes('Failed to parse')){
    const role=message.includes('AcceptancePlan')?'QA':message.includes('AppBrief')?'Requirements':'Planning';
    return `${role} returned a proposal that failed validation. Open Activity for the saved details.`;
  }
  return message.length>500?message.slice(0,500)+'… Full details are saved in Activity.':message;
}
const steps=[['Requirements',['REQUIREMENTS','REQUIREMENTS_READY']],['Architect',['PLANNING']],['Test planning',['TEST_PLANNING']],['Builders',['BUILDING','REPAIRING']],['Verification',['VERIFYING','FUNCTIONALLY_VERIFIED']],['Security',['SECURITY_CHECK','SECURITY_PASSED']],['Release',['CI_PLANNING','DEPLOYMENT_PLANNING']]] as const;
const summaries:Record<string,[string,string]>={
  AUTONOMOUS_DRAFT_READY:['Design proposal saved','Review the agent-authored design. No app has been built yet.'],
  AUTONOMOUS_INPUT_NEEDED:['Requirements intake','A blocking business question needs your answer.'],
  AUTONOMOUS_PAUSED:['Planning paused','The saved task can be inspected before continuing.'],
  AUTONOMOUS_REPLANNING:['Review feedback','Requirements intake is checking the requested changes before a new proposal.'],
  AUTONOMOUS_APPROVED:['Plan approved','Source generation is authorized; preview and publishing are separate decisions.'],
  AUTONOMOUS_REJECTED:['Plan declined','Source generation was not authorized.'],
  AUTONOMOUS_BUILDING:['Implementation','Generating the reviewed source and using actual checks for repairs.'],
  AUTONOMOUS_BUILD_PAUSED:['Build paused','Source, approval and task history are retained for inspection/resume.'],
  AUTONOMOUS_BUILD_CHECKS_PASSED:['Build checks passed','TypeScript and production build passed. Application behavior remains unverified.'],
  AUTONOMOUS_TESTING:['App checks','Defining independent assertions and checking actual behavior against them.'],
  AUTONOMOUS_ACCEPTANCE_FROZEN:['Assertions frozen','Requirements-derived checks are saved outside the app source. They have not passed by proposal alone.'],
  AUTONOMOUS_TEST_PAUSED:['App checks paused','Source, assertions and recovery evidence are retained.'],
  AUTONOMOUS_CHECKS_BLOCKED:['Coverage needs attention','Some approved criteria require checks beyond the current browser protocol.'],
  AUTONOMOUS_APP_CHECKS_PASSED:['Selected app checks passed','Build and frozen browser assertions passed for the saved source. Preview and release are separate.'],
  TOOL_CALL_STARTED:['Workspace tool','Executing a scoped tool operation.'],
  TOOL_CALL_COMPLETED:['Workspace tool','A tool returned evidence; inspect its scope before claiming success.'],
  TASK_ACTION_STARTED:['Task dispatch','An agent is working on its assigned task.'],
  TASK_RECOVERY_PLANNED:['Senior review','A recovery strategy was saved for the next attempt.'],
  TASK_PAUSED:['Task paused','Task history and observations are retained.'],
  REQUIREMENTS:['Requirements agent','Turning your idea into a business brief.'],
  REQUIREMENTS_READY:['Requirements saved','The shared brief is available below.'],
  PLANNING:['Architect agent','Designing interfaces, data storage and file ownership.'],
  TEST_PLANNING:['Acceptance planning agent','Defining what the finished app must do. No application tests are running yet.'],
  PLAN_REVIEW:['Your review','The plan and proposed checks are ready for your approval.'],
  APPROVED:['Plan approved','Builders can now work from the reviewed contract.'],
  BUILDING:['Builders','Generating the approved application files.'],
  VERIFYING:['Test runner','Running the configured build and application checks.'],
  REPAIRING:['Repair workflow','Using saved failure evidence to correct the application.'],
  REPAIR_DIAGNOSIS:['QA diagnosis','A repair diagnosis was saved for the responsible builder.'],
  FUNCTIONALLY_VERIFIED:['Application checks passed','The configured functional checks passed for this source.'],
  SECURITY_CHECK:['Security checks','Evaluating the configured policy gates.'],
  SECURITY_PASSED:['Configured gates passed','A local preview can be requested with your approval.'],
  CI_PLANNING:['App CI agent','Preparing checks for the generated app repository.'],
  DEPLOYMENT_PLANNING:['Deployment agent','Preparing the generated app release plan.'],
};

function describe(event:WorkflowEvent):[string,string]{
  const p=event.payload;
  if(event.status==='MODEL_ROUTED')return [String(p.model).startsWith('groq:')?'Groq assistance selected':'Local 7B selected',String(p.reason)];
  if(event.status==='TOOL_CALL_STARTED'||event.status==='TOOL_CALL_COMPLETED')return [p.tool==='check_build'?'Isolated verification':String(p.tool??'Workspace tool').replaceAll('_',' '),String(p.summary??'A scoped tool call was recorded.')];
  if(event.status==='TASK_ACTION_STARTED')return [name(p.task_state?.inflight_role??p.owner),String(p.summary??'Task dispatched.')];
  if(event.status==='PLANNING_QUALITY_REVIEW')return [name(p.reviewer),p.issues?.length?p.issues.join(' '):p.summary];
  if(event.status==='AGENT_HANDOFF')return [`${name(p.sender)} → ${name(p.recipient)}`,String(p.summary??'Saved context supplied to the next role.')];
  if(event.status==='AGENT_CALL_STARTED')return [`${name(p.schema)} · model call`, `Generating a structured proposal${p.attempt>1?` · correction attempt ${p.attempt}`:''}.`];
  if(event.status==='AGENT_CALL_FAILED')return [`${name(p.schema)} · call failed`,String(p.summary??'The model call failed. Open its recorded call for details.')];
  if(event.status==='AGENT_CALL_COMPLETED')return [`${name(p.schema)} · response validated`,'The response passed its schema checks. Application tests have not been implied.'];
  if(event.status==='AGENT_VALIDATION_FAILED')return [`${name(p.schema)} · ${p.retrying?'correcting proposal':'needs attention'}`,String(p.summary??'Proposal validation failed.')];
  if(event.payload.reason)return ['Step needs attention',conciseIssue(String(event.payload.reason))];
  const fallback=summaries[event.status]??[event.status.toLowerCase().replaceAll('_',' '),'Recorded workflow update.'];
  return [p.delegated_to&&event.status!=='TEST_PLANNING'?`${name(p.delegated_to)} agent`:fallback[0],p.file?`Working on ${p.file}`:p.summary??fallback[1]];
}

export default function AgentFlow({workflow,events,busy,status,onContext}:Props){
  const autonomous=workflow==='autonomous';
  const routes=autonomous?[['Requirements',['requirements','intake_reviewer']],['Planner',['planner']],['Implementation',['builder','frontend','backend','qa']],['Senior review',['senior_reviewer']],['Acceptance QA',['acceptance_qa']],['Test quality',['acceptance_reviewer','requirements_reviewer']],['Coverage review',['coverage_reviewer']],['Verification',['verification']]] as const:steps;
  const routeRole=(event:WorkflowEvent)=>event.status==='TOOL_CALL_STARTED'&&event.payload.tool==='check_build'?'verification':event.status==='TASK_ACTION_STARTED'?(event.payload.task_state?.task?.inputs?.stage==='acceptance_plan'?'acceptance_qa':event.payload.task_state?.inflight_role):event.status==='AGENT_HANDOFF'?event.payload.recipient:'';
  const visible=events.filter(e=>e.status in summaries||['MODEL_ROUTED','PLANNING_QUALITY_REVIEW','AGENT_HANDOFF','AGENT_CALL_STARTED','AGENT_CALL_COMPLETED','AGENT_CALL_FAILED','AGENT_VALIDATION_FAILED','FAILED','VERIFICATION_FAILED','SECURITY_BLOCKED','INTERRUPTED','CANCELLED'].includes(e.status));
  const recent=visible.slice(-8).reverse();
  const active=autonomous?events.filter(e=>e.status==='TASK_ACTION_STARTED'||e.status==='TOOL_CALL_STARTED'&&e.payload.tool==='check_build').at(-1):events.filter(e=>steps.some(([,statuses])=>(statuses as readonly string[]).includes(e.status))).at(-1);
  const failed=['FAILED','VERIFICATION_FAILED','SECURITY_BLOCKED','INTERRUPTED'].includes(status);
  return <section className="panel agent-flow" aria-labelledby="agent-flow-title">
    <div className="panel-title"><div><span className="eyebrow">YOUR TEAM IN ACTION</span><h2 id="agent-flow-title">Follow the work as it happens.</h2></div><span className={`flow-state ${busy?'is-live':''}`} role="status"><span/>{busy?'Working':failed?'Needs attention':status==='PLAN_REVIEW'?'Awaiting your review':'Saved progress'}</span></div>
    <p className="flow-intro">Live actions, decisions and saved handoffs from your agent team.</p>
    <ol className="agent-route" aria-label="Agent workflow">{routes.map(([label,statuses])=>{
      const visited=events.some(e=>(statuses as readonly string[]).includes(autonomous?routeRole(e):e.status));
      const current=active&&(statuses as readonly string[]).includes(autonomous?routeRole(active):active.status);
      return <li key={label} className={current?(busy?'route-active':failed?'route-attention':'route-current'):visited?'route-visited':''}><span/>{label}{current&&<small>{busy?'Active':failed?'Paused':'Latest'}</small>}</li>;
    })}</ol>
    <div className="flow-updates" role="log" aria-label="Recent agent activity" aria-live="polite" aria-relevant="additions text">
      {recent.length===0?<p className="muted">Agent activity will appear when planning starts.</p>:recent.map(event=>{
        const [title,summary]=describe(event);
        const handoff=event.status==='AGENT_HANDOFF';
        const warning=event.status==='AGENT_VALIDATION_FAILED'||event.status==='AGENT_CALL_FAILED'||event.status==='FAILED'||(event.status==='PLANNING_QUALITY_REVIEW'&&event.payload.issues?.length>0);
        return <article key={event.sequence} className={`flow-update ${handoff?'flow-handoff':''} ${warning?'flow-warning':''}`}>
          <span className="flow-marker" aria-hidden="true">{handoff?'↗':warning?'!':'·'}</span>
          <div className="flow-body"><div className="flow-update-heading"><h3>{title}</h3><time dateTime={event.timestamp}>{new Date(event.timestamp).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})}</time></div><p>{summary}</p>
            {['AGENT_CALL_COMPLETED','AGENT_CALL_FAILED','AGENT_VALIDATION_FAILED'].includes(event.status)&&event.payload.report&&<button className="text-button" onClick={()=>onContext(event)}>Inspect recorded call →</button>}
            {handoff&&<details><summary>What was shared</summary><p>{(event.payload.context_fields??[]).map((field:string)=>field.replaceAll('_',' ')).join(' · ')}</p><button className="text-button" onClick={()=>onContext(event)}>Open saved context →</button></details>}
            {event.status==='AGENT_VALIDATION_FAILED'&&<small>{event.payload.retrying?'A bounded correction is being requested automatically.':event.payload.schema==='FileOperation'?'Correction attempts ended. This generated file was not accepted.':'Correction attempts ended. The run remains unapproved.'}</small>}
          </div>
        </article>;
      })}
    </div>
    <p className="flow-footnote">Activity summaries describe recorded actions. Full history and evidence remain in the tabs.</p>
  </section>;
}
