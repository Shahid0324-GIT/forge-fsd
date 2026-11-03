import {useState} from 'react';

export type ReviewControls={
  enabled:boolean;
  onDecision:(action:'approve'|'reject',fingerprint:string)=>void;
  onChanges:(fingerprint:string,feedback:string)=>void;
};

export default function AutonomousDecision({fingerprint,controls}:{fingerprint:string;controls:ReviewControls}){
  const [consent,setConsent]=useState(false);
  const [feedback,setFeedback]=useState('');
  return <section aria-labelledby="autonomous-decision-title">
    <h3 id="autonomous-decision-title">Your decision</h3>
    <p>Approval starts source generation, automatic repair and isolated build checks, followed by independent requirements-derived browser checks. Missing coverage remains visible.</p>
    {!controls.enabled&&<p className="hint">Load the current proposal or wait for active work to finish before deciding.</p>}
    <label className="consent"><input type="checkbox" checked={consent} disabled={!controls.enabled} onChange={event=>setConsent(event.target.checked)}/> I approve source generation and isolated development checks for this plan.</label>
    <div className="decision-actions">
      <button type="button" className="primary" disabled={!controls.enabled||!consent} onClick={()=>controls.onDecision('approve',fingerprint)}>Approve &amp; build</button>
      <button type="button" className="secondary" disabled={!controls.enabled} onClick={()=>controls.onDecision('reject',fingerprint)}>Decline plan</button>
    </div>
    <form onSubmit={event=>{event.preventDefault();if(controls.enabled&&feedback.trim())controls.onChanges(fingerprint,feedback.trim());}}>
      <label className="question" htmlFor="review-feedback">Requested changes<textarea id="review-feedback" value={feedback} maxLength={2000} disabled={!controls.enabled} onChange={event=>setFeedback(event.target.value)} placeholder="Describe what should change in the proposed app."/></label>
      <button type="submit" className="secondary" disabled={!controls.enabled||!feedback.trim()}>Request changes</button>
    </form>
    <p className="muted">Routine code fixes and test iterations do not need another approval. Preview and publishing remain separate decisions.</p>
  </section>;
}
