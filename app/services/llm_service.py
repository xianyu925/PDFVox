import logging
from app.config import settings
from openai import OpenAI

# 配置日志
if settings.ENABLE_LOGGING:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    logger = logging.getLogger(__name__)
else:
    # 禁用日志
    logging.basicConfig(level=logging.CRITICAL)
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.CRITICAL)


class LLMService:
    """Service for interacting with language models"""

    def __init__(self):
        self.client = OpenAI(
            base_url="https://ark.cn-beijing.volces.com/api/v3",
            api_key=settings.API_KEY,
        )

    def generate_explanation(
        self, system_prompt, user_prompt, image_base64=None, max_tokens=800
    ):
        """Send a streaming chat request and collect the result as text."""
        try:
            logger.info("开始生成讲解，准备API调用")

            # 火山引擎API格式
            input_messages = []

            # 添加系统提示
            if system_prompt:
                input_messages.append(
                    {
                        "role": "system",
                        "content": [{"type": "input_text", "text": system_prompt}],
                    }
                )

            # Add user prompt - handle both text-only and multimodal formats
            if isinstance(user_prompt, list) and all(
                isinstance(item, dict) for item in user_prompt
            ):
                # 转换为火山引擎格式
                user_content = []
                for item in user_prompt:
                    if item.get("type") == "text":
                        user_content.append(
                            {"type": "input_text", "text": item.get("text")}
                        )
                    elif item.get("type") == "image_url":
                        image_url = item.get("image_url", {}).get("url")
                        user_content.append(
                            {"type": "input_image", "image_url": image_url}
                        )
                input_messages.append({"role": "user", "content": user_content})
                logger.info("多模态输入已准备，包含文本和图像")
            else:
                # Text-only format
                input_messages.append(
                    {
                        "role": "user",
                        "content": [{"type": "input_text", "text": user_prompt}],
                    }
                )
                logger.info("文本输入已准备")

            # 使用火山引擎API
            logger.info("正在调用火山引擎API")
            response = self.client.responses.create(
                model="doubao-seed-1-8-251228",
                input=input_messages,
            )
            logger.info("API调用成功")

            # 提取响应内容
            explanation = ""

            if hasattr(response, "output") and response.output:
                logger.info(f"输出项数量: {len(response.output)}")

                # 只处理第二个output项（索引为1）
                if len(response.output) >= 2:
                    item = response.output[1]
                    if hasattr(item, "content") and isinstance(item.content, list):
                        for content_item in item.content:
                            if hasattr(content_item, "text"):
                                explanation += content_item.text
                                logger.info(
                                    f"从content的text属性提取到文本: {content_item.text[:100]}..."
                                )

                # 如果没有提取到内容，尝试处理第一个output项
                if not explanation and len(response.output) > 0:
                    item = response.output[0]
                    if hasattr(item, "content") and isinstance(item.content, list):
                        for content_item in item.content:
                            if hasattr(content_item, "text"):
                                explanation += content_item.text
                                logger.info(
                                    f"从第一个output的content属性提取到文本: {content_item.text[:100]}..."
                                )

                logger.info(f"最终提取响应内容，长度: {len(explanation)}")

            return explanation.replace("\u0000", "")
        except Exception as e:
            logger.error(f"生成讲解失败: {str(e)}", exc_info=True)
            raise
