"""Offline checks of the JSON Schema subset used in this proposal.

This is not a general JSON Schema validator and does not exercise Krita.
Use a complete Draft 2020-12 validator in the server implementation.
"""
from pathlib import Path
import copy, json, math, re
P=Path(__file__).resolve().parent
read=lambda p:json.loads(p.read_text())
checks=[]
def ck(name,ok): checks.append({'name':name,'passed':bool(ok)})
def valid(schema,value,path='$'):
    allowed={'$schema','type','properties','required','additionalProperties','minProperties','items','prefixItems','minItems','maxItems','minimum','maximum','exclusiveMinimum','minLength','enum','const','pattern','anyOf','oneOf','allOf','if','then','else'}
    assert not set(schema)-allowed, 'Unsupported schema keyword '+str(set(schema)-allowed)
    def must(ok,msg):
        if not ok:raise ValueError(path+': '+msg)
    def matches(s):
        try:valid(s,value,path);return True
        except ValueError:return False
    if 'const' in schema:must(value==schema['const'],'const')
    if 'enum' in schema:must(value in schema['enum'],'enum')
    if 'anyOf' in schema:must(any(matches(s) for s in schema['anyOf']),'anyOf')
    if 'oneOf' in schema:must(sum(matches(s) for s in schema['oneOf'])==1,'oneOf')
    for s in schema.get('allOf',[]):valid(s,value,path)
    if 'if' in schema:
        branch='then' if matches(schema['if']) else 'else'
        if branch in schema:valid(schema[branch],value,path)
    kind=schema.get('type')
    predicates={'object':lambda:isinstance(value,dict),'array':lambda:isinstance(value,list),
        'string':lambda:isinstance(value,str),'boolean':lambda:isinstance(value,bool),'null':lambda:value is None,
        'integer':lambda:isinstance(value,int) and not isinstance(value,bool),
        'number':lambda:isinstance(value,(float,int)) and not isinstance(value,bool) and math.isfinite(value)}
    if kind:must(predicates[kind](),'type '+kind)
    if isinstance(value,dict):
        props=schema.get('properties',{})
        must(all(k in value for k in schema.get('required',[])),'required fields')
        must(len(value)>=schema.get('minProperties',0),'minProperties')
        if schema.get('additionalProperties') is False:must(not set(value)-set(props),'unknown fields')
        for key in value:
            if key in props:valid(props[key],value[key],path+'.'+key)
    if isinstance(value,list):
        must(len(value)>=schema.get('minItems',0),'minItems');must(len(value)<=schema.get('maxItems',math.inf),'maxItems')
        prefix=schema.get('prefixItems',[])
        for i,v in enumerate(value):
            s=prefix[i] if i<len(prefix) else schema.get('items',{})
            if s is False:must(False,'extra array item')
            else:valid(s,v,path+'['+str(i)+']')
    if isinstance(value,str):
        must(len(value)>=schema.get('minLength',0),'minLength')
        if 'pattern' in schema:must(bool(re.search(schema['pattern'],value)),'pattern')
    if isinstance(value,(int,float)) and not isinstance(value,bool):
        for key,fn in [('minimum',lambda a,b:a>=b),('maximum',lambda a,b:a<=b),('exclusiveMinimum',lambda a,b:a>b)]:
            if key in schema:must(fn(value,schema[key]),key)

catalogue=read(P/'tools.json')['tools'];index={t['name']:t for t in catalogue}
ck('69 unique tool names',len(catalogue)==len(index)==69)
ck('27 MVP and 42 extension tools',sum(t['phase'].startswith('MVP') for t in catalogue)==27 and sum(t['phase']=='EXTENSION' for t in catalogue)==42)
for t in catalogue:
    for key,v in [('inputSchema',t['example']['input']),('outputSchema',t['example']['structuredContent'])]:
        valid(t[key],v);ck(t['name']+' example '+key,True)
    if t['phase'].startswith('MVP'):
        ck(t['name']+' rejects unknown top-level input fields',t['inputSchema'].get('additionalProperties') is False)
mvp=read(P/'mvp.tools.json')['tools']
ck('registration file has only MVP tools',len(mvp)==27 and all(index[t['name']]['phase'].startswith('MVP') for t in mvp))
for p in P.glob('*.profile.json'):valid(read(P/'profile.schema.json'),read(p));ck(p.name+' profile example',True)
workflow=read(P/'paint-workflow.example.json');last_revision=12
for step in workflow:
    t=index[step['call']['name']];args=step['call']['arguments'];result=step['result']['structuredContent']
    valid(t['inputSchema'],args);valid(t['outputSchema'],result)
    if 'guard' in args:ck(t['name']+' workflow expected revision',args['guard']['expected_revision']==last_revision)
    if 'source' in args:ck(t['name']+' workflow read revision',args['source']['revision']==last_revision)
    if result['revision'] is not None:
        ck(t['name']+' monotonic workflow revision',result['revision']>=last_revision)
        last_revision=result['revision']
    ck(t['name']+' full MCP result example',step['result']['isError'] is False and bool(step['result']['content']))
ck('workflow has inspect-paint-export-validation sequence',len(workflow)==14 and last_revision==19)
for error in read(P/'errors.example.json'):
    for t in mvp:valid(t['outputSchema'],error['structuredContent'])
    ck(error['structuredContent']['error']['code']+' error envelope',error['isError'] and error['structuredContent']['status']=='failed')

def rejects(tool,mutation,label):
    t=index['krita_'+tool];sample=copy.deepcopy(t['example']['input']);mutation(sample)
    try:valid(t['inputSchema'],sample);ok=False
    except ValueError:ok=True
    ck(label,ok)
rejects('paint_stroke',lambda a:a['points'][0].update(pressure=1.1),'reject out-of-range pressure')
rejects('paint_stroke',lambda a:a['guard'].update(expected_revision=-1),'reject negative revision')
rejects('paint_stroke',lambda a:a['brush'].update(preset_sha256='not-a-hash'),'reject malformed preset hash')
rejects('paint_stroke',lambda a:a.update(hidden_script='do anything'),'reject unknown stroke argument')
rejects('capture',lambda a:a.update(target='layer',layer_id=None),'reject layer capture without layer ID')
rejects('history_step',lambda a:a.update(action='restore_checkpoint',checkpoint_id=None),'reject checkpoint restore without checkpoint')
rejects('layer_update',lambda a:a.update(properties={}),'reject empty property update')
rejects('document_save',lambda a:a.update(overwrite=True),'reject baseline overwrite in MVP save')

# Validate the two JSON blocks embedded in the implementation README.
blocks=re.findall(r'```json\n(.*?)\n```',(P/'README.md').read_text(),re.S)
for i,block in enumerate(blocks):
    parsed=json.loads(block)
    if 'arguments' in parsed:valid(index[parsed['name']]['inputSchema'],parsed['arguments'])
    else:valid(index['krita_edit_commit']['outputSchema'],parsed['structuredContent'])
    ck('README JSON example '+str(i+1),True)
for name in ['README.md','TOOL-CATALOGUE.md']:
    for target in re.findall(r'\]\(([^)]+)\)',(P/name).read_text()):
        if '://' not in target and not target.startswith('#'):ck(name+' link '+target,(P/target).is_file())

report={'status':'PASS' if all(c['passed'] for c in checks) else 'FAIL','checks':len(checks),'failed':[c['name'] for c in checks if not c['passed']],
 'scope':'Offline example/schema-subset, negative-input and document-link checks. No Krita/MCP server implementation or runtime tests performed.',
 'tools':69,'mvp_tools':27,'extension_tools':42,'workflow_steps':14}
(P/'validation-report.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2));raise SystemExit(report['status']!='PASS')
