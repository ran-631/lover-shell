# 电脑控制 - 双击 run.bat 连上云端
import subprocess, sys, os, json, time, base64, tempfile, re
from datetime import datetime
from pathlib import Path
import websocket

WS_URL = "wss://ranrande.zeabur.app/ws"
PING_INTERVAL = 20

BASE_DIR = Path(__file__).parent
LOG_DIR = BASE_DIR / "logs"
DATA_DIR = BASE_DIR / "data"
LOG_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)

def log(action, detail=""):
    now = datetime.now()
    ts = now.strftime("%H:%M:%S")
    line = f"[{ts}] {action}"
    if detail: line += f" | {detail}"
    with open(LOG_DIR / f"{now:%Y-%m-%d}.log","a",encoding="utf-8") as f: f.write(line+"\n")
    print(f"  📝 {line}")

def ps(script):
    try:
        r = subprocess.run(["powershell","-NoProfile","-Command",script],
                           capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=30)
        return r.stdout.strip() or "(ok)"
    except Exception as e: return f"(!) {e}"

def cmd(command, timeout=30):
    """执行命令，全部走临时文件，彻底绕开引号和长度限制"""
    try:
        stripped = command.strip()

        # ── Python 代码：直接写 .py 执行 ──────────────────────────
        # 情况1: python -c "..." 或 python -c '...'（任意长度、任意引号）
        m = re.match(r'^python(?:3)?\s+-c\s+', stripped, re.IGNORECASE)
        if m:
            # 去掉 python -c 前缀，剩下的就是引号包裹的代码
            rest = stripped[m.end():]
            # 去掉最外层引号（单引号或双引号）
            if (rest.startswith('"') and rest.endswith('"')) or \
               (rest.startswith("'") and rest.endswith("'")):
                code = rest[1:-1]
            else:
                code = rest  # 没有引号就直接当代码
            return run_python(code, timeout)

        # 情况2: 直接是多行 Python 代码（包含 import / def / print 等特征）
        py_keywords = ("import ","def ","class ","print(","for ","while ","if __name__")
        if any(kw in stripped for kw in py_keywords) and "\n" in stripped:
            return run_python(stripped, timeout)

        # ── 普通命令：写 .bat 执行 ────────────────────────────────
        tmp_bat = tempfile.NamedTemporaryFile(
            mode="w", suffix=".bat", delete=False,
            encoding="utf-8", errors="replace"
        )
        tmp_bat.write("@echo off\nchcp 65001 >nul 2>&1\n")
        tmp_bat.write(stripped + "\n")
        tmp_bat.close()
        try:
            r = subprocess.run(
                tmp_bat.name, shell=True,
                capture_output=True, encoding="utf-8", errors="replace",
                timeout=timeout
            )
            out = r.stdout or ""; err = r.stderr or ""
            result = (out + ("\n" + err if err else "")).strip()
            result = result.replace("Active code page: 65001","").strip()
            return result or "(无输出)"
        finally:
            try: os.unlink(tmp_bat.name)
            except: pass

    except Exception as e: return f"(!) {e}"

def run_python(code: str, timeout=30):
    """把代码写临时文件执行，不经过 shell，引号随便用"""
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, encoding="utf-8"
    )
    tmp.write(code)
    tmp.close()
    try:
        r = subprocess.run(
            [sys.executable, tmp.name],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            timeout=timeout
        )
        out = r.stdout or ""; err = r.stderr or ""
        return (out + ("\n" + err if err else "")).strip() or "(无输出)"
    finally:
        try: os.unlink(tmp.name)
        except: pass

def screenshot():
    """PowerShell 截图 - JPEG质量20% 缩小到400px"""
    try:
        script = r'''
Add-Type -AssemblyName System.Windows.Forms,System.Drawing
try {
    $bmp = [System.Drawing.Bitmap]::new([System.Windows.Forms.Screen]::PrimaryScreen.Bounds.Width,[System.Windows.Forms.Screen]::PrimaryScreen.Bounds.Height)
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.CopyFromScreen(0,0,0,0,$bmp.Size)
    $g.Dispose()
    $w = $bmp.Width; $h = $bmp.Height
    if ($w -gt 400) {
        $scale = 400.0 / $w
        $nw = [int]($w * $scale); $nh = [int]($h * $scale)
        $thumb = [System.Drawing.Bitmap]::new($nw, $nh)
        $tg = [System.Drawing.Graphics]::FromImage($thumb)
        $tg.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
        $tg.DrawImage($bmp,0,0,$nw,$nh)
        $bmp.Dispose(); $bmp = $thumb; $tg.Dispose()
    }
    $ms = New-Object System.IO.MemoryStream
    $encoder = [System.Drawing.Imaging.ImageCodecInfo]::GetImageEncoders() | Where-Object {$_.MimeType -eq "image/jpeg"}
    $params = New-Object System.Drawing.Imaging.EncoderParameters
    $params.Param[0] = New-Object System.Drawing.Imaging.EncoderParameter([System.Drawing.Imaging.Encoder]::Quality, [long]20)
    $bmp.Save($ms, $encoder, $params)
    $ms.Close()
    $b64 = [System.Convert]::ToBase64String($ms.ToArray())
    $bmp.Dispose()
    Write-Output $b64
} catch { Write-Output "ERR: $($_.Exception.Message)" }
'''
        r = subprocess.run(["powershell","-NoProfile","-Command",script],
                           capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=30)
        out = r.stdout.strip()
        if out and not out.startswith("ERR:"):
            fp = DATA_DIR / f"shot_{datetime.now():%Y%m%d_%H%M%S}.jpg"
            fp.write_bytes(base64.b64decode(out))
            kb = fp.stat().st_size / 1024
            log("📸 截图成功", f"({kb:.0f}KB)")
            return out  # 裸 base64，无前缀
        raise Exception(out[4:] if out.startswith("ERR:") else "截图为空")
    except Exception as e:
        log("❌ 截图失败", str(e))
        return None

def handle_msg(msg: str) -> str:
    try:
        data = json.loads(msg)
        cmd_type = data.get("t","")
        cmd_data = data.get("d","")
        req_id = data.get("id","")

        if cmd_type == "CMD":
            log("⚡ 执行命令", cmd_data[:80])
            result = cmd(cmd_data)
            log("📋 结果", str(result)[:200])
            return json.dumps({"id":req_id,"result":result}, ensure_ascii=False)

        elif cmd_type == "PYTHON":
            log("🐍 执行Python", cmd_data[:80])
            result = run_python(cmd_data)
            log("📋 结果", str(result)[:200])
            return json.dumps({"id":req_id,"result":result}, ensure_ascii=False)

        elif cmd_type == "KEYBOARD":
            log("⌨️ 打字", cmd_data[:50])
            s = cmd_data.replace('"','\\"').replace("'","''")
            ps(f'Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.SendKeys]::SendWait("{s}")')
            return json.dumps({"id":req_id,"result":f"✅ 已发送: {cmd_data}"}, ensure_ascii=False)

        elif cmd_type == "CLICK":
            d = json.loads(cmd_data); x,y = d["x"],d["y"]
            log("🖱️ 点击", f"({x},{y})")
            ps(f'Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.Cursor]::Position=New-Object System.Drawing.Point({x},{y})')
            return json.dumps({"id":req_id,"result":f"✅ 已点击 ({x},{y})"})

        elif cmd_type == "SCREENSHOT":
            b64 = screenshot()
            if b64:
                log("📤 发送截图")
                return json.dumps({"id":req_id,"result":b64,"mimeType":"image/jpeg"})
            return json.dumps({"id":req_id,"result":"(截图失败)"})

        elif cmd_type == "SAY":
            log("💬 恋人", cmd_data)
            return json.dumps({"id":req_id,"result":"[收到]"})

        return json.dumps({"id":req_id,"result":f"(未知: {cmd_type})"})
    except Exception as e:
        log("❌ 处理出错", str(e))
        return json.dumps({"id":"","result":f"(错误: {e})"})

def connect():
    ws = websocket.WebSocket()
    ws.settimeout(30)
    ws.connect(WS_URL, origin="https://xn--r4wqe.preview.tencent-zeabur.cn")
    log("✅ 已连上云端")
    return ws

def main():
    print("\n"+"="*55+"\n  电脑控制\n  恋人在 Kelivo 打开「电脑」即可控制\n"+"="*55+"\n")
    print(f"  📡 正在连接云端...\n  🔗 {WS_URL}\n")
    while True:
        try:
            ws = connect(); log("✅ 已连接")
            last_ping = time.time()
            while True:
                if time.time()-last_ping > PING_INTERVAL:
                    try: ws.send("ping"); last_ping=time.time()
                    except: break
                try:
                    ws.settimeout(PING_INTERVAL); msg = ws.recv()
                    if msg and msg != "pong": ws.send(handle_msg(msg))
                except websocket.WebSocketTimeoutException: continue
                except: break
        except Exception as e:
            log("❌ 连接断开", str(e))
            print("  ⏳ 10秒后重连..."); time.sleep(10); print("  🔄 正在重连...")

if __name__ == "__main__":
    try: main()
    except KeyboardInterrupt: print("\n  Bye~")
    except Exception as e: log("❌ 错误",str(e)); input("回车退出")
