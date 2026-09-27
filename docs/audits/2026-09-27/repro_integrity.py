import asyncio
from sqlalchemy import update
from agent_eval_redteam.adapters.repositories import Repository, traces
from agent_eval_redteam.domain.services import EvalPlatform, bootstrap
from agent_eval_redteam.workflows.primary import run_primary
async def main():
 p=EvalPlatform(Repository('sqlite://'));bootstrap(p)
 p.authorize_security_testing(agent_id='support-bot@1.0.0',approved_by='security',categories=['pii','prompt_injection'],reason='Isolated evidence integrity audit')
 p.repo.create_run(run_id='integrity',agent_id='support-bot@1.0.0',suite_id='support-core',suite_version='1.0.0',requested_by='alice',idempotency_key=None,baseline_run_id=None)
 async def stop(ctx,env): raise RuntimeError('intentional pause before score')
 await run_primary('integrity',p.env,actor='alice',overrides={'Score traces':stop})
 t=p.repo.traces_for('integrity')[0]
 changed=t.model_dump(mode='json'); changed['final_output'] += ' altered content'
 with p.repo.engine.begin() as conn:
  conn.execute(update(traces).where(traces.c.trace_id==t.trace_id).values(body=changed))
 print('integrity_before_scoring',p.get_trace(t.trace_id)['integrity_ok'])
 r=await p.resume_run('integrity',actor='alice')
 print('after_scoring',r.status,r.release_decision,'case_count',r.scorecard['n_cases'])
 p.repo.close()
asyncio.run(main())

