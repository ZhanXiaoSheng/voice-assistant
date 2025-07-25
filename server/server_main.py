# server/server_main.py

import asyncio
import websockets
import os
import sys
import wave
import json
import uuid
import yaml
from collections import defaultdict

# 添加项目根目录到Python路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)


from utils.logger import setup_logger
from modules.asr import transcribe_audio
from modules.gpt import GPTProcessor
from modules.tts import synthesize_speech

# 构建配置文件的正确路径
config_path = os.path.join(project_root, "config", "server.yaml")

# 加载配置
with open(config_path, "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)

# 初始化日志
logger = setup_logger("Server", "server.log", config["log_level"])

# 初始化GPT处理器
gpt_processor = GPTProcessor(
    api_key=config["gpt"]["api_key"],
    base_url=config["gpt"]["base_url"].strip(),
    model=config["gpt"]["model"],
    max_history=config["gpt"]["max_history"],
    trim_history_to=config["gpt"]["trim_history_to"],
    system_prompt=config["gpt"].get("system_prompt", "你叫小迪，是一个专业的智能语音助手")
)

# 创建临时目录
TEMP_DIR = config["temp_dir"]
os.makedirs(TEMP_DIR, exist_ok=True)

# 保存每个连接的音频片段
user_sessions = defaultdict(dict)

async def handle_audio_message(websocket, uid, message):
    """处理音频消息"""
    try:
        user_sessions[uid].setdefault('audio_buffer', []).append(message)
        await websocket.send(json.dumps({"status": "receiving_audio"}))
    except Exception as e:
        logger.error(f"处理音频消息出错: {e}")
        raise

async def handle_text_message(websocket, uid, message):
    """处理文本消息"""
    try:
        logger.info(f"处理文本消息，UID: {uid}")
        data = json.loads(message)
        
        if data.get("state") == "end":
            # 保存为 wav 文件
            wav_path = os.path.join(TEMP_DIR, f"{uid}.wav")
            with wave.open(wav_path, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                wf.writeframes(b''.join(user_sessions[uid].get('audio_buffer', [])))
            
            # 处理流程
            await websocket.send(json.dumps({"status": "processing_asr"}))
            asr_text = transcribe_audio(wav_path, config["asr"]["remote_url"])
            
            await websocket.send(json.dumps({"status": "processing_gpt"}))
            gpt_reply = gpt_processor.chat(uid, asr_text)
            
            await websocket.send(json.dumps({"status": "processing_tts"}))
            tts_path = os.path.join(TEMP_DIR, f"{uid}_reply.mp3")
            audio_data = await synthesize_speech(gpt_reply, config["tts"]["voice"], tts_path)
            
            await websocket.send(audio_data)  
            await websocket.close()  # 发送完毕后关闭连接
            
            # 清理临时文件
            for path in [wav_path, tts_path]:
                if os.path.exists(path):
                    os.remove(path)
            if 'audio_buffer' in user_sessions[uid]:
                del user_sessions[uid]['audio_buffer']
                
    except json.JSONDecodeError:
        await websocket.send(json.dumps({"error": "Invalid JSON format"}))
    except Exception as e:
        logger.error(f"处理消息出错: {e}")
        await websocket.send(json.dumps({
            "type": "error",
            "message": str(e)
        }))
        try:
            await websocket.close()
        except:
            pass
        raise

async def ws_handler(websocket, path):
    """WebSocket连接处理器"""
    uid = str(uuid.uuid4())
    user_sessions[uid] = {'connected': True}
    logger.info(f"新连接来自: {websocket.remote_address}, UID: {uid}")
    
    try:
        # 发送欢迎消息
        await websocket.send(json.dumps({
            "status": "connected",
            "message": "语音助手已就绪，请开始说话"
        }))
        
        # 主消息循环
        async for message in websocket:
            try:
                if isinstance(message, bytes):
                    await handle_audio_message(websocket, uid, message)
                elif isinstance(message, str):
                    await handle_text_message(websocket, uid, message)
            except Exception as e:
                logger.error(f"处理消息出错: {e}")
                await websocket.send(json.dumps({"error": str(e)}))
                
    except websockets.exceptions.ConnectionClosed:
        logger.info(f"客户端断开连接: {uid}")
    except Exception as e:
        logger.error(f"连接处理出错: {e}")
    finally:
        # 注意：只有在连接真正关闭时才清理会话
        # 移除了自动清理会话的代码，让GPT会话保持
        # 清理会话
        # gpt_processor.clear_conversation(uid)  # 清除GPT对话历史
        # if uid in user_sessions:
        #     # 清理临时文件
        #     wav_path = os.path.join(TEMP_DIR, f"{uid}.wav")
        #     tts_path = os.path.join(TEMP_DIR, f"{uid}_reply.mp3")
        #     for path in [wav_path, tts_path]:
        #         if os.path.exists(path):
        #             os.remove(path)
        #     del user_sessions[uid]
        # logger.info(f"清理完成: {uid}")
        wav_path = os.path.join(TEMP_DIR, f"{uid}.wav")
        tts_path = os.path.join(TEMP_DIR, f"{uid}_reply.mp3")
        for path in [wav_path, tts_path]:
            if os.path.exists(path):
                try:
                    os.remove(path)
                except:
                    pass
        logger.info(f"清理临时文件完成: {uid}")

async def main():
    """主服务函数"""
    # Windows平台需要此设置
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    # 启动WebSocket服务
    server = await websockets.serve(
        ws_handler,
        config["server"]["host"],
        config["server"]["port"],
        ping_interval=60,
        ping_timeout=120,
        close_timeout=30
    )
    
    logger.info(f"WebSocket 服务已启动 ws://{config['server']['host']}:{config['server']['port']}")

    try:
        await server.wait_closed()
    except KeyboardInterrupt:
        logger.info("服务正在关闭...")
    finally:
        server.close()
        await server.wait_closed()

if __name__ == "__main__":
    asyncio.run(main())