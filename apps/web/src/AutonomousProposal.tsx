export type AutonomousDraft={
  title:string;
  design:string;
  database:'none'|'sqlite';
  files:{path:string;owner:string;purpose:string}[];
  acceptance_criteria:string[];
  test_strategy:string;
  assumptions:string[];
};

export default function AutonomousProposal({draft}:{draft:AutonomousDraft}){
  return <div>
    <h3>{draft.title}</h3>
    <p className="hint">Design proposal only. No application was built or verified by this planning step.</p>
    <h3>Agent-authored design</h3><p style={{whiteSpace:'pre-wrap'}}>{draft.design}</p>
    <p><strong>Storage:</strong> {draft.database==='none'?'No database':draft.database}</p>
    <h3>Requested behavior</h3>
    <ul>{draft.acceptance_criteria.map((criterion,index)=><li key={index}>{criterion}</li>)}</ul>
    <h3>Proposed responsibilities</h3>
    {draft.files.map(file=><details key={file.path}><summary>{file.path} · {file.owner}</summary><p>{file.purpose}</p></details>)}
    <h3>Suggested checks · not executed</h3><p>{draft.test_strategy}</p>
    {draft.assumptions.length>0&&<><h3>Assumptions to review</h3><ul>{draft.assumptions.map((assumption,index)=><li key={index}>{assumption}</li>)}</ul></>}
  </div>;
}
