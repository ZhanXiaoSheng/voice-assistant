# client/client_main.py

import asyncio
import websockets
import pyaudio
import json
import os
import tempfile
import playsound
import uuid
import sys
import pygame


# 添加项目根目录到Python路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import time
import yaml
from utils.logger import setup_logger
from modules.vad import VADProcessor
from modules.asr import save_audio_to_wav, transcribe_audio_remote

# 初始化 pygame mixer（在文件顶部）
pygame.mixer.init()

# 构建配置文件的正确路径
client_config_path = os.path.join(project_root, "config", "client.yaml")
#server_config_path = os.path.join(project_root, "config", "server.yaml")

# 加载客户端配置
with open(client_config_path, "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)

# 初始化日志
logger = setup_logger("Client", "client.log", config["log_level"])

# 创建临时目录
os.makedirs(config["temp_dirs"]["wakeup"], exist_ok=True)
os.makedirs(config["temp_dirs"]["temp"], exist_ok=True)

class VoiceWakeupListener:
    def __init__(self, wakeup_word: str, keywords: list, remote_asr_url: str):
        self.wakeup_word = wakeup_word
        self.keywords = keywords
        self.remote_asr_url = remote_asr_url
        
        # 初始化VAD
        self.vad = VADProcessor(config["vad"]["aggressiveness"])
        
        # 音频参数
        self.CHUNK = int(config["audio"]["rate"] * config["audio"]["chunk_ms"] / 1000)
        self.FORMAT = getattr(pyaudio, config["audio"]["format"])
        self.CHANNELS = config["audio"]["channels"]
        self.RATE = config["audio"]["rate"]

    def listen(self):
        """监听唤醒词"""
        p = pyaudio.PyAudio()
        stream = p.open(
            format=self.FORMAT,
            channels=self.CHANNELS,
            rate=self.RATE,
            input=True,
            frames_per_buffer=self.CHUNK
        )
        logger.info(f"唤醒监听中，请说唤醒词“{self.wakeup_word}”……")

        frames = []
        speech_started = False
        silence_count = 0
        max_silence_chunks = int(config["wakeup"]["max_silence_ms"] / config["audio"]["chunk_ms"])
        uid = str(uuid.uuid4())

        try:
            while True:
                data = stream.read(self.CHUNK, exception_on_overflow=False)
                if self.vad.is_speech(data, self.RATE):
                    frames.append(data)
                    silence_count = 0
                    speech_started = True
                elif speech_started:
                    silence_count += 1
                    if silence_count > max_silence_chunks:
                        # 语音段结束，保存并发送识别
                        wav_path = os.path.join(config["temp_dirs"]["wakeup"], f"wakeup_{uid}.wav")
                        save_audio_to_wav(frames, wav_path, self.CHANNELS, self.RATE)
                        logger.info("检测语音段完毕，发送至ASR识别...")
                        text = transcribe_audio_remote(wav_path, self.remote_asr_url)
                        if any(kw in text for kw in self.keywords):
                            logger.info("检测到唤醒词，进入对话模式！")
                            # 清理文件
                            if os.path.exists(wav_path):
                                os.remove(wav_path)
                            break
                        else:
                            logger.info("未检测到唤醒词，继续监听...")
                            if os.path.exists(wav_path):
                                os.remove(wav_path)
                            frames.clear()
                            speech_started = False
                            silence_count = 0
        finally:
            stream.stop_stream()
            stream.close()
            p.terminate()

class VoiceClient:
    def __init__(self):
        # 初始化VAD
        self.vad = VADProcessor(config["vad"]["aggressiveness"])
        
        # 音频参数
        self.CHUNK = int(config["audio"]["rate"] * config["audio"]["chunk_ms"] / 1000)
        self.FORMAT = getattr(pyaudio, config["audio"]["format"])
        self.CHANNELS = config["audio"]["channels"]
        self.RATE = config["audio"]["rate"]

        # WebSocket连接
        self.websocket = None

    def play_audio(self, file_path: str):
        """
        使用 pygame 播放音频文件（最稳定的方式）
        :param file_path: 音频文件路径
        """
        try:
            # 初始化 mixer（如果还没有）
            if not pygame.mixer.get_init():
                pygame.mixer.init()
            
            # 加载并播放音频
            pygame.mixer.music.load(file_path)
            pygame.mixer.music.play()
            
            # 等待播放完成
            while pygame.mixer.music.get_busy():
                pygame.time.wait(100)  # 等待100ms
                
            # 卸载音乐
            pygame.mixer.music.unload()
            
        except Exception as e:
            logger.error(f"播放音频失败: {e}")
            raise


    async def connect(self):
        """建立WebSocket连接"""
        if self.websocket is None or self.websocket.closed:
            self.websocket = await websockets.connect(config["server"]["url"])
            print("已连接到语音助手服务器")
        return self.websocket
    

    
    # async def dialogue(self):
        """进行一轮对话"""
        try:
            async with websockets.connect(config["server"]["url"]) as ws:
                p = pyaudio.PyAudio()
                stream = p.open(
                    format=self.FORMAT,
                    channels=self.CHANNELS,
                    rate=self.RATE,
                    input=True,
                    frames_per_buffer=self.CHUNK
                )
                silence_count = 0
                speech_started = False
                logger.info("请开始说话（静音自动结束本轮对话）...")
                await ws.send(json.dumps({'state': 'start'}))
                
                while True:
                    data = stream.read(self.CHUNK, exception_on_overflow=False)
                    if self.vad.is_speech(data, self.RATE):
                        silence_count = 0
                        speech_started = True
                        await ws.send(data)
                        print('.', end='', flush=True)
                    else:
                        silence_count += 1
                        if speech_started:
                            await ws.send(data)
                    if speech_started and silence_count > int(config["dialogue"]["max_silence_ms"] / config["audio"]["chunk_ms"]):
                        await ws.send(json.dumps({'state': 'end'}))
                        break
                logger.info("\n本轮录音结束，等待助手回复...")
                stream.stop_stream()
                stream.close()
                p.terminate()

                # 等待语音回复
                while True:
                    try:
                        message = await asyncio.wait_for(ws.recv(), timeout=config["dialogue"]["timeout"])
                    except asyncio.TimeoutError:
                        logger.error("等待助手回复超时")
                        break
                    if isinstance(message, bytes):
                        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as f:
                            f.write(message)
                            temp_path = f.name
                        logger.info(f"助手回复正在播放: {temp_path}")
                        try:
                            playsound.playsound(temp_path, block=True)
                            logger.info("助手语音回复播放完成")
                        except Exception as e:
                            logger.error(f"播放助手语音回复失败: {e}")
                        if os.path.exists(temp_path):
                            os.unlink(temp_path)
                        break
                    else:
                        try:
                            resp = json.loads(message)
                            if 'message' in resp:
                                print("助手:", resp['message'])
                            elif 'status' in resp:
                                print("系统:", resp['status'])
                            elif 'error' in resp:
                                print("系统: 错误：", resp['error'])
                        except Exception:
                            logger.error(f"收到非音频消息：{message}")
        except Exception as e:
            logger.error(f"对话异常: {e}")

    async def dialogue(self):
        """进行一轮对话"""
        try:
            ws = await self.connect()
            
            p = pyaudio.PyAudio()
            stream = p.open(
                format=self.FORMAT,
                channels=self.CHANNELS,
                rate=self.RATE,
                input=True,
                frames_per_buffer=self.CHUNK
            )
            silence_count = 0
            speech_started = False
            logger.info("请开始说话（静音自动结束本轮对话）...")
            await ws.send(json.dumps({'state': 'start'}))
            
            while True:
                data = stream.read(self.CHUNK, exception_on_overflow=False)
                if self.vad.is_speech(data, self.RATE):
                    silence_count = 0
                    speech_started = True
                    await ws.send(data)
                    print('.', end='', flush=True)
                else:
                    silence_count += 1
                    if speech_started:
                        await ws.send(data)
                if speech_started and silence_count > int(config["dialogue"]["max_silence_ms"] / config["audio"]["chunk_ms"]):
                    await ws.send(json.dumps({'state': 'end'}))
                    break
            logger.info("\n本轮录音结束，等待助手回复...")
            stream.stop_stream()
            stream.close()
            p.terminate()

            # 等待语音回复
            while True:
                try:
                    message = await asyncio.wait_for(ws.recv(), timeout=config["dialogue"]["timeout"])
                except asyncio.TimeoutError:
                    logger.info("等待助手回复超时")
                    break
                if isinstance(message, bytes):
                    # 创建临时文件时使用完整路径
                    temp_dir = config["temp_dirs"]["temp"]
                    temp_filename = f"reply_{uuid.uuid4().hex}.mp3"
                    temp_path = os.path.join(temp_dir, temp_filename)
                    
                    # 确保目录存在
                    os.makedirs(temp_dir, exist_ok=True)
                    
                    # 保存音频文件
                    with open(temp_path, "wb") as f:
                        f.write(message)
                    
                    logger.info(f"助手回复正在播放: {temp_path}")
                    try:
                        self.play_audio(temp_path)
                        logger.info("助手语音回复播放完成")
                    except Exception as e:
                        logger.error(f"播放助手语音回复失败: {e}")
                    
                    # 清理临时文件
                    if os.path.exists(temp_path):
                        try:
                            os.remove(temp_path)
                        except Exception as e:
                            logger.error(f"清理临时文件失败: {e}")
                    break
                else:
                    try:
                        resp = json.loads(message)
                        if 'message' in resp:
                            print("助手:", resp['message'])
                        elif 'status' in resp:
                            print("系统:", resp['status'])
                        elif 'error' in resp:
                            print("系统: 错误：", resp['error'])
                    except Exception:
                        print(f"收到非音频消息：{message}")
        except Exception as e:
            logger.error(f"对话异常: {e}")
            # 重置连接
            self.websocket = None


    async def wait_for_speech(self, timeout=3):
        """
        等待用户继续说话
        :param timeout: 等待超时时间（秒）
        :return: 如果检测到语音活动返回True，超时返回False
        """
        logger.info(f"等待用户继续说话...（{timeout}秒内）")
        
        p = pyaudio.PyAudio()
        stream = p.open(
            format=self.FORMAT,
            channels=self.CHANNELS,
            rate=self.RATE,
            input=True,
            frames_per_buffer=self.CHUNK
        )
        
        start_time = time.time()
        speech_detected = False
        
        try:
            while time.time() - start_time < timeout:
                data = stream.read(self.CHUNK, exception_on_overflow=False)
                if self.vad.is_speech(data, self.RATE):
                    speech_detected = True
                    break
                await asyncio.sleep(0.01)  # 短暂休眠避免CPU占用过高
        finally:
            stream.stop_stream()
            stream.close()
            p.terminate()
        
        if speech_detected:
            logger.info("检测到用户继续说话")
        else:
            logger.info("等待超时，未检测到语音")
            
        return speech_detected

async def main():
    # 从配置中获取ASR URL
    remote_asr_url = config["asr"]["remote_url"]
    
    wakeup_listener = VoiceWakeupListener(
        wakeup_word=config["wakeup"]["word"],
        keywords=config["wakeup"]["keywords"],
        remote_asr_url=remote_asr_url
    )
    voice_client = VoiceClient()
    
    while True:
        logger.info("---- 等待唤醒 ----")
        wakeup_listener.listen()  # 等待唤醒词
        logger.info("---- 进入多轮语音对话 ----")
        try:
            while True:
                await voice_client.dialogue()
                logger.info("等待用户继续说话...（3秒内无输入则退出对话）")
                
                # 注意：这里的wait_for_speech需要重新实现
                # 暂时用简单的延时替代
                # await asyncio.sleep(3)
                # break  # 暂时直接退出对话循环
                if not await voice_client.wait_for_speech(timeout=3):
                    logger.info("对话超时结束")
                    break
                else:
                    logger.info("继续对话...")
                
        except Exception as e:
            logger.error(f"对话异常: {e}")
            continue

if __name__ == "__main__":
    # Windows平台需要此设置
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())