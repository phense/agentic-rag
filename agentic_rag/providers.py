"""Explicit, bounded inference adapters. Inspection never performs IO.

Ollama verifies a tag's SHA256 before and after inference. Compatible HTTP
servers can only assert a logical model ID: discovery/response agreement is
not cryptographic attestation of remote weights. No adapter falls back/retries.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from hashlib import sha256
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import stat
import struct
import time
import threading
from functools import wraps
from collections.abc import Mapping
from urllib.parse import urlsplit

import httpx

MAX_RESPONSE_BYTES = 4 * 1024 * 1024
_http_client = httpx.Client  # injectable transport boundary; production has no mock mode
_inference_slots = threading.BoundedSemaphore(2)


def _after_fork():
    global _inference_slots
    _inference_slots = threading.BoundedSemaphore(2)


if hasattr(os,'register_at_fork'):
    os.register_at_fork(after_in_child=_after_fork)


def _bounded_inference(function):
    @wraps(function)
    def bounded(*args,**kwargs):
        slots=_inference_slots
        if not slots.acquire(blocking=False):
            raise ProviderError('capacity',True,'Provider inference capacity is busy; retry the bounded operation later.')
        try:return function(*args,**kwargs)
        finally:slots.release()
    return bounded


class ProviderError(RuntimeError):
    """Safe diagnostics only: never interpolate exceptions, inputs or bodies."""
    def __init__(self, code: str, retryable: bool, message: str):
        self.code, self.retryable = code, retryable
        super().__init__(message)


def _config(message='Invalid provider configuration; inspect the profile offline.'):
    return ProviderError('configuration', False, message)


def _bounded_int(value, low, high):
    return type(value) is int and low <= value <= high


def _endpoint(url):
    if not isinstance(url, str) or len(url) > 1024:
        raise _config()
    try:
        p = urlsplit(url)
        port = p.port
        if (p.scheme not in ('http', 'https') or not p.hostname or p.username is not None
                or p.password is not None or '?' in url or '#' in url
                or p.path.rstrip('/') not in ('', '/v1') or '\\' in url
                or any(c.isspace() or ord(c) < 32 for c in url)):
            raise ValueError
        local = p.hostname == 'localhost'
        try:local = local or ipaddress.ip_address(p.hostname).is_loopback
        except ValueError:pass
        if p.scheme != 'https' and not local:
            raise ValueError
    except (ValueError, AttributeError):
        raise _config('Use HTTPS for hosted inference, or HTTP on a loopback origin; no URL credentials or queries.') from None
    # Preserve the operator's exact origin identity (except trailing slash).
    return url.rstrip('/'), not local


def _credential_refs(env, file):
    if (not isinstance(env, str) or not isinstance(file, str)
            or (env and not re.fullmatch(r'[A-Z_][A-Z0-9_]{0,127}', env))
            or (env and file)):
        raise _config('Use one credential reference: an environment variable name or a protected token file.')


@dataclass(frozen=True)
class EmbeddingProfile:
    provider: str
    model: str
    revision: str
    url: str
    dimensions: int
    normalization: str = 'none'
    metric: str = 'cosine'
    representation: str = 'raw-v1'
    credential_env: str = ''
    credential_file: str = ''
    max_batch: int = 32
    max_input_chars: int = 4000
    timeout: float = 30.0

    @classmethod
    def from_mapping(cls, values):
        if not isinstance(values, Mapping) or set(values) - {f.name for f in dataclasses.fields(cls)}:
            raise _config('Unknown embedding profile fields; store credentials as protected references only.')
        try:return cls(**values)
        except TypeError:raise _config('Embedding profile requires provider, model, revision, url and dimensions.') from None

    def __post_init__(self):
        if self.provider not in ('ollama', 'openai-compatible'):
            raise ProviderError('unsupported_capability', False, 'Supported embedding providers: ollama and openai-compatible.')
        for value in (self.model, self.revision):
            if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}', value):
                raise _config('Model and revision must be bounded public identifiers.')
        if self.provider == 'ollama' and not re.fullmatch(r'[0-9a-f]{64}', self.revision):
            raise _config('Ollama revision must be the full lowercase SHA256 tag digest.')
        if self.provider == 'openai-compatible' and self.model != self.revision:
            raise _config('HTTP model and revision must be the same pinned logical model ID; arbitrary revision labels are unsupported.')
        url, _ = _endpoint(self.url)
        if self.provider == 'ollama' and urlsplit(url).path not in ('', '/'):
            raise _config('Ollama requires an origin URL without a path.')
        object.__setattr__(self, 'url', url)
        if not _bounded_int(self.dimensions, 1, 4000):raise _config('Dimensions must be 1 through 4000.')
        if self.normalization not in ('none','l2') or self.metric != 'cosine' or self.representation != 'raw-v1':
            raise ProviderError('unsupported_capability', False, 'Supported vector space: raw-v1, cosine, normalization none or l2.')
        if not _bounded_int(self.max_batch,1,32) or not _bounded_int(self.max_input_chars,1,4000):
            raise _config('Embedding limits: 1 through 32 inputs, each at most 4000 characters.')
        if type(self.timeout) not in (float,int) or not math.isfinite(self.timeout) or not .1 <= self.timeout <= 120:
            raise _config('Provider timeout must be finite, between 0.1 and 120 seconds.')
        _credential_refs(self.credential_env, self.credential_file)

    @property
    def descriptor(self):
        return {key:getattr(self,key) for key in ('provider','model','revision','url','dimensions','normalization','metric','representation')}

    @property
    def identity(self):
        return sha256(json.dumps(self.descriptor,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def resolve_profile(cfg, name) -> EmbeddingProfile:
    try:value = cfg.embedding_profiles[name]
    except (KeyError,TypeError):raise _config('Unknown embedding profile; inspect configured profile names.') from None
    return value if isinstance(value,EmbeddingProfile) else EmbeddingProfile.from_mapping(value)


def describe_profile(profile):
    """Offline/read-only inspection; no credential reads, requests or model calls."""
    _, egress = _endpoint(profile.url)
    return {'identity':profile.identity,'descriptor':profile.descriptor,'destination':profile.url,
            'external_egress':egress,'capabilities':['embedding'],'max_batch':profile.max_batch,
            'max_input_chars':profile.max_input_chars,'max_total_input_chars':profile.max_batch*profile.max_input_chars,
            'timeout_seconds':profile.timeout,'max_requests_per_batch':3,'max_requests_per_probe':3,
            'max_requests_per_identity_check':1,'max_requests_per_selection':4,'max_response_bytes':MAX_RESPONSE_BYTES,
            'automatic_retries':0,'fallback':False,'credential_configured':bool(profile.credential_env or profile.credential_file),
            'max_concurrent_inference_per_process':2,
            'identity_guarantee':('ollama-sha256-tag' if profile.provider=='ollama'
                else 'server-asserted-logical-model-id; not weight attestation')}


def _token(env, file):
    value = ''
    if env:
        value = os.environ.get(env, '')
    elif file:
        fd = None
        try:
            fd = os.open(Path(file).expanduser(),os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) != 0o600 or st.st_size > 8192:
                raise ValueError
            value = os.read(fd,8193).decode('utf-8').strip()
        except (OSError,ValueError,UnicodeError):
            raise ProviderError('authentication',False,'Credential file must be an owner-held regular 0600 file, not a symlink.') from None
        finally:
            if fd is not None:os.close(fd)
    if (env or file) and (not value or len(value)>8192 or any(ord(c)<33 or ord(c)>126 for c in value)):
        raise ProviderError('authentication',False,'Credential reference is missing or invalid; configure/rotate it locally.')
    return value


def _headers(env, file):
    token = _token(env,file)
    return {'Authorization':'Bearer '+token} if token else {}


def _remaining(deadline):
    seconds = deadline-time.monotonic()
    if seconds<=0:raise ProviderError('transient',True,'Inference deadline exceeded; retry the bounded operation later.')
    return seconds


def _loads(raw):
    def invalid_constant(_):raise ValueError('nonfinite JSON')
    return json.loads(raw,parse_constant=invalid_constant)


def _json(client, method, url, deadline, **kwargs):
    try:
        client.cookies.clear()
        with client.stream(method,url,timeout=_remaining(deadline),**kwargs) as response:
            status = response.status_code
            if status in (401,403):raise ProviderError('authentication',False,'Provider rejected authentication; check the configured credential reference.')
            if status==429:raise ProviderError('rate_limit',True,'Provider rate limit reached; retry later within the job budget.')
            if status==404:raise ProviderError('model_missing',False,'Provider endpoint or pinned model is missing; inspect the profile.')
            if status>=500 or status in (408,409,425):raise ProviderError('transient',True,'Provider temporarily unavailable; retry later within the job budget.')
            if 300<=status<400:raise _config('Provider redirects are refused; configure the final HTTPS endpoint explicitly.')
            if status>=400:raise ProviderError('unsupported_capability',False,'Provider rejected this capability or request; check the documented profile contract.')
            body=bytearray()
            for chunk in response.iter_bytes(chunk_size=4096):
                _remaining(deadline)
                if len(body)+len(chunk)>MAX_RESPONSE_BYTES:raise ProviderError('invalid_response',False,'Provider response exceeds the byte limit.')
                body.extend(chunk)
            return _loads(body)
    except (httpx.HTTPError,OSError):
        raise ProviderError('transient',True,'Provider transport failed; check destination availability and retry later.') from None
    except (ValueError,UnicodeError,RecursionError):
        raise ProviderError('invalid_response',False,'Provider returned invalid JSON; no content was accepted.') from None


def _base(profile):
    return profile.url if urlsplit(profile.url).path.rstrip('/')=='/v1' else profile.url+'/v1'


def _identity(client,profile,deadline):
    if profile.provider=='ollama':
        result=_json(client,'GET',profile.url+'/api/tags',deadline)
        name=profile.model if ':' in profile.model else profile.model+':latest'
        rows=result.get('models') if isinstance(result,dict) else None
        if not isinstance(rows,list):raise ProviderError('invalid_response',False,'Provider model discovery was malformed.')
        matches=[r for r in rows if isinstance(r,dict) and r.get('name',r.get('model'))==name]
        if not matches:raise ProviderError('model_missing',False,'Pinned embedding model is missing; install the configured revision explicitly.')
        valid=len(matches)==1 and matches[0].get('digest')==profile.revision
    else:
        result=_json(client,'GET',_base(profile)+'/models',deadline)
        rows=result.get('data') if isinstance(result,dict) else None
        if not isinstance(rows,list):raise ProviderError('invalid_response',False,'Provider model discovery was malformed.')
        matches=[r for r in rows if isinstance(r,dict) and r.get('id')==profile.revision]
        if not matches:raise ProviderError('model_missing',False,'Pinned logical model ID is absent from provider discovery.')
        valid=len(matches)==1
    if not valid:raise ProviderError('identity_mismatch',False,'Provider model identity changed or is ambiguous; restore the pinned revision or create a new profile.')
    return profile.identity


def verify_identity(profile):
    """One discovery request, no synthetic inference and no corpus input."""
    headers=_headers(profile.credential_env,profile.credential_file)
    with _http_client(trust_env=False,follow_redirects=False,headers=headers,timeout=profile.timeout) as client:
        return _identity(client,profile,time.monotonic()+profile.timeout)


def validate_vectors(vectors, count, dimensions, normalization='none'):
    """Reject nonnumeric/zero/nonfinite values and values unsafe for halfvec."""
    invalid=ProviderError('invalid_response',False,'Provider returned invalid vectors: require finite, nonzero, dimension-correct halfvec values.')
    if not isinstance(vectors,list) or len(vectors)!=count:raise invalid
    output=[]
    for vector in vectors:
        if not isinstance(vector,list) or len(vector)!=dimensions:raise invalid
        try:
            if any(type(v) not in (int,float) or not math.isfinite(v) for v in vector):raise invalid
            norm=math.hypot(*vector)
        except OverflowError:raise invalid from None
        if not math.isfinite(norm) or norm==0:raise invalid
        values=[float(v)/norm if normalization=='l2' else float(v) for v in vector]
        try:half=[struct.unpack('e',struct.pack('e',v))[0] for v in values]
        except (OverflowError,struct.error):raise invalid from None
        if not any(v!=0 for v in half) or any(not math.isfinite(v) for v in half):raise invalid
        output.append(values)
    return output


@_bounded_inference
def embed_profile(texts, profile):
    if (not isinstance(texts,list) or not 1<=len(texts)<=profile.max_batch
            or any(not isinstance(t,str) or not t.strip() or len(t)>profile.max_input_chars for t in texts)):
        raise _config('Embedding batch exceeds configured bounds or contains empty/non-text input; split inputs explicitly.')
    headers=_headers(profile.credential_env,profile.credential_file)
    deadline=time.monotonic()+profile.timeout
    with _http_client(trust_env=False,follow_redirects=False,headers=headers,timeout=profile.timeout) as client:
        _identity(client,profile,deadline)
        if profile.provider=='ollama':
            result=_json(client,'POST',profile.url+'/api/embed',deadline,json={'model':profile.model,'input':texts,'truncate':False})
            vectors=result.get('embeddings') if isinstance(result,dict) else None
        else:
            result=_json(client,'POST',_base(profile)+'/embeddings',deadline,json={'model':profile.model,'input':texts,'encoding_format':'float'})
            if not isinstance(result,dict) or result.get('model')!=profile.revision:
                raise ProviderError('identity_mismatch',False,'Embedding response did not confirm the pinned logical model ID.')
            rows=result.get('data')
            if (not isinstance(rows,list) or len(rows)!=len(texts) or any(not isinstance(r,dict) or type(r.get('index')) is not int for r in rows)
                    or sorted(r['index'] for r in rows)!=list(range(len(texts)))):
                raise ProviderError('invalid_response',False,'Embedding response indices are incomplete or ambiguous.')
            vectors=[r.get('embedding') for r in sorted(rows,key=lambda r:r['index'])]
        output=validate_vectors(vectors,len(texts),profile.dimensions,profile.normalization)
        _identity(client,profile,deadline)
        return output


def verify_profile(profile):
    """Explicit caller-authorized synthetic capability probe; never reads corpus."""
    vectors=embed_profile(['Synthetic connectivity probe; no stored knowledge.'[:profile.max_input_chars]],profile)
    return {**describe_profile(profile),'verified':True,'probe_inputs':1,'probe_dimensions':len(vectors[0])}


def _llm_profile(cfg, timeout=None):
    limits=[cfg.llm_timeout] + ([timeout] if timeout is not None else [])
    if any(type(t) not in (int,float) or not math.isfinite(t) or t<=0 for t in limits):
        raise _config('Extraction timeout must be finite and positive.')
    # Reuse the logical-ID and endpoint/credential contract without a vector call.
    return EmbeddingProfile(provider='openai-compatible',model=cfg.llm_model,revision=cfg.llm_revision,
        url=cfg.llm_url,dimensions=1,credential_env=cfg.llm_credential_env,credential_file=cfg.llm_credential_file,
        timeout=min(120,*limits))


def describe_llm(cfg):
    """Offline extraction-slot metadata; does not read credentials or invoke CLIs."""
    if cfg.llm_provider in ('claude','codex'):
        return {'provider':cfg.llm_provider,'model':cfg.llm_model,'capabilities':['structured-extraction'],
            'inspection_is_offline':True,'credential_source':'existing-cli-login-and-environment',
            'external_egress':True,'destination':'existing CLI account/provider configuration',
            'identity_guarantee':'CLI-selected model; no weight attestation','timeout_seconds':cfg.llm_timeout,
            'max_inference_calls_per_probe':1,'automatic_retries':0,'fallback':False}
    if cfg.llm_provider!='openai-compatible':
        raise ProviderError('unsupported_capability',False,'Supported extraction providers: claude, codex and openai-compatible.')
    p=_llm_profile(cfg)
    if not _bounded_int(cfg.llm_max_input_chars,1,64000) or not _bounded_int(cfg.llm_max_output_tokens,1,8192):
        raise _config('Extraction input/output limits must be finite bounded integers.')
    return {'provider':p.provider,'model':p.model,'revision':p.revision,'destination':p.url,
        'capabilities':['structured-extraction'],'inspection_is_offline':True,'external_egress':_endpoint(p.url)[1],
        'identity_guarantee':'server-asserted-logical-model-id; not weight attestation',
        'max_input_chars':cfg.llm_max_input_chars,'max_schema_chars':64000,
        'max_output_tokens':cfg.llm_max_output_tokens,'max_requests_per_probe':3,
        'max_requests_per_call':3,'max_response_bytes':MAX_RESPONSE_BYTES,'timeout_seconds':p.timeout,
        'credential_configured':bool(p.credential_env or p.credential_file),'automatic_retries':0,'fallback':False}


def probe_llm(cfg):
    """Explicit synthetic probe. The operator/CLI must authorize possible egress."""
    from .llm import run_structured
    result=run_structured('Synthetic connectivity check. Return {"ok":true}.',
        {'type':'object','properties':{'ok':{'type':'boolean'}},'required':['ok'],'additionalProperties':False},cfg,timeout=20)
    if result!={'ok':True}:raise ProviderError('invalid_response',False,'Synthetic extraction probe did not return the expected result.')
    return {**describe_llm(cfg),'verified':True,'probe_inputs':1}


@_bounded_inference
def run_http_structured(prompt,schema,cfg,*,system=None,timeout=None):
    """Independent extraction slot; finite JSON-schema response, no CLI fallback."""
    from jsonschema import Draft202012Validator
    p=_llm_profile(cfg,timeout)
    if (not _bounded_int(cfg.llm_max_input_chars,1,64000) or not _bounded_int(cfg.llm_max_output_tokens,1,8192)
            or not isinstance(prompt,str) or not isinstance(system or '',str)
            or len(prompt)+len(system or '')>cfg.llm_max_input_chars):
        raise _config('Extraction request exceeds configured finite input/output limits.')
    try:
        Draft202012Validator.check_schema(schema)
        schema_text=json.dumps(schema)
        if len(schema_text)>64000:raise ValueError
    except Exception:raise _config('Extraction requires a valid, bounded JSON schema.') from None
    def refs(value):
        if isinstance(value,dict):return any(k in ('$ref','$dynamicRef','$recursiveRef') or refs(v) for k,v in value.items())
        if isinstance(value,list):return any(refs(v) for v in value)
        return False
    if refs(schema):
        raise ProviderError('unsupported_capability',False,'Extraction requires an inline JSON schema without references.')
    headers=_headers(p.credential_env,p.credential_file)
    deadline=time.monotonic()+p.timeout
    messages=([{'role':'system','content':system}] if system is not None else [])+[{'role':'user','content':prompt}]
    with _http_client(trust_env=False,follow_redirects=False,headers=headers,timeout=p.timeout) as client:
        _identity(client,p,deadline)
        result=_json(client,'POST',_base(p)+'/chat/completions',deadline,json={
            'model':p.model,'messages':messages,'max_tokens':cfg.llm_max_output_tokens,
            'response_format':{'type':'json_schema','json_schema':{'name':'structured_result','strict':True,'schema':schema}}})
        if not isinstance(result,dict) or result.get('model')!=p.revision:
            raise ProviderError('identity_mismatch',False,'Extraction response did not confirm the pinned logical model ID.')
        try:
            choices=result['choices']
            if not isinstance(choices,list) or len(choices)!=1 or choices[0].get('finish_reason')!='stop':raise ValueError
            raw=choices[0]['message']['content']
            if not isinstance(raw,str):raise ValueError
            output=_loads(raw)
            if not isinstance(output,dict):raise ValueError
            Draft202012Validator(schema).validate(output)
        except Exception:
            raise ProviderError('invalid_response',False,'Extraction output was incomplete or failed its JSON schema; no content was accepted.') from None
        _identity(client,p,deadline)
        return output
