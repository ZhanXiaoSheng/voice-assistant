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
        # 确保audio_buffer存在
        if 'audio_buffer' not in user_sessions[uid]:
            user_sessions[uid]['audio_buffer'] = []
        
        user_sessions[uid]['audio_buffer'].append(message)
        # 不再发送状态更新，避免干扰
        # await websocket.send(json.dumps({"status": "receiving_audio"}))
        logger.debug(f"接收音频数据，当前缓冲区大小: {len(user_sessions[uid]['audio_buffer'])}")
    except Exception as e:
        logger.error(f"处理音频消息出错: {e}")
        raise

async def handle_text_message(websocket, uid, message):
    """处理文本消息"""
    try:
        logger.info(f"处理文本消息，UID: {uid}")
        data = json.loads(message)
        
        if data.get("state") == "end":
            # 检查是否有音频数据
            audio_buffer = user_sessions[uid].get('audio_buffer', [])
            if not audio_buffer:
                logger.warning(f"用户 {uid} 没有音频数据")
                await websocket.send(json.dumps({"error": "没有检测到语音数据"}))
                return
                
            logger.info(f"处理音频数据，共 {len(audio_buffer)} 帧")

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

            # 检查ASR结果
            if not asr_text.strip():
                logger.warning(f"ASR识别结果为空: '{asr_text}'")
                await websocket.send(json.dumps({"error": "未识别到有效语音内容"}))
                return
            
            await websocket.send(json.dumps({"status": "processing_gpt"}))
            gpt_reply = gpt_processor.chat(uid, asr_text)
            
            await websocket.send(json.dumps({"status": "processing_tts"}))
            tts_path = os.path.join(TEMP_DIR, f"{uid}_reply.mp3")
            audio_data = await synthesize_speech(gpt_reply, config["tts"]["voice"], tts_path)
            
            await websocket.send(audio_data)  

            # 清理音频缓冲区，但保持会话
            # 清理临时文件
            for path in [wav_path, tts_path]:
                if os.path.exists(path):
                    os.remove(path)
            if 'audio_buffer' in user_sessions[uid]:
                del user_sessions[uid]['audio_buffer']

            #await websocket.close()  # 发送完毕后关闭连接
            
                
    except json.JSONDecodeError:
        await websocket.send(json.dumps({"error": "Invalid JSON format"}))
    except Exception as e:
        logger.error(f"处理消息出错: {e}")
        await websocket.send(json.dumps({
            "type": "error",
            "message": str(e)
        }))
        # try:
        #     await websocket.close()
        # except:
        #     pass
        # raise

async def ws_handler(websocket, path):
    """WebSocket连接处理器"""
    uid = str(uuid.uuid4())
    user_sessions[uid] = {'connected': True}
    logger.info(f"新连接来自: {websocket.remote_address}, UID: {uid}")
    
    try:
        # 发送连接确认消息
        await websocket.send(json.dumps({
            "status": "connected",
            "message": "语音助手已就绪"
        }))
        
        # 初始化GPT对话（设置系统提示）
        gpt_processor.initialize_conversation(uid)
        
        # 获取欢迎语并转换为语音发送
        welcome_message = gpt_processor.get_welcome_message(uid)
        logger.info(f"欢迎语: {welcome_message}")
        
        # 转换欢迎语为语音并发送
        tts_path = os.path.join(TEMP_DIR, f"{uid}_welcome.mp3")
        welcome_audio = await synthesize_speech(welcome_message, config["tts"]["voice"], tts_path)
        await websocket.send(welcome_audio)
        logger.info("已发送欢迎语音")
        
        # 清理欢迎语音文件
        if os.path.exists(tts_path):
            os.remove(tts_path)
        
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
        # 清理临时文件
        wav_path = os.path.join(TEMP_DIR, f"{uid}.wav")
        tts_path = os.path.join(TEMP_DIR, f"{uid}_reply.mp3")
        welcome_tts_path = os.path.join(TEMP_DIR, f"{uid}_welcome.mp3")
        for path in [wav_path, tts_path,welcome_tts_path]:
            if os.path.exists(path):
                try:
                    os.remove(path)
                except:
                    pass
        # 清理GPT会话
        gpt_processor.clear_conversation(uid)
        logger.info(f"清理完成: {uid}")

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