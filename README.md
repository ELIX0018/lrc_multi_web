## 项目简介

音声项目是一个基于文本或LRC歌词生成语音的系统，主要功能包括：
- 解析LRC/VTT歌词文件
- 调用TTS API生成语音
- 按时间轴拼接音频片段
- 双声道合并（新音声左声道，原音声右声道）
- 提供Web界面进行任务提交与状态查看

## 功能特性

- 🎵 **LRC/VTT解析**: 支持标准LRC和VTT格式歌词文件解析
- 🎤 **语音生成**: 调用TTS API为每段歌词生成高质量语音
- 🎼 **时间轴拼接**: 按照LRC时间轴精确拼接音频片段
- 🎧 **双声道合并**: 生成音频左声道，原音频右声道
- 🌐 **Web界面**: 提供友好的Web界面进行操作
- ⚙️ **模型选择**: 支持多种语音模型选择
- 🔄 **断点续传**: 支持任务中断后继续处理
- ▶️ **在线试听**: 支持在线播放生成的音频

## 技术架构

- **后端**: Python 3.x + Flask
- **音频处理**: pydub库
- **网络请求**: requests库
- **前端**: HTML + CSS + JavaScript + Jinja2模板
- **API**: RESTful API接口

## 快速开始

### 环境要求
- Python 3.6+
- TTS API服务器（运行在 http://127.0.0.1:8000）

### 安装依赖
```bash
pip install -r requirements.txt
```

### 启动服务
```bash
python web_app.py
```

访问地址: http://localhost:5001

## 使用说明

### 基本使用流程
1. 访问 http://localhost:5001
2. 配置API服务器地址（默认为 http://127.0.0.1:8000）
3. 选择语音模型
4. 上传LRC/VTT歌词文件
5. （可选）上传原音频文件用于双声道合并
6. 点击"开始处理"按钮
7. 等待处理完成，查看状态页面
8. 下载生成的音频文件

### 双声道合并功能
1. 访问 http://localhost:5001/stereo_merge
2. 上传两个音频文件
3. 设置每个音频的声道位置（左/右/中/自适应）
4. 调节音量（0.0-2.0）
5. 点击"开始合并"按钮
6. 等待处理完成，下载结果

## 项目文档

- [开发文档](DEVELOPMENT.md): 详细介绍项目结构和核心代码
- [部署说明](DEPLOYMENT.md): 部署步骤和维护指南

## 目录结构

```
音声项目/
├── templates/              # Web界面模板文件
│   ├── index.html          # 主页模板
│   ├── stereo_merge.html   # 双声道合并页面模板
│   ├── stereo_merge_status.html  # 双声道合并状态页面模板
│   ├── task_confirmation.html    # 任务确认页面模板
│   └── task_status.html    # 任务状态页面模板
├── lrc_tts_processor.py    # 核心处理逻辑
├── requirements.txt        # 项目依赖
├── web_app.py             # Web应用主程序
├── api.json               # API接口文档
├── README.md              # 项目说明文档
├── DEVELOPMENT.md         # 开发文档
└── DEPLOYMENT.md          # 部署说明
```

## 核心类说明

### LrcTtsProcessor
位于 `lrc_tts_processor.py` 文件中，是项目的核心处理类。

主要功能：
- `parse_lrc_file()`: 解析LRC文件
- `parse_vtt_file()`: 解析VTT文件
- `generate_speech()`: 调用API生成语音
- `advanced_stereo_merge()`: 高级双声道合并
- `process_complete_workflow()`: 完整处理工作流

## 配置说明

### Web服务配置
在 `web_app.py` 中可以修改以下配置：
```python
# 端口配置
app.run(debug=True, host='0.0.0.0', port=5001)

# 文件大小限制
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB
```

### API地址配置
- 默认API地址: http://127.0.0.1:8000
- 可在Web界面中动态修改
- 支持测试连接功能

## 贡献指南

1. Fork 本项目
2. 创建功能分支
3. 提交代码更改
4. 发起 Pull Request

## 许可证

本项目采用 MIT 许可证，详情请见 [LICENSE](LICENSE) 文件。

## 联系方式

如有问题或建议，请提交 Issue 或联系项目维护者。"# Voice_Project" 
