import uvicorn
from app.config import settings


def main():
    """启动PDFVox Web服务器"""
    try:
        uvicorn.run(
            "app.main:app",
            host=settings.HOST,
            port=settings.PORT,
            reload=settings.AUTO_RELOAD,
        )
    except Exception as e:
        print(f"服务器启动失败: {e}")
        raise

if __name__ == "__main__":
    main()