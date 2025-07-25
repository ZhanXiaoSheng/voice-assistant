# modules/gpt.py

import openai
from typing import List, Dict
from utils.logger import setup_logger

logger = setup_logger("GPT", "gpt.log")

class GPTProcessor:
    def __init__(self, api_key: str, base_url: str, model: str, max_history: int, trim_history_to: int,system_prompt:str = "你叫小迪，是一个专业的智能语音助手"):
        
        self.client = openai.OpenAI(api_key=api_key, base_url=base_url)
        self.model = model
        self.max_history = max_history
        self.trim_history_to = trim_history_to
        self.conversations = {}  # 存储每个用户的对话历史
        # 系统提示
        self.system_prompt = system_prompt

    def initialize_conversation(self, user_id: str):
        """初始化对话，发送系统提示"""
        self.conversations[user_id] = [
            {"role": "system", "content": self.system_prompt}
        ]
        logger.info(f"已为用户 {user_id} 初始化对话")
    
    def chat(self, user_id: str, message: str) -> str:
        """
        与GPT进行对话
        :param user_id: 用户唯一标识
        :param message: 用户消息
        :return: GPT回复
        """
        try:
            # 获取或初始化对话历史
            if user_id not in self.conversations:
                self.initialize_conversation(user_id)
            
            conversation = self.conversations[user_id]
            
            # 添加用户消息
            conversation.append({"role": "user", "content": message})
            
            # 调用GPT API
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=conversation,
            )
            reply = resp.choices[0].message.content
            logger.info(f"GPT回复: {reply}")
            
            # 添加助手回复
            conversation.append({"role": "assistant", "content": reply})
            
            # 限制对话历史长度
            if len(conversation) > self.max_history:
                conversation[:] = conversation[-self.trim_history_to:]  # 保留最近几条
                
            return reply
        except Exception as e:
            logger.error(f"GPT处理失败: {e}")
            raise

    def clear_conversation(self, user_id: str):
        """清除指定用户的对话历史"""
        if user_id in self.conversations:
            del self.conversations[user_id]