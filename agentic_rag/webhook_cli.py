"""Local/remote scoped management; operator-only capture, signing and sender."""
import json
from pathlib import Path


def add_parser(sub):
    commands=sub.add_parser('webhooks',help='explicit signed callbacks; capture defaults off').add_subparsers(dest='webhook_cmd',required=True)
    p=commands.add_parser('subscribe')
    p.add_argument('--endpoint',required=True);p.add_argument('--project',required=True)
    scope=p.add_mutually_exclusive_group(required=True);scope.add_argument('--domain');scope.add_argument('--jobs',action='store_true')
    p.add_argument('--kind',action='append',required=True,dest='kinds');p.add_argument('--idempotency-key',required=True)
    p=commands.add_parser('status');p.add_argument('subscription_id')
    for name in ('update','disable','rotate','test','replay'):
        p=commands.add_parser(name);p.add_argument('subscription_id');p.add_argument('--expected-revision',type=int,required=True)
        if name=='update':p.add_argument('--endpoint',required=True)
        if name=='replay':p.add_argument('--delivery-id',required=True)
    p=commands.add_parser('key-init');p.add_argument('--output',required=True,type=Path)
    p=commands.add_parser('key-export');p.add_argument('subscription_id');p.add_argument('--output',required=True,type=Path)
    p=commands.add_parser('capture');p.add_argument('state',choices=['on','off'])
    p=commands.add_parser('sender');p.add_argument('--limit',type=int,default=1)
    commands.add_parser('prune')


def run(cfg,args):
    from . import db,mcp_server,webhooks,webhook_delivery
    from .service.context import CURRENT
    operation=args.webhook_cmd
    if operation in ('key-init','key-export','capture','sender','prune'):
        webhook_delivery._operator(cfg)
        if operation=='key-init':result=webhook_delivery.key_init(cfg,args.output)
        elif operation=='key-export':result=webhook_delivery.key_export(cfg,subscription_id=args.subscription_id,output=args.output)
        elif operation=='capture':result=webhook_delivery.capture(cfg,args.state=='on')
        elif operation=='prune':result=webhook_delivery.prune(cfg)
        else:
            if not 1<=args.limit<=100:raise ValueError('webhook_invalid')
            result={'deliveries':[]}
            for _ in range(args.limit):
                outcome=webhook_delivery.send_one(cfg)
                if outcome.get('state')=='idle':break
                result['deliveries'].append(outcome)
    else:
        arguments={k:v for k,v in vars(args).items() if k not in ('cmd','webhook_cmd','jobs')}
        if operation=='subscribe' and args.jobs:arguments['domain']=None
        if cfg.service_mode=='client' and CURRENT.get() is None:
            from .service.client import RemoteClient
            with RemoteClient(cfg) as client:result=client.invoke('webhook_'+operation,arguments)
        else:
            with db.connect(cfg,role='reader' if operation=='status' else 'writer') as conn:
                result=getattr(webhooks,operation)(conn,cfg,**arguments)
    print(json.dumps(mcp_server._plain(result),sort_keys=True))
    return 0
