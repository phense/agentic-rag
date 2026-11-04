"""The SDK stdio transport with a pre-decoding typed duplicate-key guard."""
from contextlib import asynccontextmanager
from io import TextIOWrapper
import json
import sys
import anyio
import mcp.types as types
from mcp.shared.message import SessionMessage
from mcp.server.fastmcp import FastMCP
from .metadata import validate_transport,MetadataError


@asynccontextmanager
async def guarded_stdio(stdin=None,stdout=None):
    stdin=stdin or anyio.wrap_file(TextIOWrapper(sys.stdin.buffer,encoding='utf-8',errors='replace'))
    stdout=stdout or anyio.wrap_file(TextIOWrapper(sys.stdout.buffer,encoding='utf-8'))
    incoming,read_stream=anyio.create_memory_object_stream(0)
    write_stream,outgoing=anyio.create_memory_object_stream(0)
    async def read():
        try:
            async with incoming:
                async for line in stdin:
                    try:
                        validate_transport(line)
                        message=types.JSONRPCMessage.model_validate_json(line)
                    except MetadataError:
                        raw=json.loads(line);identity=raw.get('id') if isinstance(raw,dict) else None
                        # JSON-RPC notifications and malformed IDs must never execute,
                        # and cannot receive a response carrying a valid request ID.
                        if type(identity) not in (str,int):continue
                        error=types.JSONRPCError(jsonrpc='2.0',id=identity,
                            error=types.ErrorData(code=-32602,message='invalid_filter'))
                        await write_stream.send(SessionMessage(types.JSONRPCMessage(error)))
                        continue
                    except Exception as exc:
                        await incoming.send(exc)
                        continue
                    await incoming.send(SessionMessage(message))
        except anyio.ClosedResourceError:
            await anyio.lowlevel.checkpoint()
    async def write():
        try:
            async with outgoing:
                async for packet in outgoing:
                    await stdout.write(packet.message.model_dump_json(by_alias=True,exclude_none=True)+'\n')
                    await stdout.flush()
        except anyio.ClosedResourceError:
            await anyio.lowlevel.checkpoint()
    async with anyio.create_task_group() as group:
        group.start_soon(read);group.start_soon(write)
        yield read_stream,write_stream


class MetadataMCP(FastMCP):
    async def run_stdio_async(self):
        async with guarded_stdio() as (incoming,outgoing):
            await self._mcp_server.run(incoming,outgoing,self._mcp_server.create_initialization_options())
