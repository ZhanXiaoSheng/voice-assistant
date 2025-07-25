# 语音助手 (Voice Assistant)

一个基于 Python 实现的简单语音助手，具备语音唤醒、语音识别 (ASR)、自然语言处理 (NLP)、语音合成 (TTS) 和音频播放功能。

## 功能特性

*   **语音唤醒**: 使用关键词（如“小迪”）唤醒语音助手。
*   **语音识别 (ASR)**: 将用户的语音转换为文本。依赖远程 ASR 服务。
*   **自然语言处理 (NLP)**: 使用 OpenAI GPT 模型进行对话理解和生成。
*   **语音合成 (TTS)**: 将文本回复转换为语音。使用 `edge-tts` 库。
*   **音频播放**: 在客户端播放 TTS 生成的语音回复。
*   **多轮对话**: 支持连续的语音交互，直到超时或用户结束。

## 项目结构
profile
Qwen3-Coder
好的，这是一个根据你的语音助手项目编写的 README.md 文件：

markdown


1
2
3
4
5
6
7
8
9
10
11
12
13
14
15
⌄
⌄
# 语音助手 (Voice Assistant)

一个基于 Python 实现的简单语音助手，具备语音唤醒、语音识别 (ASR)、自然语言处理 (NLP)、语音合成 (TTS) 和音频播放功能。

## 功能特性

*   **语音唤醒**: 使用关键词（如“小迪”）唤醒语音助手。
*   **语音识别 (ASR)**: 将用户的语音转换为文本。依赖远程 ASR 服务。
*   **自然语言处理 (NLP)**: 使用 OpenAI GPT 模型进行对话理解和生成。
*   **语音合成 (TTS)**: 将文本回复转换为语音。使用 `edge-tts` 库。
*   **音频播放**: 在客户端播放 TTS 生成的语音回复。
*   **多轮对话**: 支持连续的语音交互，直到超时或用户结束。

## 项目结构

voice_assistant/
├── config/ # 配置文件目录
│ ├── client.yaml # 客户端配置
│ └── server.yaml # 服务端配置
├── logs/ # 日志文件目录 (运行时自动生成)
├── modules/ # 核心功能模块
│ ├── asr.py # 语音识别模块 (调用远程服务)
│ ├── gpt.py # GPT 对话处理模块
│ ├── tts.py # 语音合成模块 (使用 edge-tts)
│ └── vad.py # 语音活动检测模块 (使用 webrtcvad)
├── client/ # 客户端代码
│ └── client_main.py # 客户端主程序
├── server/ # 服务端代码
│ └── server_main.py # 服务端主程序
├── utils/ # 工具类
│ └── logger.py # 统一日志管理
├── temp_audio/ # 服务端临时音频文件目录 (运行时自动生成)
├── wakeup_audio/ # 客户端临时唤醒音频文件目录 (运行时自动生成)
├── requirements.txt # Python 依赖库列表
└── README.md # 项目说明文件


## 实现流程

### 1. 服务端 (Server)

1.  **启动**: 服务端 (`server/server_main.py`) 启动一个 WebSocket 服务器。
2.  **监听**: 等待客户端通过 WebSocket 连接。
3.  **连接建立**:
    *   客户端连接后，服务端为该连接分配一个唯一的 UID。
    *   初始化 GPT 对话历史，并发送系统提示（"你叫小迪，是一个专业的智能语音助手"）。
    *   生成预设的欢迎语（"你好！我是小迪，你的专业智能语音助手。有什么我可以帮助你的吗？"）。
    *   调用 TTS 模块将欢迎语转换为音频。
    *   通过 WebSocket 将欢迎语音频数据发送给客户端。
4.  **处理对话**:
    *   接收客户端发送的音频数据（二进制 WebSocket 消息）并缓存。
    *   接收客户端发送的文本控制消息（如 `{"state": "end"}`）。
    *   当收到 `end` 信号时：
        *   将缓存的音频数据保存为 `.wav` 文件。
        *   调用 ASR 模块将 `.wav` 文件发送到远程 ASR 服务进行识别，得到文本。
        *   将 ASR 识别出的文本发送给 GPT 模块进行对话处理。
        *   获取 GPT 的文本回复。
        *   调用 TTS 模块将 GPT 回复文本转换为音频。
        *   通过 WebSocket 将回复音频数据发送给客户端。
5.  **会话管理**: 维护每个 UID 的对话历史，以支持多轮对话。连接断开时清理相关资源。

### 2. 客户端 (Client)

1.  **唤醒监听**:
    *   客户端 (`client/client_main.py`) 使用 PyAudio 持续采集音频。
    *   使用 `webrtcvad` 检测语音活动 (VAD)。
    *   当检测到一段语音后，停止采集并保存为临时 `.wav` 文件。
    *   调用远程 ASR 服务识别这段音频。
    *   如果识别结果包含预设的唤醒词（如“小迪”），则进入对话模式。
2.  **建立连接**:
    *   唤醒成功后，客户端通过 WebSocket 连接到服务端。
3.  **接收欢迎语**:
    *   连接建立后，客户端立即接收服务端发送的欢迎语音频数据。
    *   客户端播放欢迎语音频。
4.  **发起对话**:
    *   客户端再次使用 PyAudio 和 VAD 采集用户的语音指令。
    *   实时将采集到的音频数据（二进制）通过 WebSocket 发送给服务端。
    *   当检测到用户停止说话（静音超时）时，发送一个 `{"state": "end"}` 文本消息给服务端。
5.  **接收回复**:
    *   客户端等待服务端处理完毕并返回回复音频数据。
    *   接收到音频数据后，客户端通过Pygame播放助手的语音回复。
6.  **继续对话**:
    *   播放完回复后，客户端短暂监听是否有新的语音输入。
    *   如果检测到语音，则重复“发起对话”和“接收回复”流程。
    *   如果超时未检测到语音，则断开当前 WebSocket 连接，回到“唤醒监听”状态。

## 核心模块说明

| 模块路径         | 功能描述                                                                 |
| :--------------- | :----------------------------------------------------------------------- |
| `modules/vad.py` | 使用 `webrtcvad` 库实现语音活动检测 (Voice Activity Detection)。         |
| `modules/asr.py` | 提供函数调用远程 ASR 服务进行语音转文本，以及客户端保存音频的辅助功能。 |
| `modules/gpt.py` | 封装与 OpenAI GPT API 的交互，管理对话历史，提供对话和欢迎语功能。      |
| `modules/tts.py` | 使用 `edge-tts` 库将文本合成为 MP3 音频数据。                           |
| `utils/logger.py`| 使用 Python `logging` 模块提供统一的日志记录功能。                      |

## 配置文件

### `config/server.yaml`

```yaml
server:
  host: "0.0.0.0"             # 服务端监听地址
  port: 10197                 # 服务端监听端口

asr:
  remote_url: "http://..."    # 远程 ASR 服务的 URL

gpt:
  api_key: "sk-..."           # OpenAI API 密钥
  base_url: "https://..."     # OpenAI API 基础 URL (可选，用于中转)
  model: "gpt-3.5-turbo"      # 使用的 GPT 模型
  max_history: 20             # 最大对话历史长度
  trim_history_to: 4          # 超长时保留最近的 N 条记录

tts:
  voice: "zh-CN-XiaoxiaoNeural" # edge-tts 使用的语音角色

temp_dir: "temp_audio"        # 服务端临时文件目录

log_level: "INFO"             # 日志级别

```

### `config/client.yaml`

```yaml
server:
  url: "ws://localhost:10197" # 服务端 WebSocket 地址

audio:
  format: "paInt16"           # 音频采样格式
  channels: 1                 # 声道数
  rate: 16000                 # 采样率
  chunk_ms: 30                # 音频块时长 (ms)

vad:
  aggressiveness: 2           # VAD 敏感度 (0-3)

wakeup:
  word: "小迪"                # 主唤醒词
  keywords: ["小迪", ...]     # 唤醒词列表 (用于识别容错)
  max_silence_ms: 800         # 唤醒语音段结束的静音时长

dialogue:
  max_silence_ms: 1000        # 对话中语音段结束的静音时长
  timeout: 30                 # 等待服务端回复的超时时间 (秒)

temp_dirs:
  wakeup: "wakeup_audio"      # 客户端唤醒临时文件目录
  temp: "temp_audio"          # 客户端其他临时文件目录

log_level: "INFO"             # 日志级别

```

## 安装与运行

### 环境要求

1. **Python 3.7+**
2. **访问远程 ASR 服务**
3. **访问 OpenAI API 或兼容服务**

### 导出依赖

```shell
pip freeze > requirements.txt
```

### 安装依赖

```shell
pip install -r requirements.txt
```

### 运行服务端

```shell
cd server
python server_main.py
```

### 运行客户端

```shell
cd client
python client_main.py
```

## 依赖库

- websockets: WebSocket 通信
- pyaudio: 音频采集与播放 (部分功能)
- webrtcvad: 语音活动检测
- pygame: 音频播放
- requests: HTTP 请求 (用于 ASR)
- openai: OpenAI API 客户端
- edge-tts: 微软 Edge TTS
- pyyaml: YAML 配置文件解析

## 其他说明

### webrtcvad

```text
webrtcvad 是一个有 C/C++ 原生扩展的 Python 包，在 Windows 上必须依赖 微软编译器工具链（VC++ Build Tools） 来编译底层 C++ 代码。
```
安装 webrtcvad需要安装 Visual C++ Build Tools
打开链接：https://visualstudio.microsoft.com/visual-cpp-build-tools/

### WebSocket

WebSocket版本号10.4 其他版本可能会报错


## todo 
1. 语音唤醒；唤醒后发送欢迎语给用户。自定义promot：你叫小迪，是一个专业的人工智能语音助手。
2. 多轮对话
3. UI展示
4. 流式生成
5. 情感识别
6. 知识库
7. 唤醒词可配置
8. tts语音合成 音色可配置
9. 清理音频文件
10. 对音频加入简单降噪或使用 noisereduce 来处理背景噪音影响识别准确率。