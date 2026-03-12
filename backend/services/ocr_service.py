import base64
import json
import re
from config import config
from prompts import get_ocr_prompt

if config.LANGFUSE_ENABLED and config.LANGFUSE_SECRET_KEY:
    from langfuse.openai import OpenAI
else:
    from openai import OpenAI

class OCRService:
    """多语言 OCR 识别服务"""
    
    def __init__(self):
        self.client = OpenAI(
            api_key=config.LVM_API_KEY,
            base_url=config.LVM_BASE_URL
        )
        self.model = config.LVM_MODEL
    
    def encode_image(self, image_bytes: bytes) -> str:
        """将图片编码为 base64"""
        return base64.b64encode(image_bytes).decode("utf-8")
    
    async def recognize(self, image_bytes: bytes, languages: list[str] = None) -> dict:
        """
        识别图片中的文字
        
        Args:
            image_bytes: 图片二进制数据
            languages: 期望识别的语言列表，如 ["中文", "英文", "日文"]
        
        Returns:
            {
                "success": bool,
                "text": str,           # 识别出的完整文字
                "languages_detected": list,  # 检测到的语言
                "text_blocks": list,   # 文字块详情
                "message": str
            }
        """
        base64_image = self.encode_image(image_bytes)
        image_data_url = f"data:image/png;base64,{base64_image}"
        prompt = get_ocr_prompt(languages)

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": image_data_url
                                }
                            },
                            {"type": "text", "text": prompt}
                        ]
                    }
                ],
                max_tokens=2000,
                name="language-agent-ocr",
                metadata={"model": self.model},
            )
            
            result_text = response.choices[0].message.content
            
            # 解析 JSON 结果
            result = None
            json_match = re.search(r'```json\s*(.*?)\s*```', result_text, re.DOTALL)
            if json_match:
                try:
                    result = json.loads(json_match.group(1))
                except json.JSONDecodeError:
                    pass
            
            # 如果没找到或解析失败，尝试直接解析整个文本
            if result is None:
                try:
                    result = json.loads(result_text)
                except json.JSONDecodeError:
                    # 尝试提取 JSON 对象（更宽松的匹配）
                    json_obj_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', result_text, re.DOTALL)
                    if json_obj_match:
                        try:
                            result = json.loads(json_obj_match.group(0))
                        except json.JSONDecodeError:
                            pass
            
            # 如果仍然无法解析 JSON，返回原始文本
            if result is None:
                return {
                    "success": True,
                    "text": result_text,
                    "languages_detected": [],
                    "text_blocks": [],
                    "message": "识别成功，但结果格式非标准"
                }
            
            return {
                "success": True,
                "text": result.get("text", ""),
                "languages_detected": result.get("languages_detected", []),
                "text_blocks": result.get("text_blocks", []),
                "message": "识别成功"
            }
            
        except json.JSONDecodeError:
            return {
                "success": True,
                "text": result_text,
                "languages_detected": [],
                "text_blocks": [],
                "message": "识别成功，但结果格式非标准"
            }
        except Exception as e:
            return {
                "success": False,
                "text": "",
                "languages_detected": [],
                "text_blocks": [],
                "message": f"识别失败: {str(e)}"
            }
