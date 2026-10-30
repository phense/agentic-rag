"""A client can discover and validate durable-input requests from OpenAPI."""
from copy import deepcopy

import pytest
from jsonschema import Draft202012Validator, ValidationError
from starlette.testclient import TestClient

from .test_api import app_fixture, headers, KEYS
from .test_scope import service_store
from .test_worker_fencing import window
from .test_checkpoint_api import packet


def test_openapi_describes_real_enrollment_and_durable_input(service_store, tmp_path):
    cfg, _ = service_store
    app, _ = app_fixture(tmp_path, cfg)
    with TestClient(app, base_url='https://testserver') as client:
        spec = client.get('/v1/openapi.json', headers=headers(KEYS[0])).json()
        paths = spec['paths']
        assert paths['/health']['get']['security'] == []
        assert paths['/v1/login']['post']['security'] == []
        assert '202' in paths['/v1/windows']['post']['responses']
        for path, payload in [('/v1/windows', window()), ('/v1/checkpoints', packet()),
                              ('/v1/login', {'username': 'alice', 'password': 'private'})]:
            operation = paths[path]['post']
            assert any(p['name'] == 'x-rag-protocol' and p['required'] for p in operation['parameters'])
            schema = operation['requestBody']['content']['application/json']['schema']
            validator = Draft202012Validator({**schema, 'components': spec['components']})
            validator.validate(payload)
            invalid = deepcopy(payload)
            del invalid[{'/v1/windows': 'window', '/v1/checkpoints': 'snapshot', '/v1/login': 'password'}[path]]
            with pytest.raises(ValidationError):
                validator.validate(invalid)
        receipt = paths['/v1/jobs/{receipt}']['get']
        assert any(p['name'] == 'receipt' and p['in'] == 'path' and p['schema']['format'] == 'uuid' for p in receipt['parameters'])
        assert paths['/v1/sessions/{session}/windows']['get']['parameters'][-1]['schema']['maximum'] == 4
        for path, method, body in [('/v1/windows', 'post', window()), ('/v1/checkpoints', 'post', packet()),
                                   ('/v1/capabilities', 'get', None)]:
            result = client.request(method, path, headers=headers(KEYS[0]), json=body)
            schema = paths[path][method]['responses'][str(result.status_code)]['content']['application/json']['schema']
            Draft202012Validator({**schema, 'components': spec['components']}).validate(result.json())


def test_trace_discovery_matches_real_metadata_and_job_origin(service_store,tmp_path):
    cfg,_=service_store;app,_=app_fixture(tmp_path,cfg)
    with TestClient(app,base_url='https://testserver') as client:
        response=client.get('/v1/openapi.json',headers=headers(KEYS[0]));spec=response.json()
        for endpoint in ['/v1/traces','/v1/traces/export','/v1/traces/{identity}']:
            assert 'X-Rag-Request-ID' in spec['paths'][endpoint]['get']['responses']['200']['headers']
            assert any(p['name']=='X-Rag-Correlation-ID' for p in spec['paths'][endpoint]['get']['parameters'])
        result=client.get('/v1/traces',headers=headers(KEYS[0]))
        Draft202012Validator(spec['paths']['/v1/traces']['get']['responses']['200']['content']['application/json']['schema']).validate(result.json())
        detail=client.get('/v1/traces/'+response.headers['x-rag-request-id'],headers=headers(KEYS[0]))
        Draft202012Validator(spec['paths']['/v1/traces/{identity}']['get']['responses']['200']['content']['application/json']['schema']).validate(detail.json())
        assert 'origin_request_id' in spec['paths']['/v1/windows']['post']['responses']['202']['content']['application/json']['schema']['properties']
