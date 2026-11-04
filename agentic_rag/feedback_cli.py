"""Small local/remote adapter for explicit retrieval feedback."""
from __future__ import annotations

import json


def add_parser(sub):
    parser=sub.add_parser('feedback',help='explicit scoped retrieval signals; never changes knowledge')
    commands=parser.add_subparsers(dest='feedback_cmd',required=True)
    search=commands.add_parser('search')
    search.add_argument('query')
    search.add_argument('--domain',required=True)
    where=search.add_mutually_exclusive_group(required=True)
    where.add_argument('--project')
    where.add_argument('--scope',choices=['global'])
    search.add_argument('--idempotency-key',required=True)
    search.add_argument('-k',type=int,default=8)
    search.add_argument('--strategy',choices=['lexical','auto','hybrid'],default='lexical')
    search.add_argument('--rerank',choices=['auto','off'],default='off')
    search.add_argument('--context',choices=['auto','off'],default='off')
    for name in ('submit','update','retract'):
        p=commands.add_parser(name)
        if name=='submit':
            p.add_argument('event_id')
            p.add_argument('--idempotency-key',required=True)
        else:
            p.add_argument('feedback_id')
            p.add_argument('--expected-revision',type=int,required=True)
        if name!='retract':
            p.add_argument('--kind',required=True,choices=['useful','not_useful','wrong_source','missing_evidence'])
            p.add_argument('--result-id')
            p.add_argument('--expected-id')
            p.add_argument('--comment',default='')
    get=commands.add_parser('get')
    anchor=get.add_mutually_exclusive_group(required=True)
    anchor.add_argument('--feedback-id')
    anchor.add_argument('--event-id')
    listing=commands.add_parser('list')
    listing.add_argument('--limit',type=int,default=20)
    approve=commands.add_parser('approve',help='local owner: approve one current negative signal for private evaluation')
    approve.add_argument('feedback_id')
    approve.add_argument('--expected-revision',type=int,required=True)
    approve.add_argument('--query',required=True)
    for name in ('summary','export'):
        p=commands.add_parser(name,help='local owner only; no ranking or knowledge changes')
        p.add_argument('--domain',required=True)
        where=p.add_mutually_exclusive_group(required=True)
        where.add_argument('--project')
        where.add_argument('--scope',choices=['global'])
        p.add_argument('--limit',type=int,default=32)
        if name=='export':p.add_argument('--output',required=True)



def run(cfg,args):
    from . import mcp_server
    from .service.context import CURRENT
    name='memory_feedback_'+args.feedback_cmd
    arguments={k:v for k,v in vars(args).items() if k not in ('cmd','feedback_cmd','filter','metadata')}
    if args.feedback_cmd in ('approve','summary','export'):
        from .benchmark import feedback as private
        if 'output' in arguments:arguments['output_path']=arguments.pop('output')
        operation='export_feedback' if args.feedback_cmd=='export' else args.feedback_cmd
        result=getattr(private,operation)(cfg,**arguments)
    elif cfg.service_mode=='client' and CURRENT.get() is None:
        from .service.client import RemoteClient
        with RemoteClient(cfg) as client:
            result=client.invoke(name,arguments)
    else:
        from . import db,feedback
        request=CURRENT.get()
        cfg=request.config if request is not None else cfg
        role='reader' if args.feedback_cmd in ('get','list') else 'writer'
        operation='list_feedback' if args.feedback_cmd=='list' else 'capture' if args.feedback_cmd=='search' else args.feedback_cmd
        with db.connect(cfg,role=role) as conn:
            result=getattr(feedback,operation)(conn,cfg,**arguments)
    print(json.dumps(mcp_server._plain(result),sort_keys=True))
    return 0
