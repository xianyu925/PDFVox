from openai import OpenAI, AsyncOpenAI

from app.config import settings
from app.utils.logging import get_logger

logger = get_logger(__name__)


class LLMService:
    """Service for interacting with language models"""

    def __init__(self):
        self.client = OpenAI(
            base_url="https://ark.cn-beijing.volces.com/api/v3",
            api_key=settings.API_KEY,
        )
        # 【新增】专门为流式并发准备的异步客户端
        self.async_client = AsyncOpenAI(
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
                model="doubao-seed-2-0-pro-260215",
                input=input_messages,
            )
            logger.info("API调用成功")

            # 提取响应内容
            explanation = ""

            item = response.output[1]
            if hasattr(item, "content") and isinstance(item.content, list):
                for content_item in item.content:
                    if hasattr(content_item, "text"):
                        explanation += content_item.text
                        logger.info(
                            f"从content的text属性提取到文本: {content_item.text[:100]}..."
                        )

            logger.info(f"最终提取响应内容，长度: {len(explanation)}")

            return explanation.replace("\u0000", "")
        except Exception as e:
            logger.error(f"生成讲解失败: {str(e)}", exc_info=True)
            raise

    async def stream_explanation(
        self, system_prompt, user_prompt, page_num=1, image_base64=None, max_tokens=800
    ):
        """流式生成讲解，返回统一事件流 - 与TTS增量输入接口对齐"""
        import time

        try:
            logger.info(f"开始流式生成讲解，页面: {page_num}")

            # 发送开始事件
            yield {
                "type": "start",
                "data": {"page": page_num, "stage": "llm"},
                "page": page_num,
                "ts": time.time(),
            }

            # OpenAI标准格式（用于流式API）
            input_messages = []

            # 添加系统提示
            if system_prompt:
                input_messages.append(
                    {
                        "role": "system",
                        "content": system_prompt,
                    }
                )

            # Add user prompt - handle both text-only and multimodal formats
            if isinstance(user_prompt, list) and all(
                isinstance(item, dict) for item in user_prompt
            ):
                # 转换为OpenAI标准格式
                user_content = []
                for item in user_prompt:
                    if item.get("type") == "text":
                        user_content.append({"type": "text", "text": item.get("text")})
                    elif item.get("type") == "image_url":
                        image_url = item.get("image_url", {}).get("url")
                        user_content.append(
                            {"type": "image_url", "image_url": {"url": image_url}}
                        )
                input_messages.append({"role": "user", "content": user_content})
                logger.info("多模态输入已准备，包含文本和图像")
            else:
                # Text-only format
                input_messages.append(
                    {
                        "role": "user",
                        "content": user_prompt,
                    }
                )
                logger.info("文本输入已准备")

            # 使用OpenAI聊天补全接口（流式）
            logger.info("正在调用OpenAI聊天补全API（流式）")
            response = await self.async_client.chat.completions.create(
                model="doubao-seed-1-8-251228",
                messages=input_messages,
                stream=True,  # 启用流式输出
            )
            logger.info("API调用成功，开始流式接收")

            # 流式提取响应内容，返回统一事件
            explanation = ""
            async for chunk in response:
                if chunk.choices and len(chunk.choices) > 0:
                    delta = chunk.choices[0].delta
                    if delta and delta.content:
                        content_piece = delta.content
                        explanation += content_piece

                        # 生成文本事件 - 与TTS增量输入对齐
                        yield {
                            "type": "text",
                            "data": content_piece,
                            "page": page_num,
                            "ts": time.time(),
                        }

            # 发送结束事件
            yield {
                "type": "end",
                "data": {"page": page_num, "stage": "llm", "length": len(explanation)},
                "page": page_num,
                "ts": time.time(),
            }

            logger.info(f"LLM流式生成完成，页面: {page_num}, 长度: {len(explanation)}")

        except Exception as e:
            logger.error(f"流式生成讲解失败: {str(e)}", exc_info=True)
            yield {
                "type": "error",
                "data": {"error": str(e), "stage": "llm"},
                "page": page_num,
                "ts": time.time(),
            }
