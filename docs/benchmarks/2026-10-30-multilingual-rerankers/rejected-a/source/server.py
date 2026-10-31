"""Measurement-only loopback bridge. Not an installed or production model service."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--model', required=True)
    p.add_argument('--name', required=True)
    p.add_argument('--port', type=int, required=True)
    p.add_argument('--log', required=True)
    a = p.parse_args()
    start = time.perf_counter()
    root = Path(a.model)
    log = open(a.log, 'x', buffering=1)
    lock = threading.Lock()
    gate = threading.BoundedSemaphore(2)
    state = {'active': 0, 'completed': 0, 'rejected': 0, 'requests': 0}

    def record(value):
        with lock:
            log.write(json.dumps(value, allow_nan=False) + '\n')

    if a.name == 'jina-v3.5':
        import torch
        from transformers import AutoModel
        torch.set_num_threads(4)
        torch.set_num_interop_threads(1)
        # Pinned upstream modeling.py is audited and loaded exclusively from disk.
        model = AutoModel.from_pretrained(str(root), trust_remote_code=True,
            local_files_only=True, torch_dtype=torch.float32,
            attn_implementation='sdpa').eval()
        model._ensure_tokenizer()

        inference_lock = threading.Lock()

        def predict(query, docs):
            before = time.perf_counter()
            # Upstream reconfigures its shared fast tokenizer. Serialize this
            # entire mutable model/tokenizer call; the second accepted request
            # waits in the service and remains inside its client deadline.
            with inference_lock:
                acquired = time.perf_counter()
                query, docs, lengths, qlength = model._truncate_texts(query, docs, 512, 512)
                truncated_ms = (time.perf_counter() - acquired)*1000
                with torch.inference_mode():
                    scores = model.rerank(query, docs, top_n=len(docs))
            out = [0.0]*len(docs)
            for row in scores:
                out[int(row['index'])] = float(row['relevance_score'])
            # The model emits cosine scores, not probabilities. The lab bridge
            # explicitly maps the documented [-1,1] range onto the product's
            # [0,1] transport contract. Preserve every original cosine as evidence.
            if not all(-1.00001 <= s <= 1.00001 for s in out):
                raise ValueError('cosine_range')
            normalized = [(max(-1.0,min(1.0,s))+1)/2 for s in out]
            return normalized, dict(prepare_ms=truncated_ms,
                prepare_scope='external512tokenpretruncation only; upstream retokenization included in total inference, not this subtotal',
                queue_wait_ms=(acquired-before)*1000,
                tokens=lengths, native_scores=out,
                query_tokens=qlength, cap='512 tokens/document; upstream listwise prompt',
                score_semantics='bridge (native_cosine+1)/2; not calibrated probability')
    else:
        import numpy as np
        import onnxruntime as ort
        from tokenizers import Tokenizer
        tokenizer = Tokenizer.from_file(str(root/'tokenizer.json'))
        tokenizer.enable_truncation(max_length=512)
        token_config = json.loads((root/'tokenizer_config.json').read_text())
        pad = token_config.get('pad_token', '<pad>')
        if isinstance(pad,dict):pad=pad['content']
        pad_id = tokenizer.token_to_id(pad)
        if pad_id is None:raise ValueError('tokenizer_pad_identity')
        tokenizer.enable_padding(pad_id=pad_id,pad_token=pad)
        options = ort.SessionOptions()
        options.intra_op_num_threads = 4
        options.inter_op_num_threads = 1
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        session = ort.InferenceSession(str(root/'model.onnx'), sess_options=options,
            providers=['CPUExecutionProvider'])
        names = {v.name for v in session.get_inputs()}

        def predict(query, docs):
            before = time.perf_counter()
            # Per-request encodings; shared tokenizer settings remain immutable.
            encoded = tokenizer.encode_batch([(query, doc) for doc in docs])
            all_inputs = dict(input_ids=np.asarray([e.ids for e in encoded], dtype=np.int64),
                attention_mask=np.asarray([e.attention_mask for e in encoded], dtype=np.int64),
                token_type_ids=np.asarray([e.type_ids for e in encoded], dtype=np.int64))
            inputs = {k:v for k,v in all_inputs.items() if k in names}
            prep = (time.perf_counter()-before)*1000
            logits = session.run(None, inputs)[0].reshape(-1)
            if len(logits) != len(docs) or not np.isfinite(logits).all():
                raise ValueError('invalid_model_output')
            # ONNX emits logits. This measurement bridge explicitly uses a fixed
            # sigmoid to satisfy the product transport contract; MiniLM's upstream
            # default activation is Identity. This is not per-request min/max
            # scaling and does not imply calibrated confidence across models.
            scores = 1/(1+np.exp(-logits.astype(np.float64)))
            return [float(v) for v in scores], dict(prepare_ms=prep,prepare_scope='complete ONNX input tokenization and tensor construction',
                native_scores=[float(v) for v in logits], tokens=[sum(e.attention_mask) for e in encoded],
                cap='512 tokens/query-document pair', score_semantics='bridge sigmoid(native_logit); not calibrated probability')

    record(dict(kind='loaded', name=a.name, load_ms=(time.perf_counter()-start)*1000,
        pid=os.getpid(), affinity=sorted(os.sched_getaffinity(0)),
        cgroup=Path('/proc/self/cgroup').read_text(),
        rss_peak_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss))

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, code, body):
            data = json.dumps(body, allow_nan=False).encode()
            try:
                self.send_response(code)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass  # Disconnected adapter deadline; inference still has to drain.

        def do_GET(self):
            if self.path == '/v1/models':
                return self.send(200, {'data':[{'id':a.name}]})
            if self.path == '/health':
                return self.send(200, {'ready':True, **state})
            return self.send(404, {})

        def do_POST(self):
            if self.path != '/v1/rerank':
                return self.send(404,{})
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 400000:
                return self.send(413,{})
            try:
                data = json.loads(self.rfile.read(size))
                docs = data['documents']
                query = data['query']
                if data.get('model') != a.name or not isinstance(query,str) or not isinstance(docs,list) or not 1<=len(docs)<=24 or not all(isinstance(d,str) for d in docs):
                    raise ValueError('request')
            except (ValueError, KeyError, TypeError):
                return self.send(400,{})
            if not gate.acquire(blocking=False):
                with lock:
                    state['rejected'] += 1
                return self.send(429,{'error':'measurement_capacity'})
            before = time.perf_counter()
            with lock:
                state['active'] += 1
                state['requests'] += 1
                seq = state['requests']
            try:
                scores, detail = predict(query, docs)
                if len(scores) != len(docs) or not all(math.isfinite(v) for v in scores):
                    raise ValueError('finite_complete_output')
                body = dict(model=a.name, results=[dict(index=i,relevance_score=s)
                    for i,s in enumerate(scores)], measurement=dict(sequence=seq, **detail))
                self.send(200,body)
                record(dict(kind='inference', sequence=seq,
                    elapsed_ms=(time.perf_counter()-before)*1000, candidates=len(docs),
                    input_sha256=hashlib.sha256(json.dumps([query,docs],ensure_ascii=False).encode()).hexdigest(),
                    input_chars=sum(map(len,docs)), output=body,
                    rss_peak_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss))
            except Exception as exc:
                self.send(500,{'error':type(exc).__name__})
                record(dict(kind='error',sequence=seq,error=type(exc).__name__))
            finally:
                with lock:
                    state['active'] -= 1
                    state['completed'] += 1
                gate.release()

    ThreadingHTTPServer(('127.0.0.1',a.port),Handler).serve_forever()


if __name__ == '__main__':
    main()
