from agent_eval_redteam.domain.services import bundled_suites
from agent_eval_redteam.domain.scoring import score_trace
from agent_eval_redteam.domain.project_models import Trace
from agent_eval_redteam.adapters.sandbox import Sandbox
s=bundled_suites()[1]; c=s.case('cal-out-of-scope') if any(c.case_id=='cal-out-of-scope' for c in s.cases) else next(c for c in s.cases if c.expect.must_abstain)
t=Trace(trace_id='t',run_id='r',case_id=c.case_id,phase='baseline',repeat=0,agent_id='a',model='claude-opus-5',final_output='NEEDS_EVIDENCE',stop_reason='model_context_window_exceeded')
r=score_trace(c,s,t,Sandbox.for_case(c).sensitive_by_owner())
print('context_truncation', c.case_id, 'passed=', r.passed, 'recovery_applicable=', r.dimensions['recovery'].applicable)
