import logging
from fastapi import APIRouter, HTTPException
from app.models.schemas import ExplainRequest, StatusResponse
from app.services.explain_service import ExplainService
from app.services.tts_service import TTSService
from app.config import settings

import logging
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


router = APIRouter()
service = ExplainService()
tts_service = TTSService()


@router.get("/status/{task_id}", response_model=StatusResponse)
def explain_status(task_id: str):
    from app.models.db import get_task

    task = get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return StatusResponse(
        task_id=task_id, status=task.get("status", "unknown"), detail=task.get("detail")
    )


@router.post("/all")
def explain_all(req: ExplainRequest):
    try:
        results = service.explain_all_pages(req.file_id, req.course_name)
        logger.info(f"批量讲解生成成功，共{len(results)}页")

        # 为每个页面生成音频
        for page, result in results.items():
            if "combined_text" in result:
                try:
                    audio_path = tts_service.generate_and_get_audio(
                        req.file_id, page, result["combined_text"]
                    )
                    result["audio_url"] = f"/audio/{req.file_id}/page/{page}"
                    logger.info(f"第{page}页音频生成成功")
                except Exception as e:
                    logger.error(f"第{page}页音频生成失败: {str(e)}", exc_info=True)
                    result["audio_url"] = None

        return results
    except Exception as e:
        logger.error(f"批量讲解生成失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
