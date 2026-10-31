"""Explicit public preparation and offline, bounded loopback ONNX reranking."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import threading

from .reranker_profiles import catalogue, preset

MAX_BODY = 65536


def verify(path, artifact):
    if path.is_symlink() or not path.is_file() or path.stat().st_size != artifact['bytes']:
        raise ValueError('reranker artifact missing or invalid')
    with path.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != artifact['sha256']:
            raise ValueError('reranker artifact checksum mismatch')


def prepare(root, names):
    """Only this explicit command can download; interrupted staging is retryable."""
    import httpx
    root = Path(root)
    for name in names:
        row = preset(name)
        directory = root / name
        directory.mkdir(parents=True, exist_ok=True)
        for filename, artifact in row['files'].items():
            target = directory / filename
            if target.exists():
                verify(target, artifact)
                continue
            url = f"https://huggingface.co/{row['repo']}/resolve/{row['revision']}/{artifact['upstream_path']}"
            fd, stage = tempfile.mkstemp(prefix='.download-', dir=directory)
            stage = Path(stage)
            try:
                with os.fdopen(fd, 'wb') as output, httpx.Client(trust_env=False, follow_redirects=True, timeout=60) as client:
                    with client.stream('GET', url) as response:
                        response.raise_for_status()
                        size = 0
                        for chunk in response.iter_bytes():
                            size += len(chunk)
                            if size > artifact['bytes']:
                                raise ValueError('oversized reranker download')
                            output.write(chunk)
                    output.flush()
                    os.fsync(output.fileno())
                verify(stage, artifact)
                # Never replace an already installed artifact during a retry.
                os.link(stage, target)
            finally:
                stage.unlink(missing_ok=True)
    return {'prepared': list(names)}


class OnnxRanker:
    def __init__(self, root, row, threads):
        root = Path(root) / row['id']
        for name, artifact in row['files'].items():
            verify(root / name, artifact)
        import numpy as np
        import onnxruntime as ort
        from tokenizers import Tokenizer
        self.np = np
        self.tokenizer = Tokenizer.from_file(str(root / 'tokenizer.json'))
        self.tokenizer.enable_truncation(max_length=512)
        pad = row['pad']
        pad_id = self.tokenizer.token_to_id(pad)
        if pad_id is None:
            raise ValueError('reranker padding token missing')
        self.tokenizer.enable_padding(pad_id=pad_id, pad_token=pad)
        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        self.session = ort.InferenceSession(str(root / 'model.onnx'), sess_options=options,
                                           providers=['CPUExecutionProvider'])
        self.inputs = {v.name for v in self.session.get_inputs()}
        if not {'input_ids', 'attention_mask'} <= self.inputs or self.inputs - {'input_ids', 'attention_mask', 'token_type_ids'}:
            raise ValueError('unsupported reranker inputs')

    def __call__(self, query, documents):
        np = self.np
        encoded = self.tokenizer.encode_batch([(query, doc) for doc in documents])
        values = {name: np.asarray([getattr(e, attr) for e in encoded], dtype=np.int64)
                  for name, attr in [('input_ids', 'ids'), ('attention_mask', 'attention_mask'), ('token_type_ids', 'type_ids')]}
        logits = self.session.run(None, {k: values[k] for k in self.inputs})[0].reshape(-1)
        if len(logits) != len(documents) or not np.isfinite(logits).all():
            raise ValueError('invalid reranker output')
        # Stable sigmoid preserves logit order; these are not truth probabilities.
        return [1 / (1 + math.exp(-float(x))) if x >= 0 else math.exp(float(x)) / (1 + math.exp(float(x))) for x in logits]


def create_app(rankers):
    """One shared native slot stays occupied after an HTTP caller times out."""
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route
    from starlette.middleware.trustedhost import TrustedHostMiddleware
    gate = threading.Lock()
    rows = {preset(name)['alias']: (preset(name), fn) for name, fn in rankers.items()}

    async def models(request):
        return JSONResponse({'data': [{'id': alias, 'revision': row['files']['model.onnx']['sha256']}
                                      for alias, (row, _) in rows.items()]})

    async def rerank(request):
        try:
            # Never accept cross-origin browser submission to the local daemon.
            if request.headers.get('origin') is not None:
                return JSONResponse({'error': 'origin_denied'}, 403)
            body = bytearray()
            async with asyncio.timeout(5):
                async for chunk in request.stream():
                    if len(body) + len(chunk) > MAX_BODY:
                        return JSONResponse({'error': 'request_too_large'}, 413)
                    body.extend(chunk)
            data = json.loads(body)
            if not isinstance(data, dict) or set(data) - {'model', 'query', 'documents', 'top_n', 'return_documents'}:
                raise ValueError()
            query, docs = data['query'], data['documents']
            if (not isinstance(query, str) or not 1 <= len(query) <= 512
                    or not isinstance(docs, list) or not 1 <= len(docs) <= 12
                    or any(not isinstance(d, str) or not 1 <= len(d) <= 1200 for d in docs)
                    or type(data.get('top_n')) is not int or data['top_n'] != len(docs)
                    or data.get('return_documents', False) is not False
                    or not isinstance(data['model'], str) or data['model'] not in rows):
                raise ValueError()
        except (ValueError, KeyError, TypeError, RecursionError):
            return JSONResponse({'error': 'invalid_request'}, 400)
        except TimeoutError:
            return JSONResponse({'error': 'request_timeout'}, 408)
        if not gate.acquire(blocking=False):
            return JSONResponse({'error': 'reranker_capacity'}, 429)
        def execute():
            try:
                scores = rows[data['model']][1](query, docs)
                if len(scores) != len(docs) or any(type(s) not in (int, float) or not math.isfinite(s) or not 0 <= s <= 1 for s in scores):
                    raise ValueError()
                return {'model': data['model'], 'results': [{'index': i, 'relevance_score': score} for i, score in enumerate(scores)]}
            finally:
                gate.release()
        try:
            future = asyncio.get_running_loop().run_in_executor(None, execute)
        except BaseException:
            gate.release()
            raise
        # A disconnected caller must not cancel a queued executor call: that
        # call owns the slot release even if its native kernel has not started.
        future.add_done_callback(lambda done: done.exception() if not done.cancelled() else None)
        try:
            return JSONResponse(await asyncio.shield(future))
        except Exception:
            return JSONResponse({'error': 'inference_unavailable'}, 503)

    app = Starlette(routes=[Route('/v1/models', models), Route('/v1/rerank', rerank, methods=['POST'])])
    return TrustedHostMiddleware(app, allowed_hosts=['127.0.0.1', 'localhost', 'testserver'])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for command in ('prepare', 'serve'):
        part = sub.add_parser(command)
        part.add_argument('--models-dir', type=Path, required=True)
        part.add_argument('--profiles', nargs='+', choices=[p['id'] for p in catalogue()], default=[p['id'] for p in catalogue()])
        if command == 'serve':
            part.add_argument('--host', choices=['127.0.0.1'], default='127.0.0.1')
            part.add_argument('--port', type=int, default=8766)
            part.add_argument('--threads', type=int, choices=range(1, 9), default=4)
    args = parser.parse_args(argv)
    if args.command == 'prepare':
        print(json.dumps(prepare(args.models_dir, args.profiles)))
    else:
        if not 1 <= args.port <= 65535:
            parser.error('port must be1..65535')
        rankers = {name: OnnxRanker(args.models_dir, preset(name), args.threads) for name in args.profiles}
        import uvicorn
        uvicorn.run(create_app(rankers), host=args.host, port=args.port, access_log=False,
                    log_level='error', proxy_headers=False, limit_concurrency=8)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
