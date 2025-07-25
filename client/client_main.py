# client/client_main.py

import asyncio
import websockets
import pyaudio
import json
import os
import uuid
import sys
import pygame
import time
import yaml

# 添加项目根目录到Python路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from utils.logger import setup_logger
from modules.vad import VADProcessor
from modules.asr import save_audio_to_wav, transcribe_audio_remote


# 构建配置文件的正确路径
client_config_path = os.path.join(project_root, "config", "client.yaml")

# 加载客户端配置
with open(client_config_path, "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)

# 初始化日志
logger = setup_logger("Client", "client.log", config["log_level"])

# 创建临时目录
os.makedirs(config["temp_dirs"]["wakeup"], exist_ok=True)
os.makedirs(config["temp_dirs"]["temp"], exist_ok=True)

# 初始化 pygame mixer（在文件顶部）
pygame.mixer.init()

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
        # 消息队列
        self.message_queue = asyncio.Queue()
         # 消息处理任务
        self.message_handler_task = None
        # 是否已连接标志
        self.is_connected = False


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
            try:
                self.websocket = await websockets.connect(
                    config["server"]["url"],
                    ping_interval=20,
                    ping_timeout=10
                )
                logger.info("已连接到语音助手服务器")
                # 启动消息处理任务
                if self.message_handler_task is None or self.message_handler_task.done():
                    self.message_handler_task = asyncio.create_task(self.handle_messages())

                self.is_connected = True
                print("连接已建立，等待初始化消息...")
                    
            except Exception as e:
                print(f"连接服务器失败: {e}")
                self.websocket = None
                self.is_connected = False
                raise
        else:
            # 连接已经存在且有效
            self.is_connected = True
        return self.websocket

    async def handle_initial_messages(self):
        """处理连接后的初始消息（连接确认和欢迎语）"""
        logger.info("等待并处理初始消息...")
        start_time = time.time()
        timeout = 10.0  # 10秒超时
        messages_processed = 0
        audio_messages = []  # 存储音频消息
        
        while (time.time() - start_time) < timeout and messages_processed < 10:
            try:
                # 等待消息，超时1秒
                message = await asyncio.wait_for(self.message_queue.get(), timeout=1.0)
                
                if isinstance(message, bytes):
                    # 处理音频数据（欢迎语）
                    logger.info("检测到音频消息，准备播放欢迎语...")
                    audio_messages.append(message)
                    messages_processed += 1
                    # 立即播放音频消息
                    await self.play_audio_response(message)
                else:
                    # 处理文本消息
                    try:
                        resp = json.loads(message)
                        if resp.get('status') == 'connected':
                            print(f"系统: {resp['message']}")
                            messages_processed += 1
                        elif resp.get('type') == 'welcome':
                            print(f"助手: {resp['message']}")
                            messages_processed += 1
                        elif resp.get('status'):
                            print(f"系统: {resp['status']}")
                            messages_processed += 1
                        else:
                            print(f"服务器消息: {message}")
                            messages_processed += 1
                    except json.JSONDecodeError:
                        print(f"收到文本消息: {message}")
                        messages_processed += 1
                        
            except asyncio.TimeoutError:
                # 超时，检查是否已经处理了必要的消息
                if messages_processed > 0:
                    logger.info("初始消息处理完成")
                    break
                # 否则继续等待
                continue
            except Exception as e:
                logger.error(f"处理初始消息时出错: {e}")
                break
        
        # 播放所有收集到的音频消息
        for audio_data in audio_messages:
            try:
                await self.play_audio_response(audio_data)
            except Exception as e:
                logger.error(f"播放初始音频消息失败: {e}")
        
        logger.info("初始消息处理结束")
        await asyncio.sleep(0.5)  # 等待播放完成

        """处理连接后的初始消息（连接确认和欢迎语）"""
        logger.info("等待并处理初始消息...")
        start_time = time.time()
        timeout = 10.0  # 10秒超时
        messages_processed = 0
        
        while (time.time() - start_time) < timeout and messages_processed < 5:
            try:
                # 等待消息，超时1秒
                message = await asyncio.wait_for(self.message_queue.get(), timeout=1.0)
                
                if isinstance(message, bytes):
                    # 处理音频数据（欢迎语）
                    logger.info("处理欢迎语音频...")
                    await self.play_audio_response(message)
                    messages_processed += 1
                else:
                    # 处理文本消息
                    try:
                        resp = json.loads(message)
                        if resp.get('status') == 'connected':
                            print(f"系统: {resp['message']}")
                            messages_processed += 1
                        elif resp.get('type') == 'welcome':
                            print(f"助手: {resp['message']}")
                            messages_processed += 1
                        elif resp.get('status'):
                            print(f"系统: {resp['status']}")
                            messages_processed += 1
                        else:
                            print(f"服务器消息: {message}")
                            messages_processed += 1
                    except json.JSONDecodeError:
                        print(f"收到文本消息: {message}")
                        messages_processed += 1
                        
            except asyncio.TimeoutError:
                # 超时，检查是否已经处理了必要的消息
                if messages_processed > 0:
                    logger.info("初始消息处理完成")
                    break
                # 否则继续等待
                continue
            except Exception as e:
                logger.error(f"处理初始消息时出错: {e}")
                break
        
        logger.info("初始消息处理结束")

    async def handle_messages(self):
        """持续处理来自服务器的消息"""
        try:
            async for message in self.websocket:
                # 所有消息都放入队列，由其他方法处理
                await self.message_queue.put(message)
        except Exception as e:
            print(f"消息接收异常: {e}")
            self.is_connected = False
            
    async def wait_for_initial_messages(self, timeout=10):
        """等待并处理初始消息（连接确认和欢迎语）"""
        start_time = time.time()
        connected_received = False
        
        while (time.time() - start_time) < timeout:
            try:
                result = await self.process_next_message(timeout=1.0)
                if result is None:
                    # 超时，继续等待
                    continue
                # 处理了消息，继续等待可能的欢迎语等
                if not connected_received:
                    # 等待一段时间确保所有初始消息都处理完
                    await asyncio.sleep(0.5)
                    connected_received = True
            except Exception as e:
                print(f"处理初始消息时出错: {e}")
                break
        
        if connected_received:
            print("初始化消息处理完成")

    async def process_next_message(self, timeout=None):
        """处理下一个消息"""
        try:
            if timeout:
                message = await asyncio.wait_for(self.message_queue.get(), timeout=timeout)
            else:
                message = await self.message_queue.get()
                
            if isinstance(message, bytes):
                # 处理音频数据
                await self.play_audio_response(message)
                return "audio"
            else:
                # 处理文本消息
                try:
                    resp = json.loads(message)
                    if resp.get('status') == 'connected':
                        print(f"系统: {resp['message']}")
                    elif resp.get('type') == 'welcome':
                        print(f"助手: {resp['message']}")
                    elif resp.get('status'):
                        print(f"系统: {resp['status']}")
                    elif resp.get('message'):
                        print(f"助手: {resp['message']}")
                    elif resp.get('error'):
                        print(f"错误: {resp['error']}")
                    else:
                        print(f"服务器消息: {message}")
                    return "text"
                except json.JSONDecodeError:
                    print(f"收到文本消息: {message}")
                    return "text"
        except asyncio.TimeoutError:
            return None
        except Exception as e:
            print(f"处理消息异常: {e}")
            return None


    async def play_audio_response(self, audio_data: bytes):
        """播放服务器返回的音频响应"""
        try:
            # 创建临时文件
            temp_dir = config["temp_dirs"]["temp"]
            temp_filename = f"response_{uuid.uuid4().hex}.mp3"
            temp_path = os.path.join(temp_dir, temp_filename)
            
            # 确保目录存在
            os.makedirs(temp_dir, exist_ok=True)
            
            # 保存音频文件
            with open(temp_path, "wb") as f:
                f.write(audio_data)
            
            print(f"播放助手回复: {temp_path}")
            self.play_audio(temp_path)
            print("播放完成")
            
            # 清理临时文件
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception as e:
                    print(f"清理音频文件失败: {e}")
        except Exception as e:
            print(f"播放音频响应失败: {e}")
    

    async def dialogue(self):
        """进行一轮对话"""
        try:
            # 确保连接
            if not self.is_connected:
                await self.connect()
            # 等待连接建立
            retry_count = 0
            while not self.is_connected and retry_count < 5:
                await asyncio.sleep(0.5)
                retry_count += 1
            
            if not self.is_connected:
                raise Exception("无法建立连接")
            
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
            # 发送开始信号
            await self.websocket.send(json.dumps({'state': 'start'}))

            # 收集音频数据
            audio_frames = []
            
            while True:
                data = stream.read(self.CHUNK, exception_on_overflow=False)
                if self.vad.is_speech(data, self.RATE):
                    silence_count = 0
                    speech_started = True
                    audio_frames.append(data)
                    await self.websocket.send(data)
                    print('.', end='', flush=True)
                else:
                    silence_count += 1
                    if speech_started:
                        audio_frames.append(data)
                        await self.websocket.send(data)
                        print('-', end='', flush=True)
                if speech_started and silence_count > int(config["dialogue"]["max_silence_ms"] / config["audio"]["chunk_ms"]):
                    await self.websocket.send(json.dumps({'state': 'end'}))
                    print(f"\n发送音频数据: {len(audio_frames)} 帧")
                    break
            
            print("\n本轮录音结束，等待助手回复...")
            stream.stop_stream()
            stream.close()
            p.terminate()

            # 等待并处理助手回复
            reply_received = False
            start_time = time.time()
            timeout = config["dialogue"]["timeout"]
            
            while not reply_received and (time.time() - start_time) < timeout:
                result = await self.process_next_message(timeout=1.0)
                if result == "audio":
                    reply_received = True
                elif result is None:
                    # 超时，继续等待
                    continue
                # 其他消息继续处理
                    
            if not reply_received:
                print("等待助手回复超时")
                # 超时后断开连接
                await self.close()
                return False  # 返回False表示对话结束需要重新连接
            else:
                return True  # 返回True表示可以继续对话
  
        except websockets.exceptions.ConnectionClosed:
            print("WebSocket连接已关闭，重新连接...")
            self.websocket = None
            self.is_connected = False
            raise
        except Exception as e:
            print(f"对话异常: {e}")
            # 只有真正的连接错误才重置连接
            if "连接" in str(e) or "connection" in str(e).lower() or isinstance(e, websockets.exceptions.ConnectionClosed):
                self.websocket = None
                self.is_connected = False
            raise


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
    
    async def close(self):
        """关闭WebSocket连接"""
        if self.message_handler_task and not self.message_handler_task.done():
            self.message_handler_task.cancel()
            try:
                await self.message_handler_task
            except asyncio.CancelledError:
                pass
        if self.websocket and not self.websocket.closed:
            await self.websocket.close()
        self.is_connected = False
        logger.info("WebSocket连接已关闭")

async def main():
    # 从配置中获取ASR URL
    remote_asr_url = config["asr"]["remote_url"]
    
    wakeup_listener = VoiceWakeupListener(
        wakeup_word=config["wakeup"]["word"],
        keywords=config["wakeup"]["keywords"],
        remote_asr_url=remote_asr_url
    )
    voice_client = VoiceClient()
    
    try:
        while True:
            logger.info("---- 等待唤醒 ----")
            wakeup_listener.listen()  # 等待唤醒词
            logger.info("---- 进入多轮语音对话 ----")
            
            # 每次唤醒都重新建立连接
            try:
                await voice_client.connect()
                # 处理初始消息（连接确认和欢迎语）
                await voice_client.handle_initial_messages()
                # 等待一小段时间确保连接建立
                await asyncio.sleep(0.5)
            except Exception as e:
                logger.error(f"无法连接到服务器: {e}")
                continue
                
            try:
                conversation_active = True
                while conversation_active:
                    result = await voice_client.dialogue()
                    if result:  # 对话成功
                        # 等待用户继续说话
                        if not await voice_client.wait_for_speech(timeout=3):
                            logger.info("对话超时结束")
                            conversation_active = False
                            # 断开连接
                            await voice_client.close()
                        else:
                            logger.info("继续对话...")
                    else:  # 对话超时或失败
                        conversation_active = False
                        # 连接已在 dialogue 中关闭
            except Exception as e:
                logger.error(f"对话异常: {e}")
                # 断开连接
                await voice_client.close()
                continue
    finally:
        # 程序退出时关闭连接
        await voice_client.close()

if __name__ == "__main__":
    # Windows平台需要此设置
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())