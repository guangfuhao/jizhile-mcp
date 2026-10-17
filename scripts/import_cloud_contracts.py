import pathlib,re,json,yaml,hashlib
import argparse
from datetime import datetime
from zoneinfo import ZoneInfo
parser=argparse.ArgumentParser(description='Import sanitized request contracts from downloaded official Apifox Markdown. Requires PyYAML for development only.')
parser.add_argument('docs_dir',type=pathlib.Path)
parser.add_argument('--output',type=pathlib.Path,default=pathlib.Path('src/jizhile_mcp/cloud_contracts.json'))
parser.add_argument('--retrieved-date',default=datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat())
args=parser.parse_args()
root=args.docs_dir;contracts={};issues=[]
allowed={'type','properties','items','required','enum','description','default','minimum','maximum','minLength','maxLength','minItems','maxItems','pattern','format','nullable','oneOf','anyOf','allOf','additionalProperties'}
def clean(s):
 if isinstance(s,dict):
  return {k:({n:clean(v) for n,v in val.items()} if k=='properties' else clean(val)) for k,val in s.items() if k in allowed}
 if isinstance(s,list):return [clean(x) for x in s]
 return s

def infer(v):
 if isinstance(v,dict):return {'type':'object','properties':{k:infer(x) for k,x in v.items()}}
 if isinstance(v,list):return {'type':'array','items':infer(v[0]) if v else {}}
 if isinstance(v,bool):return {'type':'boolean'}
 if isinstance(v,int):return {'type':'integer'}
 if isinstance(v,float):return {'type':'number'}
 if v is None:return {'type':['string','null']}
 return {'type':'string'}

for x in json.loads((root/'index.json').read_text()):
 f=root/x['url'].rsplit('/',1)[1];spec=yaml.safe_load(f.read_text().split('```yaml',1)[1].rsplit('```',1)[0])
 assert {s['url'] for s in spec['servers']}=={'https://api.yddm.com'}
 for path,methods in spec['paths'].items():
  for method,op in methods.items():
   content=op.get('requestBody',{}).get('content',{});assert not content or list(content)==['application/json']
   c=next(iter(content.values()),{});body=clean(c.get('schema',{}));basis='schema'
   ex=c.get('example',{})
   if isinstance(ex,str):
    try:ex=json.loads(re.sub(r'(?m)\s+//[^\r\n]*','',ex))
    except ValueError:ex={}
   if not body.get('properties') and isinstance(ex,dict) and ex:
    body=infer(ex);basis='documented_example'
    # Examples document parameter names and types but not optionality. Require
    # identifiers/search targets, never supply example targets as defaults.
    targets=[k for k in ex if k in ['keyword','q','nid','tid','user_id'] or k.endswith('_id')]
    body['required']=targets
   notes=[]
   if path=='/xhs/share_id_to_web_id':
    assert set(ex)=={'share_link'}
    body=infer(ex);body['required']=['share_link'];basis='documented_example'
    notes.append('官方请求schema误写为响应结构，按同页share_link请求示例及描述修正。')
   if path=='/jd/shop_list':
    assert 'shop_id' in ex
    body['properties']['shop_id']=infer(ex['shop_id'])
    body['required']=[k for k in body.get('required',[]) if k!='goods_id']
    body['required'].append('shop_id')
    notes.append('官方schema写goods_id，请求示例为shop_id；保留文档字段并按店铺示例要求shop_id。')
   if path=='/youtube/video_detail_v2':
    assert 'video_id ' in body['properties'] and 'video_id' in ex
    body['properties']['video_id']=body['properties'].pop('video_id ')
    body['required']=[k.strip() for k in body.get('required',[])]
    notes.append('官方schema的video_id尾部有空格，按同页请求示例规范为video_id。')
   if path in ['/toutiao/search','/xingtu/author_show_items']:
    for key,value in ex.items():
     if key not in body['properties']:
      body['properties'][key]=infer(value)
      notes.append('补入官方请求示例中定义但schema遗漏的参数：'+key)
   props=body.get('properties',{})
   # Fields with no type in Bilibili schema are explicitly null in its example.
   for k,v in props.items():
    if not v.get('type') and not any(i in v for i in ['anyOf','oneOf','allOf']):
     v.update(infer(ex[k]) if isinstance(ex,dict) and k in ex else {'type':'string'})
   headers=[q for q in op.get('parameters',[]) if q['in']=='header'];assert all(q['name'].lower() in ['x-api-key','authorization'] for q in headers)
   assert not any(q['in']!='header' for q in op.get('parameters',[]))
   tariff_text=' '.join(q.get('description','') for q in headers)
   points=re.search(r'([\d.]+)\s*积分\s*/\s*次',tariff_text)
   rec={'title':op['summary'].strip(),'path':path,'method':method.upper(),'encoding':'json','provider':'yddm',
        'request_schema':body,'schema_basis':basis,'contract_notes':notes,'allowed':list(props),'required':body.get('required',[]),
        'fixed':{},'example_params':{},'source':x['url'].removesuffix('.md'),'source_sha256':hashlib.sha256(f.read_bytes()).hexdigest(),
        'retrieved_date':args.retrieved_date,'host':'https://api.yddm.com','auth_header':'X-API-Key','documented_points_per_request':points.group(1) if points else None,
        'deprecated':bool(op.get('deprecated')),'doc_status':op.get('x-apifox-status'),'billing_cost_path':['data','cost'],'billing_balance_path':['data','balance']}
   if path=='/users/me':rec['kind']='balance'
   else:rec['kind']='task_submit' if any(t in path for t in ['async_commit','/submit','async_submit']) else 'task_poll' if any(t in path for t in ['async_get','async_check']) else 'query'
   if path in contracts:issues.append(path)
   contracts[path]=rec
assert not issues,issues
out=args.output;out.write_text(json.dumps({'index_url':'https://s.apifox.cn/6faad22e-3ea1-4934-8926-69d0efb2dce1/llms.txt','retrieved_date':args.retrieved_date,'contracts':contracts},ensure_ascii=False,indent=2)+'\n')
print('contracts',len(contracts),'example-based',[p for p,v in contracts.items() if v['schema_basis']!='schema'])
print('header priced',sum(v['documented_points_per_request'] is not None for v in contracts.values()))
