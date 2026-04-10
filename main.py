import argparse
import uvicorn
from pdfvox import PDFVox
from config import settings


def run_legacy():
    pdf_vox = PDFVox(settings.API_KEY)
    audio_files = pdf_vox.process(settings.DEFAULT_PDF_PATH, settings.DEFAULT_OUTPUT_DIR)

    print("Generated audio files:")
    for file in audio_files:
        print(f"Page {file['page']}: {file['audio_path']}")


def run_web():
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=settings.AUTO_RELOAD)


def main():
    parser = argparse.ArgumentParser(description="PDFVox runner")
    parser.add_argument("--mode", choices=["legacy", "web"], default="web", help="运行模式: legacy（CLI）或 web（FastAPI）")
    args = parser.parse_args()

    if args.mode == "legacy":
        run_legacy()
    else:
        run_web()


if __name__ == "__main__":
    main()

