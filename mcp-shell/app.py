#!/usr/bin/env python3
"""mcp-shell - 双 MCP 服务 (终极安全稳定 & 302重定向修复版)"""
import subprocess
import os
import json
import asyncio
import traceback
import shlex
from starlette.applications import Starlette
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket
from starlette.responses import Response, JSONResponse, StreamingResponse
import uvicorn

port = int(os.getenv("PORT", 8080))

sse1_clients = {}
sse2_clients = {}
local_ws = None
local_ws_lock = asyncio.Lock()
pending = {}

class SSEConnection:
    def __init__(self, session_id: str):
        self.queue = asyncio.Queue(maxsize=100)
        self.session_id = session_id

async def health(request):
    async with local_ws_lock:
        ws_connected = local_ws is not None
    return JSONResponse({
        "status": "ok", 
        "service": "mcp-shell", 
        "computer_connected": ws_connected
    })

async def sse1_stream(request):
    sid = request.query_params.get("session_id", "default_session")
    conn = SSEConnection(sid)
    sse1_clients[sid] = conn
    
    async def es():
        try:
            host = request.headers.get("host", "ranrande.zeabur.app")
            # 修复 302 关键点：强行使用 https 协议，防止反向代理导致 302 重定向报错
            yield f"event: endpoint\ndata: https://{host}/sse/messages?session_id={sid}\n\n"
            while True:
                data = await conn.queue.get()
                try:
                    json_data = json.dumps(data)
                    yield f"data: {json_data}\n\n"
                except Exception:
                    pass
        except asyncio.CancelledError:
            pass
        finally:
            sse1_clients.pop(sid, None)
            
    return StreamingResponse(es(), media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "Access-Control-Allow-Origin": "*"
        })

async def sse1_post(request):
    sid = request.query_params.get("session_id", "default_session")
    conn = sse1_clients.get(sid)
    if not conn: 
        return JSONResponse({"error": f"session {sid} not found"}, 404)
    
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid json"}, 400)
        
    mid = body.get("id", 0)
    method = body.get("method", "")
    params = body.get("params", {})
    
    if method == "initialize":
        await conn.queue.put({
            "jsonrpc": "2.0",
            "id": mid,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "mcp-shell", "version": "1.0.0"}
            }
        })
    elif method == "notifications/initialized":
        pass
    elif method == "tools/list":
        await conn.queue.put({
            "jsonrpc": "2.0",
            "id": mid,
            "result": {
                "tools": [{
                    "name": "run",
                    "description": "云端执行命令",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"command": {"type": "string"}},
                        "required": ["command"]
                    }
                }]
            }
        })
    elif method == "tools/call":
        cmd = params.get("arguments", {}).get("command", "")
        try:
            args = shlex.split(cmd)
            r = subprocess.run(args, shell=False, capture_output=True, text=True, timeout=60)
            o = (r.stdout or "(ok)") + ("\n" + r.stderr if r.stderr else "")
            await conn.queue.put({
                "jsonrpc": "2.0", 
                "id": mid, 
                "result": {"content": [{"type": "text", "text": o}]}
            })
        except Exception as e:
            await conn.queue.put({
                "jsonrpc": "2.0", 
                "id": mid, 
                "error": {"code": -32603, "message": str(e)}
            })
    else:
        await conn.queue.put({"jsonrpc": "2.0", "id": mid, "result": {}})
    return Response(status_code=202)

async def sse2_stream(request):
    sid = request.query_params.get("session_id", "default_session")
    conn = SSEConnection(sid)
    sse2_clients[sid] = conn
    
    async def es():
        try:
            host = request.headers.get("host", "ranrande.zeabur.app")
            # 修复 302 关键点：强行使用 https 协议，防止反向代理导致 302 重定向报错
            yield f"event: endpoint\ndata: https://{host}/sse2/messages?session_id={sid}\n\n"
            while True:
                data = await conn.queue.get()
                try:
                    json_data = json.dumps(data)
                    yield f"data: {json_data}\n\n"
                except Exception:
                    pass
        except asyncio.CancelledError:
            pass
        finally:
            sse2_clients.pop(sid, None)
            
    return StreamingResponse(es(), media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "Access-Control-Allow-Origin": "*"
        })

async def sse2_post(request):
    global local_ws, pending
    sid = request.query_params.get("session_id", "default_session")
    conn = sse2_clients.get(sid)
    if not conn: 
        return JSONResponse({"error": f"session {sid} not found"}, 404)
    
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid json"}, 400)
        
    mid = body.get("id", 0)
    method = body.get("method", "")
    params = body.get("params", {})
    
    if method == "initialize":
        await conn.queue.put({
            "jsonrpc": "2.0",
            "id": mid,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "mcp-shell", "version": "1.0.0"}
            }
        })
    elif method == "notifications/initialized":
        pass
    elif method == "tools/list":
        tools = [
            {"name": "computer", "description": "电脑 - 执行cmd命令", "inputSchema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
            {"name": "keyboard", "description": "键盘 - 模拟打字输入", "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}},
            {"name": "click", "description": "鼠标 - 点击屏幕坐标", "inputSchema": {"type": "object", "properties": {"x": {"type": "integer"}, "y": {"type": "integer"}}, "required": ["x", "y"]}},
            {"name": "screenshot", "description": "截图 - 获取屏幕截图", "inputSchema": {"type": "object", "properties": {}}},
            {"name": "say", "description": "消息 - 发送消息给电脑", "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}},
        ]
        await conn.queue.put({"jsonrpc": "2.0", "id": mid, "result": {"tools": tools}})
    elif method == "tools/call":
        tool_name = params.get("name", "")
        args = params.get("arguments", {})
        result = "[电脑离线]"
        fut = None
        
        async with local_ws_lock:
            if local_ws:
                rid = f"r{mid or '0'}_{asyncio.get_running_loop().time()}"
                fut = asyncio.get_running_loop().create_future()
                pending[rid] = fut
                
                ct = {"computer": "CMD", "keyboard": "KEYBOARD", "click": "CLICK", "screenshot": "SCREENSHOT", "say": "SAY"}.get(tool_name, "CMD")
                cd = {"computer": args.get("command", ""), "keyboard": args.get("text", ""), "click": json.dumps({"x": args.get("x", 0), "y": args.get("y", 0)}), "screenshot": "", "say": args.get("text", "")}.get(tool_name, str(args))
                
                try:
                    await local_ws.send_text(json.dumps({"t": ct, "d": cd, "id": rid}))
                except Exception:
                    local_ws = None
                    result = "[电脑离线]"
                    pending.pop(rid, None)
                    fut = None
        
        if fut:
            try:
                result = await asyncio.wait_for(fut, 30)
            except asyncio.TimeoutError:
                result = "[电脑超时]"
            except Exception as e:
                result = f"(云端转发错误: {e})"
            finally:
                pending.pop(rid, None)
                
        try:
            rd = json.loads(result)
            if rd.get("mimeType", "").startswith("image/"):
                content = [{"type": "image", "data": rd.get("result", ""), "mimeType": rd["mimeType"]}]
            else:
                content = [{"type": "text", "text": rd.get("result", result)}]
        except Exception:
            content = [{"type": "text", "text": result}]
            
        await conn.queue.put({"jsonrpc": "2.0", "id": mid, "result": {"content": content}})
    else:
        await conn.queue.put({"jsonrpc": "2.0", "id": mid, "result": {}})
    return Response(status_code=202)

async def ws_handler(ws: WebSocket):
    global local_ws, pending
    try:
        await ws.accept()
        async with local_ws_lock:
            local_ws = ws
        while True:
            raw = await ws.receive_text()
            try:
                data = json.loads(raw)
                rid = data.get("id", "")
                if rid and rid in pending:
                    pending[rid].set_result(raw)
            except Exception:
                pass
    except Exception:
        pass
    finally:
        async with local_ws_lock:
            if local_ws == ws:
                local_ws = None
        for rid, fut in list(pending.items()):
            if not fut.done():
                fut.set_result("[电脑已断开连接]")

app = Starlette(routes=[
    Route("/", endpoint=health),
    Route("/sse", endpoint=sse1_stream),
    Route("/sse/messages", endpoint=sse1_post, methods=["POST"]),
    Route("/sse2", endpoint=sse2_stream),
    Route("/sse2/messages", endpoint=sse2_post, methods=["POST"]),
    WebSocketRoute("/ws", endpoint=ws_handler),
])

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
