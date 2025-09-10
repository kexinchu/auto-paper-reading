"""
邮件发送模块
负责发送论文摘要邮件
"""

import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from typing import List, Dict, Optional
import logging
from datetime import datetime
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class EmailSender:
    def __init__(self, email_config: Dict):
        self.smtp_server = email_config.get('smtp_server', 'smtp.gmail.com')
        self.smtp_port = email_config.get('smtp_port', 587)
        self.sender_email = email_config.get('sender_email')
        self.sender_password = email_config.get('sender_password')
        self.recipient_email = email_config.get('recipient_email')
        
        if not all([self.sender_email, self.sender_password, self.recipient_email]):
            raise ValueError("邮件配置不完整，请检查config.yaml中的email配置")
    
    def send_paper_summary(self, extracted_contents: List[Dict], subject_prefix: str = "每日论文摘要") -> bool:
        """
        发送论文摘要邮件
        """
        try:
            # 创建邮件内容
            subject = f"{subject_prefix} - {datetime.now().strftime('%Y年%m月%d日')}"
            body = self._format_email_body(extracted_contents)
            
            # 创建邮件
            message = MIMEMultipart()
            message["From"] = self.sender_email
            message["To"] = self.recipient_email
            message["Subject"] = subject
            
            # 添加正文
            message.attach(MIMEText(body, "html", "utf-8"))
            
            # 发送邮件
            return self._send_email(message)
            
        except Exception as e:
            logger.error(f"发送邮件失败: {e}")
            return False
    
    def send_with_attachments(self, extracted_contents: List[Dict], pdf_paths: List[str] = None) -> bool:
        """
        发送带PDF附件的邮件
        """
        try:
            subject = f"每日论文摘要 - {datetime.now().strftime('%Y年%m月%d日')}"
            body = self._format_email_body(extracted_contents)
            
            # 创建邮件
            message = MIMEMultipart()
            message["From"] = self.sender_email
            message["To"] = self.recipient_email
            message["Subject"] = subject
            
            # 添加正文
            message.attach(MIMEText(body, "html", "utf-8"))
            
            # 添加PDF附件
            if pdf_paths:
                for pdf_path in pdf_paths:
                    if os.path.exists(pdf_path):
                        self._attach_file(message, pdf_path)
            
            # 发送邮件
            return self._send_email(message)
            
        except Exception as e:
            logger.error(f"发送带附件邮件失败: {e}")
            return False
    
    def _format_email_body(self, extracted_contents: List[Dict]) -> str:
        """
        格式化邮件正文
        """
        if not extracted_contents:
            return """
            <html>
            <body>
                <h2>今日论文摘要</h2>
                <p>今天没有找到相关的论文。</p>
                <p>请检查关键词配置或arXiv数据源。</p>
            </body>
            </html>
            """
        
        html_body = f"""
        <html>
        <body>
            <h2>今日论文摘要 ({datetime.now().strftime('%Y年%m月%d日')})</h2>
            <p>共找到 <strong>{len(extracted_contents)}</strong> 篇相关论文：</p>
        """
        
        for i, content in enumerate(extracted_contents, 1):
            html_body += f"""
            <div style="margin-bottom: 30px; padding: 15px; border-left: 4px solid #007acc; background-color: #f8f9fa;">
                <h3>{i}. {content['title']}</h3>
                <p><strong>作者</strong>: {content['authors']}</p>
                <div style="background-color: white; padding: 10px; border-radius: 5px; margin-top: 10px;">
                    <h4>核心内容:</h4>
                    <div style="white-space: pre-line;">{content['extracted_content']}</div>
                </div>
            </div>
            """
        
        html_body += """
            <hr>
            <p style="color: #666; font-size: 12px;">
                此邮件由自动论文阅读工具生成<br>
                生成时间: """ + datetime.now().strftime('%Y-%m-%d %H:%M:%S') + """
            </p>
        </body>
        </html>
        """
        
        return html_body
    
    def _attach_file(self, message: MIMEMultipart, file_path: str):
        """
        添加文件附件
        """
        try:
            with open(file_path, "rb") as attachment:
                part = MIMEBase('application', 'octet-stream')
                part.set_payload(attachment.read())
            
            encoders.encode_base64(part)
            
            filename = os.path.basename(file_path)
            part.add_header(
                'Content-Disposition',
                f'attachment; filename= {filename}'
            )
            
            message.attach(part)
            logger.info(f"添加附件: {filename}")
            
        except Exception as e:
            logger.error(f"添加附件失败 {file_path}: {e}")
    
    def _send_email(self, message: MIMEMultipart) -> bool:
        """
        发送邮件
        """
        try:
            # 创建SSL上下文
            context = ssl.create_default_context()
            
            # 连接SMTP服务器
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls(context=context)
                server.login(self.sender_email, self.sender_password)
                
                # 发送邮件
                text = message.as_string()
                server.sendmail(self.sender_email, self.recipient_email, text)
                
            logger.info("邮件发送成功")
            return True
            
        except Exception as e:
            logger.error(f"发送邮件失败: {e}")
            return False
    
    def test_connection(self) -> bool:
        """
        测试邮件连接
        """
        try:
            logger.info(f"正在测试邮件连接: {self.sender_email} -> {self.smtp_server}:{self.smtp_port}")
            context = ssl.create_default_context()
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls(context=context)
                server.login(self.sender_email, self.sender_password)
            
            logger.info("邮件连接测试成功")
            return True
            
        except smtplib.SMTPAuthenticationError as e:
            logger.error(f"Gmail认证失败: {e}")
            logger.error("请检查是否使用了Gmail应用专用密码，而不是普通密码")
            logger.error("参考 GMAIL_SETUP.md 文件获取详细配置说明")
            return False
        except Exception as e:
            logger.error(f"邮件连接测试失败: {e}")
            return False


def test_email_sender():
    """
    测试邮件发送功能
    """
    # 测试配置（需要用户提供真实的邮件配置）
    email_config = {
        'smtp_server': 'smtp.gmail.com',
        'smtp_port': 587,
        'sender_email': 'your_email@gmail.com',
        'sender_password': 'your_app_password',
        'recipient_email': 'your_email@gmail.com'
    }
    
    # 测试数据
    test_contents = [
        {
            'title': 'Test Paper 1',
            'authors': 'Author 1, Author 2',
            'extracted_content': 'This is a test paper about machine learning.',
            'extraction_time': datetime.now().isoformat(),
            'source': 'abstract'
        }
    ]
    
    try:
        sender = EmailSender(email_config)
        
        # 测试连接
        if sender.test_connection():
            print("邮件连接测试成功")
            
            # 发送测试邮件
            success = sender.send_paper_summary(test_contents, "测试邮件")
            if success:
                print("测试邮件发送成功")
            else:
                print("测试邮件发送失败")
        else:
            print("邮件连接测试失败")
            
    except Exception as e:
        print(f"测试失败: {e}")


if __name__ == "__main__":
    test_email_sender()
