from __future__ import annotations
import argparse, hashlib, json, re, shutil
from pathlib import Path
from typing import Any

ROOT=Path(__file__).resolve().parents[2]
TARGET=ROOT/'deploy'/'musitu-financial-fabric'/'provider-neutral'
CONTRACT=TARGET/'runtime-contract.json'
SOURCE=TARGET/'manifest-profile-policy.json'
POLICY=TARGET/'manifest-target-evidence-policy.json'
BASE='80c72d9f711561dd46337d7286ee7bfb2bb5e658'
POLICY_SCHEMA='mff.manifest-target-evidence-policy.v1'
SOURCE_SCHEMA='mff.manifest-profile-policy.v1'
MANIFEST_SCHEMA='mff.runtime-manifest-evidence.v1'
EVIDENCE_SCHEMA='mff.manifest-target-validation-evidence.v1'
SCOPE='static_manifest_association_only'
SHA=re.compile(r'^[0-9a-f]{64}$')
OCI=re.compile(r'^sha256:[0-9a-f]{64}$')
NO_CLAIMS=('kubernetes_api_admission_observed','deployment_observed','target_health_observed')

def load(p:Path)->Any:return json.loads(p.read_text(encoding='utf-8'))
def rel(p:Path)->str:return p.resolve().relative_to(ROOT.resolve()).as_posix()
def sha(p:Path)->str:return hashlib.sha256(p.read_bytes()).hexdigest()
def canon(v:object)->str:return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()
def project(d:dict[str,Any])->dict[str,Any]:return {k:v for k,v in d.items() if k!='target_validation'}

def repo_file(v:object)->Path|None:
    if not isinstance(v,str) or not v.strip():return None
    q=Path(v.strip())
    if q.is_absolute():return None
    r=(ROOT/q).resolve()
    try:r.relative_to(ROOT.resolve())
    except ValueError:return None
    return r if r.is_file() else None

def policy_errors(p:object,s:object)->list[str]:
    e=[]
    if not isinstance(p,dict):return ['manifest target-evidence policy root must be an object']
    expected={'schema_version':POLICY_SCHEMA,'authoritative_runtime_base_commit':BASE,'source_manifest_policy_schema_version':SOURCE_SCHEMA,'manifest_evidence_schema_version':MANIFEST_SCHEMA,'target_evidence_schema_version':EVIDENCE_SCHEMA,'manifest_descriptor_projection':'canonical_descriptor_without_target_validation','validation_scope':SCOPE,'forbidden_observed_claims':list(NO_CLAIMS)}
    for k,v in expected.items():
        if p.get(k)!=v:e.append(f'policy {k} is invalid')
    if not isinstance(s,dict):return e+['source manifest policy root must be an object']
    if s.get('schema_version')!=SOURCE_SCHEMA:e.append('source manifest policy schema drifted')
    if s.get('authoritative_runtime_base_commit')!=BASE:e.append('source manifest policy base drifted')
    if s.get('manifest_evidence_schema_version')!=MANIFEST_SCHEMA:e.append('source manifest evidence schema drifted')
    if s.get('target_validation_status_required_for_resolution')!='passed':e.append('source policy no longer requires passed target validation')
    return e

def association(key:str,row:dict[str,Any],manifest:Path,d:object,s:dict[str,Any],source_sha:str)->list[str]:
    e=[]
    if not isinstance(d,dict):return ['manifest evidence descriptor root must be an object']
    msha=sha(manifest); mref=rel(manifest); env=d.get('environment_id'); digest=row.get('image_digest')
    direct={'schema_version':MANIFEST_SCHEMA,'runtime_key':key,'authoritative_runtime_base_commit':BASE,'manifest_path':mref,'manifest_sha256':msha}
    for k,v in direct.items():
        if d.get(k)!=v:e.append(f'manifest descriptor {k} mismatch')
    if not isinstance(env,str) or not env.strip():e.append('manifest descriptor environment_id missing');env=''
    if not isinstance(digest,str) or not OCI.fullmatch(digest):e.append('contract image_digest invalid')
    elif d.get('image_digest')!=digest:e.append('manifest descriptor image_digest mismatch')
    refs=d.get('profile_refs'); required=set(s.get('required_profile_refs') or [])
    if not isinstance(refs,dict) or set(refs)!=required:e.append('manifest descriptor profile_refs inventory mismatch');refs={}
    t=d.get('target_validation')
    if not isinstance(t,dict):return e+['target_validation must be an object']
    if t.get('status')!='passed':e.append('target_validation.status must be passed')
    if t.get('environment_id')!=env:e.append('target_validation environment mismatch')
    for k in ('method','verifier','trust_model'):
        if not isinstance(t.get(k),str) or not t[k].strip():e.append(f'target_validation.{k} missing')
    ep=repo_file(t.get('evidence_ref')); declared=str(t.get('evidence_sha256','')).lower()
    if ep is None:return e+['target_validation evidence_ref must reference existing bytes']
    if not SHA.fullmatch(declared):e.append('target_validation evidence_sha256 malformed')
    elif sha(ep)!=declared:e.append('target_validation retained-byte SHA mismatch')
    try:x=load(ep)
    except Exception:return e+['target_validation evidence must be structured JSON']
    if not isinstance(x,dict):return e+['target_validation evidence root must be an object']
    expected={'schema_version':EVIDENCE_SCHEMA,'validation_scope':SCOPE,'runtime_key':key,'authoritative_runtime_base_commit':BASE,'manifest_path':mref,'manifest_sha256':msha,'environment_id':env,'image_digest':d.get('image_digest'),'source_manifest_policy_sha256':source_sha,'profile_refs_sha256':canon(refs),'manifest_descriptor_semantics_sha256':canon(project(d)),'method':t.get('method'),'verifier':t.get('verifier'),'trust_model':t.get('trust_model')}
    for k,v in expected.items():
        if x.get(k)!=v:e.append(f'target evidence {k} mismatch')
    for k in NO_CLAIMS:
        if x.get(k) is not False:e.append(f'target evidence must keep {k}=false')
    return e

def write_json(p:Path,v:object)->str:p.write_text(json.dumps(v,sort_keys=True,separators=(',',':'))+'\n',encoding='utf-8');return sha(p)

def self_test()->list[str]:
    p,s=load(POLICY),load(SOURCE); f=policy_errors(p,s)
    if f:return f
    key='__manifest_target_self_test__'; folder=TARGET/'manifests'/key;folder.mkdir(parents=True,exist_ok=False)
    m=folder/'runtime.json';ep=folder/'validation.json';digest='sha256:'+'1'*64;source_sha=sha(SOURCE);profile_ref=rel(POLICY);row={'image_digest':digest}
    try:
        m.write_text('{"kind":"Deployment"}\n',encoding='utf-8')
        d={'schema_version':MANIFEST_SCHEMA,'runtime_key':key,'authoritative_runtime_base_commit':BASE,'manifest_path':rel(m),'manifest_sha256':sha(m),'environment_id':'self-test','image_digest':digest,'profile_refs':{k:profile_ref for k in s['required_profile_refs']}}
        t={'status':'passed','environment_id':'self-test','method':'self-test','verifier':'self-test','trust_model':'synthetic','evidence_ref':rel(ep),'evidence_sha256':''};d['target_validation']=t
        def ev(src:dict[str,Any])->dict[str,Any]:
            tv=src['target_validation'];return {'schema_version':EVIDENCE_SCHEMA,'validation_scope':SCOPE,'runtime_key':src['runtime_key'],'authoritative_runtime_base_commit':BASE,'manifest_path':src['manifest_path'],'manifest_sha256':src['manifest_sha256'],'environment_id':src['environment_id'],'image_digest':src['image_digest'],'source_manifest_policy_sha256':source_sha,'profile_refs_sha256':canon(src['profile_refs']),'manifest_descriptor_semantics_sha256':canon(project(src)),'method':tv['method'],'verifier':tv['verifier'],'trust_model':tv['trust_model'],'kubernetes_api_admission_observed':False,'deployment_observed':False,'target_health_observed':False}
        t['evidence_sha256']=write_json(ep,ev(d))
        if association(key,row,m,d,s,source_sha):f.append('valid synthetic association rejected')
        bad=ev(d);bad['runtime_key']='wrong';c=json.loads(json.dumps(d));c['target_validation']['evidence_sha256']=write_json(ep,bad)
        if not association(key,row,m,c,s,source_sha):f.append('unrelated runtime evidence accepted')
        bad=ev(d);bad['kubernetes_api_admission_observed']=True;c=json.loads(json.dumps(d));c['target_validation']['evidence_sha256']=write_json(ep,bad)
        if not association(key,row,m,c,s,source_sha):f.append('admission overclaim accepted')
        ep.write_text('generic bytes\n',encoding='utf-8');c=json.loads(json.dumps(d));c['target_validation']['evidence_sha256']=sha(ep)
        if not association(key,row,m,c,s,source_sha):f.append('generic evidence bytes accepted')
        good=ev(d);c=json.loads(json.dumps(d));c['environment_id']='changed';c['target_validation']['environment_id']='changed';c['target_validation']['evidence_sha256']=write_json(ep,good)
        if not association(key,row,m,c,s,source_sha):f.append('post-evidence descriptor drift accepted')
        return f
    finally:
        shutil.rmtree(folder,ignore_errors=True)
        try:(TARGET/'manifests').rmdir()
        except OSError:pass

def contract_errors()->tuple[list[str],tuple[int,int]]:
    p,s=load(POLICY),load(SOURCE);e=policy_errors(p,s);source_sha=sha(SOURCE);c=load(CONTRACT)
    if c.get('authoritative_runtime_base_commit')!=BASE:return e+['runtime contract base drifted'],(0,0)
    defaults=c.get('defaults_for_unresolved_fields',{});resolved=unresolved=0
    for row in c.get('runtimes',[]):
        if not isinstance(row,dict):e.append('non-object runtime row');continue
        key=str(row.get('key','unknown'));ref=row.get('manifest_path',defaults.get('manifest_path'))
        if ref in (None,'',[],{}):unresolved+=1;continue
        m=repo_file(ref)
        if m is None:e.append(f'{key}: manifest_path invalid');continue
        suffix=s.get('descriptor_suffix');dp=repo_file(f'{rel(m)}{suffix}') if isinstance(suffix,str) else None
        if dp is None:e.append(f'{key}: manifest evidence descriptor missing');continue
        try:d=load(dp)
        except Exception:e.append(f'{key}: manifest evidence descriptor invalid JSON');continue
        errs=association(key,row,m,d,s,source_sha)
        if errs:e.extend(f'{key}: {x}' for x in errs)
        else:resolved+=1
    return e,(resolved,unresolved)

def main()->int:
    a=argparse.ArgumentParser();g=a.add_mutually_exclusive_group(required=True);g.add_argument('--self-test',action='store_true');g.add_argument('--contract',action='store_true');args=a.parse_args()
    if args.self_test:
        f=self_test()
        if f:
            for x in f:print('SELF-TEST FAILURE:',x)
            return 4
        print('PASS: manifest target-evidence validator rejects generic/unrelated retained bytes, authority/descriptor drift, and admission/health/deployment overclaims');return 0
    e,(r,u)=contract_errors()
    if e:
        for x in e:print('MANIFEST TARGET EVIDENCE BLOCKER:',x)
        return 2
    print(f'PASS: manifest_target_evidence: validated {r} resolved manifests; {u} remain unresolved')
    print('BOUNDARY: static association evidence only; no Kubernetes API admission, scheduling, target health, deployment, production authorization, or independent validation is proved');return 0

if __name__=='__main__':raise SystemExit(main())
