"""Discoverable protocol-1 HTTP contracts; request models match the gateways."""
from pydantic import TypeAdapter

from ..continuity.model import Checkpoint
from .checkpoints import Packet
from .ingest import Envelope


def document(tools):
    schemas = {}
    def register(name, model):
        schema = (model.model_json_schema if hasattr(model, 'model_json_schema') else TypeAdapter(model).json_schema)(ref_template='#/components/schemas/{model}')
        schemas.update(schema.pop('$defs', {}))
        schemas[name] = schema
        return {'$ref': '#/components/schemas/' + name}
    def obj(properties, required=()):
        return {'type': 'object', 'properties': properties, 'required': list(required)}
    def array(item):
        return {'type': 'array', 'items': item}
    string = {'type': 'string'}
    nullable = {'type': ['string', 'null']}
    integer = {'type': 'integer'}
    boolean = {'type': 'boolean'}
    identifier = {'type': 'string', 'format': 'uuid'}
    source = register('SourceEnvelope', Envelope)
    packet = register('CheckpointPacket', Packet)
    checkpoint = register('Checkpoint', Checkpoint)
    error = obj({'error': string}, ['error'])
    protocol = {'name': 'x-rag-protocol', 'in': 'header', 'required': True, 'schema': {'type': 'string', 'const': '1'}}
    paths = {}
    def operation(path, method, result, *, body=None, status=200, public=False, params=(), description=None):
        def response(schema, text):
            return {'description': text, 'content': {'application/json': {'schema': schema}}}
        responses = {str(status): response(result, 'Durably accepted' if status == 202 else 'Successful response')}
        for code, text in [(400, 'Invalid input'), (401, 'Invalid or revoked credentials'), (403, 'Scope denied'),
                           (404, 'Not found or inaccessible'), (409, 'Cursor or job state conflict'),
                           (413, 'Request or result too large'), (426, 'Unsupported protocol; upgrade client'),
                           (429, 'Capacity exceeded; retry with backoff'), (503, 'Schema or provider unavailable'),
                           (507, 'Storage budget exceeded; pending input is retained')]:
            responses[str(code)] = response(error, text)
        entry = {'responses': responses, 'security': [] if public else [{'bearer': []}],
                 'parameters': ([] if path == '/health' else [protocol]) + list(params)}
        if body is not None:
            entry['requestBody'] = {'required': True, 'content': {'application/json': {'schema': body}}}
        if description:
            entry['description'] = description
        paths.setdefault(path, {})[method] = entry
    def path_parameter(name, schema=string):
        return {'name': name, 'in': 'path', 'required': True, 'schema': schema}
    def query(name, schema):
        return {'name': name, 'in': 'query', 'required': False, 'schema': schema}
    receipt_params = [path_parameter('receipt', identifier)]
    session_params = [path_parameter('session')]
    receipt = obj({'receipt': identifier, 'durable': {'const': True}, 'state': string}, ['receipt', 'durable', 'state'])
    job = obj({'receipt': identifier, 'state': string, 'code': nullable,
               'queue': {'type': ['object', 'null'], 'properties': {'status': string, 'attempts': integer, 'next_attempt_at': string}},
               'created_at': string, 'applied_at': nullable}, ['receipt', 'state', 'code', 'queue', 'created_at', 'applied_at'])
    checkpoint_response = obj({'checkpoint': checkpoint, 'rendered': string}, ['checkpoint', 'rendered'])
    operation('/health', 'get', obj({'status': {'const': 'ok'}}, ['status']), public=True)
    login = obj({'username': {'type': 'string', 'maxLength': 80}, 'password': string, 'uploader_id': identifier}, ['username', 'password'])
    login['additionalProperties'] = False
    operation('/v1/login', 'post', obj({'access_token': string, 'token_type': {'const': 'Bearer'},
              'expires_at': string, 'uploader_id': identifier}, ['access_token', 'token_type', 'expires_at', 'uploader_id']), body=login, public=True)
    operation('/v1/logout', 'post', obj({'logged_out': {'const': True}}, ['logged_out']))
    operation('/v1/windows', 'post', receipt, body=source, status=202,
              description='Idempotent source submission. 202 means source, stream head and queue committed; it does not mean extraction applied.')
    operation('/v1/checkpoints', 'post', obj({'durable': {'const': True}, 'checkpoint': checkpoint}, ['durable', 'checkpoint']), body=packet)
    operation('/v1/checkpoints/{session}', 'get', checkpoint_response, params=session_params,
              description='Own raw client session ID; the service derives the authenticated uploader namespace.')
    for path, method in [('/v1/jobs/{receipt}', 'get'), ('/v1/jobs/{receipt}/cancel', 'post'), ('/v1/jobs/{receipt}/retry', 'post')]:
        operation(path, method, job, params=receipt_params)
    operation('/v1/capabilities', 'get', obj({'protocol': {'const': 1}, 'server_version': string,
              'migrations': array(string), 'tools': array(string), 'limits': {'type': 'object'},
              'principal': obj({'user': string, 'machine': nullable, 'read_only': boolean}, ['user', 'machine', 'read_only'])},
              ['protocol', 'server_version', 'migrations', 'tools', 'limits', 'principal']))
    operation('/v1/admin/status', 'get', obj({'status': string, 'protocol': {'const': 1},
              'queue': {'type': 'object', 'additionalProperties': integer}, 'machines': array(obj({'id': string, 'label': string, 'enabled': boolean, 'user': string}))},
              ['status', 'protocol', 'queue', 'machines']), description='Requires a current administrator principal.')
    operation('/v1/sessions', 'get', obj({'sessions': array(obj({'session_id': string, 'project': string, 'actor': string, 'created_at': string})), 'next': nullable}, ['sessions', 'next']),
              params=[query('before', string), query('limit', {'type': 'integer', 'minimum': 1, 'maximum': 100, 'default': 50})])
    operation('/v1/sessions/{session}/windows', 'get', obj({'session_id': string, 'windows': array(obj({'id': identifier, 'window': {'$ref': '#/components/schemas/Window'}, 'state': string})), 'next': nullable}, ['session_id', 'windows', 'next']),
              params=session_params+[query('after', identifier), query('limit', {'type': 'integer', 'minimum': 1, 'maximum': 4, 'default': 1})])
    operation('/v1/sessions/{session}/checkpoint', 'get', checkpoint_response, params=session_params,
              description='Team-readable server session ID returned by /v1/sessions; current team and project grants are required.')
    for tool in tools:
        operation('/v1/tools/'+tool.name, 'post', tool.outputSchema or {'type': 'object'}, body=tool.inputSchema, description=tool.description)
        paths['/v1/tools/'+tool.name]['post']['operationId'] = tool.name
    operation('/v1/openapi.json', 'get', {'type': 'object'})
    return {'openapi': '3.1.0', 'info': {'title': 'agentic-rag service', 'version': '1'}, 'paths': paths,
            'components': {'schemas': schemas, 'securitySchemes': {'bearer': {'type': 'http', 'scheme': 'bearer'}}}}
