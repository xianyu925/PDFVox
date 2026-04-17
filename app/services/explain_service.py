import logging
from pathlib import Path
import uuid
from app.models.schemas import ExplainResponse
from app.services.pdf_service import PDFService
from app.services.llm_service import LLMService
from app.models.db import get_upload, save_task, update_task_status
from app.config import settings

# 配置日志
if settings.ENABLE_LOGGING:
    logging.basicConfig(
        level=logging.DEBUG,  # 设置为DEBUG以显示所有日志
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    logger = logging.getLogger(__name__)
else:
    # 只显示错误日志
    logging.basicConfig(level=logging.ERROR)
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.ERROR)


class ExplainService:
    def __init__(self):
        self.pdf_service = PDFService()
        self.llm_service = LLMService()
        self.summary_cache = {}  # 缓存摘要，格式: {file_id: {page: summary}}

    def generate_summaries(
        self,
        file_id: str,
        course_name: str = "机器学习导论",
    ) -> dict:
        """生成所有页面的摘要并缓存

        Args:
            file_id: 文件ID
            course_name: 课程名称

        Returns:
            dict: 所有页面的摘要，格式: {page: summary}
        """
        import time

        start_time = time.time()
        logger.info(
            f"=== 开始生成所有页面摘要 ===\n"
            f"课程名称: {course_name}\n"
            f"开始时间: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(start_time))}"
        )

        # 检查上传记录
        upload = get_upload(file_id)
        if not upload:
            logger.error(f"上传记录未找到: {file_id}")
            raise FileNotFoundError(f"Upload record not found: {file_id}")

        # 检查PDF路径
        pdf_path = upload.get("path")
        if not pdf_path:
            logger.error("上传路径缺失")
            raise ValueError("Upload path is missing")

        # 获取PDF总页数
        try:
            with self.pdf_service.load_pdf(pdf_path) as pdf:
                total_pages = len(pdf.pages)
            logger.info(f"PDF总页数: {total_pages}")
        except Exception as e:
            logger.error(f"获取PDF页数失败: {str(e)}", exc_info=True)
            raise

        # 初始化缓存
        if file_id not in self.summary_cache:
            self.summary_cache[file_id] = {}
            logger.info(f"初始化摘要缓存: {file_id}")

        summary_count = 0
        cached_count = 0

        try:
            # 批量生成所有页面的摘要
            for page_num in range(1, total_pages + 1):
                logger.info(f"=== 处理第{page_num}页摘要 ===")

                # 检查缓存
                if page_num in self.summary_cache[file_id]:
                    cached_count += 1
                    logger.info(f"使用缓存的摘要: file_id={file_id}, page={page_num}")
                    logger.debug(f"缓存摘要: {self.summary_cache[file_id][page_num]}")
                else:
                    # 提取PDF页面的base64图像
                    try:
                        image_base64 = self.pdf_service.get_page_image(
                            pdf_path, page_num
                        )
                        logger.info(f"PDF页面{page_num}图像提取完成")
                    except Exception as e:
                        logger.error(
                            f"提取PDF页面{page_num}图像失败: {str(e)}", exc_info=True
                        )
                        continue

                    # 系统提示词和用户提示词
                    summary_system_prompt = (
                        "你是一位大学教授，正在给学生讲解课程PPT。请为PPT页面生成简洁的摘要，突出核心概念和关键知识点。"
                        "摘要应该简洁明了，重点突出，不超过100字。"
                    )
                    summary_user_prompt = [
                        {
                            "type": "text",
                            "text": f"请为以下{course_name}课程PPT的第{page_num}页内容生成简洁摘要，要求：\n"
                            "1. 突出核心概念和关键知识点\n"
                            "2. 简洁明了，不超过100字\n"
                            "3. 不要包含冗余内容\n",
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{image_base64}"
                            },
                        },
                    ]

                    logger.info(f"开始调用LLM生成第{page_num}页摘要")
                    try:
                        summary = self.llm_service.generate_explanation(
                            summary_system_prompt, summary_user_prompt, max_tokens=200
                        )
                        summary_count += 1
                        logger.info(f"第{page_num}页摘要生成完成")
                        logger.debug(f"摘要内容: {summary}")

                        # 缓存摘要
                        self.summary_cache[file_id][page_num] = summary
                        logger.info(f"摘要已缓存: page={page_num}")
                    except Exception as e:
                        logger.error(
                            f"生成第{page_num}页摘要失败: {str(e)}", exc_info=True
                        )
                        continue

            end_time = time.time()
            duration = end_time - start_time
            logger.info(
                f"=== 摘要生成完成 ===\n"
                f"总页数: {total_pages}\n"
                f"生成摘要: {summary_count}页\n"
                f"使用缓存: {cached_count}页\n"
                f"总缓存页数: {len(self.summary_cache[file_id])}页\n"
                f"耗时: {duration:.2f} 秒"
            )
            return self.summary_cache[file_id]
        except Exception as e:
            logger.error(f"摘要生成失败: {str(e)}", exc_info=True)
            raise

    def explain_all_pages(
        self,
        file_id: str,
        course_name: str = "机器学习导论",
    ) -> dict:
        """批量生成所有页面的讲解

        Args:
            file_id: 文件ID
            course_name: 课程名称

        Returns:
            dict: 所有页面的讲解结果，格式: {page: ExplainResponse}
        """
        import time

        start_time = time.time()
        logger.info(
            f"=== 开始批量生成所有页面讲解 ===\n"
            f"文件ID: {file_id}\n"
            f"课程名称: {course_name}\n"
            f"开始时间: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(start_time))}"
        )

        # 检查上传记录
        upload = get_upload(file_id)
        if not upload:
            logger.error(f"上传记录未找到: {file_id}")
            raise FileNotFoundError(f"Upload record not found: {file_id}")

        # 检查PDF路径
        pdf_path = upload.get("path")
        if not pdf_path:
            logger.error("上传路径缺失")
            raise ValueError("Upload path is missing")
        logger.info(f"PDF路径: {pdf_path}")

        # 获取PDF总页数
        try:
            with self.pdf_service.load_pdf(pdf_path) as pdf:
                total_pages = len(pdf.pages)
            logger.info(f"PDF总页数: {total_pages}")
        except Exception as e:
            logger.error(f"获取PDF页数失败: {str(e)}", exc_info=True)
            raise

        # 生成所有页面的摘要
        summary_start_time = time.time()
        if file_id not in self.summary_cache or len(self.summary_cache[file_id]) == 0:
            logger.info(f"=== 开始批量生成所有页面摘要 ===")
            try:
                self.generate_summaries(file_id, course_name)
                summary_end_time = time.time()
                summary_duration = summary_end_time - summary_start_time
                logger.info(
                    f"=== 批量生成摘要完成 ===\n耗时: {summary_duration:.2f} 秒"
                )
            except Exception as e:
                logger.error(f"批量生成摘要失败: {str(e)}", exc_info=True)
                raise
        else:
            summary_end_time = time.time()
            summary_duration = summary_end_time - summary_start_time
            logger.info(f"=== 使用缓存的摘要 ===\n耗时: {summary_duration:.2f} 秒")

        # 批量生成所有页面的讲解
        results = {}
        success_count = 0
        fail_count = 0

        logger.info(f"=== 开始批量生成讲解，共{total_pages}页 ===")

        for current_page in range(1, total_pages + 1):
            logger.info(f"=== 处理第{current_page}页 ===")

            task_id = str(uuid.uuid4())
            logger.info(f"创建任务: {task_id}")

            try:
                save_task(
                    task_id,
                    {
                        "task_id": task_id,
                        "file_id": file_id,
                        "page": current_page,
                        "status": "started",
                        "detail": f"开始生成第{current_page}页讲解",
                    },
                )
                logger.info(f"任务创建成功: {task_id}")

                # 从缓存中获取当前页、上一页和下一页的摘要
                current_summary = self.summary_cache[file_id].get(current_page, "")
                prev_summary = (
                    self.summary_cache[file_id].get(current_page - 1, "")
                    if current_page > 1
                    else ""
                )
                next_summary = (
                    self.summary_cache[file_id].get(current_page + 1, "")
                    if current_page < total_pages
                    else ""
                )

                logger.info(
                    f"获取摘要完成:\n"
                    f"  当前页摘要: {current_summary[:100]}...\n"
                    f"  上一页摘要: {prev_summary[:100]}...\n"
                    f"  下一页摘要: {next_summary[:100]}..."
                )

                # 提取PDF页面的base64图像
                try:
                    image_base64 = self.pdf_service.get_page_image(
                        pdf_path, current_page
                    )
                    logger.info(
                        f"PDF页面{current_page}图像提取完成，大小: {len(image_base64)}字节"
                    )
                except Exception as e:
                    logger.error(
                        f"提取PDF页面{current_page}图像失败: {str(e)}", exc_info=True
                    )
                    update_task_status(task_id, "failed", f"提取图像失败: {str(e)}")
                    results[current_page] = {"error": str(e), "status": "failed"}
                    fail_count += 1
                    continue

                # 系统提示词和用户提示词
                explanation_system_prompt = (
                    "你是一位大学教授，正在给学生讲解课程PPT。请以专业、清晰、有条理的方式讲解PPT内容，语气像在课堂上讲课一样。"
                    "重点讲解核心概念、理论框架和关键知识点，避免冗余内容和对无关元素的过多讲解。"
                    "讲解要逻辑连贯，层次分明，适合大学学生的理解水平。"
                    "请参考上一页和下一页的摘要，使讲解更加流畅，在开头和结尾提供自然的过渡。"
                )

                # 构建用户提示词，包含当前页图像和摘要信息
                prompt_text = f"请为以下{course_name}课程PPT的第{current_page}页内容生成一段课堂讲解，要求：\n"
                prompt_text += "1. 以大学教授的语气和风格讲解\n"
                prompt_text += "2. 重点讲解核心概念、理论框架和关键知识点\n"
                prompt_text += "3. 避免冗余内容和对无关元素的过多讲解\n"
                prompt_text += "4. 讲解逻辑清晰，层次分明，适合大学学生理解\n"
                prompt_text += "5. 讲解时长自由发挥，可长可短\n"
                prompt_text += "6. 不要带有老师的神态描写与动作描写，不要带有类似于markdown加粗等符号，单纯生成讲解稿\n\n"

                if prev_summary:
                    prompt_text += f"上一页摘要: {prev_summary}\n\n"
                if next_summary:
                    prompt_text += f"下一页摘要: {next_summary}\n"

                explanation_user_prompt = [
                    {"type": "text", "text": prompt_text},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{image_base64}"},
                    },
                ]

                logger.info(f"开始调用LLM生成第{current_page}页讲解")
                try:
                    explanation = self.llm_service.generate_explanation(
                        explanation_system_prompt,
                        explanation_user_prompt,
                        max_tokens=800,
                    )
                    logger.info(
                        f"第{current_page}页讲解生成完成，长度: {len(explanation)}"
                    )
                    logger.debug(f"讲解内容: {explanation[:200]}...")
                except Exception as e:
                    logger.error(f"LLM生成讲解失败: {str(e)}", exc_info=True)
                    update_task_status(task_id, "failed", f"LLM生成失败: {str(e)}")
                    results[current_page] = {"error": str(e), "status": "failed"}
                    fail_count += 1
                    continue

                combined_text = explanation
                logger.info(f"文本准备完成，总长度: {len(combined_text)}")

                update_task_status(
                    task_id, "completed", f"第{current_page}页讲解生成成功"
                )
                logger.info(f"任务完成: {task_id}")

                results[current_page] = {
                    "task_id": task_id,
                    "file_id": file_id,
                    "page": current_page,
                    "explanation": explanation,
                    "combined_text": combined_text,
                    "audio_url": None,
                }
                success_count += 1
                logger.info(f"第{current_page}页处理成功")

            except Exception as e:
                logger.error(f"第{current_page}页讲解生成失败: {str(e)}", exc_info=True)
                if "task_id" in locals():
                    update_task_status(task_id, "failed", str(e))
                results[current_page] = {"error": str(e), "status": "failed"}
                fail_count += 1
                logger.info(f"第{current_page}页处理失败")

        # 计算总耗时
        explanation_end_time = time.time()
        explanation_duration = explanation_end_time - summary_end_time
        total_duration = explanation_end_time - start_time

        logger.info(
            f"=== 批量讲解生成完成 ===\n"
            f"总页数: {total_pages}\n"
            f"成功: {success_count}页\n"
            f"失败: {fail_count}页\n"
            f"成功率: {success_count/total_pages*100:.2f}%\n"
            f"摘要生成耗时: {summary_duration:.2f} 秒\n"
            f"讲解生成耗时: {explanation_duration:.2f} 秒\n"
            f"总耗时: {total_duration:.2f} 秒"
        )

        # 合并所有音频文件
        audio_start_time = time.time()
        logger.info(
            f"=== 开始合并音频文件 ===\n文件ID: {file_id}\n总页数: {total_pages}"
        )
        # 检查output目录中的音频文件
        import os

        output_dir = "output"
        if os.path.exists(output_dir):
            audio_files = [
                f
                for f in os.listdir(output_dir)
                if f.startswith(file_id) and f.endswith(".mp3")
            ]
            logger.info(f"在output目录中找到的音频文件: {audio_files}")
        else:
            logger.warning("output目录不存在")
        try:
            from app.services.tts_service import TTSService

            tts_service = TTSService()
            logger.info(
                f"调用merge_audio_files，参数: file_id={file_id}, total_pages={total_pages}"
            )
            merged_audio_path = tts_service.merge_audio_files(file_id, total_pages)
            audio_end_time = time.time()
            audio_duration = audio_end_time - audio_start_time
            if merged_audio_path:
                logger.info(
                    f"音频合并成功: {merged_audio_path}\n耗时: {audio_duration:.2f} 秒"
                )
                # 添加合并音频的URL到结果中
                results["merged_audio_url"] = f"/audio/{file_id}/merged"
            else:
                logger.warning(f"音频合并失败\n耗时: {audio_duration:.2f} 秒")
        except Exception as e:
            audio_end_time = time.time()
            audio_duration = audio_end_time - audio_start_time
            logger.error(
                f"音频合并失败: {str(e)}\n耗时: {audio_duration:.2f} 秒", exc_info=True
            )

        # 添加总耗时信息到结果中
        final_end_time = time.time()
        final_total_duration = final_end_time - start_time
        results["time_info"] = {
            "start_time": time.strftime(
                "%Y-%m-%d %H:%M:%S", time.localtime(start_time)
            ),
            "end_time": time.strftime(
                "%Y-%m-%d %H:%M:%S", time.localtime(final_end_time)
            ),
            "total_duration": final_total_duration,
            "summary_duration": summary_duration,
            "explanation_duration": explanation_duration,
            "audio_duration": audio_duration if "audio_duration" in locals() else None,
        }

        logger.info(f"=== 整个过程完成 ===\n总耗时: {final_total_duration:.2f} 秒")

        return results
