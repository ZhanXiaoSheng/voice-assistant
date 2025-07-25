# modules/asr.py

import requests
import os
from utils.logger import setup_logger
import wave

logger = setup_logger("ASR", "asr.log")

def transcribe_audio(wav_path: str, remote_url: str) -> str:
    """
    通过远程ASR服务将音频文件转换为文本
    :param wav_path: 音频文件路径
    :param remote_url: 远程ASR服务URL
    :return: 识别出的文本
    """
    try:
        with open(wav_path, "rb") as f:
            files = {'file': (os.path.basename(wav_path), f, 'audio/wav')}
            response = requests.post(remote_url, files=files)
            response.raise_for_status()
            asr_result = response.json()
            
            text = asr_result.get("result", [{}])[0].get("text", "")
            logger.info(f"ASR结果: {text}")
            return text
    except Exception as e:
        logger.error(f"ASR处理失败: {e}")
        raise

def save_audio_to_wav(frames: list, filename: str, channels: int, sample_rate: int):
    """
    将音频帧保存为WAV文件
    :param frames: 音频帧列表
    :param filename: 输出文件名
    :param channels: 声道数
    :param sample_rate: 采样率
    """
    with wave.open(filename, 'wb') as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)  # paInt16 = 2 bytes
        wf.setframerate(sample_rate)
        wf.writeframes(b''.join(frames))

def transcribe_audio_remote(wav_path: str, remote_url: str) -> str:
    """
    通过远程ASR服务将音频文件转换为文本
    :param wav_path: 音频文件路径
    :param remote_url: 远程ASR服务URL
    :return: 识别出的文本
    """
    try:
        with open(wav_path, "rb") as f:
            files = {'file': (os.path.basename(wav_path), f, 'audio/wav')}
            response = requests.post(remote_url, files=files)
            response.raise_for_status()
            asr_result = response.json()
            
            text = asr_result.get("result", [{}])[0].get("text", "")
            logger.info(f"ASR结果: {text}")
            return text
    except Exception as e:
        logger.error(f"ASR处理失败: {e}")
        return ""