#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LRC音声处理器
完整的LRC文件处理和音声生成系统
功能：
1. 解析LRC文件
2. 调用API生成音声
3. 按时间轴拼接音频片段
4. 双声道合并（新音声左声道，原音声右声道）
"""

import requests
import json
import re
import os
import time
import tempfile
import shutil
import math
from typing import List, Dict, Optional
from pydub import AudioSegment
from pydub.silence import detect_silence

class LrcTtsProcessor:
    """LRC音声处理器主类"""
    
    def __init__(self, api_base_url="http://127.0.0.1:8000", model_name="原神-中文-宵宫_ZH", speed_factor=1.0):
        """
        初始化处理器
        
        Args:
            api_base_url: TTS API服务器地址
            model_name: 使用的语音模型名称
            speed_factor: 语音速度因子 (0.0-2.0)
        """
        # 确保URL末尾没有斜杠
        self.api_base_url = api_base_url.rstrip('/')
        self.model_name = model_name
        self.speed_factor = speed_factor
        self.session = requests.Session()
        
    def parse_lrc_file(self, file_path: str) -> List[Dict]:
        """
        解析LRC或VTT文件
        
        Args:
            file_path: LRC或VTT文件路径
            
        Returns:
            包含时间和歌词的列表
        """
        lyrics = []
        line_count = 0
        
        try:
            # 检查文件扩展名
            if file_path.lower().endswith('.vtt'):
                return self.parse_vtt_file(file_path)
            
            # 解析LRC文件，使用utf-8-sig自动处理BOM
            with open(file_path, 'r', encoding='utf-8-sig') as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if line:
                        line_count += 1
                        # 匹配LRC格式: [mm:ss.xx]歌词
                        # 支持多种LRC时间格式，包括可能的多个时间标签在同一行
                        matches = re.finditer(r'\[(\d{1,3}):(\d{2})(?:[.:](\d{2,3}))?\](.*)', line)
                        match_count = 0
                        for match in matches:
                            match_count += 1
                            minutes = int(match.group(1))
                            seconds = int(match.group(2))
                            # 处理不同的毫秒格式（可能是2位或3位）
                            milliseconds_str = match.group(3) if match.group(3) else "00"
                            # 标准化为3位毫秒
                            if len(milliseconds_str) == 2:
                                milliseconds = int(milliseconds_str) * 10
                            else:
                                milliseconds = int(milliseconds_str)
                            text = match.group(4).strip()
                            
                            # 只处理非空文本
                            if text and len(text) > 0 and not text.isspace():  # 只处理非空文本
                                # 转换为总毫秒数
                                total_ms = (minutes * 60 + seconds) * 1000 + milliseconds
                                
                                lyrics.append({
                                    'time_ms': total_ms,
                                    'text': text,
                                    'line_num': line_num
                                })
                                
                        # 如果没有匹配但行不为空，可能是特殊格式
                        if match_count == 0 and line.startswith('['):
                            # 尝试另一种匹配方式
                            alt_matches = re.finditer(r'\[(\d{1,3}):(\d{2}):(\d{2})[.:](\d{2,3})\](.*)', line)
                            for match in alt_matches:
                                hours = int(match.group(1))
                                minutes = int(match.group(2))
                                seconds = int(match.group(3))
                                milliseconds_str = match.group(4)
                                # 标准化为3位毫秒
                                if len(milliseconds_str) == 2:
                                    milliseconds = int(milliseconds_str) * 10
                                else:
                                    milliseconds = int(milliseconds_str)
                                text = match.group(5).strip()
                                
                                if text and len(text) > 0 and not text.isspace():
                                    # 转换为总毫秒数（包含小时）
                                    total_ms = (hours * 3600 + minutes * 60 + seconds) * 1000 + milliseconds
                                    
                                    lyrics.append({
                                        'time_ms': total_ms,
                                        'text': text,
                                        'line_num': line_num
                                    })
        except Exception as e:
            raise Exception(f"解析LRC文件失败: {e}")
        
        # 按时间排序
        original_count = len(lyrics)
        lyrics.sort(key=lambda x: x['time_ms'])
        
        # 去除重复的时间条目，保留最后一个
        unique_lyrics = []
        seen_times = set()
        for lyric in lyrics:
            if lyric['time_ms'] not in seen_times:
                unique_lyrics.append(lyric)
                seen_times.add(lyric['time_ms'])
            # 如果时间相同，用新的替换旧的
            else:
                # 找到已存在的条目并替换
                for i, existing in enumerate(unique_lyrics):
                    if existing['time_ms'] == lyric['time_ms']:
                        unique_lyrics[i] = lyric
                        break
        
        print(f"📝 LRC文件解析完成:")
        print(f"   总行数: {line_count}")
        print(f"   解析到时间条目: {original_count}")
        print(f"   去重后有效条目: {len(unique_lyrics)}")
        return unique_lyrics
    
    def parse_vtt_file(self, vtt_file_path: str) -> List[Dict]:
        """
        解析VTT文件
        
        Args:
            vtt_file_path: VTT文件路径
            
        Returns:
            包含时间和歌词的列表
        """
        lyrics = []
        
        try:
            with open(vtt_file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                
            # 跳过WEBVTT头部
            i = 0
            while i < len(lines) and not lines[i].strip():
                i += 1
                
            # 跳过WEBVTT声明行
            if i < len(lines) and lines[i].strip().upper().startswith('WEBVTT'):
                i += 1
                
            # 跳过空行和头部信息
            while i < len(lines) and lines[i].strip():
                if lines[i].strip().isdigit():  # 序号行
                    i += 1
                    break
                i += 1
                
            line_num = 1
            while i < len(lines):
                line = lines[i].strip()
                
                # 跳过空行
                if not line:
                    i += 1
                    continue
                    
                # 检查是否是时间戳行 (格式: hh:mm:ss.mmm --> hh:mm:ss.mmm)
                if '-->' in line:
                    # 解析时间戳
                    time_match = re.match(r'(\d{2}):(\d{2}):(\d{2})\.(\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})\.(\d{3})', line)
                    if time_match:
                        # 提取开始时间
                        hours = int(time_match.group(1))
                        minutes = int(time_match.group(2))
                        seconds = int(time_match.group(3))
                        milliseconds = int(time_match.group(4))
                        
                        # 转换为总毫秒数
                        total_ms = (hours * 3600 + minutes * 60 + seconds) * 1000 + milliseconds
                        
                        # 获取下一行的文本内容
                        i += 1
                        text_lines = []
                        while i < len(lines) and lines[i].strip() and not '-->' in lines[i] and not lines[i].strip().isdigit():
                            text_line = lines[i].strip()
                            if text_line:
                                text_lines.append(text_line)
                            i += 1
                            
                        text = ' '.join(text_lines).strip()
                        
                        if text:  # 只处理非空文本
                            lyrics.append({
                                'time_ms': total_ms,
                                'text': text,
                                'line_num': line_num
                            })
                            line_num += 1
                        continue
                        
                i += 1
                
        except Exception as e:
            raise Exception(f"解析VTT文件失败: {e}")
        
        # 按时间排序
        lyrics.sort(key=lambda x: x['time_ms'])
        return lyrics
    
    def test_api_connection(self) -> bool:
        """测试API连接"""
        try:
            response = self.session.get(f"{self.api_base_url}/api", timeout=10)
            return response.status_code == 200
        except:
            return False
    
    def generate_speech(self, text: str) -> Optional[str]:
        """
        生成语音
        
        Args:
            text: 要转换的文本
            
        Returns:
            音频文件路径或None
        """
        payload = {
            "app_key": "",
            "dl_url": "",
            "version": "v4",
            "model_name": self.model_name,
            "prompt_text_lang": "中文",
            "emotion": "默认",
            "text": text,
            "text_lang": "中文",
            "top_k": 10,
            "top_p": 1,
            "temperature": 1,
            "text_split_method": "按标点符号切",
            "batch_size": 1,
            "batch_threshold": 0.75,
            "split_bucket": True,
            "speed_facter": self.speed_factor,  # 使用配置的速度因子
            "fragment_interval": 0.3,
            "media_type": "wav",
            "parallel_infer": True,
            "repetition_penalty": 1.35,
            "seed": -1,
            "sample_steps": 16,
            "if_sr": False
        }
        
        try:
            print(f"🔄 生成语音: {text} (速度因子: {self.speed_factor})")
            response = self.session.post(f"{self.api_base_url}/infer_single", 
                                       json=payload, timeout=1800)  # 30分钟超时
            
            if response.status_code == 200:
                result = response.json()
                audio_path = result.get('audio_url') or result.get('result')
                if audio_path:
                    return audio_path
                else:
                    print(f"❌ API响应中没有音频路径: {result}")
            else:
                print(f"❌ API调用失败，状态码: {response.status_code}")
                print(f"响应: {response.text}")
        except Exception as e:
            print(f"❌ 生成语音失败: {e}")
        
        return None
    
    def download_audio(self, audio_path: str, output_file: str) -> bool:
        """
        下载音频文件
        
        Args:
            audio_path: API返回的音频路径（可能是相对路径或完整URL）
            output_file: 本地保存路径
            
        Returns:
            是否下载成功
        """
        try:
            # 处理API返回的不同格式的路径
            if audio_path.startswith('http'):
                # 如果是完整URL，检查是否需要替换主机部分
                if '0.0.0.0' in audio_path:
                    # 替换0.0.0.0为用户指定的API地址
                    from urllib.parse import urlparse
                    parsed_url = urlparse(audio_path)
                    # 使用用户指定的API地址的主机和端口
                    api_parsed = urlparse(self.api_base_url)
                    new_url = f"{api_parsed.scheme}://{api_parsed.netloc}{parsed_url.path}"
                    download_url = new_url
                else:
                    # 直接使用完整URL
                    download_url = audio_path
            elif audio_path.startswith('/'):
                # 如果是相对路径，拼接API基础URL
                download_url = f"{self.api_base_url}{audio_path}"
            else:
                # 其他情况也拼接API基础URL
                download_url = f"{self.api_base_url}/{audio_path}"
            
            print(f"📥 下载音频: {download_url}")
            
            response = self.session.get(download_url, timeout=120)
            
            if response.status_code == 200:
                with open(output_file, 'wb') as f:
                    f.write(response.content)
                print(f"✅ 下载成功: {output_file} ({len(response.content)} 字节)")
                return True
            else:
                print(f"❌ 下载失败，状态码: {response.status_code}")
        except Exception as e:
            print(f"❌ 下载失败: {e}")
        
        return False
    
    def process_lrc_to_speech_segments(self, lrc_file_path: str, output_dir: str, progress_callback=None) -> List[Dict]:
        """
        处理LRC文件，生成所有语音片段
        
        Args:
            lrc_file_path: LRC文件路径
            output_dir: 输出目录
            progress_callback: 进度回调函数
            
        Returns:
            成功生成的音频片段信息列表
        """
        print("🎵 开始处理LRC文件...")
        
        # 解析LRC文件
        lyrics = self.parse_lrc_file(lrc_file_path)
        total_lines = len(lyrics)
        print(f"📝 解析到 {total_lines} 行歌词")
        
        # 创建输出目录
        os.makedirs(output_dir, exist_ok=True)
        
        # 生成语音片段
        successful_segments = []
        failed_segments = []  # 记录失败的片段
        failed_details = []   # 记录失败的详细信息
        
        # 检查已存在的音频片段（断点续传）
        existing_segments = {}
        for filename in os.listdir(output_dir):
            if filename.startswith("segment_") and filename.endswith(".wav"):
                # 解析文件名格式: segment_001_1000ms.wav
                parts = filename.split("_")
                if len(parts) >= 3:
                    try:
                        index = int(parts[1]) - 1  # 转换为0基索引
                        time_ms = int(parts[2].replace("ms.wav", ""))
                        file_path = os.path.join(output_dir, filename)
                        if os.path.exists(file_path):
                            existing_segments[index] = {
                                'file_path': file_path,
                                'time_ms': time_ms,
                                'text': lyrics[index]['text'] if index < len(lyrics) else '',
                                'index': index
                            }
                    except (ValueError, IndexError):
                        pass  # 忽略无法解析的文件名
        
        print(f"🔄 检测到 {len(existing_segments)} 个已存在的音频片段")
        
        # 处理每个歌词条目
        for i, lyric in enumerate(lyrics):
            try:
                # 检查是否已存在该片段
                if i in existing_segments:
                    print(f"⏭️  跳过已存在的片段 {i+1}/{total_lines}: {lyric['text']}")
                    successful_segments.append(existing_segments[i])
                    # 更新进度 - 片段已存在
                    if progress_callback:
                        progress_callback(i+1, total_lines, f"跳过已存在的片段 {i+1}/{total_lines}: {lyric['text']}")
                    continue
                
                # 更新进度 - 片段开始处理
                if progress_callback:
                    progress_callback(i, total_lines, f"正在生成第 {i+1}/{total_lines} 个语音片段: {lyric['text']}")
                
                print(f"\n--- 处理第 {i+1}/{total_lines} 句 ---")
                print(f"📝 文本: {lyric['text']}")
                print(f"⏰ 时间: {lyric['time_ms']}ms")
                
                # 生成语音（不重试，失败直接跳过）
                audio_path = self.generate_speech(lyric['text'])
                
                if audio_path:
                    # 下载音频
                    output_file = os.path.join(output_dir, f"segment_{i+1:03d}_{lyric['time_ms']}ms.wav")
                    
                    if self.download_audio(audio_path, output_file):
                        successful_segments.append({
                            'file_path': output_file,
                            'time_ms': lyric['time_ms'],
                            'text': lyric['text'],
                            'index': i
                        })
                        print(f"✅ 片段 {i+1} 处理完成")
                        # 更新进度 - 片段处理完成
                        if progress_callback:
                            progress_callback(i+1, total_lines, f"第 {i+1}/{total_lines} 个语音片段处理完成: {lyric['text']}")
                    else:
                        print(f"❌ 片段 {i+1} 下载失败")
                        failed_segments.append(i)
                        failed_details.append(f"片段 {i+1} 下载失败: {lyric['text']}")
                else:
                    print(f"❌ 片段 {i+1} 生成失败")
                    failed_segments.append(i)
                    failed_details.append(f"片段 {i+1} 生成失败: {lyric['text']}")
                
                    
            except Exception as e:
                print(f"❌ 处理第 {i+1} 个片段时发生未预期的错误: {e}")
                failed_segments.append(i)
                failed_details.append(f"片段 {i+1} 处理异常: {lyric['text']} - {str(e)}")
                # 继续处理下一个片段，不中断整个流程
        
        if progress_callback:
            progress_callback(total_lines, total_lines, f"语音片段生成完成 ({len(successful_segments)}/{total_lines})")
        
        print(f"\n🎉 语音片段生成完成！")
        print(f"✅ 成功: {len(successful_segments)}")
        print(f"❌ 失败: {len(failed_segments)}")
        
        # 显示失败的详细信息
        if failed_details:
            print("\n📝 失败详情:")
            for detail in failed_details[:10]:  # 只显示前10个失败详情
                print(f"   {detail}")
            if len(failed_details) > 10:
                print(f"   ... 还有 {len(failed_details) - 10} 个失败条目")
        
        # 将失败信息存储在返回结果中
        return {
            'successful_segments': successful_segments,
            'failed_count': len(failed_segments),
            'failed_details': failed_details
        }
    
    def concatenate_audio_with_timing(self, segments: List[Dict], output_file: str) -> bool:
        """
        按时间轴拼接音频片段
        
        Args:
            segments: 音频片段信息列表
            output_file: 输出文件路径
            
        Returns:
            是否拼接成功
        """
        try:
            print("🎼 开始按时间轴拼接音频...")
            
            # 按时间排序
            segments = sorted(segments, key=lambda x: x['time_ms'])
            
            # 创建空音频
            final_audio = AudioSegment.empty()
            current_time = 0
            
            for i, segment in enumerate(segments):
                print(f"🎵 处理片段 {i+1}/{len(segments)}: {segment['text']}")
                
                # 加载音频片段
                if not os.path.exists(segment['file_path']):
                    print(f"⚠️ 文件不存在: {segment['file_path']}")
                    continue
                
                audio_segment = AudioSegment.from_wav(segment['file_path'])
                target_time = segment['time_ms']
                
                # 添加静音间隔（如果需要）
                if target_time > current_time:
                    silence_duration = target_time - current_time
                    silence = AudioSegment.silent(duration=silence_duration)
                    final_audio += silence
                    print(f"🔇 添加静音: {silence_duration}ms")
                    current_time = target_time
                
                # 添加音频片段
                final_audio += audio_segment
                current_time += len(audio_segment)
                print(f"✅ 片段已添加，当前总长度: {current_time}ms")
            
            # 导出最终音频
            final_audio.export(output_file, format="wav")
            print(f"🎉 拼接完成！输出: {output_file}")
            print(f"📊 最终音频长度: {len(final_audio)}ms ({len(final_audio)/1000:.2f}秒)")
            
            return True
            
        except Exception as e:
            print(f"❌ 音频拼接失败: {e}")
            return False
    
    def merge_with_original_audio(self, generated_audio_path: str, original_audio_path: str, output_path: str) -> bool:
        """
        将生成的音频与原音频合并为双声道
        
        Args:
            generated_audio_path: 生成的音频文件路径
            original_audio_path: 原音频文件路径
            output_path: 输出文件路径
            
        Returns:
            是否合并成功
        """
        try:
            print("🎧 开始双声道合并...")
            
            # 加载音频文件
            generated_audio = AudioSegment.from_wav(generated_audio_path)
            
            # 根据原音频格式自动检测
            if original_audio_path.lower().endswith('.wav'):
                original_audio = AudioSegment.from_wav(original_audio_path)
            elif original_audio_path.lower().endswith('.mp3'):
                original_audio = AudioSegment.from_mp3(original_audio_path)
            else:
                # 尝试通用方法
                original_audio = AudioSegment.from_file(original_audio_path)
            
            print(f"📊 生成音频长度: {len(generated_audio)}ms")
            print(f"📊 原音频长度: {len(original_audio)}ms")
            
            # 统一长度（以较长的为准）
            max_length = max(len(generated_audio), len(original_audio))
            
            # 扩展较短的音频（用静音填充）
            if len(generated_audio) < max_length:
                silence = AudioSegment.silent(duration=max_length - len(generated_audio))
                generated_audio = generated_audio + silence
                print(f"🔇 生成音频已扩展到 {max_length}ms")
            
            if len(original_audio) < max_length:
                silence = AudioSegment.silent(duration=max_length - len(original_audio))
                original_audio = original_audio + silence
                print(f"🔇 原音频已扩展到 {max_length}ms")
            
            # 转换为单声道（如果需要）
            generated_mono = generated_audio.set_channels(1)
            original_mono = original_audio.set_channels(1)
            
            # 创建双声道音频：生成的音频在左声道，原音频在右声道
            stereo_audio = AudioSegment.from_mono_audiosegments(generated_mono, original_mono)
            
            # 导出
            stereo_audio.export(output_path, format="wav")
            
            print(f"🎉 双声道合并完成！")
            print(f"📁 输出文件: {output_path}")
            print(f"📊 最终音频长度: {len(stereo_audio)}ms")
            print("🎧 左声道：生成的音声，右声道：原音频")
            
            return True
            
        except Exception as e:
            print(f"❌ 双声道合并失败: {e}")
            return False

    def advanced_stereo_merge(self, audio1_path: str, audio2_path: str, 
                            audio1_position: str, audio2_position: str,
                            audio1_volume: float, audio2_volume: float,
                            output_path: str, progress_callback=None) -> bool:
        """
        高级双声道合并功能
        
        Args:
            audio1_path: 第一个音频文件路径
            audio2_path: 第二个音频文件路径
            audio1_position: 第一个音频的声道位置 ('left', 'right', 'center', 'adaptive', 'original')
            audio2_position: 第二个音频的声道位置 ('left', 'right', 'center', 'adaptive', 'original')
            audio1_volume: 第一个音频的音量调节 (0.0-2.0, 1.0为原始音量)
            audio2_volume: 第二个音频的音量调节 (0.0-2.0, 1.0为原始音量)
            output_path: 输出文件路径
            progress_callback: 进度回调函数 (current, total, message)
            
        Returns:
            是否合并成功
        """
        try:
            print("🎧 开始高级双声道合并...")
            
            # 加载音频文件
            def load_audio(file_path, progress_callback=None, progress_start=0, progress_end=10):
                if progress_callback:
                    progress_callback(progress_start, 100, f"正在加载音频文件: {os.path.basename(file_path)}...")
                
                if file_path.lower().endswith('.wav'):
                    audio = AudioSegment.from_wav(file_path)
                elif file_path.lower().endswith('.mp3'):
                    audio = AudioSegment.from_mp3(file_path)
                else:
                    audio = AudioSegment.from_file(file_path)
                
                if progress_callback:
                    progress_callback(progress_end, 100, f"音频文件加载完成: {os.path.basename(file_path)}")
                
                return audio
            
            # 更新进度 - 开始加载音频
            if progress_callback:
                progress_callback(0, 100, "开始加载音频文件...")
            
            audio1 = load_audio(audio1_path, progress_callback, 0, 10)
            audio2 = load_audio(audio2_path, progress_callback, 10, 20)
            
            # 调节音量（在转换为单声道之前应用音量调节）
            if progress_callback:
                progress_callback(20, 100, "正在调节音量...")
                
            if audio1_volume != 1.0:
                # 正确的音量调节方法：使用 20 * log10(volume_ratio) 转换为分贝
                # 处理边界情况：音量不能为负数或零
                if audio1_volume > 0:
                    gain_db = 20 * math.log10(audio1_volume)
                    audio1 = audio1.apply_gain(gain_db)
                else:
                    # 如果音量为0或负数，则静音
                    audio1 = audio1.apply_gain(-120)  # 接近静音
                    
            if audio2_volume != 1.0:
                # 正确的音量调节方法：使用 20 * log10(volume_ratio) 转换为分贝
                # 处理边界情况：音量不能为负数或零
                if audio2_volume > 0:
                    gain_db = 20 * math.log10(audio2_volume)
                    audio2 = audio2.apply_gain(gain_db)
                else:
                    # 如果音量为0或负数，则静音
                    audio2 = audio2.apply_gain(-120)  # 接近静音
            
            print(f"📊 音频1长度: {len(audio1)}ms, 音量: {audio1_volume}")
            print(f"📊 音频2长度: {len(audio2)}ms, 音量: {audio2_volume}")
            
            # 更新进度 - 音频加载完成
            if progress_callback:
                progress_callback(25, 100, "音频文件加载完成，正在统一长度...")
            
            # 统一长度（以较长的为准）
            max_length = max(len(audio1), len(audio2))
            
            # 扩展较短的音频（用静音填充）
            if len(audio1) < max_length:
                if progress_callback:
                    progress_callback(25, 100, f"正在扩展音频1长度至 {max_length}ms...")
                silence = AudioSegment.silent(duration=max_length - len(audio1))
                audio1 = audio1 + silence
                print(f"🔇 音频1已扩展到 {max_length}ms")
            
            if len(audio2) < max_length:
                if progress_callback:
                    progress_callback(30, 100, f"正在扩展音频2长度至 {max_length}ms...")
                silence = AudioSegment.silent(duration=max_length - len(audio2))
                audio2 = audio2 + silence
                print(f"🔇 音频2已扩展到 {max_length}ms")
            
            # 更新进度 - 长度统一完成
            if progress_callback:
                progress_callback(35, 100, "长度统一完成，正在处理声道...")
            
            # 处理"原声"选项 - 保持原始声道配置
            # 如果选择了"原声"，则不转换为单声道，直接使用原始音频
            if audio1_position == 'original':
                # 保持audio1的原始声道配置
                processed_audio1 = audio1
            else:
                # 转换为单声道
                processed_audio1 = audio1.set_channels(1)
                
            if audio2_position == 'original':
                # 保持audio2的原始声道配置
                processed_audio2 = audio2
            else:
                # 转换为单声道
                processed_audio2 = audio2.set_channels(1)
            
            # 如果任一音频是"原声"，需要特殊处理
            if audio1_position == 'original' or audio2_position == 'original':
                # 至少有一个音频选择"原声"，需要保持原始声道配置
                # 确保两个音频参数一致
                target_frame_rate = max(processed_audio1.frame_rate, processed_audio2.frame_rate)
                target_sample_width = max(processed_audio1.sample_width, processed_audio2.sample_width)
                
                # 统一参数
                processed_audio1 = processed_audio1.set_frame_rate(target_frame_rate).set_sample_width(target_sample_width)
                processed_audio2 = processed_audio2.set_frame_rate(target_frame_rate).set_sample_width(target_sample_width)
                
                # 确保长度一致
                if len(processed_audio1) != len(processed_audio2):
                    max_length = max(len(processed_audio1), len(processed_audio2))
                    if len(processed_audio1) < max_length:
                        silence = AudioSegment.silent(duration=max_length - len(processed_audio1), 
                                                     frame_rate=target_frame_rate)
                        silence = silence.set_sample_width(target_sample_width)
                        processed_audio1 = processed_audio1 + silence
                    if len(processed_audio2) < max_length:
                        silence = AudioSegment.silent(duration=max_length - len(processed_audio2), 
                                                     frame_rate=target_frame_rate)
                        silence = silence.set_sample_width(target_sample_width)
                        processed_audio2 = processed_audio2 + silence
                
                # 更新进度 - 声道处理完成
                if progress_callback:
                    progress_callback(50, 100, "声道处理完成，正在合并音频...")
                
                # 特殊处理：当至少一个音频选择"原声"时
                if audio1_position == 'original' and audio2_position == 'original':
                    # 两个都是原声，直接混合
                    stereo_audio = processed_audio1.overlay(processed_audio2)
                elif audio1_position == 'original':
                    # 音频1是原声，音频2需要根据位置处理
                    if audio2_position == 'left':
                        # 音频2放在左声道，音频1保持原样
                        # 将音频1的左声道与音频2混合到左声道，音频1的右声道保持到右声道
                        if processed_audio1.channels > 1:
                            # 原始音频是立体声
                            left_channel = processed_audio1.split_to_mono()[0]  # 原始左声道
                            right_channel = processed_audio1.split_to_mono()[1]  # 原始右声道
                            # 将音频2叠加到左声道
                            mono2 = processed_audio2.set_channels(1)
                            # 确保参数一致
                            mono2 = mono2.set_frame_rate(left_channel.frame_rate).set_sample_width(left_channel.sample_width)
                            # 确保长度一致
                            if len(mono2) != len(left_channel):
                                max_len = max(len(mono2), len(left_channel))
                                if len(mono2) < max_len:
                                    silence = AudioSegment.silent(duration=max_len - len(mono2), 
                                                                 frame_rate=left_channel.frame_rate)
                                    silence = silence.set_sample_width(left_channel.sample_width)
                                    mono2 = mono2 + silence
                                if len(left_channel) < max_len:
                                    silence = AudioSegment.silent(duration=max_len - len(left_channel), 
                                                                 frame_rate=left_channel.frame_rate)
                                    silence = silence.set_sample_width(left_channel.sample_width)
                                    left_channel = left_channel + silence
                            left_channel = left_channel.overlay(mono2)
                        else:
                            # 原始音频是单声道
                            left_channel = processed_audio1.set_channels(1)
                            right_channel = processed_audio1.set_channels(1)
                            mono2 = processed_audio2.set_channels(1)
                            # 确保参数一致
                            mono2 = mono2.set_frame_rate(left_channel.frame_rate).set_sample_width(left_channel.sample_width)
                            # 确保长度一致
                            if len(mono2) != len(left_channel):
                                max_len = max(len(mono2), len(left_channel))
                                if len(mono2) < max_len:
                                    silence = AudioSegment.silent(duration=max_len - len(mono2), 
                                                                 frame_rate=left_channel.frame_rate)
                                    silence = silence.set_sample_width(left_channel.sample_width)
                                    mono2 = mono2 + silence
                                if len(left_channel) < max_len:
                                    silence = AudioSegment.silent(duration=max_len - len(left_channel), 
                                                                 frame_rate=left_channel.frame_rate)
                                    silence = silence.set_sample_width(left_channel.sample_width)
                                    left_channel = left_channel + silence
                            left_channel = left_channel.overlay(mono2)
                        # 使用手动创建立体声的方法避免参数不一致问题
                        stereo_audio = self._create_stereo_manually(left_channel, right_channel)
                    elif audio2_position == 'right':
                        # 音频2放在右声道，音频1保持原样
                        if processed_audio1.channels > 1:
                            # 原始音频是立体声
                            left_channel = processed_audio1.split_to_mono()[0]  # 原始左声道
                            right_channel = processed_audio1.split_to_mono()[1]  # 原始右声道
                            # 将音频2叠加到右声道
                            mono2 = processed_audio2.set_channels(1)
                            # 确保参数一致
                            mono2 = mono2.set_frame_rate(right_channel.frame_rate).set_sample_width(right_channel.sample_width)
                            # 确保长度一致
                            if len(mono2) != len(right_channel):
                                max_len = max(len(mono2), len(right_channel))
                                if len(mono2) < max_len:
                                    silence = AudioSegment.silent(duration=max_len - len(mono2), 
                                                                 frame_rate=right_channel.frame_rate)
                                    silence = silence.set_sample_width(right_channel.sample_width)
                                    mono2 = mono2 + silence
                                if len(right_channel) < max_len:
                                    silence = AudioSegment.silent(duration=max_len - len(right_channel), 
                                                                 frame_rate=right_channel.frame_rate)
                                    silence = silence.set_sample_width(right_channel.sample_width)
                                    right_channel = right_channel + silence
                            right_channel = right_channel.overlay(mono2)
                        else:
                            # 原始音频是单声道
                            left_channel = processed_audio1.set_channels(1)
                            right_channel = processed_audio1.set_channels(1)
                            mono2 = processed_audio2.set_channels(1)
                            # 确保参数一致
                            mono2 = mono2.set_frame_rate(right_channel.frame_rate).set_sample_width(right_channel.sample_width)
                            # 确保长度一致
                            if len(mono2) != len(right_channel):
                                max_len = max(len(mono2), len(right_channel))
                                if len(mono2) < max_len:
                                    silence = AudioSegment.silent(duration=max_len - len(mono2), 
                                                                 frame_rate=right_channel.frame_rate)
                                    silence = silence.set_sample_width(right_channel.sample_width)
                                    mono2 = mono2 + silence
                                if len(right_channel) < max_len:
                                    silence = AudioSegment.silent(duration=max_len - len(right_channel), 
                                                                 frame_rate=right_channel.frame_rate)
                                    silence = silence.set_sample_width(right_channel.sample_width)
                                    right_channel = right_channel + silence
                            right_channel = right_channel.overlay(mono2)
                        # 使用手动创建立体声的方法避免参数不一致问题
                        stereo_audio = self._create_stereo_manually(left_channel, right_channel)
                    elif audio2_position == 'center':
                        # 音频2放在中心，音频1保持原样
                        if processed_audio1.channels > 1:
                            # 原始音频是立体声
                            left_channel = processed_audio1.split_to_mono()[0]  # 原始左声道
                            right_channel = processed_audio1.split_to_mono()[1]  # 原始右声道
                            # 将音频2叠加到两个声道
                            mono2 = processed_audio2.set_channels(1)
                            # 确保参数一致
                            mono2 = mono2.set_frame_rate(left_channel.frame_rate).set_sample_width(left_channel.sample_width)
                            # 确保长度一致
                            if len(mono2) != len(left_channel):
                                max_len = max(len(mono2), len(left_channel))
                                if len(mono2) < max_len:
                                    silence = AudioSegment.silent(duration=max_len - len(mono2), 
                                                                 frame_rate=left_channel.frame_rate)
                                    silence = silence.set_sample_width(left_channel.sample_width)
                                    mono2 = mono2 + silence
                                if len(left_channel) < max_len:
                                    silence = AudioSegment.silent(duration=max_len - len(left_channel), 
                                                                 frame_rate=left_channel.frame_rate)
                                    silence = silence.set_sample_width(left_channel.sample_width)
                                    left_channel = left_channel + silence
                            left_channel = left_channel.overlay(mono2)
                            right_channel = right_channel.overlay(mono2)
                        else:
                            # 原始音频是单声道
                            left_channel = processed_audio1.set_channels(1)
                            right_channel = processed_audio1.set_channels(1)
                            mono2 = processed_audio2.set_channels(1)
                            # 确保参数一致
                            mono2 = mono2.set_frame_rate(left_channel.frame_rate).set_sample_width(left_channel.sample_width)
                            # 确保长度一致
                            if len(mono2) != len(left_channel):
                                max_len = max(len(mono2), len(left_channel))
                                if len(mono2) < max_len:
                                    silence = AudioSegment.silent(duration=max_len - len(mono2), 
                                                                 frame_rate=left_channel.frame_rate)
                                    silence = silence.set_sample_width(left_channel.sample_width)
                                    mono2 = mono2 + silence
                                if len(left_channel) < max_len:
                                    silence = AudioSegment.silent(duration=max_len - len(left_channel), 
                                                                 frame_rate=left_channel.frame_rate)
                                    silence = silence.set_sample_width(left_channel.sample_width)
                                    left_channel = left_channel + silence
                            left_channel = left_channel.overlay(mono2)
                            right_channel = right_channel.overlay(mono2)
                        # 使用手动创建立体声的方法避免参数不一致问题
                        stereo_audio = self._create_stereo_manually(left_channel, right_channel)
                    elif audio2_position == 'adaptive':
                        # 音频2自适应，音频1保持原样
                        if processed_audio1.channels > 1:
                            # 原始音频是立体声
                            left_channel = processed_audio1.split_to_mono()[0]  # 原始左声道
                            right_channel = processed_audio1.split_to_mono()[1]  # 原始右声道
                            # 将音频2叠加到右声道
                            mono2 = processed_audio2.set_channels(1)
                            # 确保参数一致
                            mono2 = mono2.set_frame_rate(right_channel.frame_rate).set_sample_width(right_channel.sample_width)
                            # 确保长度一致
                            if len(mono2) != len(right_channel):
                                max_len = max(len(mono2), len(right_channel))
                                if len(mono2) < max_len:
                                    silence = AudioSegment.silent(duration=max_len - len(mono2), 
                                                                 frame_rate=right_channel.frame_rate)
                                    silence = silence.set_sample_width(right_channel.sample_width)
                                    mono2 = mono2 + silence
                                if len(right_channel) < max_len:
                                    silence = AudioSegment.silent(duration=max_len - len(right_channel), 
                                                                 frame_rate=right_channel.frame_rate)
                                    silence = silence.set_sample_width(right_channel.sample_width)
                                    right_channel = right_channel + silence
                            right_channel = right_channel.overlay(mono2)
                        else:
                            # 原始音频是单声道
                            left_channel = processed_audio1.set_channels(1)
                            right_channel = processed_audio1.set_channels(1)
                            mono2 = processed_audio2.set_channels(1)
                            # 确保参数一致
                            mono2 = mono2.set_frame_rate(right_channel.frame_rate).set_sample_width(right_channel.sample_width)
                            # 确保长度一致
                            if len(mono2) != len(right_channel):
                                max_len = max(len(mono2), len(right_channel))
                                if len(mono2) < max_len:
                                    silence = AudioSegment.silent(duration=max_len - len(mono2), 
                                                                 frame_rate=right_channel.frame_rate)
                                    silence = silence.set_sample_width(right_channel.sample_width)
                                    mono2 = mono2 + silence
                                if len(right_channel) < max_len:
                                    silence = AudioSegment.silent(duration=max_len - len(right_channel), 
                                                                 frame_rate=right_channel.frame_rate)
                                    silence = silence.set_sample_width(right_channel.sample_width)
                                    right_channel = right_channel + silence
                            right_channel = right_channel.overlay(mono2)
                        # 使用手动创建立体声的方法避免参数不一致问题
                        stereo_audio = self._create_stereo_manually(left_channel, right_channel)
                    else:
                        # 默认情况，直接混合
                        stereo_audio = processed_audio1.overlay(processed_audio2)
                elif audio2_position == 'original':
                    # 音频2是原声，音频1需要根据位置处理
                    if audio1_position == 'left':
                        # 音频1放在左声道，音频2保持原样
                        if processed_audio2.channels > 1:
                            # 原始音频是立体声
                            left_channel = processed_audio2.split_to_mono()[0]  # 原始左声道
                            right_channel = processed_audio2.split_to_mono()[1]  # 原始右声道
                            # 将音频1叠加到左声道
                            mono1 = processed_audio1.set_channels(1)
                            # 确保参数一致
                            mono1 = mono1.set_frame_rate(left_channel.frame_rate).set_sample_width(left_channel.sample_width)
                            # 确保长度一致
                            if len(mono1) != len(left_channel):
                                max_len = max(len(mono1), len(left_channel))
                                if len(mono1) < max_len:
                                    silence = AudioSegment.silent(duration=max_len - len(mono1), 
                                                                 frame_rate=left_channel.frame_rate)
                                    silence = silence.set_sample_width(left_channel.sample_width)
                                    mono1 = mono1 + silence
                                if len(left_channel) < max_len:
                                    silence = AudioSegment.silent(duration=max_len - len(left_channel), 
                                                                 frame_rate=left_channel.frame_rate)
                                    silence = silence.set_sample_width(left_channel.sample_width)
                                    left_channel = left_channel + silence
                            left_channel = left_channel.overlay(mono1)
                        else:
                            # 原始音频是单声道
                            left_channel = processed_audio2.set_channels(1)
                            right_channel = processed_audio2.set_channels(1)
                            mono1 = processed_audio1.set_channels(1)
                            # 确保参数一致
                            mono1 = mono1.set_frame_rate(left_channel.frame_rate).set_sample_width(left_channel.sample_width)
                            # 确保长度一致
                            if len(mono1) != len(left_channel):
                                max_len = max(len(mono1), len(left_channel))
                                if len(mono1) < max_len:
                                    silence = AudioSegment.silent(duration=max_len - len(mono1), 
                                                                 frame_rate=left_channel.frame_rate)
                                    silence = silence.set_sample_width(left_channel.sample_width)
                                    mono1 = mono1 + silence
                                if len(left_channel) < max_len:
                                    silence = AudioSegment.silent(duration=max_len - len(left_channel), 
                                                                 frame_rate=left_channel.frame_rate)
                                    silence = silence.set_sample_width(left_channel.sample_width)
                                    left_channel = left_channel + silence
                            left_channel = left_channel.overlay(mono1)
                        # 使用手动创建立体声的方法避免参数不一致问题
                        stereo_audio = self._create_stereo_manually(left_channel, right_channel)
                    elif audio1_position == 'right':
                        # 音频1放在右声道，音频2保持原样
                        if processed_audio2.channels > 1:
                            # 原始音频是立体声
                            left_channel = processed_audio2.split_to_mono()[0]  # 原始左声道
                            right_channel = processed_audio2.split_to_mono()[1]  # 原始右声道
                            # 将音频1叠加到右声道
                            mono1 = processed_audio1.set_channels(1)
                            # 确保参数一致
                            mono1 = mono1.set_frame_rate(right_channel.frame_rate).set_sample_width(right_channel.sample_width)
                            # 确保长度一致
                            if len(mono1) != len(right_channel):
                                max_len = max(len(mono1), len(right_channel))
                                if len(mono1) < max_len:
                                    silence = AudioSegment.silent(duration=max_len - len(mono1), 
                                                                 frame_rate=right_channel.frame_rate)
                                    silence = silence.set_sample_width(right_channel.sample_width)
                                    mono1 = mono1 + silence
                                if len(right_channel) < max_len:
                                    silence = AudioSegment.silent(duration=max_len - len(right_channel), 
                                                                 frame_rate=right_channel.frame_rate)
                                    silence = silence.set_sample_width(right_channel.sample_width)
                                    right_channel = right_channel + silence
                            right_channel = right_channel.overlay(mono1)
                        else:
                            # 原始音频是单声道
                            left_channel = processed_audio2.set_channels(1)
                            right_channel = processed_audio2.set_channels(1)
                            mono1 = processed_audio1.set_channels(1)
                            # 确保参数一致
                            mono1 = mono1.set_frame_rate(right_channel.frame_rate).set_sample_width(right_channel.sample_width)
                            # 确保长度一致
                            if len(mono1) != len(right_channel):
                                max_len = max(len(mono1), len(right_channel))
                                if len(mono1) < max_len:
                                    silence = AudioSegment.silent(duration=max_len - len(mono1), 
                                                                 frame_rate=right_channel.frame_rate)
                                    silence = silence.set_sample_width(right_channel.sample_width)
                                    mono1 = mono1 + silence
                                if len(right_channel) < max_len:
                                    silence = AudioSegment.silent(duration=max_len - len(right_channel), 
                                                                 frame_rate=right_channel.frame_rate)
                                    silence = silence.set_sample_width(right_channel.sample_width)
                                    right_channel = right_channel + silence
                            right_channel = right_channel.overlay(mono1)
                        # 使用手动创建立体声的方法避免参数不一致问题
                        stereo_audio = self._create_stereo_manually(left_channel, right_channel)
                    elif audio1_position == 'center':
                        # 音频1放在中心，音频2保持原样
                        if processed_audio2.channels > 1:
                            # 原始音频是立体声
                            left_channel = processed_audio2.split_to_mono()[0]  # 原始左声道
                            right_channel = processed_audio2.split_to_mono()[1]  # 原始右声道
                            # 将音频1叠加到两个声道
                            mono1 = processed_audio1.set_channels(1)
                            # 确保参数一致
                            mono1 = mono1.set_frame_rate(left_channel.frame_rate).set_sample_width(left_channel.sample_width)
                            # 确保长度一致
                            if len(mono1) != len(left_channel):
                                max_len = max(len(mono1), len(left_channel))
                                if len(mono1) < max_len:
                                    silence = AudioSegment.silent(duration=max_len - len(mono1), 
                                                                 frame_rate=left_channel.frame_rate)
                                    silence = silence.set_sample_width(left_channel.sample_width)
                                    mono1 = mono1 + silence
                                if len(left_channel) < max_len:
                                    silence = AudioSegment.silent(duration=max_len - len(left_channel), 
                                                                 frame_rate=left_channel.frame_rate)
                                    silence = silence.set_sample_width(left_channel.sample_width)
                                    left_channel = left_channel + silence
                            left_channel = left_channel.overlay(mono1)
                            right_channel = right_channel.overlay(mono1)
                        else:
                            # 原始音频是单声道
                            left_channel = processed_audio2.set_channels(1)
                            right_channel = processed_audio2.set_channels(1)
                            mono1 = processed_audio1.set_channels(1)
                            # 确保参数一致
                            mono1 = mono1.set_frame_rate(left_channel.frame_rate).set_sample_width(left_channel.sample_width)
                            # 确保长度一致
                            if len(mono1) != len(left_channel):
                                max_len = max(len(mono1), len(left_channel))
                                if len(mono1) < max_len:
                                    silence = AudioSegment.silent(duration=max_len - len(mono1), 
                                                                 frame_rate=left_channel.frame_rate)
                                    silence = silence.set_sample_width(left_channel.sample_width)
                                    mono1 = mono1 + silence
                                if len(left_channel) < max_len:
                                    silence = AudioSegment.silent(duration=max_len - len(left_channel), 
                                                                 frame_rate=left_channel.frame_rate)
                                    silence = silence.set_sample_width(left_channel.sample_width)
                                    left_channel = left_channel + silence
                            left_channel = left_channel.overlay(mono1)
                            right_channel = right_channel.overlay(mono1)
                        # 使用手动创建立体声的方法避免参数不一致问题
                        stereo_audio = self._create_stereo_manually(left_channel, right_channel)
                    elif audio1_position == 'adaptive':
                        # 音频1自适应，音频2保持原样
                        if processed_audio2.channels > 1:
                            # 原始音频是立体声
                            left_channel = processed_audio2.split_to_mono()[0]  # 原始左声道
                            right_channel = processed_audio2.split_to_mono()[1]  # 原始右声道
                            # 将音频1叠加到左声道
                            mono1 = processed_audio1.set_channels(1)
                            # 确保参数一致
                            mono1 = mono1.set_frame_rate(left_channel.frame_rate).set_sample_width(left_channel.sample_width)
                            # 确保长度一致
                            if len(mono1) != len(left_channel):
                                max_len = max(len(mono1), len(left_channel))
                                if len(mono1) < max_len:
                                    silence = AudioSegment.silent(duration=max_len - len(mono1), 
                                                                 frame_rate=left_channel.frame_rate)
                                    silence = silence.set_sample_width(left_channel.sample_width)
                                    mono1 = mono1 + silence
                                if len(left_channel) < max_len:
                                    silence = AudioSegment.silent(duration=max_len - len(left_channel), 
                                                                 frame_rate=left_channel.frame_rate)
                                    silence = silence.set_sample_width(left_channel.sample_width)
                                    left_channel = left_channel + silence
                            left_channel = left_channel.overlay(mono1)
                        else:
                            # 原始音频是单声道
                            left_channel = processed_audio2.set_channels(1)
                            right_channel = processed_audio2.set_channels(1)
                            mono1 = processed_audio1.set_channels(1)
                            # 确保参数一致
                            mono1 = mono1.set_frame_rate(left_channel.frame_rate).set_sample_width(left_channel.sample_width)
                            # 确保长度一致
                            if len(mono1) != len(left_channel):
                                max_len = max(len(mono1), len(left_channel))
                                if len(mono1) < max_len:
                                    silence = AudioSegment.silent(duration=max_len - len(mono1), 
                                                                 frame_rate=left_channel.frame_rate)
                                    silence = silence.set_sample_width(left_channel.sample_width)
                                    mono1 = mono1 + silence
                                if len(left_channel) < max_len:
                                    silence = AudioSegment.silent(duration=max_len - len(left_channel), 
                                                                 frame_rate=left_channel.frame_rate)
                                    silence = silence.set_sample_width(left_channel.sample_width)
                                    left_channel = left_channel + silence
                            left_channel = left_channel.overlay(mono1)
                        # 使用手动创建立体声的方法避免参数不一致问题
                        stereo_audio = self._create_stereo_manually(left_channel, right_channel)
                    else:
                        # 默认情况，直接混合
                        stereo_audio = processed_audio1.overlay(processed_audio2)
                else:
                    # 使用手动创建立体声的方法避免参数不一致问题
                    stereo_audio = self._create_stereo_manually(processed_audio1, processed_audio2)
            else:
                # 两个都不是"原声"，使用原来的处理逻辑
                # 确保两个音频参数一致
                target_frame_rate = max(processed_audio1.frame_rate, processed_audio2.frame_rate)
                target_sample_width = max(processed_audio1.sample_width, processed_audio2.sample_width)
                
                # 统一参数
                processed_audio1 = processed_audio1.set_frame_rate(target_frame_rate).set_sample_width(target_sample_width)
                processed_audio2 = processed_audio2.set_frame_rate(target_frame_rate).set_sample_width(target_sample_width)
                
                # 确保长度一致（通过重新采样）
                if len(processed_audio1) != len(processed_audio2):
                    max_length = max(len(processed_audio1), len(processed_audio2))
                    if len(processed_audio1) < max_length:
                        # 使用安全的方法扩展音频
                        if progress_callback:
                            progress_callback(40, 100, "正在调整音频1参数...")
                        silence = AudioSegment.silent(duration=max_length - len(processed_audio1), 
                                                     frame_rate=target_frame_rate)
                        silence = silence.set_sample_width(target_sample_width)
                        processed_audio1 = processed_audio1 + silence
                    if len(processed_audio2) < max_length:
                        # 使用安全的方法扩展音频
                        if progress_callback:
                            progress_callback(45, 100, "正在调整音频2参数...")
                        silence = AudioSegment.silent(duration=max_length - len(processed_audio2), 
                                                     frame_rate=target_frame_rate)
                        silence = silence.set_sample_width(target_sample_width)
                        processed_audio2 = processed_audio2 + silence
                
                # 更新进度 - 单声道转换完成
                if progress_callback:
                    progress_callback(50, 100, "单声道转换完成，正在合并声道...")
                
                # 使用更高效的方法创建立体声：分块处理
                def manual_stereo_merge_chunked(left_audio, right_audio, left_position, right_position, 
                                              progress_callback=None):
                    # 确保参数一致
                    frame_rate = max(left_audio.frame_rate, right_audio.frame_rate)
                    sample_width = max(left_audio.sample_width, right_audio.sample_width)
                    
                    left_audio = left_audio.set_frame_rate(frame_rate).set_sample_width(sample_width).set_channels(1)
                    right_audio = right_audio.set_frame_rate(frame_rate).set_sample_width(sample_width).set_channels(1)
                    
                    # 获取样本数组（确保获取的是实际的样本值而不是AudioSegment对象）
                    left_samples = left_audio.get_array_of_samples()
                    right_samples = right_audio.get_array_of_samples()
                    
                    # 获取样本（分块处理以避免内存问题）
                    total_samples = min(len(left_samples), len(right_samples))
                    chunk_size = 100000  # 每次处理10万个样本
                    total_chunks = (total_samples // chunk_size) + (1 if total_samples % chunk_size > 0 else 0)
                    
                    stereo_bytes = bytearray()
                    
                    for chunk_idx in range(total_chunks):
                        if progress_callback:
                            progress_percent = 50 + int((chunk_idx / total_chunks) * 40)  # 50%到90%
                            progress_callback(progress_percent, 100, f"正在合并声道... ({chunk_idx+1}/{total_chunks})")
                        
                        start_idx = chunk_idx * chunk_size
                        end_idx = min((chunk_idx + 1) * chunk_size, total_samples)
                        
                        # 获取当前块的样本值（确保是整数）
                        left_chunk = left_samples[start_idx:end_idx]
                        right_chunk = right_samples[start_idx:end_idx]
                        
                        # 确保长度一致
                        min_len = min(len(left_chunk), len(right_chunk))
                        
                        # 根据位置设置声道
                        final_left_samples = [0] * min_len
                        final_right_samples = [0] * min_len
                        
                        # 处理左声道音频
                        if left_position == 'left':
                            for i in range(min_len):
                                final_left_samples[i] += left_chunk[i]
                        elif left_position == 'right':
                            for i in range(min_len):
                                final_right_samples[i] += left_chunk[i]
                        elif left_position == 'center':
                            # 中心声道，降低音量避免过载
                            for i in range(min_len):
                                adjusted_val = left_chunk[i] // 2
                                final_left_samples[i] += adjusted_val
                                final_right_samples[i] += adjusted_val
                        elif left_position == 'adaptive':  # 自适应（原保持原状）
                            # 自适应处理，对于音频1，默认放在左声道
                            for i in range(min_len):
                                final_left_samples[i] += left_chunk[i]
                        else:  # original - 原声，不进行左右声道处理，直接混合
                            # 原声处理，将音频直接混合到两个声道
                            for i in range(min_len):
                                final_left_samples[i] += left_chunk[i]
                                final_right_samples[i] += left_chunk[i]
                        
                        # 处理右声道音频
                        if right_position == 'right':
                            for i in range(min_len):
                                final_right_samples[i] += right_chunk[i]
                        elif right_position == 'left':
                            for i in range(min_len):
                                final_left_samples[i] += right_chunk[i]
                        elif right_position == 'center':
                            # 中心声道，降低音量避免过载
                            for i in range(min_len):
                                adjusted_val = right_chunk[i] // 2
                                final_left_samples[i] += adjusted_val
                                final_right_samples[i] += adjusted_val
                        elif right_position == 'adaptive':  # 自适应（原保持原状）
                            # 自适应处理，对于音频2，默认放在右声道
                            for i in range(min_len):
                                final_right_samples[i] += right_chunk[i]
                        else:  # original - 原声，不进行左右声道处理，直接混合
                            # 原声处理，将音频直接混合到两个声道
                            for i in range(min_len):
                                final_left_samples[i] += right_chunk[i]
                                final_right_samples[i] += right_chunk[i]
                        
                        # 交错合并创建立体声音频
                        for i in range(min_len):
                            # 处理左声道样本
                            left_val = final_left_samples[i]
                            # 处理右声道样本
                            right_val = final_right_samples[i]
                            
                            # 确保left_val和right_val是整数类型
                            if not isinstance(left_val, int):
                                left_val = int(left_val)
                            if not isinstance(right_val, int):
                                right_val = int(right_val)
                            
                            # 根据采样宽度正确处理样本数据
                            if sample_width == 1:  # 8-bit
                                # 确保值在-128到127范围内，然后转换为0-255
                                left_val = max(-128, min(127, left_val))
                                right_val = max(-128, min(127, right_val))
                                stereo_bytes.append(left_val + 128)  # 转换为无符号
                                stereo_bytes.append(right_val + 128)  # 转换为无符号
                            elif sample_width == 2:  # 16-bit
                                # 确保值在-32768到32767范围内
                                left_val = max(-32768, min(32767, left_val))
                                right_val = max(-32768, min(32767, right_val))
                                # 转换为小端序字节
                                stereo_bytes.extend(left_val.to_bytes(2, byteorder='little', signed=True))
                                stereo_bytes.extend(right_val.to_bytes(2, byteorder='little', signed=True))
                            elif sample_width == 4:  # 32-bit
                                # 确保值在-2147483648到2147483647范围内
                                left_val = max(-2147483648, min(2147483647, left_val))
                                right_val = max(-2147483648, min(2147483647, right_val))
                                # 转换为小端序字节
                                stereo_bytes.extend(left_val.to_bytes(4, byteorder='little', signed=True))
                                stereo_bytes.extend(right_val.to_bytes(4, byteorder='little', signed=True))
                            else:
                                # 默认处理（避免byte must be in range(0, 256)错误）
                                try:
                                    stereo_bytes.extend(left_val.to_bytes(sample_width, byteorder='little', signed=True))
                                    stereo_bytes.extend(right_val.to_bytes(sample_width, byteorder='little', signed=True))
                                except OverflowError:
                                    # 如果值超出范围，使用安全的默认值
                                    stereo_bytes.extend((0).to_bytes(sample_width, byteorder='little', signed=True))
                                    stereo_bytes.extend((0).to_bytes(sample_width, byteorder='little', signed=True))
                    
                    return AudioSegment(
                        data=bytes(stereo_bytes),
                        sample_width=sample_width,
                        frame_rate=frame_rate,
                        channels=2
                    )
                
                # 使用分块处理方法创建立体声
                stereo_audio = manual_stereo_merge_chunked(processed_audio1, processed_audio2, audio1_position, audio2_position, progress_callback)
            
            # 更新进度 - 声道合并完成
            if progress_callback:
                progress_callback(95, 100, "声道合并完成，正在导出文件...")
            
            # 导出（分段导出以避免内存问题）
            stereo_audio.export(output_path, format="wav")
            
            print(f"🎉 高级双声道合并完成！")
            print(f"📁 输出文件: {output_path}")
            print(f"📊 最终音频长度: {len(stereo_audio)}ms")
            
            # 更新进度 - 导出完成
            if progress_callback:
                progress_callback(100, 100, "合并完成！")
            
            return True
            
        except Exception as e:
            print(f"❌ 高级双声道合并失败: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _create_stereo_manually(self, left_audio, right_audio):
        """
        手动创建立体声音频，避免参数不一致导致的错误
        
        Args:
            left_audio: 左声道音频（单声道）
            right_audio: 右声道音频（单声道）
            
        Returns:
            立体声音频
        """
        # 确保两个音频参数一致
        target_frame_rate = max(left_audio.frame_rate, right_audio.frame_rate)
        target_sample_width = max(left_audio.sample_width, right_audio.sample_width)
        
        # 统一参数
        left_audio = left_audio.set_frame_rate(target_frame_rate).set_sample_width(target_sample_width).set_channels(1)
        right_audio = right_audio.set_frame_rate(target_frame_rate).set_sample_width(target_sample_width).set_channels(1)
        
        # 确保长度一致
        if len(left_audio) != len(right_audio):
            max_length = max(len(left_audio), len(right_audio))
            if len(left_audio) < max_length:
                silence = AudioSegment.silent(duration=max_length - len(left_audio), 
                                             frame_rate=target_frame_rate)
                silence = silence.set_sample_width(target_sample_width)
                left_audio = left_audio + silence
            if len(right_audio) < max_length:
                silence = AudioSegment.silent(duration=max_length - len(right_audio), 
                                             frame_rate=target_frame_rate)
                silence = silence.set_sample_width(target_sample_width)
                right_audio = right_audio + silence
        
        # 获取样本数组
        left_samples = left_audio.get_array_of_samples()
        right_samples = right_audio.get_array_of_samples()
        
        # 确保长度一致
        min_len = min(len(left_samples), len(right_samples))
        left_samples = left_samples[:min_len]
        right_samples = right_samples[:min_len]
        
        # 手动创建立体声音频
        stereo_bytes = bytearray()
        sample_width = left_audio.sample_width
        
        for i in range(min_len):
            left_val = left_samples[i]
            right_val = right_samples[i]
            
            # 确保left_val和right_val是整数类型
            if not isinstance(left_val, int):
                left_val = int(left_val)
            if not isinstance(right_val, int):
                right_val = int(right_val)
            
            # 根据采样宽度正确处理样本数据
            if sample_width == 1:  # 8-bit
                # 确保值在-128到127范围内，然后转换为0-255
                left_val = max(-128, min(127, left_val))
                right_val = max(-128, min(127, right_val))
                stereo_bytes.append(left_val + 128)  # 转换为无符号
                stereo_bytes.append(right_val + 128)  # 转换为无符号
            elif sample_width == 2:  # 16-bit
                # 确保值在-32768到32767范围内
                left_val = max(-32768, min(32767, left_val))
                right_val = max(-32768, min(32767, right_val))
                # 转换为小端序字节
                stereo_bytes.extend(left_val.to_bytes(2, byteorder='little', signed=True))
                stereo_bytes.extend(right_val.to_bytes(2, byteorder='little', signed=True))
            elif sample_width == 4:  # 32-bit
                # 确保值在-2147483648到2147483647范围内
                left_val = max(-2147483648, min(2147483647, left_val))
                right_val = max(-2147483648, min(2147483647, right_val))
                # 转换为小端序字节
                stereo_bytes.extend(left_val.to_bytes(4, byteorder='little', signed=True))
                stereo_bytes.extend(right_val.to_bytes(4, byteorder='little', signed=True))
            else:
                # 默认处理（避免byte must be in range(0, 256)错误）
                try:
                    stereo_bytes.extend(left_val.to_bytes(sample_width, byteorder='little', signed=True))
                    stereo_bytes.extend(right_val.to_bytes(sample_width, byteorder='little', signed=True))
                except OverflowError:
                    # 如果值超出范围，使用安全的默认值
                    stereo_bytes.extend((0).to_bytes(sample_width, byteorder='little', signed=True))
                    stereo_bytes.extend((0).to_bytes(sample_width, byteorder='little', signed=True))
        
        return AudioSegment(
            data=bytes(stereo_bytes),
            sample_width=sample_width,
            frame_rate=target_frame_rate,
            channels=2
        )

    def process_complete_workflow(self, lrc_file_path: str, original_audio_path: str = None, 
                                output_dir: str = "output", progress_callback=None) -> Dict:
        """
        完整的处理流程
        
        Args:
            lrc_file_path: LRC文件路径
            original_audio_path: 原音频文件路径（可选）
            output_dir: 输出目录
            progress_callback: 进度回调函数
            
        Returns:
            处理结果信息
        """
        start_time = time.time()
        results = {
            'success': False,
            'segments_generated': 0,
            'segments_total': 0,
            'generated_audio': None,
            'final_audio': None,
            'processing_time': 0,
            'failed_count': 0,
            'failed_details': []
        }
        
        try:
            print("🚀 开始完整处理流程...")
            
            # 1. 测试API连接
            if not self.test_api_connection():
                raise Exception("无法连接到TTS API服务器")
            print("✅ API连接正常")
            
            # 2. 创建输出目录
            segments_dir = os.path.join(output_dir, "segments")
            os.makedirs(segments_dir, exist_ok=True)
            os.makedirs(output_dir, exist_ok=True)
            
            # 3. 生成语音片段（传递进度回调函数）
            segment_results = self.process_lrc_to_speech_segments(lrc_file_path, segments_dir, progress_callback)
            segments = segment_results['successful_segments']
            results['segments_generated'] = len(segments)
            results['failed_count'] = segment_results['failed_count']
            results['failed_details'] = segment_results['failed_details']
            
            # 解析LRC文件获取总数
            lyrics = self.parse_lrc_file(lrc_file_path)
            results['segments_total'] = len(lyrics)
            
            # 检查是否所有片段都已处理
            success_rate = results['segments_generated'] / results['segments_total'] if results['segments_total'] > 0 else 0
            print(f"📊 片段生成成功率: {success_rate:.2%} ({results['segments_generated']}/{results['segments_total']})")
            
            if results['segments_generated'] == 0:
                raise Exception("没有成功生成任何语音片段")
            elif results['segments_generated'] < results['segments_total']:
                print(f"⚠️  注意：只生成了 {results['segments_generated']}/{results['segments_total']} 个片段")
                print("将继续处理已生成的片段...")
            
            # 4. 拼接音频
            generated_audio_path = os.path.join(output_dir, "generated_speech.wav")
            print(f"🎼 开始拼接音频到: {generated_audio_path}")
            if not self.concatenate_audio_with_timing(segments, generated_audio_path):
                raise Exception("音频拼接失败")
            
            results['generated_audio'] = generated_audio_path
            
            # 5. 双声道合并（如果提供了原音频）
            if original_audio_path and os.path.exists(original_audio_path):
                final_audio_path = os.path.join(output_dir, "final_mixed_audio.wav")
                print(f"🎧 开始双声道合并到: {final_audio_path}")
                if self.merge_with_original_audio(generated_audio_path, original_audio_path, final_audio_path):
                    results['final_audio'] = final_audio_path
                else:
                    print("⚠️ 双声道合并失败，但生成的音频可用")
            
            results['success'] = True
            
        except Exception as e:
            print(f"❌ 处理失败: {e}")
            results['error'] = str(e)
        
        finally:
            results['processing_time'] = time.time() - start_time
            print(f"\n⏱️ 总处理时间: {results['processing_time']:.2f}秒")
        
        return results

def main():
    """主函数 - 命令行测试"""
    print("🎵 LRC音声处理器")
    print("=" * 50)
    
    # 创建处理器
    processor = LrcTtsProcessor()
    
    # 测试LRC文件
    lrc_file = "test.lrc"
    if not os.path.exists(lrc_file):
        print(f"❌ LRC文件不存在: {lrc_file}")
        return
    
    # 执行完整流程
    results = processor.process_complete_workflow(
        lrc_file_path=lrc_file,
        original_audio_path=None,  # 暂时不提供原音频
        output_dir="complete_output"
    )
    
    # 显示结果
    print("\n" + "=" * 50)
    print("📊 处理结果")
    print("=" * 50)
    print(f"✅ 处理成功: {'是' if results['success'] else '否'}")
    print(f"🎵 片段生成: {results['segments_generated']}/{results['segments_total']}")
    print(f"⏱️ 处理时间: {results['processing_time']:.2f}秒")
    
    if results.get('generated_audio'):
        print(f"🎧 生成音频: {results['generated_audio']}")
    
    if results.get('final_audio'):
        print(f"🎯 最终音频: {results['final_audio']}")
    
    if results.get('error'):
        print(f"❌ 错误信息: {results['error']}")

if __name__ == "__main__":
    main()