import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd() / 'src'))
from agent_eval_redteam.adapters.repositories import Repository, traces
from agent_eval_redteam.domain.services import EvalPlatform, bootstrap
from agent_eval_redteam.adapters.agents import ScriptedAgent
from agent_eval_redteam.workflows.primary import run_primary
from sqlalchemy import delete

def platform():
    p = EvalPlatform(Repository('sqlite://')); bootstrap(p)
    for aid in ['support-bot@1.0.0','support-bot@1.1.0-rc1']:
        p.authorize_security_testing(agent_id=aid, approved_by='sec', categories=['pii','prompt_injection'], reason='Audit test window')
    return p
async def run(p, aid='support-bot@1.0.0', **kw):
    return await p.start_run(agent_id=aid, suite_id='support-core', suite_version='1.0.0', requested_by='alice', **kw)

async def main():
    p=platform(); real=p.repo.save_artifact
    def crash(run_id,step,payload):
        result=real(run_id,step,payload)
        if step=='Gate release': raise RuntimeError('simulated process death after gate commit')
        return result
    p.repo.save_artifact=crash
    try: await run(p,'support-bot@1.1.0-rc1',idempotency_key='crash')
    except RuntimeError: pass
    rid=p.repo.run_by_idempotency_key('crash')['run_id']
    print('CRASH_GATE before',p.get_run(rid).status,p.get_run(rid).release_decision)
    p.repo.save_artifact=real
    result=await p.resume_run(rid,actor='alice')
    print('CRASH_GATE after',result.status,result.release_decision,'approval=',p.repo.get_approval(rid,'Gate release'),'monitor=',result.steps[-1].done)
    try: await p.decide_gate(run_id=rid,approver='bob',decision='approve',reason='Review the recovery result')
    except Exception as e: print('CRASH_GATE approval now fails:',str(e))
    p.repo.close()

    p=platform()
    class Slow(ScriptedAgent):
        calls=0
        async def run(self,prompt,sandbox,*,repeat):
            Slow.calls+=1
            await asyncio.sleep(.002)
            return await super().run(prompt,sandbox,repeat=repeat)
    p.env.adapter_factory=lambda a:Slow([])
    p.repo.create_run(run_id='parallel',agent_id='support-bot@1.0.0',suite_id='support-core',suite_version='1.0.0',requested_by='alice',idempotency_key=None,baseline_run_id=None)
    results=await asyncio.gather(p.resume_run('parallel',actor='alice'),p.resume_run('parallel',actor='bob'),return_exceptions=True)
    print('CONCURRENT statuses',[r.status if hasattr(r,'status') else str(r) for r in results], 'calls=',Slow.calls,'traces=',len(p.repo.traces_for('parallel')))
    print('CONCURRENT run_completed=',sum(e['event_type']=='run_completed' for e in p.audit_trail('parallel')))
    p.repo.close()

    p=platform(); rid='missing-traces'
    p.repo.create_run(run_id=rid,agent_id='support-bot@1.0.0',suite_id='support-core',suite_version='1.0.0',requested_by='alice',idempotency_key=None,baseline_run_id=None)
    async def stop(ctx,env): raise RuntimeError('stop before scoring')
    await run_primary(rid,p.env,actor='alice',overrides={'Score traces':stop})
    keep=next(t for t in p.repo.traces_for(rid) if t.phase=='baseline')
    with p.repo.engine.begin() as c: c.execute(delete(traces).where(traces.c.run_id==rid,traces.c.trace_id!=keep.trace_id))
    result=await p.resume_run(rid,actor='alice')
    print('MISSING_TRACES',result.status,result.release_decision,'n_cases=',result.scorecard['n_cases'],'stored_traces=',len(p.repo.traces_for(rid)))
    p.repo.close()

    p=platform(); accepted=await run(p)
    # Populate 50 newer scored/review runs, equivalent persisted state to 50 real non-accepted runs.
    baseline=p.repo.get_run_metrics(accepted.run_id)
    for n in range(50):
        rid=f'review-{n}'
        p.repo.create_run(run_id=rid,agent_id='support-bot@1.1.0-rc1',suite_id='support-core',suite_version='1.0.0',requested_by='alice',idempotency_key=None,baseline_run_id=None)
        p.repo.save_run_metrics(run_id=rid,agent_name='support-bot',suite_id='support-core',suite_version='1.0.0',scorecard=baseline['scorecard'],outcomes=baseline['case_outcomes'])
        p.repo.update_run(rid,status='needs_review')
        p.repo.save_artifact(rid,'Gate release',{'decision':{'outcome':'review','policy_version':'audit','reasons':['audit'],'overridable':True}})
    result=await run(p,'support-bot@1.1.0-rc1')
    print('BASELINE_WINDOW prior_accepted=',accepted.run_id,'selected=',result.comparison['baseline_run_id'],'note=',result.comparison.get('note'))
    p.repo.close()
asyncio.run(main())
