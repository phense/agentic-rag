"""Exercise the actual pre-decoding stdio transport, including invalid notifications."""
import asyncio
import json
import pytest
from agentic_rag.metadata_stdio import guarded_stdio

class Input:
    def __init__(self,lines):self.lines=lines
    async def __aiter__(self):
        for line in self.lines:yield line

class Output:
    def __init__(self):self.lines=[]
    async def write(self,line):self.lines.append(line)
    async def flush(self):pass

@pytest.mark.parametrize('identity',[1,None,True])
def test_duplicate_typed_stdio_message_never_reaches_dispatch(identity):
    bad={'jsonrpc':'2.0','method':'tools/call','params':{'name':'memory_search','arguments':{'filter':None}}}
    if identity is not None:bad['id']=identity
    raw=json.dumps(bad).replace('"filter": null','"filter":{"version":1,"version":1}')
    good='{"jsonrpc":"2.0","id":2,"method":"ping"}'
    async def check():
        stdout=Output()
        async with guarded_stdio(Input([raw,good]),stdout) as (incoming,outgoing):
            packet=await incoming.receive()
            assert packet.message.root.id==2
            await outgoing.aclose()
        if type(identity) is int:
            assert len(stdout.lines)==1
            error=json.loads(stdout.lines[0]);assert error['id']==1 and error['error']['message']=='invalid_filter'
        else:assert stdout.lines==[]
    asyncio.run(check())
