"""Evaluate API-scoped retrieval with predeclared field labels (paid query embeddings)."""
import json
from pathlib import Path
from tap.agent.parameter_tools import ParameterTools
from tap.agent.kb_retrieval import KBRetriever

ROOT=Path(__file__).resolve().parents[1]
CASES=[
 ('POST:/sc/scb/scbd/selectTcktOshpList.do','협력사 번호','venCd'),
 ('POST:/sc/scb/scbd/selectTcktOshpList.do','하위 협력업체 코드','ven2Cd'),
 ('POST:/sc/scb/scbd/selectTcktOshpList.do','조회 기간 시작 날짜','fromDate'),
 ('POST:/sc/scb/scbd/selectTcktOshpList.do','조회 기간 마지막 날짜','toDate'),
 ('POST:/sc/scb/scbd/selectTcktOshpList.do','조회할 주문 식별 번호','ordNo'),
 ('POST:/pd/pdc/insertSellUitmDtl.do','팔 수 있는 수량의 상한','maxSellPossQty'),
 ('POST:/pd/pdc/insertSellUitmDtl.do','판매를 시작하는 날짜','sellStrtDt'),
 ('POST:/pd/pdc/insertSellUitmDtl.do','판매 종료 날짜','sellEndDt'),
 ('POST:/pd/pdc/selectUnitStocks.do','재고를 확인할 판매 상품 번호','slitmCd'),
 ('POST:/pd/pdc/selectUnitStocks.do','조회 기간의 시작','searchDateStart'),
 ('POST:/pd/pdb/updateItemByVen.do','웹사이트에 보여줄 판촉 이름','webExpsPrmoNm'),
 ('POST:/pd/pdb/updateItemByVen.do','한 번에 구매할 최소 개수','minBuyQty'),
]


def evaluate():
    from dotenv import load_dotenv,find_dotenv
    load_dotenv(find_dotenv(usecwd=True))
    ids=list(dict.fromkeys('hshop-openapi:'+api for api,_,_ in CASES))
    tools=ParameterTools(ROOT,{'api_selection_results':[{'selected_api_id':api} for api in ids]})
    retriever=KBRetriever(ROOT,top_k=10)
    cases=[]
    for api,query,name in CASES:
        selected='hshop-openapi:'+api
        full=tools.read('get_parameter_knowledge',selected)
        expected=[f['identity']['parameter_path'] for f in full['data']['parameters'] if f['identity']['parameter_name']==name]
        assert expected,(api,name)
        result=retriever.select(full,tools.schema(selected),[{'search_query':query}])
        report=result['retrieval'];rankings=report.get('rankings',[{'candidates':[]}])[0]['candidates']
        rank=next((i for i,row in enumerate(rankings,1) if row['parameter_path'] in expected),None)
        cases.append(dict(api_id=api,query=query,expected_paths=expected,first_correct_rank=rank,retrieval=report))
    scores=[dict(top_k=k,correct=sum(c['first_correct_rank'] is not None and c['first_correct_rank']<=k for c in cases),total=len(cases)) for k in range(1,11)]
    perfect=[s['top_k'] for s in scores if s['correct']==s['total']]
    report=dict(initial_top_k=5,recommended_by_recall=min(perfect) if perfect else 5,
                selection_note='후보 재현율만의 추천값이며 최종 채택은 매핑 품질과 누적 입력 토큰도 비교한다.',scores=scores,cases=cases)
    dest=ROOT/'data/out/evaluation/kb_top_k.json';dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'file':str(dest),'scores':scores,'recommended_by_recall':report['recommended_by_recall']},ensure_ascii=False),flush=True)

if __name__=='__main__':evaluate()
