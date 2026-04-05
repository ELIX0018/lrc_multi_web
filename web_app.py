#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LRC音声处理器Web界面
基于Flask的简单Web界面，用于上传LRC文件和下载处理结果
"""

from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for, flash
import os
import uuid
import threading
import time
from werkzeug.utils import secure_filename
from lrc_tts_processor import LrcTtsProcessor
import hashlib
import datetime

app = Flask(__name__)
app.secret_key = 'lrc_tts_processor_secret_key'
# 增加文件大小限制到100MB
app.config['MAX_CONTENT_LENGTH'] = 5000 * 1024 * 1024  # 100MB max file size

# 添加额外的配置来处理大文件
app.config['MAX_FORM_MEMORY_SIZE'] = 5000 * 1024 * 1024  # 100MB

# 添加自定义过滤器用于格式化时间戳
@app.template_filter('ctime')
def convert_timestamp(timestamp):
    """将时间戳转换为可读的日期时间格式"""
    try:
        return datetime.datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')
    except:
        return '未知时间'

# 配置目录
UPLOAD_FOLDER = 'uploads'
OUTPUT_FOLDER = 'web_outputs'
ALLOWED_EXTENSIONS = {'lrc', 'vtt', 'wav', 'mp3', 'flac'}

# 确保目录存在
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# 全局任务状态存储
processing_tasks = {}

# 双声道合并任务存储
stereo_merge_tasks = {}

def allowed_file(filename):
    """检查文件扩展名是否允许"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/stereo_merge', methods=['GET', 'POST'])
def stereo_merge():
    """双声道合并功能"""
    if request.method == 'POST':
        try:
            # 检查文件大小限制
            content_length = request.content_length
            if content_length and content_length > app.config['MAX_CONTENT_LENGTH']:
                flash(f'文件太大，超过限制大小 {app.config["MAX_CONTENT_LENGTH"] / (1024*1024):.0f}MB')
                return redirect(request.url)
            
            # 检查文件
            if 'audio1' not in request.files or 'audio2' not in request.files:
                flash('请选择两个音频文件')
                return redirect(request.url)
            
            audio1_file = request.files['audio1']
            audio2_file = request.files['audio2']
            
            if audio1_file.filename == '' or audio2_file.filename == '':
                flash('请选择两个音频文件')
                return redirect(request.url)
            
            if not allowed_file(audio1_file.filename) or not allowed_file(audio2_file.filename):
                flash('音频文件格式不支持')
                return redirect(request.url)
            
            # 获取参数
            audio1_position = request.form.get('audio1_position', 'left')
            audio2_position = request.form.get('audio2_position', 'right')
            audio1_volume = float(request.form.get('audio1_volume', 1.0))
            audio2_volume = float(request.form.get('audio2_volume', 1.0))
            
            # 保存文件
            audio1_filename = secure_filename(audio1_file.filename)
            audio2_filename = secure_filename(audio2_file.filename)
            
            # 生成唯一的任务ID
            task_id = str(uuid.uuid4())
            
            # 创建任务目录
            task_dir = os.path.join(OUTPUT_FOLDER, f"stereo_merge_{task_id}")
            os.makedirs(task_dir, exist_ok=True)
            
            # 保存音频文件
            audio1_path = os.path.join(task_dir, f"audio1_{audio1_filename}")
            audio2_path = os.path.join(task_dir, f"audio2_{audio2_filename}")
            output_path = os.path.join(task_dir, "merged_output.wav")
            
            audio1_file.save(audio1_path)
            audio2_file.save(audio2_path)
            
            # 初始化任务状态
            stereo_merge_tasks[task_id] = {
                'status': 'processing',
                'progress': '开始处理...',
                'created_time': time.time(),
                'audio1_path': audio1_path,
                'audio2_path': audio2_path,
                'audio1_position': audio1_position,
                'audio2_position': audio2_position,
                'audio1_volume': audio1_volume,
                'audio2_volume': audio2_volume,
                'output_path': output_path
            }
            
            # 启动后台处理
            thread = threading.Thread(
                target=process_stereo_merge,
                args=(task_id,)
            )
            thread.daemon = True
            thread.start()
            
            flash(f'双声道合并任务已创建！任务ID: {task_id}')
            return redirect(url_for('stereo_merge_status', task_id=task_id))
            
        except Exception as e:
            import traceback
            error_msg = str(e)
            print(f"处理失败: {error_msg}")
            print(traceback.format_exc())
            flash(f'处理失败: {error_msg}')
            return redirect(request.url)
    
    return render_template('stereo_merge.html')

@app.route('/stereo_merge_status/<task_id>')
def stereo_merge_status(task_id):
    """双声道合并任务状态页面"""
    if task_id not in stereo_merge_tasks:
        flash('任务不存在')
        return redirect(url_for('stereo_merge'))
    
    task = stereo_merge_tasks[task_id]
    return render_template('stereo_merge_status.html', task_id=task_id, task=task)

@app.route('/api/stereo_merge/<task_id>/status')
def api_stereo_merge_status(task_id):
    """API: 获取双声道合并任务状态"""
    if task_id not in stereo_merge_tasks:
        return jsonify({'error': '任务不存在'}), 404
    
    task = stereo_merge_tasks[task_id]
    return jsonify(task)

@app.route('/download_stereo/<task_id>')
def download_stereo_result(task_id):
    """下载双声道合并结果"""
    if task_id not in stereo_merge_tasks:
        flash('任务不存在')
        return redirect(url_for('stereo_merge'))
    
    task = stereo_merge_tasks[task_id]
    if task['status'] != 'completed':
        flash('任务尚未完成')
        return redirect(url_for('stereo_merge_status', task_id=task_id))
    
    try:
        output_path = task.get('output_path')
        if os.path.exists(output_path):
            return send_file(output_path, as_attachment=True, download_name="merged_audio.wav")
        else:
            flash('文件不存在')
            return redirect(url_for('stereo_merge_status', task_id=task_id))
    except Exception as e:
        flash(f'下载失败: {str(e)}')
        return redirect(url_for('stereo_merge_status', task_id=task_id))

def process_stereo_merge(task_id):
    """后台处理双声道合并"""
    try:
        task = stereo_merge_tasks[task_id]
        task['progress'] = '正在处理...'
        task['progress_percent'] = 0
        
        # 创建处理器
        processor = LrcTtsProcessor()
        
        # 定义进度回调函数
        def progress_callback(current, total, message):
            progress_percent = int((current / total) * 100) if total > 0 else 0
            task['progress'] = message
            task['current'] = current
            task['total'] = total
            task['progress_percent'] = progress_percent
            print(f"双声道合并进度: {progress_percent}% - {message}")
        
        # 执行高级双声道合并
        success = processor.advanced_stereo_merge(
            audio1_path=task['audio1_path'],
            audio2_path=task['audio2_path'],
            audio1_position=task['audio1_position'],
            audio2_position=task['audio2_position'],
            audio1_volume=task['audio1_volume'],
            audio2_volume=task['audio2_volume'],
            output_path=task['output_path'],
            progress_callback=progress_callback
        )
        
        # 更新任务状态
        if success:
            task['status'] = 'completed'
            task['progress'] = '处理完成！'
            task['progress_percent'] = 100
        else:
            task['status'] = 'failed'
            task['progress'] = '处理失败'
            task['error'] = '合并失败'
    
    except Exception as e:
        task['status'] = 'failed'
        task['progress'] = f'处理失败: {str(e)}'
        task['error'] = str(e)

@app.route('/upload', methods=['POST'])
def upload_files():
    """处理文件上传"""
    try:
        # 检查文件大小限制
        content_length = request.content_length
        if content_length and content_length > app.config['MAX_CONTENT_LENGTH']:
            flash(f'文件太大，超过限制大小 {app.config["MAX_CONTENT_LENGTH"] / (1024*1024):.0f}MB')
            return redirect(url_for('index'))
        
        # 检查LRC文件
        if 'lrc_file' not in request.files:
            flash('请选择LRC或VTT文件')
            return redirect(url_for('index'))
        
        lrc_file = request.files['lrc_file']
        if lrc_file.filename == '':
            flash('请选择LRC或VTT文件')
            return redirect(url_for('index'))
        
        if not allowed_file(lrc_file.filename):
            flash('LRC或VTT文件格式不支持')
            return redirect(url_for('index'))
        
        # 获取API地址、模型名称和速度因子
        api_url = request.form.get('api_url', 'http://127.0.0.1:8000').strip()
        model_name = request.form.get('model_name', '原神-中文-宵宫_ZH').strip()
        speed_factor = request.form.get('speed_factor', '1.0').strip()
        
        # 验证速度因子
        try:
            speed_factor = float(speed_factor)
            if speed_factor < 0.0 or speed_factor > 2.0:
                speed_factor = 1.0  # 如果超出范围，使用默认值
        except ValueError:
            speed_factor = 1.0  # 如果转换失败，使用默认值
            
        if not api_url:
            api_url = 'http://127.0.0.1:8000'
        
        # 保存LRC文件并计算MD5
        lrc_filename = secure_filename(lrc_file.filename)
        # 读取文件内容计算MD5
        lrc_content = lrc_file.read()
        lrc_md5 = hashlib.md5(lrc_content).hexdigest()
        
        # 重置文件指针
        lrc_file.seek(0)
        
        # 使用MD5命名保存文件
        lrc_path = os.path.join(UPLOAD_FOLDER, f"{lrc_md5}_{lrc_filename}")
        lrc_file.save(lrc_path)
        
        # 生成任务ID
        task_id = str(uuid.uuid4())
        
        # 创建该LRC文件专用的输出目录
        lrc_output_dir = os.path.join(OUTPUT_FOLDER, lrc_md5)
        os.makedirs(lrc_output_dir, exist_ok=True)
        
        # 检查是否已有相同的LRC文件处理记录（基于MD5）
        existing_task_id = None
        existing_task = None
        for existing_id, task_info in processing_tasks.items():
            # 检查是否已完成且LRC文件MD5相同
            if (task_info.get('status') == 'completed' and 
                task_info.get('lrc_md5') == lrc_md5):
                existing_task_id = existing_id
                existing_task = task_info
                break
        
        # 处理原音频文件（可选）
        original_audio_path = None
        if 'original_audio' in request.files:
            original_audio = request.files['original_audio']
            if original_audio.filename != '' and allowed_file(original_audio.filename):
                audio_filename = secure_filename(original_audio.filename)
                original_audio_path = os.path.join(UPLOAD_FOLDER, f"{task_id}_{audio_filename}")
                original_audio.save(original_audio_path)
        
        # 初始化任务状态
        processing_tasks[task_id] = {
            'status': 'queued',
            'progress': '任务已创建，等待处理...',
            'created_time': time.time(),
            'api_url': api_url,
            'model_name': model_name,  # 添加模型名称
            'speed_factor': speed_factor,  # 添加速度因子
            'current_segment': 0,
            'total_segments': 0,
            'lrc_filename': lrc_filename,  # 原始文件名
            'lrc_md5': lrc_md5,  # 文件MD5值
            'lrc_output_dir': lrc_output_dir,  # 该LRC专用输出目录
            'original_audio_path': original_audio_path
        }
        
        # 如果有已完成的相同任务，重定向到选择页面
        if existing_task_id and existing_task:
            # 保存当前任务信息，但标记为待确认状态
            processing_tasks[task_id]['status'] = 'pending_confirmation'
            processing_tasks[task_id]['existing_task_id'] = existing_task_id
            processing_tasks[task_id]['progress'] = '检测到已完成的相同任务，等待用户选择...'
            flash(f'检测到已完成的相同LRC文件处理记录')
            return redirect(url_for('task_confirmation', task_id=task_id, existing_task_id=existing_task_id))
        
        # 启动后台处理
        thread = threading.Thread(
            target=process_lrc_background,
            args=(task_id, lrc_path, original_audio_path, api_url, lrc_output_dir, model_name, speed_factor)
        )
        thread.daemon = True
        thread.start()
        
        flash(f'文件上传成功！任务ID: {task_id}')
        return redirect(url_for('task_status', task_id=task_id))
    
    except Exception as e:
        import traceback
        error_msg = str(e)
        print(f"上传失败: {error_msg}")
        print(traceback.format_exc())
        flash(f'上传失败: {error_msg}')
        return redirect(url_for('index'))

@app.route('/task_confirmation/<task_id>/<existing_task_id>')
def task_confirmation(task_id, existing_task_id):
    """任务确认页面 - 断点续传选择"""
    if task_id not in processing_tasks or existing_task_id not in processing_tasks:
        flash('任务不存在')
        return redirect(url_for('index'))
    
    task = processing_tasks[task_id]
    existing_task = processing_tasks[existing_task_id]
    
    return render_template('task_confirmation.html', 
                         task_id=task_id, 
                         existing_task_id=existing_task_id,
                         task=task,
                         existing_task=existing_task)

@app.route('/task_action/<task_id>', methods=['POST'])
def task_action(task_id):
    """处理用户选择的操作"""
    if task_id not in processing_tasks:
        flash('任务不存在')
        return redirect(url_for('index'))
    
    task = processing_tasks[task_id]
    
    # 获取用户选择的操作
    action = request.form.get('action')
    existing_task_id = request.form.get('existing_task_id')
    
    if action == 'preview':
        # 直接预览已完成的任务
        return redirect(url_for('task_status', task_id=existing_task_id))
    elif action == 'regenerate':
        # 重新生成，删除旧的输出文件
        # 删除与该LRC文件相关的输出目录
        lrc_md5 = task.get('lrc_md5', '')
        if lrc_md5:
            output_dir = os.path.join(OUTPUT_FOLDER, lrc_md5)
            if os.path.exists(output_dir):
                try:
                    import shutil
                    shutil.rmtree(output_dir)
                    print(f"已删除旧的输出目录: {output_dir}")
                except Exception as e:
                    print(f"删除旧输出目录失败: {e}")
            
            # 重新创建目录
            os.makedirs(output_dir, exist_ok=True)
            segments_dir = os.path.join(output_dir, "segments")
            os.makedirs(segments_dir, exist_ok=True)
        
        # 启动新任务
        task['status'] = 'queued'
        task['progress'] = '任务已创建，等待处理...'
        
        # 启动后台处理
        lrc_filename = task.get('lrc_filename', '')
        lrc_path = os.path.join(UPLOAD_FOLDER, f"{lrc_md5}_{lrc_filename}")
        original_audio_path = task.get('original_audio_path')
        api_url = task.get('api_url', 'http://127.0.0.1:8000')
        lrc_output_dir = os.path.join(OUTPUT_FOLDER, lrc_md5)
        model_name = task.get('model_name', '原神-中文-宵宫_ZH')  # 获取模型名称
        speed_factor = task.get('speed_factor', 1.0)  # 获取速度因子
        
        thread = threading.Thread(
            target=process_lrc_background,
            args=(task_id, lrc_path, original_audio_path, api_url, lrc_output_dir, model_name, speed_factor)
        )
        thread.daemon = True
        thread.start()
        
        flash('开始重新生成任务')
        return redirect(url_for('task_status', task_id=task_id))
    elif action == 'continue':
        # 继续生成（断点续传）
        task['status'] = 'queued'
        task['progress'] = '任务已创建，等待处理...'
        
        # 启动后台处理
        lrc_filename = task.get('lrc_filename', '')
        lrc_md5 = task.get('lrc_md5', '')
        lrc_path = os.path.join(UPLOAD_FOLDER, f"{lrc_md5}_{lrc_filename}")
        original_audio_path = task.get('original_audio_path')
        api_url = task.get('api_url', 'http://127.0.0.1:8000')
        lrc_output_dir = task.get('lrc_output_dir', os.path.join(OUTPUT_FOLDER, lrc_md5))
        model_name = task.get('model_name', '原神-中文-宵宫_ZH')  # 获取模型名称
        speed_factor = task.get('speed_factor', 1.0)  # 获取速度因子
        
        thread = threading.Thread(
            target=process_lrc_background,
            args=(task_id, lrc_path, original_audio_path, api_url, lrc_output_dir, model_name, speed_factor)
        )
        thread.daemon = True
        thread.start()
        
        flash('开始继续生成任务')
        return redirect(url_for('task_status', task_id=task_id))
    
    flash('无效的操作')
    return redirect(url_for('index'))

@app.route('/task/<task_id>')
def task_status(task_id):
    """任务状态页面"""
    if task_id not in processing_tasks:
        flash('任务不存在')
        return redirect(url_for('index'))
    
    task = processing_tasks[task_id]
    return render_template('task_status.html', task_id=task_id, task=task)

@app.route('/api/task/<task_id>/status')
def api_task_status(task_id):
    """API: 获取任务状态"""
    if task_id not in processing_tasks:
        return jsonify({'error': '任务不存在'}), 404
    
    task = processing_tasks[task_id]
    return jsonify(task)

@app.route('/download/<task_id>/<filename>')
def download_file(task_id, filename):
    """下载处理结果文件"""
    if task_id not in processing_tasks:
        flash('任务不存在')
        return redirect(url_for('index'))
    
    task = processing_tasks[task_id]
    if task['status'] != 'completed':
        flash('任务尚未完成')
        return redirect(url_for('task_status', task_id=task_id))
    
    try:
        # 修复文件路径问题
        file_path = os.path.join(task.get('output_dir', ''), filename)
        if os.path.exists(file_path):
            return send_file(file_path, as_attachment=True)
        else:
            flash(f'文件不存在: {filename}')
            return redirect(url_for('task_status', task_id=task_id))
    except Exception as e:
        flash(f'下载失败: {str(e)}')
        return redirect(url_for('task_status', task_id=task_id))

@app.route('/play/<task_id>/<filename>')
def play_audio(task_id, filename):
    """在线播放音频文件"""
    if task_id not in processing_tasks:
        return jsonify({'error': '任务不存在'}), 404
    
    task = processing_tasks[task_id]
    if task['status'] != 'completed':
        return jsonify({'error': '任务尚未完成'}), 400
    
    try:
        file_path = os.path.join(task.get('output_dir', ''), filename)
        if os.path.exists(file_path):
            return send_file(file_path, mimetype='audio/wav')
        else:
            return jsonify({'error': '文件不存在'}), 404
    except Exception as e:
        return jsonify({'error': f'播放失败: {str(e)}'}), 500

@app.route('/api/test_connection')
def test_api_connection():
    """测试TTS API连接"""
    api_url = request.args.get('url', 'http://127.0.0.1:8000')
    try:
        processor = LrcTtsProcessor(api_base_url=api_url)
        connected = processor.test_api_connection()
        return jsonify({
            'connected': connected,
            'message': 'API连接正常' if connected else 'API连接失败',
            'url': api_url
        })
    except Exception as e:
        return jsonify({
            'connected': False,
            'message': f'连接测试失败: {str(e)}',
            'url': api_url
        })

@app.route('/api/models')
def get_models():
    """获取模型列表"""
    api_url = request.args.get('url', 'http://127.0.0.1:8000')
    try:
        processor = LrcTtsProcessor(api_base_url=api_url)
        # 测试API连接
        if not processor.test_api_connection():
            return jsonify({'error': '无法连接到API服务器'}), 500
        
        # 获取模型列表
        response = processor.session.post(f"{api_url}/models", json={"version": "v4"})
        
        if response.status_code == 200:
            models_data = response.json()
            return jsonify(models_data)
        else:
            return jsonify({'error': f'获取模型列表失败，状态码: {response.status_code}'}), response.status_code
    except Exception as e:
        return jsonify({'error': f'获取模型列表失败: {str(e)}'}), 500

@app.route('/api/classic_models')
def get_classic_models():
    """获取经典模型列表"""
    api_url = request.args.get('url', 'http://127.0.0.1:8000')
    try:
        processor = LrcTtsProcessor(api_base_url=api_url)
        # 测试API连接
        if not processor.test_api_connection():
            return jsonify({'error': '无法连接到API服务器'}), 500
        
        # 获取经典模型列表
        response = processor.session.post(f"{api_url}/classic_model_list", json={"version": "v4"})
        
        if response.status_code == 200:
            models_data = response.json()
            return jsonify(models_data)
        else:
            return jsonify({'error': f'获取经典模型列表失败，状态码: {response.status_code}'}), response.status_code
    except Exception as e:
        return jsonify({'error': f'获取经典模型列表失败: {str(e)}'}), 500

def process_lrc_background(task_id, lrc_file_path, original_audio_path=None, api_url="http://127.0.0.1:8000", lrc_output_dir=None, model_name="原神-中文-宵宫_ZH", speed_factor=1.0):
    """后台处理LRC文件"""
    try:
        processing_tasks[task_id]['status'] = 'processing'
        processing_tasks[task_id]['progress'] = '开始处理...'
        processing_tasks[task_id]['current_segment'] = 0
        processing_tasks[task_id]['total_segments'] = 0
        processing_tasks[task_id]['current_sentence'] = ''  # 添加当前句子信息
        
        # 创建处理器，使用用户指定的API地址、模型名称和速度因子
        processor = LrcTtsProcessor(api_base_url=api_url, model_name=model_name, speed_factor=speed_factor)
        
        # 首先解析LRC文件获取总数
        lyrics = processor.parse_lrc_file(lrc_file_path)
        total_segments = len(lyrics)
        processing_tasks[task_id]['total_segments'] = total_segments
        
        print(f"📝 任务 {task_id} 开始处理，总共 {total_segments} 个片段 (速度因子: {speed_factor})")
        
        # 使用传入的LRC专用输出目录
        task_output_dir = lrc_output_dir if lrc_output_dir else os.path.join(OUTPUT_FOLDER, task_id)
        segments_dir = os.path.join(task_output_dir, "segments")
        os.makedirs(segments_dir, exist_ok=True)
        
        # 更新进度
        processing_tasks[task_id]['progress'] = f'正在生成语音片段... (0/{total_segments})'
        
        # 执行处理，传入进度回调
        def progress_callback(current, total, message):
            processing_tasks[task_id]['current_segment'] = current
            processing_tasks[task_id]['total_segments'] = total
            processing_tasks[task_id]['progress'] = f'{message} ({current}/{total})'
            # 添加当前处理的句子信息
            processing_tasks[task_id]['current_sentence'] = message
            print(f"📊 任务 {task_id} 进度更新: {message} ({current}/{total})")  # 调试信息
        
        results = processor.process_complete_workflow(
            lrc_file_path=lrc_file_path,
            original_audio_path=original_audio_path,
            output_dir=task_output_dir,
            progress_callback=progress_callback
        )
        
        # 更新任务状态
        if results['success']:
            processing_tasks[task_id]['status'] = 'completed'
            processing_tasks[task_id]['progress'] = '处理完成！'
            processing_tasks[task_id]['results'] = results
            processing_tasks[task_id]['output_dir'] = task_output_dir
            print(f"✅ 任务 {task_id} 处理完成！成功生成 {results['segments_generated']}/{results['segments_total']} 个片段")
            # 添加失败信息到任务状态中
            if results.get('failed_count', 0) > 0:
                print(f"⚠️  任务 {task_id} 有 {results['failed_count']} 个片段生成失败")
        else:
            processing_tasks[task_id]['status'] = 'failed'
            processing_tasks[task_id]['progress'] = f'处理失败: {results.get("error", "未知错误")}'
            processing_tasks[task_id]['error'] = results.get('error', '未知错误')
            print(f"❌ 任务 {task_id} 处理失败: {results.get('error', '未知错误')}")
    
    except Exception as e:
        processing_tasks[task_id]['status'] = 'failed'
        processing_tasks[task_id]['progress'] = f'处理失败: {str(e)}'
        processing_tasks[task_id]['error'] = str(e)
        print(f"❌ 任务 {task_id} 处理过程中发生异常: {str(e)}")
        import traceback
        traceback.print_exc()

@app.route('/')
def index():
    """主页"""
    return render_template('index.html')

@app.route('/current_tasks')
def current_tasks():
    """查看当前任务页面"""
    # 获取正在进行的LRC处理任务
    active_processing_tasks = {
        task_id: task for task_id, task in processing_tasks.items() 
        if task['status'] in ['queued', 'processing']
    }
    
    # 获取正在进行的双声道合并任务
    active_stereo_tasks = {
        task_id: task for task_id, task in stereo_merge_tasks.items() 
        if task['status'] in ['processing']
    }
    
    return render_template('current_tasks.html', 
                         processing_tasks=active_processing_tasks,
                         stereo_tasks=active_stereo_tasks)

if __name__ == '__main__':
    print("🌐 启动LRC音声处理器Web界面...")
    print("📡 访问地址: http://localhost:5001")
    print("⚠️ 请确保TTS API服务器运行在 http://127.0.0.1:8000")
    app.run(debug=True, host='0.0.0.0', port=5001)