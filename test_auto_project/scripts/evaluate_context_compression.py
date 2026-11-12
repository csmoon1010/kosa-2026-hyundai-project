"""Opt-in paid model evaluation of eight combinations, with labelled mapping anchors.

PYTHONPATH=src python scripts/evaluate_context_compression.py --repeat 3 --workers 4
Writes evaluation artifacts, not user scenario drafts, and never calls business APIs.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import itertools
import json
import os
from pathlib import Path
import shutil
import tempfile
import time

from tap.agent.config import CONFIG
from tap.agent.parameter_tools import ParameterTools
from tap.ir.draft_build import IR_INPUTS, generate, fixed_plan
from tap.ir.draft_validate import validate_final_ir

ROOT=Path(__file__).resolve().parents[1]
FILE='api-selection-approved-order-shipment.json'


def score(ir,tools,plan):
    steps=[s for t in ir['tasks'] for s in t['steps']]
    source=tools.read('get_response_outputs',plan[0]['selected_api_id'])
    expected_paths={o['response_path'] for o in source['data']['outputs'] if o['name']=='ordNo'}
    output_names={o['name'] for o in steps[0]['outputs'] if o['response_path'] in expected_paths}
    anchors={
        'vendor_code':any(i['field']=='venCd' and i['value']=='001442' and i['source']=='fixed' for i in steps[0]['inputs']),
        'order_output':bool(output_names),
        'consumer_bindings':all(any(b['from']['from_step_id']=='1-1' and b['from']['output_name'] in output_names and b['from']['response_path'] in expected_paths
                                    and any(i['source']=='bind' and i['ref']==b['binding_id'] and i['parameter_path']==b['to_parameter_path'] for i in s['inputs'])
                                    for b in s['bindings']) for s in steps[1:]),
        'analysis_draft':ir['status']=='needs_input' and len(steps)==4,
    }
    try:anchors['mapping_valid']=validate_final_ir(ir,tools,plan)['valid']
    except Exception:anchors['mapping_valid']=False
    return anchors


def run(options,trial,top_k):
    with tempfile.TemporaryDirectory(prefix='tap-context-eval-') as directory:
        root=Path(directory)
        (root/IR_INPUTS).mkdir(parents=True)
        approved=json.loads((ROOT/'tests/fixtures'/FILE).read_text())
        # Structured conditions use the existing intent interpretation; no query
        # decomposition request is introduced by this evaluation.
        for task in approved['intent_tasks']:
            task['conditions']=[dict(condition_id=f"C-{task['sequence']}",search_query=task['conditions'])]
        (root/IR_INPUTS/FILE).write_text(json.dumps(approved,ensure_ascii=False))
        (root/'data/out').mkdir(parents=True)
        (root/'data/out/parameters').symlink_to(ROOT/'data/out/parameters',target_is_directory=True)
        start=time.monotonic()
        row=dict(options=options,trial=trial,top_k=top_k,model=os.environ['OPENAI_DEFAULT_MODEL'])
        try:
            result=generate(root,FILE,generation_options=options)
            row.update(success=True,usage=result['usage'],score=score(result['ir'],ParameterTools(root,approved),fixed_plan(approved)))
            target=ROOT/'data/out/evaluation/live'/(''.join(str(int(v)) for v in options.values())+f'-{trial}-k{top_k}.json')
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
            row['result_file']=str(target.relative_to(ROOT))
        except Exception as error:
            row.update(success=False,error=str(error),score={})
        logs=root/'data/out/scenario_ir_logs'
        if logs.exists():
            dest=ROOT/'data/out/evaluation/live_logs';dest.mkdir(parents=True,exist_ok=True)
            for file in logs.glob('*.jsonl'):
                shutil.copy2(file,dest/file.name)
                row['log_file']=str((dest/file.name).relative_to(ROOT))
        row['seconds']=round(time.monotonic()-start,3)
        return row


def main():
    from dotenv import load_dotenv,find_dotenv
    load_dotenv(find_dotenv(usecwd=True))
    parser=argparse.ArgumentParser();parser.add_argument('--repeat',type=int,default=3)
    parser.add_argument('--workers',type=int,default=4);parser.add_argument('--top-k',type=int,default=5)
    args=parser.parse_args()
    if not 1<=args.top_k<=10 or args.repeat<1:parser.error('top-k 1~10, repeat >=1')
    CONFIG['kb_top_k']=args.top_k
    jobs=[(dict(zip(['stop_retry','kb_rag','dependency_projection'],bits)),trial)
          for trial in range(1,args.repeat+1) for bits in itertools.product([False,True],repeat=3)]
    rows=[];path=ROOT/f'data/out/evaluation/context_live_k{args.top_k}.json';path.parent.mkdir(parents=True,exist_ok=True)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        pending=[pool.submit(run,opts,trial,args.top_k) for opts,trial in jobs]
        for future in as_completed(pending):
            row=future.result();rows.append(row)
            path.write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n')
            print(json.dumps(row,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
