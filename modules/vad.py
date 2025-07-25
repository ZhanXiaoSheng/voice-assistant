# modules/vad.py

import webrtcvad
from utils.logger import setup_logger

logger = setup_logger("VAD", "vad.log")

class VADProcessor:
    def __init__(self, aggressiveness: int = 2):
        """
        初始化VAD处理器
        :param aggressiveness: VAD敏感度 (0-3, 3最敏感)
        """
        self.vad = webrtcvad.Vad(aggressiveness)
        
    def is_speech(self, data: bytes, sample_rate: int) -> bool:
        """
        检测音频数据中是否包含语音
        :param data: 音频数据块
        :param sample_rate: 采样率
        :return: 是否包含语音
        """
        try:
            return self.vad.is_speech(data, sample_rate)
        except Exception as e:
            logger.error(f"VAD检测失败: {e}")
            return False