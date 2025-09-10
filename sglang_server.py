#!/usr/bin/env python3
"""
SGLang服务器启动脚本
用于启动Qwen模型服务
"""

import os
import sys
import subprocess
import argparse
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def start_sglang_server(
    model_path: str = "/app/models/Qwen2.5-0.5B-Instruct",
    host: str = "0.0.0.0",
    port: int = 30000,
    trust_remote_code: bool = True,
    gpu_memory_utilization: float = 0.8,
    max_model_len: int = 4096,
    enable_prefix_caching: bool = True
):
    """
    启动SGLang服务器
    """
    try:
        # 构建启动命令
        cmd = [
            sys.executable, "-m", "sglang.launch_server",
            "--model-path", model_path,
            "--host", host,
            "--port", str(port),
            "--gpu-memory-utilization", str(gpu_memory_utilization),
            "--max-model-len", str(max_model_len),
        ]
        
        if trust_remote_code:
            cmd.append("--trust-remote-code")
        
        if enable_prefix_caching:
            cmd.append("--enable-prefix-caching")
        
        logger.info(f"启动SGLang服务器: {' '.join(cmd)}")
        
        # 启动服务器
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        
        # 实时输出日志
        for line in process.stdout:
            print(line.rstrip())
            if "Uvicorn running on" in line:
                logger.info("SGLang服务器启动成功")
                break
        
        # 等待进程结束
        process.wait()
        
    except KeyboardInterrupt:
        logger.info("收到中断信号，正在停止服务器...")
        if 'process' in locals():
            process.terminate()
    except Exception as e:
        logger.error(f"启动SGLang服务器失败: {e}")
        sys.exit(1)


def check_gpu():
    """检查GPU可用性"""
    try:
        import torch
        if torch.cuda.is_available():
            gpu_count = torch.cuda.device_count()
            logger.info(f"检测到 {gpu_count} 个GPU")
            for i in range(gpu_count):
                gpu_name = torch.cuda.get_device_name(i)
                logger.info(f"GPU {i}: {gpu_name}")
            return True
        else:
            logger.warning("未检测到GPU，将使用CPU运行")
            return False
    except ImportError:
        logger.warning("PyTorch未安装，无法检测GPU")
        return False


def main():
    parser = argparse.ArgumentParser(description='SGLang服务器启动脚本')
    parser.add_argument('--model-path', default='/app/models/Qwen2.5-0.5B-Instruct', help='模型路径')
    parser.add_argument('--host', default='0.0.0.0', help='服务器主机')
    parser.add_argument('--port', type=int, default=30000, help='服务器端口')
    parser.add_argument('--gpu-memory-utilization', type=float, default=0.8, help='GPU内存使用率')
    parser.add_argument('--max-model-len', type=int, default=4096, help='最大模型长度')
    parser.add_argument('--no-trust-remote-code', action='store_true', help='不信任远程代码')
    parser.add_argument('--no-prefix-caching', action='store_true', help='禁用前缀缓存')
    
    args = parser.parse_args()
    
    # 检查GPU
    check_gpu()
    
    # 启动服务器
    start_sglang_server(
        model_path=args.model_path,
        host=args.host,
        port=args.port,
        trust_remote_code=not args.no_trust_remote_code,
        gpu_memory_utilization=args.gpu_memory_utilization,
        max_model_len=args.max_model_len,
        enable_prefix_caching=not args.no_prefix_caching
    )


if __name__ == "__main__":
    main()
