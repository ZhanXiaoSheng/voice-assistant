# modules/tts.py

import os
import asyncio
import aiofiles
from edge_tts import Communicate
from utils.logger import setup_logger

logger = setup_logger("TTS", "tts.log")

async def synthesize_speech(text: str, voice: str, output_path: str) -> bytes:
    """
    使用edge-tts将文本合成为语音
    :param text: 要合成的文本
    :param voice: 语音角色
    :param output_path: 输出文件路径
    :return: 音频数据
    """
    try:
        communicate = Communicate(text=text, voice=voice)
        await communicate.save(output_path)
        logger.info(f"TTS文件已保存到: {output_path}")
        
        # 验证文件
        if not os.path.exists(output_path) or os.path.getsize(output_path) < 1024:
            raise ValueError("TTS生成失败")
            
        # 读取并返回音频数据
        async with aiofiles.open(output_path, "rb") as af:
            audio_data = await af.read()
            
        return audio_data
    except Exception as e:
        logger.error(f"TTS处理失败: {e}")
        raise